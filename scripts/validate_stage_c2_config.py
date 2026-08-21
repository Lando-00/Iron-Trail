"""Fail-closed validation for private Stage C2 deployment values."""
from __future__ import annotations

import os
from collections.abc import Mapping


def validate_config(environ: Mapping[str, str] | None = None) -> None:
    env = environ or os.environ
    ai_retries_raw = env.get("IRONTRAIL_AI_MAX_RETRIES", "2").strip()
    if ai_retries_raw not in {"0", "1", "2"}:
        raise ValueError("IRONTRAIL_AI_MAX_RETRIES must be 0, 1, or 2.")

    storage_diagnostics_raw = env.get(
        "IRONTRAIL_GRANT_OWNER_STORAGE_DIAGNOSTIC_ACCESS", "false"
    ).strip().lower()
    if storage_diagnostics_raw not in {"false", "true"}:
        raise ValueError(
            "IRONTRAIL_GRANT_OWNER_STORAGE_DIAGNOSTIC_ACCESS must be false or true."
        )

    enabled_raw = env.get("IRONTRAIL_GOOGLE_AUTH_ENABLED", "").strip().lower()
    if enabled_raw not in {"false", "true"}:
        raise ValueError("IRONTRAIL_GOOGLE_AUTH_ENABLED must be false or true.")

    patch_mode_raw = env.get("IRONTRAIL_STAGE_C2_PATCH_MODE", "").strip().lower()
    if patch_mode_raw not in {"false", "true"}:
        raise ValueError("IRONTRAIL_STAGE_C2_PATCH_MODE must be false or true.")

    max_users_raw = env.get("IRONTRAIL_MAX_USERS", "").strip()
    if max_users_raw not in {"1", "2", "3", "4", "5"}:
        raise ValueError("IRONTRAIL_MAX_USERS must be an integer from 1 to 5.")

    reveal_seed = env.get("IRONTRAIL_BETA_REVEAL_SEED", "")
    if len(reveal_seed) < 16:
        raise ValueError("IRONTRAIL_BETA_REVEAL_SEED must contain at least 16 characters.")

    current_image = env.get("SERVICE_WEB_IMAGE_NAME", "").strip()
    current_web_url = env.get("WEB_URL", "").strip()
    if patch_mode_raw == "true":
        if not current_image:
            raise ValueError("SERVICE_WEB_IMAGE_NAME is required for the Stage C2 patch.")
        if not current_web_url.startswith("https://"):
            raise ValueError("WEB_URL must be an HTTPS URL for the Stage C2 patch.")

    if enabled_raw == "false":
        return

    if patch_mode_raw != "true":
        raise ValueError(
            "IRONTRAIL_STAGE_C2_PATCH_MODE must be true when Google is enabled."
        )

    client_id = env.get("IRONTRAIL_GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("IRONTRAIL_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise ValueError("IRONTRAIL_GOOGLE_CLIENT_ID is not a Google OAuth web client ID.")
    if not client_secret or client_secret.lower() == "disabled":
        raise ValueError("IRONTRAIL_GOOGLE_CLIENT_SECRET is missing.")


if __name__ == "__main__":
    validate_config()
    print("Stage C2 deployment configuration is valid.")
