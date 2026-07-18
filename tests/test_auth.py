from __future__ import annotations

import base64
import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest

from iron_trail.auth import (
    Identity,
    InMemoryAuthRepository,
    InvitationError,
    User,
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
        self.transaction_conflicts = 0

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
        if self.transaction_conflicts:
            from azure.data.tables import TableTransactionError

            self.transaction_conflicts -= 1
            error = TableTransactionError(message="simulated conflict")
            error.status_code = 412
            raise error
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


def test_aad_identity_prefers_object_id_claim_over_generic_header() -> None:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {
                "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
                "val": "owner-object-id",
            },
            {"typ": "sub", "val": "pairwise-subject"},
            {"typ": "name", "val": "Owner"},
        ],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    identity = identity_from_headers(
        {
            "X-MS-CLIENT-PRINCIPAL-ID": "generic-principal-header",
            "X-MS-CLIENT-PRINCIPAL-IDP": "aad",
            "X-MS-CLIENT-PRINCIPAL": encoded,
        }
    )

    assert identity == Identity("aad", "owner-object-id", "Owner")


def test_google_identity_prefers_subject_claim_over_email_header() -> None:
    payload = {
        "auth_typ": "google",
        "claims": [
            {"typ": "sub", "val": "google-subject-123"},
            {"typ": "email", "val": "mutable@example.com"},
            {"typ": "name", "val": "Google tester"},
        ],
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    identity = identity_from_headers(
        {
            "X-MS-CLIENT-PRINCIPAL-ID": "mutable@example.com",
            "X-MS-CLIENT-PRINCIPAL-IDP": "google",
            "X-MS-CLIENT-PRINCIPAL": encoded,
        }
    )

    assert identity == Identity("google", "google-subject-123", "Google tester")


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


def test_admin_can_suspend_and_restore_member() -> None:
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
    member_identity = Identity("google", "member", "Member")
    member = repo.redeem(
        member_identity,
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )

    suspended = repo.suspend_user(owner, member.user_id)

    assert not suspended.is_active
    with pytest.raises(InvitationError, match="suspended"):
        repo.redeem(
            member_identity,
            code,
            bootstrap_hash="",
            bootstrap_owner_id="owner",
            max_users=2,
        )

    restored = repo.restore_user(owner, member.user_id, max_users=2)

    assert restored.is_active
    assert [user.user_id for user in repo.list_users(owner)] == [
        owner.user_id,
        member.user_id,
    ]


def test_suspended_member_frees_capacity_but_active_invite_reserves_it() -> None:
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
    repo.suspend_user(owner, member.user_id)

    repo.issue_invite(owner, ttl=timedelta(hours=1), max_users=2)

    with pytest.raises(InvitationError, match="No beta place"):
        repo.restore_user(owner, member.user_id, max_users=2)


def test_only_active_admin_can_manage_members() -> None:
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

    with pytest.raises(InvitationError, match="administrator"):
        repo.list_users(member)
    with pytest.raises(InvitationError, match="administrator cannot"):
        repo.suspend_user(owner, owner.user_id)


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


def test_azure_repository_suspends_and_restores_member() -> None:
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
    member = repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )

    table.transaction_conflicts = 1
    suspended = repo.suspend_user(owner, member.user_id)
    table.transaction_conflicts = 1
    restored = repo.restore_user(owner, member.user_id, max_users=2)

    assert not suspended.is_active
    assert restored.is_active
    assert table.entities[("auth", "state")]["userCount"] == 2


def test_azure_restore_respects_active_invite_capacity() -> None:
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
    member = repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )
    repo.suspend_user(owner, member.user_id)
    repo.issue_invite(owner, ttl=timedelta(hours=1), max_users=2)

    with pytest.raises(InvitationError, match="No beta place"):
        repo.restore_user(owner, member.user_id, max_users=2)


def test_azure_member_cannot_manage_access() -> None:
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
    member = repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        bootstrap_owner_id="owner",
        max_users=2,
    )

    with pytest.raises(InvitationError, match="administrator"):
        repo.list_users(member)
    with pytest.raises(InvitationError, match="administrator"):
        repo.suspend_user(member, owner.user_id)


def test_legacy_azure_user_without_status_remains_active() -> None:
    from datetime import UTC, datetime

    table = _FakeTable()
    identity = Identity("aad", "owner", "Owner")
    table._store(
        {
            "PartitionKey": "auth",
            "RowKey": f"user:{identity.user_id}",
            "provider": identity.provider,
            "principalId": identity.principal_id,
            "displayName": identity.display_name,
            "role": "admin",
            "createdAt": datetime.now(UTC),
        }
    )

    user = AzureAuthRepository(table).get_user(identity.user_id)

    assert user is not None
    assert user.is_active


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


def test_authenticated_marker_is_sensitive_session_state(monkeypatch) -> None:
    from iron_trail import auth

    state = {
        "it_authenticated_identity_seen": "owner-id",
        "beta_reveal_state": "preserve-until-logout-transition",
    }
    monkeypatch.setattr(auth.st, "session_state", state)

    auth.clear_sensitive_session_state()

    assert state == {"beta_reveal_state": "preserve-until-logout-transition"}


