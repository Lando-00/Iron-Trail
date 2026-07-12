"""Identity and invite-only authorization for hosted IronTrail."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import streamlit as st

from . import runtime

_USER_NAMESPACE = uuid.UUID("25b64e27-4acd-4e23-8b94-2a0657200fb4")
_AUTH_PARTITION = "auth"


class AuthenticationError(RuntimeError):
    """Raised when the platform identity cannot be trusted."""


class InvitationError(RuntimeError):
    """Raised when an invite cannot be issued or redeemed."""


class AuthRepositoryError(RuntimeError):
    """Raised when the authorization store is unavailable."""


@dataclass(frozen=True)
class Identity:
    provider: str
    principal_id: str
    display_name: str

    @property
    def user_id(self) -> str:
        value = f"{self.provider}:{self.principal_id}"
        return uuid.uuid5(_USER_NAMESPACE, value).hex


@dataclass(frozen=True)
class User:
    user_id: str
    provider: str
    principal_id: str
    display_name: str
    role: str
    created_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass
class Invite:
    code_hash: str
    expires_at: datetime
    created_by: str
    used_by: str | None = None

    @property
    def is_active(self) -> bool:
        return self.used_by is None and self.expires_at > datetime.now(UTC)


class AuthRepository(Protocol):
    def get_user(self, user_id: str) -> User | None: ...

    def redeem(
        self,
        identity: Identity,
        code: str,
        *,
        bootstrap_hash: str,
        max_users: int,
    ) -> User: ...

    def issue_invite(self, actor: User, *, ttl: timedelta, max_users: int) -> str: ...


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def identity_from_headers(headers: Mapping[str, str]) -> Identity | None:
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    principal_id = normalized.get("x-ms-client-principal-id", "").strip()
    provider = normalized.get("x-ms-client-principal-idp", "").strip().lower()
    display_name = normalized.get("x-ms-client-principal-name", "").strip()

    encoded = normalized.get("x-ms-client-principal", "").strip()
    claims: dict[str, str] = {}
    if encoded:
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded = base64.b64decode(encoded + padding).decode("utf-8")
            payload = json.loads(decoded)
            provider = provider or str(payload.get("auth_typ", "")).lower()
            claims = {
                str(item.get("typ", "")): str(item.get("val", ""))
                for item in payload.get("claims", [])
                if item.get("typ") and item.get("val")
            }
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Invalid platform identity header.") from exc

    if not principal_id:
        principal_id = _first_claim(
            claims,
            (
                "http://schemas.microsoft.com/identity/claims/objectidentifier",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
                "sub",
            ),
        )
    if not display_name:
        display_name = _first_claim(
            claims,
            (
                "name",
                "preferred_username",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            ),
        )

    if not principal_id:
        return None
    if not provider:
        raise AuthenticationError("The authenticated identity provider is missing.")

    return Identity(
        provider=provider,
        principal_id=principal_id,
        display_name=display_name or "IronTrail user",
    )


def local_user() -> User:
    return User(
        user_id="local",
        provider="local",
        principal_id="local",
        display_name="Local user",
        role="admin",
        created_at=datetime.now(UTC),
    )


def current_user() -> User:
    if not runtime.is_cloud():
        return local_user()
    return require_invited_user()


def require_invited_user(repository: AuthRepository | None = None) -> User:
    if not runtime.is_cloud():
        return local_user()

    try:
        identity = identity_from_headers(st.context.headers)
    except AuthenticationError as exc:
        st.error(str(exc))
        st.stop()

    if identity is None:
        _render_login()
        st.stop()

    try:
        repo = repository or get_auth_repository()
    except runtime.ConfigurationError:
        st.error("IronTrail cloud authentication is not configured.")
        st.stop()
    cached = st.session_state.get("it_current_user")
    checked_at = st.session_state.get("it_current_user_checked_at")
    revalidate_after = timedelta(
        seconds=runtime.env_int("IRONTRAIL_AUTH_REVALIDATE_SECONDS", 30, minimum=0)
    )
    now = datetime.now(UTC)
    if (
        isinstance(cached, User)
        and cached.user_id == identity.user_id
        and isinstance(checked_at, datetime)
        and now - checked_at < revalidate_after
    ):
        return cached

    try:
        user = repo.get_user(identity.user_id)
    except AuthRepositoryError:
        st.error("IronTrail could not verify access right now. Please retry shortly.")
        st.stop()
    if user is not None:
        st.session_state["it_current_user"] = user
        st.session_state["it_current_user_checked_at"] = now
        return user

    st.session_state.pop("it_current_user", None)
    st.session_state.pop("it_current_user_checked_at", None)
    _render_invite_gate(identity, repo)
    st.stop()


def render_account_controls(user: User, repository: AuthRepository | None = None) -> None:
    if not runtime.is_cloud():
        return

    st.caption(f"Signed in as **{user.display_name}**")
    st.markdown("[Sign out](/.auth/logout?post_logout_redirect_uri=/)")

    if not user.is_admin:
        return

    with st.expander("Invite a tester"):
        st.caption("Codes are single-use, expire automatically, and are shown only once.")
        if st.button("Generate invite code", key="generate_invite_code", use_container_width=True):
            repo = repository or get_auth_repository()
            try:
                code = repo.issue_invite(
                    user,
                    ttl=timedelta(
                        hours=runtime.env_int("IRONTRAIL_INVITE_TTL_HOURS", 72, minimum=1)
                    ),
                    max_users=runtime.env_int("IRONTRAIL_MAX_USERS", 5, minimum=1),
                )
            except (InvitationError, AuthRepositoryError) as exc:
                st.error(str(exc))
            else:
                st.session_state["it_new_invite_code"] = code

        code = st.session_state.get("it_new_invite_code")
        if code:
            st.code(code)
            st.caption("Copy this code now. IronTrail stores only its hash.")


@st.cache_resource(show_spinner=False)
def get_auth_repository() -> AuthRepository:
    from .cloud_storage import AzureAuthRepository

    return AzureAuthRepository.from_environment()


class InMemoryAuthRepository:
    """Thread-safe repository used by tests and local component previews."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.invites: dict[str, Invite] = {}
        self._lock = threading.Lock()

    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def redeem(
        self,
        identity: Identity,
        code: str,
        *,
        bootstrap_hash: str,
        max_users: int,
    ) -> User:
        with self._lock:
            existing = self.users.get(identity.user_id)
            if existing is not None:
                return existing
            if len(self.users) >= max_users:
                raise InvitationError("The private beta is full.")

            code_hash = hash_invite_code(code)
            role = "member"
            invite = self.invites.get(code_hash)
            if not self.users and bootstrap_hash and secrets.compare_digest(
                code_hash, bootstrap_hash
            ):
                role = "admin"
            elif invite is None or not invite.is_active:
                raise InvitationError("That invite code is invalid or expired.")

            user = _user_from_identity(identity, role)
            self.users[user.user_id] = user
            if invite is not None:
                invite.used_by = user.user_id
            return user

    def issue_invite(self, actor: User, *, ttl: timedelta, max_users: int) -> str:
        with self._lock:
            if not actor.is_admin or actor.user_id not in self.users:
                raise InvitationError("Only the beta administrator can issue invites.")
            active = sum(1 for invite in self.invites.values() if invite.is_active)
            if len(self.users) + active >= max_users:
                raise InvitationError("All beta places are already assigned.")
            code = secrets.token_urlsafe(24)
            self.invites[hash_invite_code(code)] = Invite(
                code_hash=hash_invite_code(code),
                expires_at=datetime.now(UTC) + ttl,
                created_by=actor.user_id,
            )
            return code


