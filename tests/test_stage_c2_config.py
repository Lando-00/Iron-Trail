from __future__ import annotations

import pytest

from scripts.validate_stage_c2_config import validate_config


def _base() -> dict[str, str]:
    return {
        "IRONTRAIL_BETA_REVEAL_SEED": "private-seed-long-enough",
        "IRONTRAIL_GOOGLE_AUTH_ENABLED": "false",
        "IRONTRAIL_GOOGLE_CLIENT_ID": "",
        "IRONTRAIL_GOOGLE_CLIENT_SECRET": "",
        "IRONTRAIL_STAGE_C2_PATCH_MODE": "false",
        "IRONTRAIL_MAX_USERS": "1",
    }


def test_google_disabled_does_not_require_unused_credentials() -> None:
    validate_config(_base())


def test_storage_diagnostic_flag_must_be_boolean_text() -> None:
    config = _base()
    config["IRONTRAIL_GRANT_OWNER_STORAGE_DIAGNOSTIC_ACCESS"] = "sometimes"

    with pytest.raises(ValueError, match="STORAGE_DIAGNOSTIC_ACCESS"):
        validate_config(config)


@pytest.mark.parametrize("value", ["-1", "3", "many"])
def test_ai_retries_are_bounded(value: str) -> None:
    config = _base()
    config["IRONTRAIL_AI_MAX_RETRIES"] = value

    with pytest.raises(ValueError, match="AI_MAX_RETRIES"):
        validate_config(config)


def test_google_enabled_requires_complete_web_client_credentials() -> None:
    config = _base()
    config["IRONTRAIL_GOOGLE_AUTH_ENABLED"] = "true"

    with pytest.raises(ValueError, match="PATCH_MODE"):
        validate_config(config)

    config["IRONTRAIL_STAGE_C2_PATCH_MODE"] = "true"
    config["SERVICE_WEB_IMAGE_NAME"] = "example.azurecr.io/irontrail/web:current"
    config["WEB_URL"] = "https://example.azurecontainerapps.io"
    with pytest.raises(ValueError, match="client ID"):
        validate_config(config)

    config["IRONTRAIL_GOOGLE_CLIENT_ID"] = "client.apps.googleusercontent.com"
    with pytest.raises(ValueError, match="CLIENT_SECRET"):
        validate_config(config)

    config["IRONTRAIL_GOOGLE_CLIENT_SECRET"] = "private-client-secret"
    validate_config(config)


def test_stage_c2_patch_requires_live_metadata_during_aad_only_rollback() -> None:
    config = _base()
    config["IRONTRAIL_STAGE_C2_PATCH_MODE"] = "true"

    with pytest.raises(ValueError, match="SERVICE_WEB_IMAGE_NAME"):
        validate_config(config)

    config["SERVICE_WEB_IMAGE_NAME"] = "example.azurecr.io/irontrail/web:current"
    with pytest.raises(ValueError, match="WEB_URL"):
        validate_config(config)

    config["WEB_URL"] = "https://example.azurecontainerapps.io"
    validate_config(config)


@pytest.mark.parametrize("max_users", ["", "0", "6", "five"])
def test_user_ceiling_is_limited_to_five(max_users: str) -> None:
    config = _base()
    config["IRONTRAIL_MAX_USERS"] = max_users

    with pytest.raises(ValueError, match="from 1 to 5"):
        validate_config(config)


def test_reveal_seed_is_required_for_full_provision() -> None:
    config = _base()
    config["IRONTRAIL_BETA_REVEAL_SEED"] = "short"

    with pytest.raises(ValueError, match="at least 16"):
        validate_config(config)
