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
        max_users=5,
    )

    assert owner.is_admin
    with pytest.raises(InvitationError, match="invalid or expired"):
        repo.redeem(
            Identity("aad", "second-owner", "Second"),
            bootstrap_code,
            bootstrap_hash=hash_invite_code(bootstrap_code),
            max_users=5,
        )


def test_admin_issues_single_use_invite() -> None:
    repo = InMemoryAuthRepository()
    bootstrap_code = "owner-bootstrap-code"
    owner = repo.redeem(
        Identity("aad", "owner", "Owner"),
        bootstrap_code,
        bootstrap_hash=hash_invite_code(bootstrap_code),
        max_users=2,
    )
    code = repo.issue_invite(owner, ttl=timedelta(hours=1), max_users=2)

    member = repo.redeem(
        Identity("google", "member", "Member"),
        code,
        bootstrap_hash="",
        max_users=2,
    )

    assert member.role == "member"
    with pytest.raises(InvitationError):
        repo.redeem(
            Identity("google", "other", "Other"),
            code,
            bootstrap_hash="",
            max_users=3,
        )

