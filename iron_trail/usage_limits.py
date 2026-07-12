"""Per-user and global limits for hosted Coach model calls."""
from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol

import streamlit as st

from . import runtime
from .cloud_storage import azure_table_client
from .coach.providers import Message, Provider, TokenUsage

_RESERVATION_LOCK = threading.Lock()


class CallKind(StrEnum):
    REVIEW = "review"
    CHAT = "chat"


class UsageLimitExceeded(RuntimeError):
    """Raised before a call that would exceed an IronTrail usage limit."""


class UsageRepositoryError(RuntimeError):
    """Raised when the usage ledger is unavailable."""


@dataclass(frozen=True)
class UsagePolicy:
    review_daily: int = 3
    review_monthly: int = 30
    chat_daily: int = 15
    chat_monthly: int = 200
    max_input_tokens: int = 20_000
    max_output_tokens: int = 1_200
    global_monthly_cost_eur: float = 10.0
    input_eur_per_million: float = 0.25
    output_eur_per_million: float = 2.0

    @classmethod
    def from_environment(cls) -> "UsagePolicy":
        return cls(
            review_daily=runtime.env_int("IRONTRAIL_REVIEW_DAILY_LIMIT", 3, minimum=1),
            review_monthly=runtime.env_int(
                "IRONTRAIL_REVIEW_MONTHLY_LIMIT", 30, minimum=1
            ),
            chat_daily=runtime.env_int("IRONTRAIL_CHAT_DAILY_LIMIT", 15, minimum=1),
            chat_monthly=runtime.env_int(
                "IRONTRAIL_CHAT_MONTHLY_LIMIT", 200, minimum=1
            ),
            max_input_tokens=runtime.env_int(
                "IRONTRAIL_AI_MAX_INPUT_TOKENS", 20_000, minimum=1
            ),
            max_output_tokens=runtime.env_int(
                "IRONTRAIL_AI_MAX_OUTPUT_TOKENS", 1_200, minimum=1
            ),
            global_monthly_cost_eur=runtime.env_float(
                "IRONTRAIL_AI_MONTHLY_CAP_EUR", 10.0, minimum=0.01
            ),
            input_eur_per_million=runtime.env_float(
                "IRONTRAIL_AI_INPUT_EUR_PER_MILLION", 0.25, minimum=0.0
            ),
            output_eur_per_million=runtime.env_float(
                "IRONTRAIL_AI_OUTPUT_EUR_PER_MILLION", 2.0, minimum=0.0
            ),
        )


@dataclass(frozen=True)
class UsageEvent:
    reservation_id: str
    month: str
    day: str
    user_id: str
    kind: CallKind
    status: str
    input_tokens: int
    output_tokens: int
    cost_eur: float
    created_at: datetime


@dataclass(frozen=True)
class UsageSnapshot:
    review_daily: int
    review_monthly: int
    chat_daily: int
    chat_monthly: int
    global_monthly_cost_eur: float


class UsageRepository(Protocol):
    def list_month(self, month: str) -> list[UsageEvent]: ...

    def create(self, event: UsageEvent) -> None: ...

    def complete(self, event: UsageEvent) -> None: ...

    def cancel(self, event: UsageEvent) -> None: ...


class AzureUsageRepository:
    def __init__(self, table_client: Any) -> None:
        self._table = table_client

    @classmethod
    def from_environment(cls) -> "AzureUsageRepository":
        table_name = os.environ.get("IRONTRAIL_USAGE_TABLE", "IronTrailUsage")
        return cls(azure_table_client(table_name))

    def list_month(self, month: str) -> list[UsageEvent]:
        from azure.core.exceptions import AzureError

        try:
            entities = self._table.query_entities(f"PartitionKey eq '{month}'")
            return [_entity_to_event(entity) for entity in entities]
        except AzureError as exc:
            raise UsageRepositoryError("Unable to read AI usage.") from exc

    def create(self, event: UsageEvent) -> None:
        from azure.core.exceptions import AzureError

        try:
            self._table.create_entity(_event_to_entity(event))
        except AzureError as exc:
            raise UsageRepositoryError("Unable to reserve AI usage.") from exc

    def complete(self, event: UsageEvent) -> None:
        from azure.core.exceptions import AzureError

        try:
            self._table.update_entity(_event_to_entity(event), mode="replace")
        except AzureError as exc:
            raise UsageRepositoryError("Unable to record AI usage.") from exc

    def cancel(self, event: UsageEvent) -> None:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        try:
            self._table.delete_entity(event.month, event.reservation_id)
        except ResourceNotFoundError:
            return
        except AzureError as exc:
            raise UsageRepositoryError("Unable to release AI usage.") from exc


class InMemoryUsageRepository:
    def __init__(self) -> None:
        self.events: dict[str, UsageEvent] = {}

    def list_month(self, month: str) -> list[UsageEvent]:
        return [event for event in self.events.values() if event.month == month]

    def create(self, event: UsageEvent) -> None:
        self.events[event.reservation_id] = event

    def complete(self, event: UsageEvent) -> None:
        self.events[event.reservation_id] = event

    def cancel(self, event: UsageEvent) -> None:
        self.events.pop(event.reservation_id, None)


