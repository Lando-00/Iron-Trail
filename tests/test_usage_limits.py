from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from iron_trail import runtime
from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.usage_limits import (
    CallKind,
    InMemoryUsageRepository,
    LimitedProvider,
    UsageLimitExceeded,
    UsageLimiter,
    UsagePolicy,
    is_pre_billing_error,
)


class FakeProvider:
    name = "fake"

    def __init__(self, *, fail: bool = False, error: Exception | None = None,
                 usage_before_error: TokenUsage | None = None) -> None:
        self.fail = fail or error is not None or usage_before_error is not None
        self.error = error or RuntimeError("provider failed")
        self.usage_before_error = usage_before_error
        self.last_usage: TokenUsage | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        if self.fail:
            # Foundry sets last_usage from response.usage before raising for an
            # empty completion — those tokens are billed.
            self.last_usage = self.usage_before_error
            raise self.error
        self.last_usage = TokenUsage(input_tokens=100, output_tokens=50)
        return "coach response"


def _policy(**overrides) -> UsagePolicy:
    values = {
        "review_daily": 1,
        "review_monthly": 2,
        "chat_daily": 2,
        "chat_monthly": 3,
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "global_monthly_cost_eur": 10.0,
        "input_eur_per_million": 1.0,
        "output_eur_per_million": 1.0,
    }
    values.update(overrides)
    return UsagePolicy(**values)


def test_limited_provider_records_actual_usage() -> None:
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )
    provider = LimitedProvider(FakeProvider(), limiter, "user-a", CallKind.REVIEW)

    assert provider.chat([Message("user", "How was training?")]) == "coach response"
    event = next(iter(repo.events.values()))
    assert event.status == "completed"
    assert event.input_tokens == 100
    assert event.output_tokens == 50


def test_daily_limit_fails_closed_before_provider_call() -> None:
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )
    first = LimitedProvider(FakeProvider(), limiter, "user-a", CallKind.REVIEW)
    first.chat([Message("user", "first")])

    with pytest.raises(UsageLimitExceeded, match="daily"):
        first.chat([Message("user", "second")])


def test_billed_failure_stays_on_the_ledger_at_its_real_cost() -> None:
    """A completion that returns no assistant text is still billed. Foundry
    reports the token usage before raising, so the ledger must keep it."""
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(repo, _policy())
    provider = LimitedProvider(
        FakeProvider(
            error=RuntimeError("No assistant message returned"),
            usage_before_error=TokenUsage(input_tokens=900, output_tokens=1200),
        ),
        limiter,
        "user-a",
        CallKind.CHAT,
    )

    with pytest.raises(RuntimeError, match="No assistant message"):
        provider.chat([Message("user", "hello")])

    event = next(iter(repo.events.values()))
    assert event.status == "failed"
    assert event.input_tokens == 900
    assert event.output_tokens == 1200
    assert event.cost_eur == pytest.approx(0.0021)


def test_unknown_failure_keeps_the_reserved_estimate() -> None:
    """If nothing tells us the call was free, assume it was billed."""
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(repo, _policy())
    provider = LimitedProvider(FakeProvider(fail=True), limiter, "user-a", CallKind.CHAT)

    with pytest.raises(RuntimeError, match="provider failed"):
        provider.chat([Message("user", "hello")])

    event = next(iter(repo.events.values()))
    assert event.status == "failed"
    assert event.cost_eur > 0


def test_pre_billing_failure_is_refunded_in_full() -> None:
    """A rejected request never reaches the model, so it must not cost the
    user an allowance or the budget a cent."""
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(repo, _policy())
    provider = LimitedProvider(
        FakeProvider(error=runtime.ConfigurationError("endpoint missing")),
        limiter,
        "user-a",
        CallKind.CHAT,
    )

    with pytest.raises(runtime.ConfigurationError):
        provider.chat([Message("user", "hello")])

    assert repo.events == {}


def test_repeated_billed_failures_cannot_farm_free_calls() -> None:
    """The exploit: every failed call was refunded, so a user could burn Azure
    tokens indefinitely without touching their quota or the global budget."""
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(chat_daily=2, chat_monthly=3),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )

    def _failing_call() -> None:
        provider = LimitedProvider(
            FakeProvider(
                error=RuntimeError("No assistant message returned"),
                usage_before_error=TokenUsage(input_tokens=900, output_tokens=1200),
            ),
            limiter,
            "user-a",
            CallKind.CHAT,
        )
        provider.chat([Message("user", "hello")])

    for _ in range(2):
        with pytest.raises(RuntimeError, match="No assistant message"):
            _failing_call()

    assert limiter.snapshot("user-a").chat_daily == 2
    with pytest.raises(UsageLimitExceeded, match="daily"):
        _failing_call()


def test_billed_failures_count_towards_the_global_budget() -> None:
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(global_monthly_cost_eur=0.00215, chat_daily=9, chat_monthly=9),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )
    provider = LimitedProvider(
        FakeProvider(
            error=RuntimeError("No assistant message returned"),
            usage_before_error=TokenUsage(input_tokens=900, output_tokens=1200),
        ),
        limiter,
        "user-a",
        CallKind.CHAT,
    )
    with pytest.raises(RuntimeError, match="No assistant message"):
        provider.chat([Message("user", "hello")])

    with pytest.raises(UsageLimitExceeded, match="budget"):
        LimitedProvider(FakeProvider(), limiter, "user-b", CallKind.CHAT).chat(
            [Message("user", "hello")]
        )


def test_timeouts_are_not_treated_as_free() -> None:
    """The server keeps generating after the client gives up, and
    APITimeoutError subclasses APIConnectionError, so ordering matters."""
    openai = pytest.importorskip("openai")

    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    connection = openai.APIConnectionError(
        message="refused", request=httpx.Request("POST", "https://example.test")
    )

    assert is_pre_billing_error(timeout) is False
    assert is_pre_billing_error(connection) is True
    assert is_pre_billing_error(runtime.ConfigurationError("nope")) is True
    assert is_pre_billing_error(RuntimeError("who knows")) is False


def test_global_budget_counts_all_users() -> None:
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(global_monthly_cost_eur=0.00015),
        clock=lambda: datetime(2026, 7, 12, tzinfo=UTC),
    )
    LimitedProvider(FakeProvider(), limiter, "user-a", CallKind.CHAT).chat(
        [Message("user", "hello")]
    )

    with pytest.raises(UsageLimitExceeded, match="budget"):
        LimitedProvider(FakeProvider(), limiter, "user-b", CallKind.CHAT).chat(
            [Message("user", "hello")]
        )


def test_abandoned_reservation_expires() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(review_daily=1, reservation_ttl_seconds=300),
        clock=lambda: now,
    )
    limiter.reserve("user-a", CallKind.REVIEW, input_tokens=10)

    later = UsageLimiter(
        repo,
        _policy(review_daily=1, reservation_ttl_seconds=300),
        clock=lambda: now + timedelta(seconds=301),
    )
    later.reserve("user-a", CallKind.REVIEW, input_tokens=10)

    assert len(repo.events) == 1


def test_provider_timeout_extends_reservation_lease() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(
        repo,
        _policy(review_daily=1, reservation_ttl_seconds=300),
        clock=lambda: now,
    )
    reservation = limiter.reserve(
        "user-a",
        CallKind.REVIEW,
        input_tokens=10,
        hold_seconds=600,
    )

    assert reservation.expires_at == now + timedelta(seconds=600)
