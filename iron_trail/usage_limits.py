"""Per-user and global limits for hosted Coach model calls."""
from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

import streamlit as st

from . import runtime
from .cloud_storage import azure_table_client
from .coach.providers import Message, Provider, TokenUsage

_USAGE_STATE_ROW = "state"


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
    reservation_ttl_seconds: int = 900

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
            reservation_ttl_seconds=runtime.env_int(
                "IRONTRAIL_AI_RESERVATION_TTL_SECONDS", 900, minimum=300
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
    expires_at: datetime | None = None


@dataclass(frozen=True)
class UsageSnapshot:
    review_daily: int
    review_monthly: int
    chat_daily: int
    chat_monthly: int
    global_monthly_cost_eur: float


class UsageRepository(Protocol):
    def reserve(
        self,
        event: UsageEvent,
        *,
        policy: UsagePolicy,
        now: datetime,
    ) -> UsageEvent: ...

    def complete(
        self,
        reservation: UsageEvent,
        usage: TokenUsage,
        *,
        policy: UsagePolicy,
    ) -> UsageEvent: ...

    def cancel(self, reservation: UsageEvent) -> None: ...

    def snapshot(self, user_id: str, current: date) -> UsageSnapshot: ...


class AzureUsageRepository:
    def __init__(self, table_client: Any) -> None:
        self._table = table_client

    @classmethod
    def from_environment(cls) -> "AzureUsageRepository":
        table_name = os.environ.get("IRONTRAIL_USAGE_TABLE", "IronTrailUsage")
        return cls(azure_table_client(table_name))

    def reserve(
        self,
        event: UsageEvent,
        *,
        policy: UsagePolicy,
        now: datetime,
    ) -> UsageEvent:
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError
        from azure.data.tables import TableTransactionError, UpdateMode

        for _ in range(6):
            try:
                state = self._get_or_create_state(event.month)
                events = self._list_month(event.month)
                active, expired = _partition_active(events, now)
                _enforce_limits(active, event, policy)

                state_update = dict(state)
                state_update["version"] = int(state.get("version", 0)) + 1
                operations: list[tuple] = [
                    (
                        "update",
                        state_update,
                        {
                            "etag": _entity_etag(state),
                            "match_condition": MatchConditions.IfNotModified,
                            "mode": UpdateMode.REPLACE,
                        },
                    ),
                    ("create", _event_to_entity(event)),
                ]
                operations.extend(
                    ("delete", _event_to_entity(item)) for item in expired[:90]
                )
                self._table.submit_transaction(operations)
                return event
            except UsageLimitExceeded:
                raise
            except TableTransactionError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to reserve AI usage.") from exc
            except AzureError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to reserve AI usage.") from exc
        raise UsageRepositoryError("AI usage changed concurrently; retry the request.")

    def complete(
        self,
        reservation: UsageEvent,
        usage: TokenUsage,
        *,
        policy: UsagePolicy,
    ) -> UsageEvent:
        event = UsageEvent(
            reservation_id=reservation.reservation_id,
            month=reservation.month,
            day=reservation.day,
            user_id=reservation.user_id,
            kind=reservation.kind,
            status="completed",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_eur=token_cost_eur(usage.input_tokens, usage.output_tokens, policy),
            created_at=reservation.created_at,
        )
        self._replace_event(reservation, event)
        return event

    def cancel(self, reservation: UsageEvent) -> None:
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        from azure.data.tables import TableTransactionError, UpdateMode

        for _ in range(6):
            try:
                state = self._get_or_create_state(reservation.month)
                stored = self._table.get_entity(
                    reservation.month, reservation.reservation_id
                )
                if stored.get("status") == "completed":
                    return
                state_update = dict(state)
                state_update["version"] = int(state.get("version", 0)) + 1
                self._table.submit_transaction(
                    [
                        (
                            "update",
                            state_update,
                            {
                                "etag": _entity_etag(state),
                                "match_condition": MatchConditions.IfNotModified,
                                "mode": UpdateMode.REPLACE,
                            },
                        ),
                        (
                            "delete",
                            stored,
                            {
                                "etag": _entity_etag(stored),
                                "match_condition": MatchConditions.IfNotModified,
                            },
                        ),
                    ]
                )
                return
            except ResourceNotFoundError:
                return
            except TableTransactionError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to release AI usage.") from exc
            except AzureError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to release AI usage.") from exc
        raise UsageRepositoryError("Unable to release concurrent AI usage.")

    def snapshot(self, user_id: str, current: date) -> UsageSnapshot:
        now = datetime.now(UTC)
        try:
            events, _ = _partition_active(
                self._list_month(current.strftime("%Y-%m")),
                now,
            )
        except Exception as exc:
            if isinstance(exc, UsageRepositoryError):
                raise
            raise UsageRepositoryError("Unable to read AI usage.") from exc
        return _snapshot(events, user_id, current.isoformat())

    def _replace_event(self, reservation: UsageEvent, completed: UsageEvent) -> None:
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        from azure.data.tables import TableTransactionError, UpdateMode

        for _ in range(6):
            try:
                state = self._get_or_create_state(reservation.month)
                stored = self._table.get_entity(
                    reservation.month, reservation.reservation_id
                )
                if stored.get("status") == "completed":
                    return
                state_update = dict(state)
                state_update["version"] = int(state.get("version", 0)) + 1
                self._table.submit_transaction(
                    [
                        (
                            "update",
                            state_update,
                            {
                                "etag": _entity_etag(state),
                                "match_condition": MatchConditions.IfNotModified,
                                "mode": UpdateMode.REPLACE,
                            },
                        ),
                        (
                            "update",
                            _event_to_entity(completed),
                            {
                                "etag": _entity_etag(stored),
                                "match_condition": MatchConditions.IfNotModified,
                                "mode": UpdateMode.REPLACE,
                            },
                        ),
                    ]
                )
                return
            except ResourceNotFoundError as exc:
                raise UsageRepositoryError("AI reservation no longer exists.") from exc
            except TableTransactionError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to record AI usage.") from exc
            except AzureError as exc:
                if getattr(exc, "status_code", None) not in {409, 412}:
                    raise UsageRepositoryError("Unable to record AI usage.") from exc
        raise UsageRepositoryError("Unable to record concurrent AI usage.")

    def _get_or_create_state(self, month: str) -> Any:
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        try:
            return self._table.get_entity(month, _USAGE_STATE_ROW)
        except ResourceNotFoundError:
            try:
                self._table.create_entity(
                    {
                        "PartitionKey": month,
                        "RowKey": _USAGE_STATE_ROW,
                        "version": 0,
                    }
                )
            except ResourceExistsError:
                pass
            return self._table.get_entity(month, _USAGE_STATE_ROW)

    def _list_month(self, month: str) -> list[UsageEvent]:
        from azure.core.exceptions import AzureError

        try:
            entities = self._table.query_entities(f"PartitionKey eq '{month}'")
            return [
                _entity_to_event(entity)
                for entity in entities
                if entity["RowKey"] != _USAGE_STATE_ROW
            ]
        except AzureError as exc:
            raise UsageRepositoryError("Unable to read AI usage.") from exc


class InMemoryUsageRepository:
    def __init__(self) -> None:
        self.events: dict[str, UsageEvent] = {}
        self._lock = threading.Lock()

    def reserve(
        self,
        event: UsageEvent,
        *,
        policy: UsagePolicy,
        now: datetime,
    ) -> UsageEvent:
        with self._lock:
            active, expired = _partition_active(list(self.events.values()), now)
            for item in expired:
                self.events.pop(item.reservation_id, None)
            _enforce_limits(active, event, policy)
            self.events[event.reservation_id] = event
            return event

    def complete(
        self,
        reservation: UsageEvent,
        usage: TokenUsage,
        *,
        policy: UsagePolicy,
    ) -> UsageEvent:
        with self._lock:
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
                    policy,
                ),
                created_at=reservation.created_at,
            )
            self.events[event.reservation_id] = event
            return event

    def cancel(self, reservation: UsageEvent) -> None:
        with self._lock:
            self.events.pop(reservation.reservation_id, None)

    def snapshot(self, user_id: str, current: date) -> UsageSnapshot:
        with self._lock:
            active, _ = _partition_active(
                [
                    event
                    for event in self.events.values()
                    if event.month == current.strftime("%Y-%m")
                ],
                datetime.now(UTC),
            )
            return _snapshot(active, user_id, current.isoformat())


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
        hold_seconds: int | None = None,
    ) -> UsageEvent:
        if input_tokens > self.policy.max_input_tokens:
            raise UsageLimitExceeded("This request is too large for the hosted Coach.")
        now = self.clock()
        event = UsageEvent(
            reservation_id=uuid.uuid4().hex,
            month=now.strftime("%Y-%m"),
            day=now.date().isoformat(),
            user_id=user_id,
            kind=kind,
            status="reserved",
            input_tokens=input_tokens,
            output_tokens=self.policy.max_output_tokens,
            cost_eur=token_cost_eur(
                input_tokens,
                self.policy.max_output_tokens,
                self.policy,
            ),
            created_at=now,
            expires_at=now
            + timedelta(
                seconds=max(
                    self.policy.reservation_ttl_seconds,
                    hold_seconds or 0,
                )
            ),
        )
        return self.repository.reserve(event, policy=self.policy, now=now)

    def complete(self, reservation: UsageEvent, usage: TokenUsage) -> UsageEvent:
        return self.repository.complete(reservation, usage, policy=self.policy)

    def cancel(self, reservation: UsageEvent) -> None:
        self.repository.cancel(reservation)

    def snapshot(self, user_id: str, today: date | None = None) -> UsageSnapshot:
        current = today or self.clock().date()
        return self.repository.snapshot(user_id, current)


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
            hold_seconds=max(300, int(timeout) + 60),
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
    return max(1, characters // 3 + len(messages) * 12)


def token_cost_eur(input_tokens: int, output_tokens: int, policy: UsagePolicy) -> float:
    return (
        input_tokens * policy.input_eur_per_million
        + output_tokens * policy.output_eur_per_million
    ) / 1_000_000


def _enforce_limits(
    active: list[UsageEvent],
    candidate: UsageEvent,
    policy: UsagePolicy,
) -> None:
    snapshot = _snapshot(active, candidate.user_id, candidate.day)
    daily_limit, monthly_limit = (
        (policy.review_daily, policy.review_monthly)
        if candidate.kind is CallKind.REVIEW
        else (policy.chat_daily, policy.chat_monthly)
    )
    daily_count = (
        snapshot.review_daily
        if candidate.kind is CallKind.REVIEW
        else snapshot.chat_daily
    )
    monthly_count = (
        snapshot.review_monthly
        if candidate.kind is CallKind.REVIEW
        else snapshot.chat_monthly
    )
    if daily_count >= daily_limit:
        raise UsageLimitExceeded("Your daily Coach allowance has been reached.")
    if monthly_count >= monthly_limit:
        raise UsageLimitExceeded("Your monthly Coach allowance has been reached.")
    if (
        snapshot.global_monthly_cost_eur + candidate.cost_eur
        > policy.global_monthly_cost_eur
    ):
        raise UsageLimitExceeded("The IronTrail Coach monthly budget has been reached.")


def _partition_active(
    events: list[UsageEvent],
    now: datetime,
) -> tuple[list[UsageEvent], list[UsageEvent]]:
    active: list[UsageEvent] = []
    expired: list[UsageEvent] = []
    for event in events:
        if (
            event.status == "reserved"
            and event.expires_at is not None
            and event.expires_at <= now
        ):
            expired.append(event)
        elif event.status in {"reserved", "completed"}:
            active.append(event)
    return active, expired


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
        "costEur": event.cost_eur,
        "createdAt": event.created_at,
        "day": event.day,
        "expiresAt": event.expires_at,
        "inputTokens": event.input_tokens,
        "kind": event.kind.value,
        "outputTokens": event.output_tokens,
        "status": event.status,
        "userId": event.user_id,
    }


def _entity_to_event(entity: Any) -> UsageEvent:
    created_at = _as_utc(entity["createdAt"])
    expires_at = entity.get("expiresAt")
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
        created_at=created_at,
        expires_at=_as_utc(expires_at) if expires_at else None,
    )


def _as_utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _entity_etag(entity: Any) -> str:
    metadata = getattr(entity, "metadata", None) or {}
    etag = metadata.get("etag") or entity.get("odata.etag")
    if not etag:
        raise UsageRepositoryError("AI usage state is missing concurrency metadata.")
    return str(etag)
