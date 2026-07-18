"""Fail-closed validation for private Stage C2 deployment values."""
from __future__ import annotations

import os
from collections.abc import Mapping


def validate_config(environ: Mapping[str, str] | None = None) -> None:
    env = environ or os.environ
    enabled_raw = env.get("IRONTRAIL_GOOGLE_AUTH_ENABLED", "").strip().lower()
    if enabled_raw not in {"false", "true"}:
        raise ValueError("IRONTRAIL_GOOGLE_AUTH_ENABLED must be false or true.")

    max_users_raw = env.get("IRONTRAIL_MAX_USERS", "").strip()
    if max_users_raw not in {"1", "2", "3", "4", "5"}:
        raise ValueError("IRONTRAIL_MAX_USERS must be an integer from 1 to 5.")

    reveal_seed = env.get("IRONTRAIL_BETA_REVEAL_SEED", "")
    if len(reveal_seed) < 16:
        raise ValueError("IRONTRAIL_BETA_REVEAL_SEED must contain at least 16 characters.")

    if enabled_raw == "false":
        return

    client_id = env.get("IRONTRAIL_GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("IRONTRAIL_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise ValueError("IRONTRAIL_GOOGLE_CLIENT_ID is not a Google OAuth web client ID.")
    if not client_secret or client_secret.lower() == "disabled":
        raise ValueError("IRONTRAIL_GOOGLE_CLIENT_SECRET is missing.")


if __name__ == "__main__":
    validate_config()
    print("Stage C2 deployment configuration is valid.")
