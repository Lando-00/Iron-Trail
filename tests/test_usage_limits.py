from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.usage_limits import (
    CallKind,
    InMemoryUsageRepository,
    LimitedProvider,
    UsageLimitExceeded,
    UsageLimiter,
    UsagePolicy,
)


class FakeProvider:
    name = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.last_usage: TokenUsage | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        if self.fail:
            raise RuntimeError("provider failed")
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


def test_failed_provider_releases_reservation() -> None:
    repo = InMemoryUsageRepository()
    limiter = UsageLimiter(repo, _policy())
    provider = LimitedProvider(FakeProvider(fail=True), limiter, "user-a", CallKind.CHAT)

    with pytest.raises(RuntimeError, match="provider failed"):
        provider.chat([Message("user", "hello")])

    assert repo.events == {}


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
