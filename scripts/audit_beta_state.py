"""Print a redacted, read-only operational summary of the Azure beta."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from azure.core.exceptions import AzureError

AUTH_TABLE = "IronTrailAuth"
DATA_TABLE = "IronTrailData"
USAGE_TABLE = "IronTrailUsage"
PROFILE_ROW = "__profile__"
USAGE_STATE_ROW = "state"

_PROVIDERS = {"aad", "google"}
_ROLES = {"admin", "member"}
_USER_STATUSES = {"active", "suspended"}
_CALL_KINDS = {"review", "chat"}
_CALL_STATUSES = {"reserved", "completed", "failed"}


class AuditError(RuntimeError):
    """Raised when beta state cannot be audited safely and completely."""


def _as_utc(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise AuditError(f"An Azure table row has an invalid {field}.") from exc
    else:
        raise AuditError(f"An Azure table row is missing {field}.")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _required_choice(
    entity: Mapping[str, Any],
    field: str,
    allowed: set[str],
    *,
    table: str,
    default: str | None = None,
) -> str:
    value = str(entity.get(field) or default or "").strip().lower()
    if value not in allowed:
        raise AuditError(f"{table} contains an invalid {field} value.")
    return value


def summarize_auth(
    entities: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    providers: Counter[str] = Counter()
    roles: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    active_invites = 0

    for entity in entities:
        row_key = str(entity.get("RowKey", ""))
        if row_key.startswith("user:"):
            providers[
                _required_choice(entity, "provider", _PROVIDERS, table=AUTH_TABLE)
            ] += 1
            roles[_required_choice(entity, "role", _ROLES, table=AUTH_TABLE)] += 1
            statuses[
                _required_choice(
                    entity,
                    "status",
                    _USER_STATUSES,
                    table=AUTH_TABLE,
                    # The original owner row predates explicit suspension
                    # state; application reads the same omission as active.
                    default="active",
                )
            ] += 1
        elif row_key.startswith("invite:") and not entity.get("usedBy"):
            if _as_utc(entity.get("expiresAt"), field="expiresAt") > now:
                active_invites += 1

    return {
        "members": {
            "total": sum(providers.values()),
            "by_provider": dict(sorted(providers.items())),
            "by_role": dict(sorted(roles.items())),
            "by_status": dict(sorted(statuses.items())),
        },
        "active_invites": active_invites,
    }


def _earliest(values: list[datetime]) -> str | None:
    return min(values).date().isoformat() if values else None


def summarize_data(
    entities: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    dataset_count = 0
    profile_count = 0
    raw_active = 0
    raw_removed_or_expired = 0
    normalized_active = 0
    normalized_expired = 0
    raw_expiries: list[datetime] = []
    normalized_expiries: list[datetime] = []

    for entity in entities:
        row_key = str(entity.get("RowKey", ""))
        if row_key == PROFILE_ROW:
            profile_count += 1
            continue
        if not row_key:
            raise AuditError(f"{DATA_TABLE} contains a row without a RowKey.")

        dataset_count += 1
        raw_expiry = _as_utc(entity.get("rawExpiresAt"), field="rawExpiresAt")
        normalized_expiry = _as_utc(
            entity.get("normalizedExpiresAt"),
            field="normalizedExpiresAt",
        )

        if entity.get("rawBlob") and raw_expiry > now:
            raw_active += 1
            raw_expiries.append(raw_expiry)
        else:
            raw_removed_or_expired += 1

        if normalized_expiry > now:
            normalized_active += 1
            normalized_expiries.append(normalized_expiry)
        else:
            normalized_expired += 1

    return {
        "datasets": dataset_count,
        "profiles": profile_count,
        "raw": {
            "active": raw_active,
            "removed_or_expired": raw_removed_or_expired,
            "earliest_active_expiry": _earliest(raw_expiries),
        },
        "normalized": {
            "active": normalized_active,
            "expired": normalized_expired,
            "earliest_active_expiry": _earliest(normalized_expiries),
        },
    }


def summarize_usage(entities: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    kinds: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    input_tokens = 0
    output_tokens = 0
    cost_eur = 0.0

    for entity in entities:
        if str(entity.get("RowKey", "")) == USAGE_STATE_ROW:
            continue
        kind = _required_choice(entity, "kind", _CALL_KINDS, table=USAGE_TABLE)
        status = _required_choice(entity, "status", _CALL_STATUSES, table=USAGE_TABLE)
        try:
            input_tokens += int(entity["inputTokens"])
            output_tokens += int(entity["outputTokens"])
            cost_eur += float(entity["costEur"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError(f"{USAGE_TABLE} contains invalid usage totals.") from exc
        kinds[kind] += 1
        statuses[status] += 1

    return {
        "calls": sum(kinds.values()),
        "by_kind": dict(sorted(kinds.items())),
        "by_status": dict(sorted(statuses.items())),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_eur": round(cost_eur, 6),
    }


def read_table_audit(
    table_service: Any,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Read the three beta tables without invoking any mutation operation."""
    try:
        auth_entities = list(
            table_service.get_table_client(AUTH_TABLE).list_entities()
        )
        data_entities = list(
            table_service.get_table_client(DATA_TABLE).list_entities()
        )
        usage_entities = list(
            table_service.get_table_client(USAGE_TABLE).query_entities(
                f"PartitionKey eq '{now:%Y-%m}'"
            )
        )
    except AzureError as exc:
        raise AuditError(
            "Unable to read beta tables. Enable the temporary Storage "
            "Table diagnostic role and wait for RBAC propagation."
        ) from exc

    return {
        "authorization": summarize_auth(auth_entities, now=now),
        "data": summarize_data(data_entities, now=now),
        "usage_current_month": summarize_usage(usage_entities),
    }


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _azure_cli_prefix() -> list[str]:
    executable = shutil.which("az")
    if not executable:
        raise AuditError("Azure CLI is not installed or is not on PATH.")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
        # Azure CLI's Windows wrapper only forwards to its bundled Python.
        # Invoke that interpreter directly so untrusted shell parsing is never
        # introduced just to run a read-only command.
        python = path.parent.parent / "python.exe"
        if not python.is_file():
            raise AuditError("Azure CLI's bundled Python executable is missing.")
        return [str(python), "-IBm", "azure.cli"]
    return [executable]