class UsageLimiter:
    def __init__(
        self,
        repository: UsageRepository,
        policy: UsagePolicy | None = None,
        *,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.policy = policy or UsagePolicy.from_environment()
        self.clock = clock

    def reserve(
        self,
        user_id: str,
        kind: CallKind,
        *,
        input_tokens: int,
    ) -> UsageEvent:
        if input_tokens > self.policy.max_input_tokens:
            raise UsageLimitExceeded("This request is too large for the hosted Coach.")

        now = self.clock()
        month = now.strftime("%Y-%m")
        day = now.date().isoformat()
        estimated_cost = token_cost_eur(
            input_tokens,
            self.policy.max_output_tokens,
            self.policy,
        )

        with _RESERVATION_LOCK:
            events = [
                event
                for event in self.repository.list_month(month)
                if event.status in {"reserved", "completed"}
            ]
            snapshot = _snapshot(events, user_id, day)
            daily_limit, monthly_limit = self._limits(kind)
            daily_count = (
                snapshot.review_daily if kind is CallKind.REVIEW else snapshot.chat_daily
            )
            monthly_count = (
                snapshot.review_monthly
                if kind is CallKind.REVIEW
                else snapshot.chat_monthly
            )
            if daily_count >= daily_limit:
                raise UsageLimitExceeded("Your daily Coach allowance has been reached.")
            if monthly_count >= monthly_limit:
                raise UsageLimitExceeded("Your monthly Coach allowance has been reached.")
            if (
                snapshot.global_monthly_cost_eur + estimated_cost
                > self.policy.global_monthly_cost_eur
            ):
                raise UsageLimitExceeded(
                    "The IronTrail Coach monthly budget has been reached."
                )

            event = UsageEvent(
                reservation_id=uuid.uuid4().hex,
                month=month,
                day=day,
                user_id=user_id,
                kind=kind,
                status="reserved",
                input_tokens=input_tokens,
                output_tokens=self.policy.max_output_tokens,
                cost_eur=estimated_cost,
                created_at=now,
            )
            self.repository.create(event)
            return event

    def complete(self, reservation: UsageEvent, usage: TokenUsage) -> UsageEvent:
        event = UsageEvent(
            reservation_id=reservation.reservation_id,
            month=reservation.month,
            day=reservation.day,
            user_id=reservation.user_id,
            kind=reservation.kind,
            status="completed",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_eur=token_cost_eur(
                usage.input_tokens,
                usage.output_tokens,
                self.policy,
            ),
            created_at=reservation.created_at,
        )
        self.repository.complete(event)
        return event

    def cancel(self, reservation: UsageEvent) -> None:
        self.repository.cancel(reservation)

    def snapshot(self, user_id: str, today: date | None = None) -> UsageSnapshot:
        current = today or self.clock().date()
        events = [
            event
            for event in self.repository.list_month(current.strftime("%Y-%m"))
            if event.status in {"reserved", "completed"}
        ]
        return _snapshot(events, user_id, current.isoformat())

    def _limits(self, kind: CallKind) -> tuple[int, int]:
        if kind is CallKind.REVIEW:
            return self.policy.review_daily, self.policy.review_monthly
        return self.policy.chat_daily, self.policy.chat_monthly


class LimitedProvider:
    def __init__(
        self,
        provider: Provider,
        limiter: UsageLimiter,
        user_id: str,
        kind: CallKind,
    ) -> None:
        self.provider = provider
        self.limiter = limiter
        self.user_id = user_id
        self.kind = kind
        self.name = provider.name
        self.last_usage: TokenUsage | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        input_tokens = estimate_tokens(messages)
        reservation = self.limiter.reserve(
            self.user_id,
            self.kind,
            input_tokens=input_tokens,
        )
        try:
            response = self.provider.chat(messages, timeout=timeout)
        except Exception:
            self.limiter.cancel(reservation)
            raise

        usage = self.provider.last_usage or TokenUsage(
            input_tokens=input_tokens,
            output_tokens=max(1, len(response) // 4),
        )
        self.last_usage = usage
        self.limiter.complete(reservation, usage)
        return response


@st.cache_resource(show_spinner=False)
def get_usage_repository() -> AzureUsageRepository:
    return AzureUsageRepository.from_environment()


def estimate_tokens(messages: list[Message]) -> int:
    characters = sum(len(message.content) for message in messages)
    return max(1, characters // 4 + len(messages) * 8)


def token_cost_eur(input_tokens: int, output_tokens: int, policy: UsagePolicy) -> float:
    return (
        input_tokens * policy.input_eur_per_million
        + output_tokens * policy.output_eur_per_million
    ) / 1_000_000


def _snapshot(events: list[UsageEvent], user_id: str, day: str) -> UsageSnapshot:
    user_events = [event for event in events if event.user_id == user_id]
    return UsageSnapshot(
        review_daily=sum(
            event.kind is CallKind.REVIEW and event.day == day for event in user_events
        ),
        review_monthly=sum(event.kind is CallKind.REVIEW for event in user_events),
        chat_daily=sum(
            event.kind is CallKind.CHAT and event.day == day for event in user_events
        ),
        chat_monthly=sum(event.kind is CallKind.CHAT for event in user_events),
        global_monthly_cost_eur=sum(event.cost_eur for event in events),
    )


def _event_to_entity(event: UsageEvent) -> dict[str, Any]:
    return {
        "PartitionKey": event.month,
        "RowKey": event.reservation_id,
        "day": event.day,
        "userId": event.user_id,
        "kind": event.kind.value,
        "status": event.status,
        "inputTokens": event.input_tokens,
        "outputTokens": event.output_tokens,
        "costEur": event.cost_eur,
        "createdAt": event.created_at,
    }


def _entity_to_event(entity: Any) -> UsageEvent:
    created_at = entity["createdAt"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return UsageEvent(
        reservation_id=str(entity["RowKey"]),
        month=str(entity["PartitionKey"]),
        day=str(entity["day"]),
        user_id=str(entity["userId"]),
        kind=CallKind(str(entity["kind"])),
        status=str(entity["status"]),
        input_tokens=int(entity["inputTokens"]),
        output_tokens=int(entity["outputTokens"]),
        cost_eur=float(entity["costEur"]),
        created_at=created_at.astimezone(UTC),
    )

