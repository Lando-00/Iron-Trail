"""Integration between per-model pricing and the billed-failure ledger.

These two landed on separate branches: per-model pricing did not know about
`fail()`, and the refund fix did not know prices vary by model. A billed
failure priced at the global default understates the global cap.
"""
from __future__ import annotations

import pytest

from iron_trail.coach.models import MODEL_CATALOG
from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.usage_limits import (
    CallKind,
    InMemoryUsageRepository,
    LimitedProvider,
    UsageLimiter,
    UsagePolicy,
)

LUNA = MODEL_CATALOG["gpt-5.6-luna"]
USER = "user-a"


class _BilledButEmptyProvider:
    """Mirrors the real failure: Foundry bills, then no text comes back."""

    name = "billed-empty"

    def __init__(self) -> None:
        self.last_usage: TokenUsage | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        self.last_usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        raise RuntimeError("No assistant message returned from Microsoft Foundry.")


def _limiter() -> UsageLimiter:
    return UsageLimiter(InMemoryUsageRepository(), UsagePolicy())


def test_a_billed_failure_is_priced_at_the_model_that_ran_it() -> None:
    limiter = _limiter()
    limited = LimitedProvider(
        _BilledButEmptyProvider(), limiter, USER, CallKind.CHAT, model=LUNA
    )

    with pytest.raises(RuntimeError):
        limited.chat([Message(role="user", content="hi")])

    spend = limiter.snapshot(USER).global_monthly_cost_eur
    # luna is 1.00 in / 6.00 out per million; the global default is 0.25 / 2.00.
    assert spend == pytest.approx(7.0)


def test_the_global_default_would_have_understated_it() -> None:
    """Guards the regression directly: without the model policy the same
    failure lands at 2.25 instead of 7.00."""
    limiter = _limiter()
    limited = LimitedProvider(
        _BilledButEmptyProvider(), limiter, USER, CallKind.CHAT, model=None
    )

    with pytest.raises(RuntimeError):
        limited.chat([Message(role="user", content="hi")])

    assert limiter.snapshot(USER).global_monthly_cost_eur == pytest.approx(2.25)


def test_a_billed_failure_still_consumes_the_callers_allowance() -> None:
    limiter = _limiter()
    limited = LimitedProvider(
        _BilledButEmptyProvider(), limiter, USER, CallKind.CHAT, model=LUNA
    )

    with pytest.raises(RuntimeError):
        limited.chat([Message(role="user", content="hi")])

    assert limiter.snapshot(USER).chat_daily == 1
