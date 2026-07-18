from __future__ import annotations

import base64
import json
from datetime import timedelta

import pytest

from iron_trail.auth import (
    Identity,
    InMemoryAuthRepository,
    InvitationError,
    hash_invite_code,
    identity_from_headers,
)
from iron_trail.cloud_storage import AzureAuthRepository


class _Entity(dict):
    def __init__(self, value, etag):
        super().__init__(value)
        self.metadata = {"etag": etag}


class _FakeTable:
    def __init__(self) -> None:
        self.entities = {}
        self.version = 0
        self.transactions = []

    def _store(self, entity):
        self.version += 1
        key = (entity["PartitionKey"], entity["RowKey"])
        self.entities[key] = _Entity(dict(entity), f'etag-{self.version}')

    def get_entity(self, partition, row):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.entities[(partition, row)]
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc

    def create_entity(self, entity):
        self._store(entity)

    def query_entities(self, query):
        if "RowKey ge 'user:'" in query:
            prefix = "user:"
        elif "RowKey ge 'invite:'" in query:
            prefix = "invite:"
        else:
            prefix = ""
        return [
            entity
            for (_, row), entity in self.entities.items()
            if row.startswith(prefix)
        ]

    def update_entity(self, entity, **kwargs):
        self._store(entity)

    def submit_transaction(self, operations):
        self.transactions.append(operations)
        for operation in operations:
            verb, entity = operation[:2]
            if verb in {"create", "update"}:
                self._store(entity)
            elif verb == "delete":
                self.entities.pop((entity["PartitionKey"], entity["RowKey"]), None)


def test_identity_uses_immutable_provider_and_principal() -> None:
    first = Identity("aad", "principal-1", "First name")
    renamed = Identity("aad", "principal-1", "Changed name")
    other_provider = Identity("google", "principal-1", "First name")

    assert first.user_id == renamed.user_id
    assert first.user_id != other_provider.user_id


def test_identity_parses_easy_auth_claim_payload() -> None:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {
                "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
                "val": "object-123",
            },
            {"typ": "name", "val": "Tester"},
        ],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    identity = identity_from_headers({"X-MS-CLIENT-PRINCIPAL": encoded})

    assert identity == Identity("aad", "object-123", "Tester")


def test_bootstrap_invite_creates_the_only_initial_admin() -> None:
    repo = InMemoryAuthRepository()
    bootstrap_code = "owner-bootstrap-code"

    owner = repo.redeem(
        Identity("aad", "owner", "Owner"),
        bootstrap_code,
        bootstrap_hash=hash_invite_code(bootstrap_code),
        bootstrap_owner_id="owner",
        max_users=5,
    )

    assert owner.is_admin
    with pytest.raises(InvitationError, match="invalid or expired"):
        repo.redeem(
            Identity("aad", "second-owner", "Second"),
            bootstrap_code,
            bootstrap_hash=hash_invite_code(bootstrap_code),
            bootstrap_owner_id="owner",
            max_users=5,
        )


def test_admin_issues_single_use_invite() -> None:
    repo = InMemoryAuthRepository()
    bootstrap_code = "owner-bootstrap-code"
    owner = repo.redeem(
        Identity("aad", "owner", "Owner"),
        bootstrap_code,
        bootstrap_hash=hash_invite_code(bootstrap_code),
        bootstrap_owner_id="owner",
        max_users=2,
    )
    code = repo.issue_invite(owner, ttl=timedelta(hours=1), max_users=2)

    member = repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )

    assert member.role == "member"
    with pytest.raises(InvitationError):
        repo.redeem(
            Identity("google", "other", "Other"),
            code,
            bootstrap_hash="",
            bootstrap_owner_id="owner",
            max_users=3,
        )


def test_azure_repository_uses_conditional_transactions() -> None:
    table = _FakeTable()
    repo = AzureAuthRepository(table)
    bootstrap_code = "owner-bootstrap-code"
    owner = repo.redeem(
        Identity("aad", "owner", "Owner"),
        bootstrap_code,
        bootstrap_hash=hash_invite_code(bootstrap_code),
        bootstrap_owner_id="owner",
        max_users=2,
    )
    code = repo.issue_invite(owner, ttl=timedelta(hours=1), max_users=2)
    repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )

    update_kwargs = [
        operation[2]
        for transaction in table.transactions
        for operation in transaction
        if operation[0] == "update"
    ]
    assert update_kwargs
    assert all(kwargs.get("etag") for kwargs in update_kwargs)
    assert all(kwargs.get("match_condition") is not None for kwargs in update_kwargs)


@pytest.mark.parametrize(
    "identity",
    [
        Identity("aad", "wrong-owner", "Wrong owner"),
        Identity("google", "owner", "Wrong provider"),
    ],
)
def test_bootstrap_invite_is_bound_to_expected_aad_owner(identity: Identity) -> None:
    repo = InMemoryAuthRepository()
    bootstrap_code = "owner-bootstrap-code"

    with pytest.raises(InvitationError, match="invalid or expired"):
        repo.redeem(
            identity,
            bootstrap_code,
            bootstrap_hash=hash_invite_code(bootstrap_code),
            bootstrap_owner_id="owner",
            max_users=1,
        )

    assert repo.users == {}


def test_azure_bootstrap_is_bound_to_expected_aad_owner() -> None:
    table = _FakeTable()
    repo = AzureAuthRepository(table)
    bootstrap_code = "owner-bootstrap-code"

    with pytest.raises(InvitationError, match="invalid or expired"):
        repo.redeem(
            Identity("aad", "wrong-owner", "Wrong owner"),
            bootstrap_code,
            bootstrap_hash=hash_invite_code(bootstrap_code),
            bootstrap_owner_id="owner",
            max_users=1,
        )

    assert not any(row.startswith("user:") for _, row in table.entities)


def test_sensitive_session_state_is_cleared(monkeypatch) -> None:
    from iron_trail import auth

    state = {
        "it_upload_bytes": b"private",
        "it_data_export_bytes": b"archive",
        "coach_chat_history": [("user", "private")],
        "invite_widget_state": "preserve",
    }
    monkeypatch.setattr(auth.st, "session_state", state)

    auth.clear_sensitive_session_state()

    assert state == {"invite_widget_state": "preserve"}