def test_initial_anonymous_rerun_preserves_reveal_progress(monkeypatch) -> None:
    from iron_trail import auth, beta_landing

    class _Stopped(Exception):
        pass

    reveal = beta_landing.RevealState(emoji_index=2, control_hits=3)
    state = {"beta_reveal_state": reveal}
    monkeypatch.setattr(auth.runtime, "is_cloud", lambda: True)
    monkeypatch.setattr(auth.st, "context", SimpleNamespace(headers={}))
    monkeypatch.setattr(auth.st, "session_state", state)
    monkeypatch.setattr(auth, "identity_from_headers", lambda _headers: None)
    monkeypatch.setattr(auth, "_render_login", lambda: None)
    monkeypatch.setattr(auth.st, "stop", lambda: (_ for _ in ()).throw(_Stopped()))

    with pytest.raises(_Stopped):
        auth.require_invited_user()

    assert state["beta_reveal_state"] == reveal


def test_logout_transition_resets_reveal_progress(monkeypatch) -> None:
    from iron_trail import auth, beta_landing

    class _Stopped(Exception):
        pass

    state = {
        "it_authenticated_identity_seen": "owner-id",
        "beta_reveal_state": beta_landing.RevealState(revealed=True),
        "beta_reveal_emoji_button": True,
    }
    monkeypatch.setattr(auth.runtime, "is_cloud", lambda: True)
    monkeypatch.setattr(auth.st, "context", SimpleNamespace(headers={}))
    monkeypatch.setattr(auth.st, "session_state", state)
    monkeypatch.setattr(auth, "identity_from_headers", lambda _headers: None)
    monkeypatch.setattr(auth, "_render_login", lambda: None)
    monkeypatch.setattr(auth.st, "stop", lambda: (_ for _ in ()).throw(_Stopped()))

    with pytest.raises(_Stopped):
        auth.require_invited_user()

    assert "beta_reveal_state" not in state
    assert "beta_reveal_emoji_button" not in state


def test_suspended_user_is_denied_after_revalidation(monkeypatch) -> None:
    from datetime import UTC, datetime

    from iron_trail import auth

    class _Stopped(Exception):
        pass

    identity = Identity("google", "member", "Member")
    suspended = User(
        user_id=identity.user_id,
        provider=identity.provider,
        principal_id=identity.principal_id,
        display_name=identity.display_name,
        role="member",
        created_at=datetime.now(UTC),
        status="suspended",
    )
    errors: list[str] = []
    state = {
        "it_current_user": suspended,
        "it_current_user_checked_at": datetime.now(UTC) - timedelta(minutes=1),
    }
    repository = SimpleNamespace(get_user=lambda _user_id: suspended)
    monkeypatch.setattr(auth.runtime, "is_cloud", lambda: True)
    monkeypatch.setattr(auth.st, "context", SimpleNamespace(headers={}))
    monkeypatch.setattr(auth.st, "session_state", state)
    monkeypatch.setattr(auth, "identity_from_headers", lambda _headers: identity)
    monkeypatch.setattr(auth.st, "error", errors.append)
    monkeypatch.setattr(auth.st, "markdown", lambda _message: None)
    monkeypatch.setattr(auth.st, "stop", lambda: (_ for _ in ()).throw(_Stopped()))

    with pytest.raises(_Stopped):
        auth.require_invited_user(repository)

    assert errors == ["Access for this identity is suspended."]
    assert "it_current_user" not in state


def test_suspend_confirmation_is_cleared_after_success(monkeypatch) -> None:
    from datetime import UTC, datetime

    from iron_trail import auth

    class _Rerun(Exception):
        pass

    owner = User(
        user_id="owner",
        provider="aad",
        principal_id="owner",
        display_name="Owner",
        role="admin",
        created_at=datetime.now(UTC),
    )
    member = User(
        user_id="member",
        provider="google",
        principal_id="member",
        display_name="Member",
        role="member",
        created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(
        list_users=lambda _actor: [owner, member],
        suspend_user=lambda _actor, _target: member,
    )
    state = {
        "suspend_member_confirm_member": True,
        "it_new_invite_code": "still-visible",
    }
    monkeypatch.setattr(auth.st, "session_state", state)
    monkeypatch.setattr(auth.st, "expander", lambda _label: nullcontext())
    monkeypatch.setattr(auth.st, "caption", lambda _message: None)
    monkeypatch.setattr(auth.st, "text", lambda _message: None)
    monkeypatch.setattr(auth.st, "error", lambda _message: None)
    monkeypatch.setattr(auth.st, "checkbox", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        auth.st,
        "button",
        lambda label, **_kwargs: label == "Suspend access",
    )
    monkeypatch.setattr(auth.st, "rerun", lambda: (_ for _ in ()).throw(_Rerun()))

    with pytest.raises(_Rerun):
        auth._render_member_management(owner, repository, max_users=2)

    assert "suspend_member_confirm_member" not in state
    assert state["it_new_invite_code"] == "still-visible"
