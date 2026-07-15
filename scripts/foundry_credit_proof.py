"""Run the bounded synthetic Microsoft Foundry credit proof."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.coach.providers.azure_foundry import AzureFoundryProvider

PROOF_CALL_COUNT = 10
MAX_INPUT_TOKENS = 2_000
MAX_OUTPUT_TOKENS = 300
MAX_SYNTHETIC_PROMPT_BYTES = 1_000
HARD_BUDGET_EUR = Decimal("0.05")
SAFETY_MULTIPLIER = Decimal("1.20")
CALL_INTERVAL_SECONDS = 6.5
MAX_429_ATTEMPTS = 3
API_VERSION = "2025-04-01-preview"
COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
MANAGEMENT_SCOPE = "https://management.azure.com/.default"
MANAGEMENT_API_VERSION = "2024-10-01"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALID_CALL_STATES = {
    "planned",
    "inflight",
    "completed",
    "uncertain",
    "retryable_429",
    "failed_terminal",
}
VALID_OUTCOMES = {
    "in_progress",
    "stopped_uncertain",
    "stopped_failure",
    "awaiting_cost_confirmation",
    "stopped_cost_overrun",
    "success",
}
EXPECTED_FIXED_TARGET = {
    "subscription_name": "Visual Studio Enterprise Subscription",
    "resource_group": "rg-IronTrail",
    "account": "irontrail-resource",
    "project": "irontrail",
    "endpoint": "https://irontrail-resource.cognitiveservices.azure.com/",
    "region": "swedencentral",
    "deployment_name": "gpt-5-mini",
    "model_name": "gpt-5-mini",
    "model_version": "2025-08-07",
    "model_format": "OpenAI",
    "sku": "DataZoneStandard",
    "capacity": 10,
    "rai_policy": "Microsoft.DefaultV2",
    "version_upgrade_option": "OnceCurrentVersionExpired",
    "quota_name": "OpenAI.DataZoneStandard.gpt-5-mini",
    "quota_limit": 300,
}
FORBIDDEN_PROMPT_FRAGMENTS = (
    "hevy",
    "health",
    "workout",
    "heart rate",
    "vault",
    "irontrail",
    "email address",
    "user id",
)


class ProofError(RuntimeError):
    """Raised when a proof guardrail prevents further work."""


@dataclass(frozen=True)
class ArmResponse:
    status: int
    headers: dict[str, str]
    body: dict[str, Any] | None


class ClaimValidatingCredential:
    def __init__(self, credential: Any, *, tenant_id: str, object_id: str) -> None:
        self._credential = credential
        self._tenant_id = tenant_id
        self._object_id = object_id

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        token = self._credential.get_token(*scopes, **kwargs)
        validate_access_token_claims(
            token.token,
            tenant_id=self._tenant_id,
            object_id=self._object_id,
        )
        return token


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(clock: Callable[[], datetime] = utc_now) -> str:
    return clock().astimezone(UTC).isoformat()


def parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ProofError(f"{field} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProofError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ProofError(f"{field} must include a timezone.")
    return parsed.astimezone(UTC)


def require_fresh_evidence(
    value: Any,
    *,
    field: str,
    now: datetime,
    maximum_age_seconds: int = 900,
) -> None:
    observed_at = parse_timestamp(value, field=field)
    age = (now.astimezone(UTC) - observed_at).total_seconds()
    if age < -60 or age > maximum_age_seconds:
        raise ProofError(f"{field} is outside the approved freshness window.")


def decimal_value(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProofError(f"{field} must be a decimal value.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ProofError(f"{field} must be a finite non-negative decimal value.")
    return parsed


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def buffered_call_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_eur_per_million: Decimal,
    output_eur_per_million: Decimal,
) -> Decimal:
    raw_cost = (
        Decimal(input_tokens) / Decimal(1_000_000) * input_eur_per_million
        + Decimal(output_tokens) / Decimal(1_000_000) * output_eur_per_million
    )
    return raw_cost * SAFETY_MULTIPLIER


def maximum_buffered_call_cost(pricing: dict[str, Any]) -> Decimal:
    return buffered_call_cost(
        MAX_INPUT_TOKENS,
        MAX_OUTPUT_TOKENS,
        input_eur_per_million=decimal_value(
            pricing["input_eur_per_million"], field="input_eur_per_million"
        ),
        output_eur_per_million=decimal_value(
            pricing["output_eur_per_million"], field="output_eur_per_million"
        ),
    )


def proof_worst_case_cost(pricing: dict[str, Any]) -> Decimal:
    return maximum_buffered_call_cost(pricing) * PROOF_CALL_COUNT


def fetch_live_pricing(
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    params = {
        "currencyCode": "EUR",
        "$filter": (
            "armRegionName eq 'swedencentral' "
            "and contains(meterName, 'GPT 5 Mini')"
        ),
        "$top": "1000",
    }
    source_url = (
        "https://prices.azure.com/api/retail/prices?"
        + url_parse.urlencode(params)
    )
    request = url_request.Request(source_url, headers={"Accept": "application/json"})
    try:
        with url_request.urlopen(request, timeout=30.0) as response:
            payload = json.loads(response.read())
    except (url_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProofError("Unable to load the live Azure retail price card.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("Items"), list):
        raise ProofError("Azure retail pricing returned an unexpected JSON shape.")

    meter_names = {
        "input": "GPT 5 Mini Inpt DZone 1M Tokens",
        "output": "GPT 5 Mini outpt DZone 1M Tokens",
    }
    matches: dict[str, dict[str, Any]] = {}
    for kind, meter_name in meter_names.items():
        rows = [
            item
            for item in payload["Items"]
            if isinstance(item, dict)
            and item.get("meterName") == meter_name
            and item.get("armRegionName") == "swedencentral"
            and item.get("currencyCode") == "EUR"
            and item.get("unitOfMeasure") == "1M"
            and item.get("serviceName") == "Foundry Models"
            and item.get("productName") == "Azure OpenAI GPT5"
            and item.get("type") == "Consumption"
            and item.get("retailPrice") == item.get("unitPrice")
        ]
        if len(rows) != 1:
            raise ProofError(
                f"Expected one authoritative Azure price row for {meter_name}, "
                f"found {len(rows)}."
            )
        if decimal_value(rows[0]["retailPrice"], field=meter_name) <= 0:
            raise ProofError(f"Azure returned a non-positive price for {meter_name}.")
        matches[kind] = rows[0]

    return {
        "observed_at": timestamp(clock),
        "source_url": source_url,
        "source_kind": "azure-retail-prices-api",
        "currency": "EUR",
        "input_meter": meter_names["input"],
        "output_meter": meter_names["output"],
        "input_eur_per_million": decimal_text(
            decimal_value(matches["input"]["retailPrice"], field="input price")
        ),
        "output_eur_per_million": decimal_text(
            decimal_value(matches["output"]["retailPrice"], field="output price")
        ),
        "input_effective_start_date": matches["input"]["effectiveStartDate"],
        "output_effective_start_date": matches["output"]["effectiveStartDate"],
    }


def build_synthetic_messages(index: int, nonce: str) -> list[Message]:
    if not 1 <= index <= PROOF_CALL_COUNT:
        raise ProofError(f"Call index must be between 1 and {PROOF_CALL_COUNT}.")
    payload = {
        "kind": "synthetic-proof",
        "index": index,
        "nonce": nonce,
        "values": [index, index + 1],
    }
    messages = [
        Message(
            "system",
            "Return exactly two concise bullet points using only the supplied synthetic object.",
        ),
        Message(
            "user",
            f"Format this object: {json.dumps(payload, sort_keys=True, separators=(',', ':'))}",
        ),
    ]
    validate_synthetic_messages(messages)
    return messages


def validate_synthetic_messages(messages: list[Message]) -> None:
    combined = "\n".join(message.content for message in messages)
    try:
        encoded = combined.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProofError("Synthetic proof prompts must be ASCII-only.") from exc
    if len(encoded) > MAX_SYNTHETIC_PROMPT_BYTES:
        raise ProofError("Synthetic proof prompt exceeds the byte safety ceiling.")
    lowered = combined.lower()
    forbidden = [fragment for fragment in FORBIDDEN_PROMPT_FRAGMENTS if fragment in lowered]
    if forbidden:
        raise ProofError(f"Synthetic proof prompt contains forbidden context: {forbidden[0]}.")


def derived_resource_ids(target: dict[str, Any]) -> dict[str, str]:
    account_resource_id = (
        f"/subscriptions/{target['subscription_id']}/resourceGroups/{target['resource_group']}"
        f"/providers/Microsoft.CognitiveServices/accounts/{target['account']}"
    )
    return {
        "account_resource_id": account_resource_id,
        "project_resource_id": f"{account_resource_id}/projects/{target['project']}",
        "deployment_resource_id": (
            f"{account_resource_id}/deployments/{target['deployment_name']}"
        ),
    }


def validate_target(target: dict[str, Any]) -> None:
    mismatches = {
        key: {"expected": expected, "observed": target.get(key)}
        for key, expected in EXPECTED_FIXED_TARGET.items()
        if target.get(key) != expected
    }
    if mismatches:
        raise ProofError(f"Proof target differs from the approved configuration: {mismatches}.")
    for field in ("subscription_id", "tenant_id"):
        if not isinstance(target.get(field), str) or not target[field]:
            raise ProofError(f"Proof target is missing {field}.")
    expected_ids = derived_resource_ids(target)
    observed_ids = {key: target.get(key) for key in expected_ids}
    if observed_ids != expected_ids:
        raise ProofError(
            f"Proof resource IDs do not match the approved target: {observed_ids}."
        )


def expected_cost_query(resource_group: str) -> dict[str, Any]:
    return {
        "type": "ActualCost",
        "timeframe": "MonthToDate",
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ServiceName"},
                {"type": "Dimension", "name": "ResourceId"},
            ],
            "filter": {
                "dimensions": {
                    "name": "ResourceGroupName",
                    "operator": "In",
                    "values": [resource_group],
                }
            },
        },
    }


def validate_ledger_structure(ledger: dict[str, Any]) -> None:
    if ledger.get("schema_version") != 1:
        raise ProofError("Unsupported proof ledger schema.")
    revision = ledger.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ProofError("Proof ledger revision is invalid.")
    target = ledger.get("target")
    if not isinstance(target, dict):
        raise ProofError("Proof ledger target is missing.")
    validate_target(target)
    identity = ledger.get("identity")
    if not isinstance(identity, dict) or not identity.get("object_id") or not identity.get("upn"):
        raise ProofError("Proof ledger identity is incomplete.")
    deployment = ledger.get("deployment")
    if not isinstance(deployment, dict):
        raise ProofError("Proof deployment evidence is missing.")
    allowed_deployment_states = {
        "not_submitted",
        "intent_recorded",
        "submitting",
        "submitted",
        "provisioning",
        "ambiguous",
        "succeeded",
        "failed",
        "not_allowed",
    }
    if deployment.get("state") not in allowed_deployment_states:
        raise ProofError("Proof deployment state is invalid.")
    if deployment["state"] in {"not_submitted", "not_allowed"}:
        if deployment.get("payload") is not None or deployment.get("payload_sha256") is not None:
            raise ProofError("Unsubmitted deployment evidence contains an unexpected payload.")
    else:
        payload = deployment.get("payload")
        if payload != expected_deployment_payload(ledger):
            raise ProofError("Recorded deployment payload is invalid.")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if deployment.get("payload_sha256") != hashlib.sha256(serialized).hexdigest():
            raise ProofError("Recorded deployment payload hash is invalid.")
    calls = ledger.get("calls")
    if not isinstance(calls, list) or len(calls) != PROOF_CALL_COUNT:
        raise ProofError("Proof ledger must contain exactly ten call records.")
    indices = [call.get("index") for call in calls if isinstance(call, dict)]
    if indices != list(range(1, PROOF_CALL_COUNT + 1)):
        raise ProofError("Proof call indices must be unique and ordered from 1 through 10.")
    nonces = [call.get("nonce") for call in calls]
    if any(not isinstance(nonce, str) or not nonce for nonce in nonces):
        raise ProofError("Every proof call requires a persisted nonce.")
    if len(set(nonces)) != PROOF_CALL_COUNT:
        raise ProofError("Every proof call nonce must be unique.")
    completed_prefix = True
    for call in calls:
        state = call.get("state")
        if state not in VALID_CALL_STATES:
            raise ProofError(f"Unsupported call state: {state}.")
        attempts = call.get("attempts")
        if not isinstance(attempts, int) or not 0 <= attempts <= MAX_429_ATTEMPTS:
            raise ProofError("Proof call attempts are invalid.")
        if state == "completed":
            if not completed_prefix:
                raise ProofError("Completed proof calls must form an ordered prefix.")
            input_tokens = call.get("input_tokens")
            output_tokens = call.get("output_tokens")
            if (
                type(input_tokens) is not int
                or type(output_tokens) is not int
                or not 0 <= input_tokens <= MAX_INPUT_TOKENS
                or not 0 <= output_tokens <= MAX_OUTPUT_TOKENS
            ):
                raise ProofError("Completed proof call token usage is invalid.")
            if (
                attempts < 1
                or not call.get("submitted_at")
                or not call.get("completed_at")
                or not (call.get("request_id") or call.get("response_id"))
                or call.get("error_code") is not None
            ):
                raise ProofError("Completed proof call evidence is incomplete.")
            expected_cost = buffered_call_cost(
                input_tokens,
                output_tokens,
                input_eur_per_million=decimal_value(
                    ledger["pricing"]["input_eur_per_million"],
                    field="input_eur_per_million",
                ),
                output_eur_per_million=decimal_value(
                    ledger["pricing"]["output_eur_per_million"],
                    field="output_eur_per_million",
                ),
            )
            if decimal_value(
                call.get("estimated_cost_eur"),
                field="estimated_cost_eur",
            ) != expected_cost:
                raise ProofError("Completed proof call cost evidence is invalid.")
            continue
        completed_prefix = False
        if state == "planned":
            empty_fields = (
                "submitted_at",
                "completed_at",
                "request_id",
                "response_id",
                "input_tokens",
                "output_tokens",
                "estimated_cost_eur",
                "error_code",
            )
            if attempts != 0 or any(call.get(field) is not None for field in empty_fields):
                raise ProofError("Planned proof call contains unexpected execution evidence.")
        elif state == "inflight":
            if attempts < 1 or not call.get("submitted_at") or call.get("completed_at"):
                raise ProofError("Inflight proof call evidence is incomplete.")
        elif state == "retryable_429":
            if (
                not 1 <= attempts < MAX_429_ATTEMPTS
                or not call.get("submitted_at")
                or not call.get("completed_at")
                or call.get("request_id") is not None
                or call.get("response_id") is not None
                or call.get("error_code") != "429"
            ):
                raise ProofError("Retryable 429 evidence is invalid.")
        else:
            if (
                attempts < 1
                or not call.get("submitted_at")
                or not call.get("completed_at")
                or not call.get("error_code")
                or decimal_value(
                    call.get("estimated_cost_eur"),
                    field="estimated_cost_eur",
                )
                != maximum_buffered_call_cost(ledger["pricing"])
            ):
                raise ProofError(f"{state} proof call evidence is incomplete.")
    quota = ledger.get("quota")
    if not isinstance(quota, dict):
        raise ProofError("Proof quota evidence is missing.")
    if quota.get("expected_after") != EXPECTED_FIXED_TARGET["capacity"]:
        raise ProofError("Proof quota target is not the approved 10K TPM allocation.")
    baseline = quota.get("baseline")
    expected_baseline = {
        "subscription_id": target["subscription_id"],
        "location": target["region"],
        "usage_name": target["quota_name"],
        "current_value": 0,
        "limit": target["quota_limit"],
    }
    if not isinstance(baseline, dict):
        raise ProofError("Proof quota baseline is missing.")
    if {key: baseline.get(key) for key in expected_baseline} != expected_baseline:
        raise ProofError("Proof quota baseline does not match the approved live state.")
    for field in ("pre_deploy", "after"):
        observation = quota.get(field)
        if observation is None:
            continue
        if not isinstance(observation, dict):
            raise ProofError(f"Proof quota {field} evidence is invalid.")
        expected_current = 0 if field == "pre_deploy" else EXPECTED_FIXED_TARGET["capacity"]
        expected = dict(expected_baseline)
        expected["current_value"] = expected_current
        if {key: observation.get(key) for key in expected} != expected:
            raise ProofError(f"Proof quota {field} evidence does not match the target.")
    call_checks = quota.get("call_checks")
    if not isinstance(call_checks, list) or len(call_checks) > PROOF_CALL_COUNT:
        raise ProofError("Proof quota call checks are invalid.")
    checked_indices = []
    for check in call_checks:
        if not isinstance(check, dict):
            raise ProofError("Proof quota call check has an invalid shape.")
        index = check.get("call_index")
        observation = check.get("observation")
        if not isinstance(index, int) or not isinstance(observation, dict):
            raise ProofError("Proof quota call check is incomplete.")
        expected = dict(expected_baseline)
        expected["current_value"] = EXPECTED_FIXED_TARGET["capacity"]
        if {key: observation.get(key) for key in expected} != expected:
            raise ProofError("Proof quota call check does not match the live target.")
        checked_indices.append(index)
    if checked_indices != sorted(set(checked_indices)):
        raise ProofError("Proof quota call checks must be unique and ordered.")
    executed_indices = {
        call["index"] for call in calls if call.get("state") != "planned"
    }
    if not executed_indices.issubset(set(checked_indices)):
        raise ProofError("An executed proof call is missing its live quota check.")
    cost_baseline = ledger.get("cost_baseline")
    if not isinstance(cost_baseline, dict) or cost_baseline.get("rows") != []:
        raise ProofError("Proof cost baseline must record zero resource-group rows.")
    if cost_baseline.get("query") != expected_cost_query(target["resource_group"]):
        raise ProofError("Proof cost baseline query does not match the approved filter.")
    if not cost_baseline.get("request_id"):
        raise ProofError("Proof cost baseline is missing its Azure request ID.")
    baseline_column_names = [
        column.get("name") for column in cost_baseline.get("columns", [])
    ]
    if baseline_column_names != ["Cost", "ServiceName", "ResourceId", "Currency"]:
        raise ProofError("Proof cost baseline columns are invalid.")
    parse_timestamp(
        cost_baseline.get("observed_at"),
        field="cost_baseline.observed_at",
    )
    cost_checks = ledger.get("cost_checks")
    if not isinstance(cost_checks, list):
        raise ProofError("Proof cost checks are invalid.")
    all_completed = all(call["state"] == "completed" for call in calls)
    if cost_checks and not all_completed:
        raise ProofError("Proof cost checks require ten completed calls.")
    latest_completion = (
        max(
            parse_timestamp(call["completed_at"], field="call.completed_at")
            for call in calls
        )
        if all_completed
        else None
    )
    request_ids = {cost_baseline.get("request_id")}
    positive_cost_seen = False
    overrun_seen = False
    for check in cost_checks:
        if not isinstance(check, dict):
            raise ProofError("Proof cost check has an invalid shape.")
        if check.get("query") != cost_baseline["query"]:
            raise ProofError("Proof cost check used an unexpected query.")
        request_id = check.get("request_id")
        if not request_id or request_id in request_ids:
            raise ProofError("Proof cost check request IDs must be unique.")
        request_ids.add(request_id)
        checked_at = parse_timestamp(
            check.get("checked_at"),
            field="cost_check.checked_at",
        )
        if latest_completion is not None and checked_at < latest_completion:
            raise ProofError("Proof cost check predates the completed calls.")
        columns = check.get("columns")
        rows = check.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ProofError("Proof cost check response is invalid.")
        foundry_rows = validated_foundry_cost_rows(ledger, columns, rows)
        cost_index = [column.get("name") for column in columns].index("Cost")
        foundry_cost = sum(
            (decimal_value(row[cost_index], field="Cost") for row in foundry_rows),
            Decimal("0"),
        )
        if check.get("foundry_rows") != foundry_rows:
            raise ProofError("Proof cost check Foundry rows are inconsistent.")
        if check.get("foundry_charge_observed") != bool(foundry_rows):
            raise ProofError("Proof cost check charge flag is inconsistent.")
        if decimal_value(
            check.get("foundry_cost_eur"),
            field="foundry_cost_eur",
        ) != foundry_cost:
            raise ProofError("Proof cost check total is inconsistent.")
        positive_cost_seen = positive_cost_seen or foundry_cost > 0
        overrun_seen = overrun_seen or foundry_cost > HARD_BUDGET_EUR

    outcome = ledger.get("outcome")
    if outcome not in VALID_OUTCOMES:
        raise ProofError("Proof outcome is invalid.")
    has_uncertain = any(call["state"] == "uncertain" for call in calls)
    has_failure = any(call["state"] == "failed_terminal" for call in calls)
    if outcome == "success" and not (
        all_completed and positive_cost_seen and not overrun_seen
    ):
        raise ProofError("Proof success lacks completed calls and valid cost evidence.")
    if outcome == "stopped_cost_overrun" and not (all_completed and overrun_seen):
        raise ProofError("Proof cost-overrun outcome lacks matching evidence.")
    if outcome == "awaiting_cost_confirmation" and not (
        all_completed and not positive_cost_seen and not overrun_seen
    ):
        raise ProofError("Proof cost-confirmation state is inconsistent.")
    if outcome == "stopped_uncertain" and not has_uncertain:
        raise ProofError("Proof uncertain outcome lacks an uncertain call.")
    if outcome == "stopped_failure" and not has_failure:
        raise ProofError("Proof failure outcome lacks a terminal call.")
    if outcome == "in_progress" and cost_checks:
        raise ProofError("Proof cannot be in progress after cost checks begin.")


@contextmanager
def exclusive_ledger_lock(ledger_path: Path):
    ensure_external_ledger_path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger_path.with_name(f"{ledger_path.name}.lock")
    handle = lock_path.open("a+b")
    try:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ProofError("Another process holds the proof ledger lock.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def initialize_ledger(
    ledger_path: Path,
    *,
    target: dict[str, Any],
    identity: dict[str, Any],
    billing_preflight: dict[str, Any],
    pricing: dict[str, Any],
    quota_baseline: dict[str, Any],
    cost_baseline: dict[str, Any],
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    ensure_external_ledger_path(ledger_path)
    target = dict(target)
    target.setdefault("quota_name", EXPECTED_FIXED_TARGET["quota_name"])
    target.setdefault("quota_limit", EXPECTED_FIXED_TARGET["quota_limit"])
    target.update(derived_resource_ids(target))
    validate_target(target)
    with exclusive_ledger_lock(ledger_path):
        if ledger_path.exists():
            raise ProofError(f"Proof ledger already exists: {ledger_path}")

        now_value = clock().astimezone(UTC)
        require_fresh_evidence(
            billing_preflight.get("observed_at"),
            field="billing_preflight.observed_at",
            now=now_value,
        )
        require_fresh_evidence(
            pricing.get("observed_at"),
            field="pricing.observed_at",
            now=now_value,
        )
        require_fresh_evidence(
            quota_baseline.get("observed_at"),
            field="quota_baseline.observed_at",
            now=now_value,
        )
        require_fresh_evidence(
            cost_baseline.get("observed_at"),
            field="cost_baseline.observed_at",
            now=now_value,
        )
        if not str(billing_preflight.get("source_url", "")).startswith(
            "https://portal.azure.com/"
        ):
            raise ProofError("Billing evidence must come from the signed-in Azure portal.")
        if (
            billing_preflight.get("qualifier") != "remaining_credit"
            or billing_preflight.get("subscription_name") != target["subscription_name"]
            or billing_preflight.get("subscription_id") != target["subscription_id"]
        ):
            raise ProofError("Billing evidence does not match the target subscription.")
        if pricing.get("source_kind") != "azure-retail-prices-api":
            raise ProofError("Pricing evidence must come from the Azure retail prices API.")
        if not str(pricing.get("source_url", "")).startswith(
            "https://prices.azure.com/api/retail/prices?"
        ):
            raise ProofError("Pricing source URL is not authoritative.")
        if (
            decimal_value(
                pricing.get("input_eur_per_million"),
                field="input_eur_per_million",
            )
            <= 0
            or decimal_value(
                pricing.get("output_eur_per_million"),
                field="output_eur_per_million",
            )
            <= 0
        ):
            raise ProofError("Live Foundry token prices must be positive.")
        remaining_credit = decimal_value(
            billing_preflight["remaining_credit_eur"], field="remaining_credit_eur"
        )
        if remaining_credit <= HARD_BUDGET_EUR:
            raise ProofError("Remaining credit must be greater than the proof budget.")

        worst_case = proof_worst_case_cost(pricing)
        if worst_case > HARD_BUDGET_EUR:
            raise ProofError(
                f"Buffered proof worst case {decimal_text(worst_case)} EUR exceeds "
                f"{decimal_text(HARD_BUDGET_EUR)} EUR."
            )

        now = now_value.isoformat()
        pricing = dict(pricing)
        pricing["safety_multiplier"] = decimal_text(SAFETY_MULTIPLIER)
        pricing["maximum_input_tokens"] = MAX_INPUT_TOKENS * PROOF_CALL_COUNT
        pricing["maximum_output_tokens"] = MAX_OUTPUT_TOKENS * PROOF_CALL_COUNT
        pricing["buffered_worst_case_eur"] = decimal_text(worst_case)
        pricing["hard_budget_eur"] = decimal_text(HARD_BUDGET_EUR)
        cost_query = expected_cost_query(target["resource_group"])
        if cost_baseline.get("query") != cost_query:
            raise ProofError("Live cost baseline query does not match the approved filter.")
        if cost_baseline.get("rows") != []:
            raise ProofError("The resource group no longer has a zero-cost baseline.")
        baseline_columns = [column.get("name") for column in cost_baseline.get("columns", [])]
        if baseline_columns != ["Cost", "ServiceName", "ResourceId", "Currency"]:
            raise ProofError("Live cost baseline columns do not match the expected response.")
        if not cost_baseline.get("request_id"):
            raise ProofError("Live cost baseline is missing its Azure request ID.")
        expected_quota_baseline = {
            "subscription_id": target["subscription_id"],
            "location": target["region"],
            "usage_name": target["quota_name"],
            "current_value": 0,
            "limit": target["quota_limit"],
        }
        observed_quota_baseline = {
            key: quota_baseline.get(key) for key in expected_quota_baseline
        }
        if observed_quota_baseline != expected_quota_baseline:
            raise ProofError(
                "Live quota baseline differs from the approved 300K TPM / zero-use state."
            )

        ledger = {
            "schema_version": 1,
            "revision": 0,
            "proof_run_id": secrets.token_hex(16),
            "created_at": now,
            "updated_at": now,
            "target": target,
            "identity": dict(identity),
            "billing_preflight": dict(billing_preflight),
            "pricing": pricing,
            "deployment": {
                "intent_recorded_at": None,
                "submitted_at": None,
                "state": "not_submitted",
                "payload": None,
                "payload_sha256": None,
                "request_id": None,
                "readback": None,
                "error_code": None,
            },
            "quota": {
                "baseline": dict(quota_baseline),
                "pre_deploy": None,
                "expected_after": EXPECTED_FIXED_TARGET["capacity"],
                "after": None,
                "last_observation": dict(quota_baseline),
                "call_checks": [],
                "verified_at": None,
            },
            "calls": [
                {
                    "index": index,
                    "nonce": secrets.token_urlsafe(12),
                    "state": "planned",
                    "attempts": 0,
                    "submitted_at": None,
                    "completed_at": None,
                    "request_id": None,
                    "response_id": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "estimated_cost_eur": None,
                    "error_code": None,
                }
                for index in range(1, PROOF_CALL_COUNT + 1)
            ],
            "cost_baseline": dict(cost_baseline),
            "cost_checks": [],
            "outcome": "in_progress",
        }
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        return ledger


def ensure_external_ledger_path(ledger_path: Path) -> None:
    resolved = ledger_path.expanduser().resolve()
    if resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents:
        raise ProofError("The private proof ledger must be outside the Git repository.")


def load_ledger(ledger_path: Path) -> dict[str, Any]:
    ensure_external_ledger_path(ledger_path)
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProofError(f"Proof ledger does not exist: {ledger_path}") from exc
    except json.JSONDecodeError as exc:
        raise ProofError(f"Proof ledger is not valid JSON: {ledger_path}") from exc
    if not isinstance(payload, dict):
        raise ProofError("Proof ledger must contain a JSON object.")
    validate_ledger_structure(payload)
    return payload


def save_ledger(
    ledger_path: Path,
    ledger: dict[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
    lock_held: bool = False,
) -> None:
    ensure_external_ledger_path(ledger_path)
    if not lock_held:
        with exclusive_ledger_lock(ledger_path):
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        return
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    expected_revision = ledger.get("revision")
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise ProofError("Proof ledger revision is invalid.")
    if ledger_path.exists():
        try:
            current = json.loads(ledger_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProofError("Cannot update a corrupt proof ledger.") from exc
        current_revision = current.get("revision") if isinstance(current, dict) else None
        if current_revision != expected_revision:
            raise ProofError(
                f"Proof ledger changed concurrently: expected revision {expected_revision}, "
                f"observed {current_revision}."
            )
    elif expected_revision != 0:
        raise ProofError("Proof ledger disappeared during an update.")
    ledger["revision"] = expected_revision + 1
    ledger["updated_at"] = timestamp(clock)
    validate_ledger_structure(ledger)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ledger_path.name}.",
        suffix=".tmp",
        dir=ledger_path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(ledger, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, ledger_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def record_deployment_intent(
    ledger_path: Path,
    payload: dict[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        return record_deployment_intent_locked(
            ledger_path,
            ledger,
            payload,
            clock=clock,
        )


def expected_deployment_payload(ledger: dict[str, Any]) -> dict[str, Any]:
    target = ledger["target"]
    return {
        "sku": {
            "name": target["sku"],
            "capacity": int(target["capacity"]),
        },
        "properties": {
            "model": {
                "format": target["model_format"],
                "name": target["model_name"],
                "version": target["model_version"],
            },
            "raiPolicyName": target["rai_policy"],
            "versionUpgradeOption": target["version_upgrade_option"],
        },
    }


def record_deployment_intent_locked(
    ledger_path: Path,
    ledger: dict[str, Any],
    payload: dict[str, Any],
    *,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    deployment = ledger["deployment"]
    if deployment["state"] != "not_submitted":
        raise ProofError("Deployment intent can only be recorded once.")
    expected_payload = expected_deployment_payload(ledger)
    if payload != expected_payload:
        raise ProofError("Deployment payload differs from the approved configuration.")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    deployment["intent_recorded_at"] = timestamp(clock)
    deployment["state"] = "intent_recorded"
    deployment["payload"] = payload
    deployment["payload_sha256"] = hashlib.sha256(serialized).hexdigest()
    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
    return ledger


def record_deployment_submitted(
    ledger_path: Path,
    *,
    request_id: str | None,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        deployment = ledger["deployment"]
        if deployment["state"] != "intent_recorded":
            raise ProofError("Deployment submission does not match the recorded intent.")
        deployment["submitted_at"] = timestamp(clock)
        deployment["state"] = "submitted"
        deployment["request_id"] = request_id
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        return ledger


def record_deployment_readback(
    ledger_path: Path,
    readback: dict[str, Any],
    account_snapshot: dict[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        return record_deployment_readback_locked(
            ledger_path,
            ledger,
            readback,
            account_snapshot,
            clock=clock,
        )


def record_deployment_readback_locked(
    ledger_path: Path,
    ledger: dict[str, Any],
    readback: dict[str, Any],
    account_snapshot: dict[str, Any],
    *,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    deployment = ledger["deployment"]
    if deployment["state"] not in {
        "intent_recorded",
        "submitting",
        "submitted",
        "provisioning",
        "ambiguous",
    }:
        raise ProofError("Deployment readback is not expected in the current ledger state.")
    target = ledger["target"]
    properties = readback.get("properties") or {}
    model = properties.get("model") or {}
    sku = readback.get("sku") or {}
    account_properties = account_snapshot.get("properties") or {}
    observed = {
        "resource_id": readback.get("id"),
        "name": readback.get("name"),
        "account_resource_id": account_snapshot.get("id"),
        "account_location": account_snapshot.get("location"),
        "account_provisioning_state": account_properties.get("provisioningState"),
        "provisioning_state": properties.get("provisioningState"),
        "sku": sku.get("name"),
        "capacity": sku.get("capacity"),
        "model_format": model.get("format"),
        "model_name": model.get("name"),
        "model_version": model.get("version"),
        "rai_policy": properties.get("raiPolicyName"),
        "version_upgrade_option": properties.get("versionUpgradeOption"),
    }
    expected = {
        "resource_id": target["deployment_resource_id"],
        "name": target["deployment_name"],
        "account_resource_id": target["account_resource_id"],
        "account_location": target["region"],
        "account_provisioning_state": "Succeeded",
        "provisioning_state": "Succeeded",
        "sku": target["sku"],
        "capacity": int(target["capacity"]),
        "model_format": target["model_format"],
        "model_name": target["model_name"],
        "model_version": target["model_version"],
        "rai_policy": target["rai_policy"],
        "version_upgrade_option": target["version_upgrade_option"],
    }
    if observed != expected:
        raise ProofError(f"Deployment readback mismatch: expected {expected}, observed {observed}.")
    deployment["state"] = "succeeded"
    deployment["readback"] = observed
    deployment["verified_at"] = timestamp(clock)
    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
    return ledger


def verify_quota_convergence(
    ledger_path: Path,
    *,
    quota_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] = utc_now,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        validate_deployment_ready(ledger)
        quota_reader = quota_reader or read_live_quota
        quota = ledger["quota"]
        baseline = quota["baseline"]
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            observation = quota_reader(ledger)
            quota["last_observation"] = observation
            identity_fields = ("subscription_id", "location", "usage_name", "limit")
            if any(observation.get(field) != baseline.get(field) for field in identity_fields):
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                raise ProofError("Live quota identity or limit changed after deployment.")
            current_value = observation.get("current_value")
            if current_value == EXPECTED_FIXED_TARGET["capacity"]:
                quota["after"] = observation
                quota["verified_at"] = timestamp(clock)
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                return ledger
            if current_value != 0:
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                raise ProofError(
                    f"Unexpected live quota usage after deployment: {current_value}."
                )
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            sleep(poll_interval_seconds)
        raise ProofError("Quota did not converge to exactly 10K TPM before the timeout.")


def check_live_cost(
    ledger_path: Path,
    *,
    cost_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        validate_inference_ready(ledger)
        if ledger["outcome"] != "awaiting_cost_confirmation":
            raise ProofError("Cost checks are allowed only after all ten proof calls.")
        if not all(call["state"] == "completed" for call in ledger["calls"]):
            raise ProofError("Cost checks require ten valid completed call records.")
        cost_reader = cost_reader or read_live_cost
        evidence = cost_reader(ledger)
        now_value = clock().astimezone(UTC)
        require_fresh_evidence(
            evidence.get("observed_at"),
            field="cost_check.observed_at",
            now=now_value,
            maximum_age_seconds=300,
        )
        latest_call = max(
            parse_timestamp(call["completed_at"], field="call.completed_at")
            for call in ledger["calls"]
        )
        observed_at = parse_timestamp(
            evidence["observed_at"],
            field="cost_check.observed_at",
        )
        if observed_at < latest_call:
            raise ProofError("Cost evidence predates the completed proof calls.")
        request_id = evidence.get("request_id")
        if not request_id:
            raise ProofError("Cost evidence is missing an Azure request ID.")
        previous_request_ids = {
            ledger["cost_baseline"]["request_id"],
            *(check["request_id"] for check in ledger["cost_checks"]),
        }
        if request_id in previous_request_ids:
            raise ProofError("Cost evidence reused an earlier Azure request ID.")
        query = evidence.get("query")
        columns = evidence.get("columns")
        rows = evidence.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ProofError("Cost evidence has an unexpected JSON shape.")
        expected_query = ledger["cost_baseline"]["query"]
        if query != expected_query:
            raise ProofError("Cost query changed during the proof.")
        foundry_rows = validated_foundry_cost_rows(ledger, columns, rows)
        cost_index = [column.get("name") for column in columns].index("Cost")
        foundry_cost = sum(
            (decimal_value(row[cost_index], field="Cost") for row in foundry_rows),
            Decimal("0"),
        )
        ledger["cost_checks"].append(
            {
                "checked_at": evidence["observed_at"],
                "request_id": request_id,
                "query": query,
                "columns": columns,
                "rows": rows,
                "foundry_charge_observed": bool(foundry_rows),
                "foundry_rows": foundry_rows,
                "foundry_cost_eur": decimal_text(foundry_cost),
            }
        )
        if foundry_cost > HARD_BUDGET_EUR:
            ledger["outcome"] = "stopped_cost_overrun"
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            raise ProofError("Foundry cost evidence exceeds the EUR 0.05 proof ceiling.")
        if foundry_cost > 0:
            ledger["outcome"] = "success"
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        return ledger


def validated_foundry_cost_rows(
    ledger: dict[str, Any],
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
) -> list[list[Any]]:
    column_names = [column.get("name") for column in columns]
    required = {"Cost", "ServiceName", "ResourceId", "Currency"}
    if not required.issubset(column_names):
        raise ProofError("Cost response is missing required columns.")
    indices = {name: column_names.index(name) for name in required}
    account_resource_id = ledger["target"]["account_resource_id"].lower()
    recognized_services = {
        "foundry models",
        "azure openai service",
        "azure ai services",
        "cognitive services",
    }
    foundry_rows = []
    for row in rows:
        if len(row) != len(columns):
            raise ProofError("Cost response row does not match its columns.")
        cost = decimal_value(row[indices["Cost"]], field="Cost")
        service = str(row[indices["ServiceName"]] or "").lower()
        resource_id = str(row[indices["ResourceId"]] or "").lower()
        currency = str(row[indices["Currency"]] or "").upper()
        recognized_resource = (
            resource_id == account_resource_id
            or resource_id.startswith(f"{account_resource_id}/")
        )
        if cost > 0 and recognized_resource:
            if currency != "EUR":
                raise ProofError("Target-resource cost evidence is not in EUR.")
            if service not in recognized_services:
                raise ProofError(
                    f"Target-resource cost used an unexpected service name: {service}."
                )
        if (
            cost > 0
            and currency == "EUR"
            and recognized_resource
            and service in recognized_services
        ):
            foundry_rows.append(row)
    return foundry_rows


def verify_cli_identity(ledger: dict[str, Any]) -> None:
    account = run_az_json("account", "show", "-o", "json")
    user = run_az_json("ad", "signed-in-user", "show", "-o", "json")
    target = ledger["target"]
    identity = ledger["identity"]
    observed_account = {
        "subscription_name": account.get("name"),
        "subscription_id": account.get("id"),
        "tenant_id": account.get("tenantId"),
    }
    expected_account = {
        "subscription_name": target["subscription_name"],
        "subscription_id": target["subscription_id"],
        "tenant_id": target["tenant_id"],
    }
    if observed_account != expected_account:
        raise ProofError(
            f"Azure CLI account mismatch: expected {expected_account}, observed {observed_account}."
        )
    observed_identity = {
        "object_id": user.get("id"),
        "upn": user.get("userPrincipalName"),
    }
    expected_identity = {
        "object_id": identity["object_id"],
        "upn": identity["upn"],
    }
    if observed_identity != expected_identity:
        raise ProofError(
            f"Azure CLI identity mismatch: expected {expected_identity}, "
            f"observed {observed_identity}."
        )


def run_az_json(*args: str) -> dict[str, Any]:
    payload = run_az_json_value(*args)
    if not isinstance(payload, dict):
        raise ProofError("Azure CLI returned an unexpected JSON shape.")
    return payload


def run_az_json_value(*args: str) -> Any:
    executable = shutil.which("az") or shutil.which("az.cmd")
    if not executable:
        raise ProofError("Azure CLI is not available.")
    process = subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise ProofError(f"Azure CLI command failed: {detail[:1_000]}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ProofError("Azure CLI returned invalid JSON.") from exc
    return payload


def read_live_quota(
    ledger: dict[str, Any],
    *,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    target = ledger["target"]
    payload = run_az_json_value(
        "cognitiveservices",
        "usage",
        "list",
        "--location",
        target["region"],
        "--subscription",
        target["subscription_id"],
        "-o",
        "json",
    )
    if not isinstance(payload, list):
        raise ProofError("Azure quota response has an unexpected JSON shape.")
    matches = [
        item
        for item in payload
        if isinstance(item, dict)
        and (item.get("name") or {}).get("value") == target["quota_name"]
    ]
    if len(matches) != 1:
        raise ProofError(
            f"Expected one live quota row for {target['quota_name']}, found {len(matches)}."
        )
    match = matches[0]
    current_value = match.get("currentValue")
    limit = match.get("limit")
    if not isinstance(current_value, (int, float)) or int(current_value) != current_value:
        raise ProofError("Azure quota current usage is not an integer.")
    if not isinstance(limit, (int, float)) or int(limit) != limit:
        raise ProofError("Azure quota limit is not an integer.")
    return {
        "observed_at": timestamp(clock),
        "subscription_id": target["subscription_id"],
        "location": target["region"],
        "usage_name": target["quota_name"],
        "current_value": int(current_value),
        "limit": int(limit),
    }


def decode_access_token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ProofError("Azure CLI returned a non-JWT access token.")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofError("Azure CLI access-token claims could not be decoded.") from exc
    if not isinstance(claims, dict):
        raise ProofError("Azure CLI access-token claims have an unexpected shape.")
    return claims


def validate_access_token_claims(token: str, *, tenant_id: str, object_id: str) -> None:
    claims = decode_access_token_claims(token)
    observed = {"tid": claims.get("tid"), "oid": claims.get("oid")}
    expected = {"tid": tenant_id, "oid": object_id}
    if observed != expected:
        raise ProofError(
            f"Azure access-token identity mismatch: expected {expected}, observed {observed}."
        )


def build_validating_cli_credential(ledger: dict[str, Any], scope: str) -> ClaimValidatingCredential:
    from azure.identity import AzureCliCredential

    target = ledger["target"]
    identity = ledger["identity"]
    credential = AzureCliCredential(
        subscription=target["subscription_id"],
    )
    validating = ClaimValidatingCredential(
        credential,
        tenant_id=target["tenant_id"],
        object_id=identity["object_id"],
    )
    validating.get_token(scope)
    return validating


def build_live_provider(ledger: dict[str, Any]) -> AzureFoundryProvider:
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI

    target = ledger["target"]
    credential = build_validating_cli_credential(ledger, COGNITIVE_SCOPE)
    token_provider = get_bearer_token_provider(credential, COGNITIVE_SCOPE)
    client = AzureOpenAI(
        azure_endpoint=target["endpoint"],
        api_version=API_VERSION,
        azure_ad_token_provider=token_provider,
        max_retries=0,
    )
    return AzureFoundryProvider(
        endpoint=target["endpoint"],
        deployment=target["deployment_name"],
        api_version=API_VERSION,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        client=client,
    )


def deployment_url(target: dict[str, Any]) -> str:
    return (
        f"https://management.azure.com{target['deployment_resource_id']}"
        f"?api-version={MANAGEMENT_API_VERSION}"
    )


def account_url(target: dict[str, Any]) -> str:
    return (
        f"https://management.azure.com{target['account_resource_id']}"
        f"?api-version={MANAGEMENT_API_VERSION}"
    )


def arm_request(
    credential: Any,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout_seconds: float = 60.0,
) -> ArmResponse:
    token = credential.get_token(MANAGEMENT_SCOPE)
    encoded_body = (
        None
        if body is None
        else json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if method == "PUT":
        headers["If-None-Match"] = "*"
    request = url_request.Request(
        url,
        data=encoded_body,
        method=method,
        headers=headers,
    )
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read()
            return ArmResponse(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=parse_json_body(raw_body),
            )
    except url_error.HTTPError as exc:
        return ArmResponse(
            status=exc.code,
            headers={key.lower(): value for key, value in exc.headers.items()},
            body=parse_json_body(exc.read()),
        )


def parse_json_body(raw_body: bytes) -> dict[str, Any] | None:
    if not raw_body:
        return None
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofError("Azure Resource Manager returned a non-JSON response.") from exc
    if not isinstance(payload, dict):
        raise ProofError("Azure Resource Manager returned an unexpected JSON shape.")
    return payload


def arm_request_id(response: ArmResponse) -> str | None:
    for name in ("x-ms-request-id", "apim-request-id", "x-request-id"):
        if response.headers.get(name):
            return response.headers[name]
    return None


def arm_error_code(response: ArmResponse) -> str:
    error = (response.body or {}).get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    return f"http_{response.status}"


def arm_error_detail(response: ArmResponse) -> str:
    error = (response.body or {}).get("error")
    if isinstance(error, dict):
        code = error.get("code") or f"HTTP {response.status}"
        message = error.get("message") or "No error message returned."
        return f"{code}: {message}"
    return f"HTTP {response.status}"


def cost_management_url(target: dict[str, Any]) -> str:
    return (
        "https://management.azure.com"
        f"/subscriptions/{target['subscription_id']}"
        "/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    )


def read_live_cost(
    ledger: dict[str, Any],
    *,
    requester: Callable[..., ArmResponse] = arm_request,
    credential_factory: Callable[[dict[str, Any], str], Any] = (
        build_validating_cli_credential
    ),
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    target = ledger["target"]
    query = expected_cost_query(target["resource_group"])
    credential = credential_factory(ledger, MANAGEMENT_SCOPE)
    response = requester(
        credential,
        "POST",
        cost_management_url(target),
        query,
        60.0,
    )
    if response.status != 200 or not response.body:
        raise ProofError(f"Cost Management query failed: {arm_error_detail(response)}.")
    properties = response.body.get("properties") or {}
    columns = properties.get("columns")
    rows = properties.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ProofError("Cost Management returned an unexpected JSON shape.")
    request_id = arm_request_id(response)
    if not request_id:
        raise ProofError("Cost Management response is missing an Azure request ID.")
    return {
        "observed_at": timestamp(clock),
        "request_id": request_id,
        "query": query,
        "columns": columns,
        "rows": rows,
    }


def deploy_model_once(
    ledger_path: Path,
    *,
    requester: Callable[..., ArmResponse] = arm_request,
    credential_factory: Callable[[dict[str, Any], str], Any] = (
        build_validating_cli_credential
    ),
    quota_reader: Callable[[dict[str, Any]], dict[str, Any]] = read_live_quota,
    identity_checker: Callable[[dict[str, Any]], None] = verify_cli_identity,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] = utc_now,
    poll_timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        ledger = load_ledger(ledger_path)
        validate_ledger_structure(ledger)
        identity_checker(ledger)
        target = ledger["target"]
        deployment = ledger["deployment"]
        if deployment["state"] == "succeeded":
            validate_deployment_ready(ledger)
            return ledger
        if deployment["state"] in {"failed", "not_allowed"}:
            raise ProofError("The deployment ledger is already in a terminal state.")

        credential = credential_factory(ledger, MANAGEMENT_SCOPE)
        url = deployment_url(target)
        if deployment["state"] == "not_submitted":
            require_fresh_evidence(
                ledger["billing_preflight"].get("observed_at"),
                field="billing_preflight.observed_at",
                now=clock().astimezone(UTC),
            )
            if (
                decimal_value(
                    ledger["billing_preflight"].get("remaining_credit_eur"),
                    field="remaining_credit_eur",
                )
                <= HARD_BUDGET_EUR
            ):
                raise ProofError("Remaining credit no longer clears the proof ceiling.")
            quota = ledger["quota"]
            live_quota = quota_reader(ledger)
            baseline = quota["baseline"]
            comparable_fields = (
                "subscription_id",
                "location",
                "usage_name",
                "current_value",
                "limit",
            )
            if any(
                live_quota.get(field) != baseline.get(field)
                for field in comparable_fields
            ):
                raise ProofError("Live quota changed before the deployment PUT.")
            quota["pre_deploy"] = live_quota
            quota["last_observation"] = live_quota
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            existing = requester(credential, "GET", url, None, 60.0)
            if existing.status == 200:
                deployment["state"] = "not_allowed"
                deployment["error_code"] = "unexpected_existing_deployment"
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                raise ProofError("The target deployment already exists; no PUT was sent.")
            if existing.status != 404:
                raise ProofError(
                    f"Unable to prove deployment absence: {arm_error_detail(existing)}."
                )
            payload = expected_deployment_payload(ledger)
            record_deployment_intent_locked(
                ledger_path,
                ledger,
                payload,
                clock=clock,
            )
            deployment["state"] = "submitting"
            deployment["submitted_at"] = timestamp(clock)
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            try:
                response = requester(credential, "PUT", url, payload, 300.0)
            except (TimeoutError, socket.timeout, url_error.URLError) as exc:
                deployment["state"] = "ambiguous"
                deployment["error_code"] = type(exc).__name__
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            else:
                deployment["request_id"] = arm_request_id(response)
                if response.status not in {200, 201, 202}:
                    deployment["state"] = "failed"
                    deployment["error_code"] = arm_error_code(response)
                    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                    raise ProofError(
                        f"Model deployment failed without retry: {arm_error_detail(response)}."
                    )
                deployment["state"] = "provisioning"
                deployment["error_code"] = None
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        elif deployment["state"] not in {
            "intent_recorded",
            "submitting",
            "submitted",
            "provisioning",
            "ambiguous",
        }:
            raise ProofError(f"Unsupported deployment state: {deployment['state']}.")

        deadline = monotonic() + poll_timeout_seconds
        while monotonic() < deadline:
            readback_response = requester(credential, "GET", url, None, 60.0)
            if readback_response.status == 200 and readback_response.body:
                state = (readback_response.body.get("properties") or {}).get(
                    "provisioningState"
                )
                if state == "Succeeded":
                    account_response = requester(
                        credential,
                        "GET",
                        account_url(target),
                        None,
                        60.0,
                    )
                    if account_response.status != 200 or not account_response.body:
                        raise ProofError(
                            "Deployment succeeded but account readback could not be verified."
                        )
                    return record_deployment_readback_locked(
                        ledger_path,
                        ledger,
                        readback_response.body,
                        account_response.body,
                        clock=clock,
                    )
                if state == "Failed":
                    deployment["state"] = "failed"
                    deployment["error_code"] = "provisioning_failed"
                    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                    raise ProofError("Model deployment provisioning failed.")
                deployment["state"] = "provisioning"
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            elif readback_response.status not in {404, 429, 500, 502, 503, 504}:
                deployment["state"] = "ambiguous"
                deployment["error_code"] = arm_error_code(readback_response)
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                raise ProofError(
                    f"Deployment polling stopped: {arm_error_detail(readback_response)}."
                )
            sleep(poll_interval_seconds)

        deployment["state"] = "ambiguous"
        deployment["error_code"] = "poll_timeout"
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        raise ProofError("Deployment state remained ambiguous after read-only polling.")


def run_proof(
    ledger_path: Path,
    *,
    provider: Any | None = None,
    quota_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    identity_checker: Callable[[dict[str, Any]], None] = verify_cli_identity,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = utc_now,
) -> dict[str, Any]:
    with exclusive_ledger_lock(ledger_path):
        return run_proof_locked(
            ledger_path,
            provider=provider,
            quota_reader=quota_reader,
            identity_checker=identity_checker,
            sleep=sleep,
            clock=clock,
        )


def run_proof_locked(
    ledger_path: Path,
    *,
    provider: Any | None,
    quota_reader: Callable[[dict[str, Any]], dict[str, Any]] | None,
    identity_checker: Callable[[dict[str, Any]], None],
    sleep: Callable[[float], None],
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    ledger = load_ledger(ledger_path)
    validate_inference_ready(ledger)
    identity_checker(ledger)
    quota_reader = quota_reader or read_live_quota

    inflight = [call for call in ledger["calls"] if call["state"] == "inflight"]
    if inflight:
        for call in inflight:
            call["state"] = "uncertain"
            call["completed_at"] = timestamp(clock)
            call["error_code"] = "resume_after_inflight"
            call["estimated_cost_eur"] = decimal_text(
                maximum_buffered_call_cost(ledger["pricing"])
            )
        ledger["outcome"] = "stopped_uncertain"
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        raise ProofError("An inflight call was marked uncertain and will not be replayed.")

    blocking = [
        call for call in ledger["calls"] if call["state"] in {"uncertain", "failed_terminal"}
    ]
    if blocking:
        raise ProofError("The ledger contains a terminal or uncertain call; no more calls are allowed.")

    provider = provider or build_live_provider(ledger)
    for call in ledger["calls"]:
        if call["state"] == "completed":
            continue
        if call["state"] not in {"planned", "retryable_429"}:
            raise ProofError(f"Unsupported call state: {call['state']}.")
        execute_call(
            ledger_path,
            ledger,
            call,
            provider=provider,
            quota_reader=quota_reader,
            sleep=sleep,
            clock=clock,
        )
        if call["index"] < PROOF_CALL_COUNT:
            sleep(CALL_INTERVAL_SECONDS)

    if not all(call["state"] == "completed" for call in ledger["calls"]):
        raise ProofError("The proof stopped before all call indices completed.")
    ledger["outcome"] = "awaiting_cost_confirmation"
    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
    return ledger


def validate_deployment_ready(ledger: dict[str, Any]) -> None:
    validate_ledger_structure(ledger)
    target = ledger["target"]
    deployment = ledger["deployment"]
    if deployment["state"] != "succeeded" or not deployment.get("verified_at"):
        raise ProofError("The deployment is not verified as succeeded.")
    payload = deployment.get("payload")
    if payload != expected_deployment_payload(ledger):
        raise ProofError("The verified deployment payload differs from the recorded intent.")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if deployment.get("payload_sha256") != hashlib.sha256(serialized).hexdigest():
        raise ProofError("The deployment payload hash is invalid.")
    expected_readback = {
        "resource_id": target["deployment_resource_id"],
        "name": target["deployment_name"],
        "account_resource_id": target["account_resource_id"],
        "account_location": target["region"],
        "account_provisioning_state": "Succeeded",
        "provisioning_state": "Succeeded",
        "sku": target["sku"],
        "capacity": EXPECTED_FIXED_TARGET["capacity"],
        "model_format": target["model_format"],
        "model_name": target["model_name"],
        "model_version": target["model_version"],
        "rai_policy": target["rai_policy"],
        "version_upgrade_option": target["version_upgrade_option"],
    }
    if deployment.get("readback") != expected_readback:
        raise ProofError("The deployment readback no longer matches the approved target.")


def validate_inference_ready(ledger: dict[str, Any]) -> None:
    validate_deployment_ready(ledger)
    target = ledger["target"]
    quota = ledger["quota"]
    baseline = quota.get("baseline") or {}
    after = quota.get("after") or {}
    if (
        baseline.get("current_value") != 0
        or baseline.get("limit") != target["quota_limit"]
        or after.get("current_value") != EXPECTED_FIXED_TARGET["capacity"]
        or after.get("limit") != target["quota_limit"]
        or after.get("usage_name") != target["quota_name"]
        or after.get("location") != target["region"]
        or after.get("subscription_id") != target["subscription_id"]
        or not quota.get("verified_at")
    ):
        raise ProofError("The exact quota delta has not been verified.")


def validate_live_quota_for_call(
    ledger: dict[str, Any],
    observation: dict[str, Any],
    *,
    now: datetime,
) -> None:
    target = ledger["target"]
    require_fresh_evidence(
        observation.get("observed_at"),
        field="quota_call_check.observed_at",
        now=now,
        maximum_age_seconds=300,
    )
    expected = {
        "subscription_id": target["subscription_id"],
        "location": target["region"],
        "usage_name": target["quota_name"],
        "current_value": EXPECTED_FIXED_TARGET["capacity"],
        "limit": target["quota_limit"],
    }
    if {key: observation.get(key) for key in expected} != expected:
        raise ProofError("Live quota changed before a proof call.")


def execute_call(
    ledger_path: Path,
    ledger: dict[str, Any],
    call: dict[str, Any],
    *,
    provider: Any,
    quota_reader: Callable[[dict[str, Any]], dict[str, Any]],
    sleep: Callable[[float], None],
    clock: Callable[[], datetime],
) -> None:
    messages = build_synthetic_messages(int(call["index"]), str(call["nonce"]))
    pricing = ledger["pricing"]
    maximum_cost = maximum_buffered_call_cost(pricing)
    if used_budget(ledger) + maximum_cost > HARD_BUDGET_EUR:
        raise ProofError("The next call could exceed the hard proof budget.")

    while int(call["attempts"]) < MAX_429_ATTEMPTS:
        quota_observation = quota_reader(ledger)
        validate_live_quota_for_call(
            ledger,
            quota_observation,
            now=clock().astimezone(UTC),
        )
        call_checks = ledger["quota"]["call_checks"]
        replacement = {
            "call_index": call["index"],
            "observation": quota_observation,
        }
        existing_check = next(
            (check for check in call_checks if check["call_index"] == call["index"]),
            None,
        )
        if existing_check is None:
            call_checks.append(replacement)
        else:
            existing_check.update(replacement)
        ledger["quota"]["last_observation"] = quota_observation
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)

        call["attempts"] = int(call["attempts"]) + 1
        call["state"] = "inflight"
        call["submitted_at"] = timestamp(clock)
        call["completed_at"] = None
        call["error_code"] = None
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)

        try:
            response_text = provider.chat(messages, timeout=120.0)
        except Exception as exc:
            request_id = exception_request_id(exc) or getattr(
                provider, "last_request_id", None
            )
            response_id = getattr(provider, "last_response_id", None)
            kind = exception_kind(exc)
            call["request_id"] = request_id
            call["response_id"] = response_id
            call["completed_at"] = timestamp(clock)
            call["error_code"] = exception_error_code(exc)
            if (
                kind == "rate_limit"
                and not request_id
                and not response_id
                and call["attempts"] < MAX_429_ATTEMPTS
            ):
                call["state"] = "retryable_429"
                save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
                sleep(retry_delay_seconds(exc))
                continue
            if kind in {"timeout", "connection"} or request_id or response_id:
                call["state"] = "uncertain"
                ledger["outcome"] = "stopped_uncertain"
            else:
                call["state"] = "failed_terminal"
                ledger["outcome"] = "stopped_failure"
            call["estimated_cost_eur"] = decimal_text(maximum_cost)
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            raise ProofError(
                f"Proof call {call['index']} stopped in state {call['state']}: "
                f"{call['error_code']}."
            ) from exc

        usage = getattr(provider, "last_usage", None)
        request_id = getattr(provider, "last_request_id", None)
        response_id = getattr(provider, "last_response_id", None)
        del response_text
        if not isinstance(usage, TokenUsage):
            call["state"] = "uncertain"
            call["completed_at"] = timestamp(clock)
            call["request_id"] = request_id
            call["response_id"] = response_id
            call["estimated_cost_eur"] = decimal_text(maximum_cost)
            call["error_code"] = "missing_usage"
            ledger["outcome"] = "stopped_uncertain"
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            raise ProofError("Foundry returned no token usage; the call is uncertain.")
        if usage.input_tokens > MAX_INPUT_TOKENS or usage.output_tokens > MAX_OUTPUT_TOKENS:
            call["state"] = "failed_terminal"
            call["completed_at"] = timestamp(clock)
            call["request_id"] = request_id
            call["response_id"] = response_id
            call["input_tokens"] = usage.input_tokens
            call["output_tokens"] = usage.output_tokens
            call["estimated_cost_eur"] = decimal_text(maximum_cost)
            call["error_code"] = "token_ceiling_exceeded"
            ledger["outcome"] = "stopped_failure"
            save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
            raise ProofError("Foundry usage exceeded the approved token ceiling.")

        actual_cost = buffered_call_cost(
            usage.input_tokens,
            usage.output_tokens,
            input_eur_per_million=decimal_value(
                pricing["input_eur_per_million"], field="input_eur_per_million"
            ),
            output_eur_per_million=decimal_value(
                pricing["output_eur_per_million"], field="output_eur_per_million"
            ),
        )
        call.update(
            {
                "state": "completed",
                "completed_at": timestamp(clock),
                "request_id": request_id,
                "response_id": response_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "estimated_cost_eur": decimal_text(actual_cost),
                "error_code": None,
            }
        )
        save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
        return

    call["state"] = "failed_terminal"
    call["completed_at"] = timestamp(clock)
    call["estimated_cost_eur"] = decimal_text(maximum_cost)
    call["error_code"] = "429_retry_limit"
    ledger["outcome"] = "stopped_failure"
    save_ledger(ledger_path, ledger, clock=clock, lock_held=True)
    raise ProofError("Foundry rate-limit retries were exhausted.")


def used_budget(ledger: dict[str, Any]) -> Decimal:
    maximum_cost = maximum_buffered_call_cost(ledger["pricing"])
    total = Decimal("0")
    for call in ledger["calls"]:
        if call["state"] == "completed" and call["estimated_cost_eur"] is not None:
            total += decimal_value(call["estimated_cost_eur"], field="estimated_cost_eur")
        elif call["state"] in {"uncertain", "failed_terminal"}:
            total += maximum_cost
    return total


def exception_kind(exc: Exception) -> str:
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError
    except ImportError:
        return "other"
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, APITimeoutError):
        return "timeout"
    if isinstance(exc, APIConnectionError):
        return "connection"
    return "other"


def exception_request_id(exc: Exception) -> str | None:
    request_id = getattr(exc, "request_id", None)
    if request_id:
        return str(request_id)
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        value = (
            headers.get("apim-request-id")
            or headers.get("x-request-id")
            or headers.get("x-ms-request-id")
        )
        return str(value) if value else None
    return None


def exception_error_code(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return str(status_code)
    return type(exc).__name__


def retry_delay_seconds(exc: Exception) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        raw_delay = headers.get("retry-after") or headers.get("retry-after-ms")
        if raw_delay:
            try:
                delay = float(raw_delay)
            except ValueError:
                delay = CALL_INTERVAL_SECONDS
            if headers.get("retry-after-ms") == raw_delay:
                delay /= 1_000
            return min(max(delay, 1.0), 60.0)
    return CALL_INTERVAL_SECONDS


def sanitized_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    states: dict[str, int] = {}
    for call in ledger["calls"]:
        states[call["state"]] = states.get(call["state"], 0) + 1
    return {
        "proof_run_id": ledger["proof_run_id"],
        "outcome": ledger["outcome"],
        "deployment_state": ledger["deployment"]["state"],
        "quota": ledger["quota"],
        "call_states": states,
        "buffered_estimated_cost_eur": decimal_text(used_budget(ledger)),
        "hard_budget_eur": decimal_text(HARD_BUDGET_EUR),
        "cost_checks": len(ledger["cost_checks"]),
    }


def decimal_argument(value: str) -> Decimal:
    try:
        parsed = decimal_value(value, field="value")
    except ProofError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the private proof ledger.")
    init.add_argument("--ledger", type=Path, required=True)
    init.add_argument("--subscription-name", required=True)
    init.add_argument("--subscription-id", required=True)
    init.add_argument("--tenant-id", required=True)
    init.add_argument("--resource-group", default="rg-IronTrail")
    init.add_argument("--account", default="irontrail-resource")
    init.add_argument("--project", default="irontrail")
    init.add_argument("--endpoint", required=True)
    init.add_argument("--region", default="swedencentral")
    init.add_argument("--deployment-name", default="gpt-5-mini")
    init.add_argument("--model-name", default="gpt-5-mini")
    init.add_argument("--model-version", default="2025-08-07")
    init.add_argument("--model-format", default="OpenAI")
    init.add_argument("--sku", default="DataZoneStandard")
    init.add_argument("--capacity", type=int, default=10)
    init.add_argument("--rai-policy", default="Microsoft.DefaultV2")
    init.add_argument("--version-upgrade-option", default="OnceCurrentVersionExpired")
    init.add_argument("--expected-object-id", required=True)
    init.add_argument("--expected-upn", required=True)
    init.add_argument("--billing-source-url", required=True)
    init.add_argument("--billing-observed-at", required=True)
    init.add_argument("--remaining-credit-eur", type=decimal_argument, required=True)

    run = subparsers.add_parser("run", help="Run or resume the ten synthetic calls.")
    run.add_argument("--ledger", type=Path, required=True)

    deploy = subparsers.add_parser(
        "deploy",
        help="Submit the approved deployment PUT once and poll read-only.",
    )
    deploy.add_argument("--ledger", type=Path, required=True)

    quota = subparsers.add_parser(
        "verify-quota",
        help="Poll live quota until the exact 0 to 10K TPM delta is visible.",
    )
    quota.add_argument("--ledger", type=Path, required=True)

    cost = subparsers.add_parser(
        "check-cost",
        help="Query authenticated Cost Management evidence for the proof.",
    )
    cost.add_argument("--ledger", type=Path, required=True)

    summary = subparsers.add_parser("summary", help="Print a redacted proof summary.")
    summary.add_argument("--ledger", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            target = {
                "subscription_name": args.subscription_name,
                "subscription_id": args.subscription_id,
                "tenant_id": args.tenant_id,
                "resource_group": args.resource_group,
                "account": args.account,
                "project": args.project,
                "endpoint": args.endpoint,
                "region": args.region,
                "deployment_name": args.deployment_name,
                "model_name": args.model_name,
                "model_version": args.model_version,
                "model_format": args.model_format,
                "sku": args.sku,
                "capacity": args.capacity,
                "rai_policy": args.rai_policy,
                "version_upgrade_option": args.version_upgrade_option,
                "quota_name": EXPECTED_FIXED_TARGET["quota_name"],
                "quota_limit": EXPECTED_FIXED_TARGET["quota_limit"],
            }
            target.update(derived_resource_ids(target))
            identity = {
                "object_id": args.expected_object_id,
                "upn": args.expected_upn,
            }
            billing_preflight = {
                "observed_at": args.billing_observed_at,
                "source_url": args.billing_source_url,
                "qualifier": "remaining_credit",
                "subscription_name": args.subscription_name,
                "subscription_id": args.subscription_id,
                "remaining_credit_eur": decimal_text(args.remaining_credit_eur),
            }
            identity_stub = {"target": target, "identity": identity}
            verify_cli_identity(identity_stub)
            pricing = fetch_live_pricing()
            quota_baseline = read_live_quota(identity_stub)
            cost_baseline = read_live_cost(identity_stub)
            ledger = initialize_ledger(
                args.ledger,
                target=target,
                identity=identity,
                billing_preflight=billing_preflight,
                pricing=pricing,
                quota_baseline=quota_baseline,
                cost_baseline=cost_baseline,
            )
        elif args.command == "deploy":
            ledger = deploy_model_once(args.ledger)
        elif args.command == "verify-quota":
            ledger = verify_quota_convergence(args.ledger)
        elif args.command == "check-cost":
            ledger = check_live_cost(args.ledger)
        elif args.command == "run":
            ledger = run_proof(args.ledger)
        else:
            ledger = load_ledger(args.ledger)
        print(json.dumps(sanitized_summary(ledger), indent=2))
        return 0
    except ProofError as exc:
        print(f"Foundry credit proof stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
