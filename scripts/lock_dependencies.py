"""Regenerate the hash-pinned dependency lockfile for the container image.

The image installs with ``pip --require-hashes``, so every artifact has to be
listed with its SHA-256. Resolution has to target the *container's* platform,
not the machine running this script — a lockfile compiled on Windows or macOS
records the wrong wheel hashes and the Docker build will refuse them.

Usage::

    python scripts/lock_dependencies.py            # rewrite the lockfile
    python scripts/lock_dependencies.py --check    # fail if it is out of date

Requires `uv <https://docs.astral.sh/uv/>`_, which resolves for another
platform without needing that platform locally::

    pip install uv
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = ROOT / "requirements-cloud.lock"

# Must match the Dockerfile base image.
PYTHON_VERSION = "3.12"
PYTHON_PLATFORM = "x86_64-manylinux2014"
EXTRA = "cloud"


def _uv() -> str:
    found = shutil.which("uv")
    if found is None:
        sys.exit("uv is not on PATH. Install it with `pip install uv` and retry.")
    return found


def _compile(output: Path) -> None:
    subprocess.run(
        [
            _uv(),
            "pip",
            "compile",
            str(ROOT / "pyproject.toml"),
            "--extra",
            EXTRA,
            "--generate-hashes",
            "--python-version",
            PYTHON_VERSION,
            "--python-platform",
            PYTHON_PLATFORM,
            "--no-header",
            "--output-file",
            str(output),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the lockfile is not up to date",
    )
    args = parser.parse_args()

    if not args.check:
        _compile(LOCKFILE)
        print(f"wrote {LOCKFILE.relative_to(ROOT)}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "requirements-cloud.lock"
        _compile(candidate)
        if candidate.read_text(encoding="utf-8") != LOCKFILE.read_text(encoding="utf-8"):
            print(
                "requirements-cloud.lock is out of date — "
                "run python scripts/lock_dependencies.py",
                file=sys.stderr,
            )
            return 1
    print("requirements-cloud.lock is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
