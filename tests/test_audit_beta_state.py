from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from azure.core.exceptions import HttpResponseError

from scripts.audit_beta_state import (
    AUTH_TABLE,
    DATA_TABLE,
    USAGE_TABLE,
    AuditError,
    read_runtime_audit,
    read_table_audit,
    run_az_json,
    summarize_auth,
    summarize_data,
    summarize_usage,
)

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)


def _auth_entities() -> list[dict]:
    return [
        {
            "PartitionKey": "auth",
            "RowKey": "user:owner-private-id",
            "provider": "aad",
            "role": "admin",
        },
        {
            "PartitionKey": "auth",
            "RowKey": "user:friend-private-id",
            "provider": "google",
            "role": "member",
            "status": "active",
        },
        {
            "PartitionKey": "auth",
            "RowKey": "invite:private-hash",
            "expiresAt": NOW + timedelta(days=1),
            "usedBy": "",
        },
        {
            "PartitionKey": "auth",
            "RowKey": "invite:expired-private-hash",
            "expiresAt": NOW - timedelta(days=1),
            "usedBy": "",
        },
    ]


def _data_entities() -> list[dict]:
    return [
        {
            "PartitionKey": "owner-private-id",
            "RowKey": "private-dataset-id",
            "rawBlob": "raw/owner-private-id/private.csv",
            "normalizedBlob": "normalized/owner-private-id/private.parquet",
            "rawExpiresAt": NOW + timedelta(days=3),
            "normalizedExpiresAt": NOW + timedelta(days=30),
        },
        {
            "PartitionKey": "friend-private-id",
            "RowKey": "__profile__",
            "bodyWeightKg": 84.5,
        },
    ]


def _usage_entities() -> list[dict]:
    return [
        {
            "PartitionKey": "2026-08",
            "RowKey": "private-reservation-id",
            "userId": "owner-private-id",
            "kind": "chat",
            "status": "completed",
            "inputTokens": 120,
            "outputTokens": 30,
            "costEur": 0.0012,
        },
        {
            "PartitionKey": "2026-08",
            "RowKey": "state",
            "globalCostEur": 0.0012,
        },
    ]


def test_summaries_are_aggregate_and_redact_private_fields() -> None:
    report = {
        "authorization": summarize_auth(_auth_entities(), now=NOW),
        "data": summarize_data(_data_entities(), now=NOW),
        "usage": summarize_usage(_usage_entities()),
    }
    encoded = json.dumps(report)

    assert report["authorization"]["members"] == {
        "total": 2,
        "by_provider": {"aad": 1, "google": 1},
        "by_role": {"admin": 1, "member": 1},
        "by_status": {"active": 2},
    }
    assert report["authorization"]["active_invites"] == 1
    assert report["data"]["datasets"] == 1
    assert report["data"]["profiles"] == 1
    assert report["data"]["raw"]["earliest_active_expiry"] == "2026-08-24"
    assert report["usage"]["calls"] == 1
    assert report["usage"]["cost_eur"] == 0.0012

    for private_value in (
        "owner-private-id",
        "friend-private-id",
        "private-hash",
        "private-dataset-id",
        "private.csv",
        "private.parquet",
        "private-reservation-id",
        "84.5",
    ):
        assert private_value not in encoded


@pytest.mark.parametrize(
    ("summarizer", "entities", "message"),
    [
        (
            lambda values: summarize_auth(values, now=NOW),
            [{"RowKey": "user:x", "provider": "email@example.com"}],
            "provider",
        ),
        (
            lambda values: summarize_data(values, now=NOW),
            [{"RowKey": "dataset", "rawExpiresAt": "not-a-date"}],
            "rawExpiresAt",
        ),
        (
            summarize_usage,
            [
                {
                    "RowKey": "reservation",
                    "kind": "chat",
                    "status": "completed",
                    "inputTokens": "many",
                    "outputTokens": 1,
                    "costEur": 0,
                }
            ],
            "usage totals",
        ),
    ],
)
def test_malformed_rows_fail_without_echoing_private_values(
    summarizer,
    entities: list[dict],
    message: str,
) -> None:
    with pytest.raises(AuditError, match=message) as caught:
        summarizer(entities)

    assert "email@example.com" not in str(caught.value)
    assert "not-a-date" not in str(caught.value)


class _ReadOnlyTable:
    def __init__(self, *, listed: list[dict] | None = None, queried: list[dict] | None = None):
        self.listed = listed or []
        self.queried = queried or []
        self.queries: list[str] = []

    def list_entities(self):
        return list(self.listed)

    def query_entities(self, query: str):
        self.queries.append(query)
        return list(self.queried)

    def create_entity(self, entity):
        raise AssertionError("audit attempted a mutation")

    update_entity = create_entity
    delete_entity = create_entity


class _TableService:
    def __init__(self) -> None:
        self.tables = {
            AUTH_TABLE: _ReadOnlyTable(listed=_auth_entities()),
            DATA_TABLE: _ReadOnlyTable(listed=_data_entities()),
            USAGE_TABLE: _ReadOnlyTable(queried=_usage_entities()),
        }

    def get_table_client(self, name: str):
        return self.tables[name]


def test_table_audit_uses_only_read_operations_and_current_month() -> None:
    service = _TableService()

    report = read_table_audit(service, now=NOW)

    assert report["authorization"]["members"]["total"] == 2
    assert service.tables[USAGE_TABLE].queries == ["PartitionKey eq '2026-08'"]


def test_table_authorization_failure_has_an_actionable_redacted_error() -> None:
    class DeniedTable:
        def list_entities(self):
            raise HttpResponseError("private Azure response")

    class DeniedService:
        def get_table_client(self, name: str):
            return DeniedTable()

    with pytest.raises(AuditError, match="temporary Storage Table diagnostic role") as exc:
        read_table_audit(DeniedService(), now=NOW)

    assert "private Azure response" not in str(exc.value)


def _runner(command, **kwargs):
    assert kwargs == {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    assert "--subscription" in command
    if "containerapp" in command:
        payload = {
            "properties": {
                "latestRevisionName": "ca-irontrail-example--revision",
                "runningStatus": "Running",
                "template": {"scale": {"minReplicas": 0, "maxReplicas": 1}},
            }
        }
    else:
        payload = [
            {"name": "gpt-5-mini", "sku": {"capacity": 20}},
            {"name": "gpt-5.6-luna", "sku": {"capacity": 30}},
            {"name": "other-private-deployment", "sku": {"capacity": 99}},
        ]
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")


def test_runtime_audit_reports_only_configured_capacity() -> None:
    report = read_runtime_audit(
        subscription_id="subscription",
        resource_group="rg",
        container_app="app",
        foundry_account="foundry",
        review_deployment="gpt-5-mini",
        chat_deployment="gpt-5.6-luna",
        runner=_runner,
        command_prefix=["az"],
    )
    encoded = json.dumps(report)

    assert report["container_app"]["max_replicas"] == 1
    assert report["foundry_capacity_ktpm"] == {
        "gpt-5-mini": 20,
        "gpt-5.6-luna": 30,
    }
    assert "other-private-deployment" not in encoded
    assert "subscription" not in encoded


def test_az_cli_failure_does_not_echo_stderr() -> None:
    def failed_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "private principal and resource details",
        )

    with pytest.raises(AuditError, match="exit code 1") as exc:
        run_az_json(
            ["containerapp", "show"],
            subscription_id="subscription",
            runner=failed_runner,
            command_prefix=["az"],
        )

    assert "private principal" not in str(exc.value)