def run_az_json(
    args: Sequence[str],
    *,
    subscription_id: str,
    runner: Runner = subprocess.run,
    command_prefix: Sequence[str] | None = None,
) -> Any:
    prefix = list(command_prefix) if command_prefix is not None else _azure_cli_prefix()
    command = [*prefix, *args, "--subscription", subscription_id, "--output", "json"]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AuditError("Azure CLI could not be started.") from exc
    if completed.returncode:
        operation = " ".join(args[:3])
        raise AuditError(
            f"Azure CLI query '{operation}' failed with exit code "
            f"{completed.returncode}."
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError("Azure CLI returned invalid JSON.") from exc


def read_runtime_audit(
    *,
    subscription_id: str,
    resource_group: str,
    container_app: str,
    foundry_account: str,
    review_deployment: str,
    chat_deployment: str,
    runner: Runner = subprocess.run,
    command_prefix: Sequence[str] | None = None,
) -> dict[str, Any]:
    app = run_az_json(
        [
            "containerapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            container_app,
        ],
        subscription_id=subscription_id,
        runner=runner,
        command_prefix=command_prefix,
    )
    deployments = run_az_json(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            foundry_account,
        ],
        subscription_id=subscription_id,
        runner=runner,
        command_prefix=command_prefix,
    )

    properties = app.get("properties") if isinstance(app, dict) else None
    if not isinstance(properties, dict):
        raise AuditError("Container Apps returned an invalid resource document.")
    revision = str(properties.get("latestRevisionName", ""))
    if not revision:
        raise AuditError("Container Apps did not report an active revision.")

    wanted = {review_deployment, chat_deployment}
    capacities: dict[str, int] = {}
    for deployment in deployments if isinstance(deployments, list) else []:
        name = str(deployment.get("name", ""))
        if name not in wanted:
            continue
        sku = deployment.get("sku")
        try:
            capacities[name] = int(sku["capacity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuditError(
                f"Foundry deployment {name!r} has invalid capacity metadata."
            ) from exc
    missing = wanted - capacities.keys()
    if missing:
        raise AuditError("Foundry did not report every configured model deployment.")

    scale = properties.get("template", {}).get("scale", {})
    return {
        "container_app": {
            "latest_revision": revision,
            "running_status": str(properties.get("runningStatus", "unknown")),
            "min_replicas": int(scale.get("minReplicas", 0)),
            "max_replicas": int(scale.get("maxReplicas", 0)),
        },
        "foundry_capacity_ktpm": dict(sorted(capacities.items())),
    }


def _required(value: str | None, name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise AuditError(f"{name} is required.")
    return cleaned


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subscription-id",
        default=os.environ.get("AZURE_SUBSCRIPTION_ID"),
    )
    parser.add_argument(
        "--resource-group",
        default=os.environ.get("AZURE_RESOURCE_GROUP", "rg-IronTrail"),
    )
    parser.add_argument(
        "--storage-account",
        default=os.environ.get("IRONTRAIL_STORAGE_ACCOUNT_NAME"),
    )
    parser.add_argument(
        "--container-app",
        default=os.environ.get("SERVICE_WEB_NAME"),
    )
    parser.add_argument(
        "--foundry-account",
        default=os.environ.get("IRONTRAIL_FOUNDRY_ACCOUNT_NAME"),
    )
    parser.add_argument(
        "--review-deployment",
        default=os.environ.get("IRONTRAIL_AI_REVIEW_DEPLOYMENT"),
    )
    parser.add_argument(
        "--chat-deployment",
        default=os.environ.get("IRONTRAIL_AI_CHAT_DEPLOYMENT"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        subscription_id = _required(args.subscription_id, "--subscription-id")
        resource_group = _required(args.resource_group, "--resource-group")
        storage_account = _required(args.storage_account, "--storage-account")
        container_app = _required(args.container_app, "--container-app")
        foundry_account = _required(args.foundry_account, "--foundry-account")
        review_deployment = _required(args.review_deployment, "--review-deployment")
        chat_deployment = _required(args.chat_deployment, "--chat-deployment")

        from azure.data.tables import TableServiceClient
        from azure.identity import AzureCliCredential

        now = datetime.now(UTC)
        table_service = TableServiceClient(
            endpoint=f"https://{storage_account}.table.core.windows.net",
            credential=AzureCliCredential(),
        )
        report = {
            "audited_at": now.isoformat(),
            **read_table_audit(table_service, now=now),
            "runtime": read_runtime_audit(
                subscription_id=subscription_id,
                resource_group=resource_group,
                container_app=container_app,
                foundry_account=foundry_account,
                review_deployment=review_deployment,
                chat_deployment=chat_deployment,
            ),
        }
    except AuditError as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