def _render_login() -> None:
    st.title("IronTrail private beta")
    st.write("Sign in with an approved identity, then redeem your one-time invite code.")
    providers = runtime.auth_providers()
    if "aad" in providers:
        st.markdown("[Continue with Microsoft](/.auth/login/aad?post_login_redirect_uri=/)")
    if "google" in providers:
        st.markdown("[Continue with Google](/.auth/login/google?post_login_redirect_uri=/)")


def _render_invite_gate(identity: Identity, repository: AuthRepository) -> None:
    st.title("Redeem your IronTrail invite")
    st.caption(f"Signed in as {identity.display_name}.")
    code = st.text_input("One-time invite code", type="password")
    if st.button("Join private beta", type="primary"):
        try:
            user = repository.redeem(
                identity,
                code,
                bootstrap_hash=os.environ.get("IRONTRAIL_BOOTSTRAP_INVITE_HASH", ""),
                max_users=runtime.env_int("IRONTRAIL_MAX_USERS", 5, minimum=1),
            )
        except (InvitationError, AuthRepositoryError) as exc:
            st.error(str(exc))
        else:
            st.session_state["it_current_user"] = user
            st.session_state["it_current_user_checked_at"] = datetime.now(UTC)
            st.rerun()
    st.markdown("[Sign out](/.auth/logout?post_logout_redirect_uri=/)")


def _user_from_identity(identity: Identity, role: str) -> User:
    return User(
        user_id=identity.user_id,
        provider=identity.provider,
        principal_id=identity.principal_id,
        display_name=identity.display_name,
        role=role,
        created_at=datetime.now(UTC),
    )


def _first_claim(claims: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = claims.get(name, "").strip()
        if value:
            return value
    return ""
