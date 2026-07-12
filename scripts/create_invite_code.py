"""Generate a one-time invite code and the SHA-256 hash stored by IronTrail."""
from __future__ import annotations

import secrets

from iron_trail.auth import hash_invite_code


def main() -> None:
    code = secrets.token_urlsafe(24)
    print(f"Invite code: {code}")
    print(f"Invite hash: {hash_invite_code(code)}")
    print("Store only the hash in Azure configuration. Share the code once.")


if __name__ == "__main__":
    main()

