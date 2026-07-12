from __future__ import annotations

import pytest

from iron_trail import runtime


def test_runtime_defaults_to_local() -> None:
    assert runtime.runtime_mode({}) is runtime.RuntimeMode.LOCAL


def test_runtime_rejects_unknown_mode() -> None:
    with pytest.raises(runtime.ConfigurationError, match="IRONTRAIL_MODE"):
        runtime.runtime_mode({"IRONTRAIL_MODE": "shared"})


def test_auth_providers_are_validated() -> None:
    assert runtime.auth_providers({"IRONTRAIL_AUTH_PROVIDERS": "aad,google"}) == (
        "aad",
        "google",
    )
    with pytest.raises(runtime.ConfigurationError, match="Unsupported"):
        runtime.auth_providers({"IRONTRAIL_AUTH_PROVIDERS": "github"})

