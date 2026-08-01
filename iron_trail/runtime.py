"""Runtime configuration for local and Azure-hosted IronTrail."""
from __future__ import annotations

import os
from enum import StrEnum
from typing import Mapping


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is invalid or missing."""


class RuntimeMode(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


def runtime_mode(environ: Mapping[str, str] | None = None) -> RuntimeMode:
    env = environ or os.environ
    raw = env.get("IRONTRAIL_MODE", RuntimeMode.LOCAL.value).strip().lower()
    try:
        return RuntimeMode(raw)
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in RuntimeMode)
        raise ConfigurationError(f"IRONTRAIL_MODE must be one of: {choices}") from exc


def is_cloud(environ: Mapping[str, str] | None = None) -> bool:
    return runtime_mode(environ) is RuntimeMode.CLOUD


def auth_providers(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    env = environ or os.environ
    raw = env.get("IRONTRAIL_AUTH_PROVIDERS", "aad")
    providers = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    supported = {"aad", "google"}
    invalid = set(providers) - supported
    if invalid:
        names = ", ".join(sorted(invalid))
        raise ConfigurationError(f"Unsupported IRONTRAIL_AUTH_PROVIDERS: {names}")
    return providers or ("aad",)


def env_bool(
    name: str,
    default: bool,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = environ or os.environ
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def auto_persist_uploads(environ: Mapping[str, str] | None = None) -> bool:
    """Whether a hosted upload is saved to the user's single slot automatically.

    Set ``IRONTRAIL_AUTO_PERSIST_UPLOADS=false`` to restore the original
    explicit opt-in flow without a code change.
    """
    return env_bool("IRONTRAIL_AUTO_PERSIST_UPLOADS", True, environ=environ)


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 0,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = environ or os.environ
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def env_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    environ: Mapping[str, str] | None = None,
) -> float:
    env = environ or os.environ
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value

