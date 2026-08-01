"""Guards for the container supply chain.

`azd deploy` runs a remote ACR build, so anything unpinned is resolved to
whatever is newest on Docker Hub or PyPI at that moment — straight into an
image that holds Storage Blob/Table Data Contributor and Cognitive Services
OpenAI User over real beta data.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
LOCKFILE = ROOT / "requirements-cloud.lock"


def test_base_image_is_pinned_by_digest() -> None:
    from_lines = [
        line for line in DOCKERFILE.splitlines() if line.strip().startswith("FROM ")
    ]

    assert from_lines, "no FROM instruction found"
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}", line), f"unpinned base image: {line}"


def test_dependencies_are_installed_with_hash_checking() -> None:
    assert "--require-hashes" in DOCKERFILE
    assert "requirements-cloud.lock" in DOCKERFILE
    # The old form resolved the whole graph at build time.
    assert 'pip install --no-cache-dir ".[cloud]"' not in DOCKERFILE


def _lock_requirements() -> dict[str, str]:
    """Map of distribution name -> pinned version from the lockfile."""
    pinned: dict[str, str] = {}
    for match in re.finditer(
        r"^([A-Za-z0-9._-]+)==([^\s\\;]+)",
        LOCKFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        pinned[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pinned


def test_every_locked_requirement_is_pinned_and_hashed() -> None:
    text = LOCKFILE.read_text(encoding="utf-8")
    requirements = _lock_requirements()

    assert requirements, "lockfile contains no pinned requirements"
    # Every requirement line must be an exact pin, never a range.
    assert not re.search(r"^[A-Za-z0-9._-]+\s*(>=|<=|~=|>|<)", text, re.MULTILINE)

    blocks = re.split(r"\n(?=[A-Za-z0-9._-]+==)", text)
    unhashed = [
        block.splitlines()[0]
        for block in blocks
        if block.strip().startswith(tuple("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
        and "--hash=sha256:" not in block
    ]
    assert not unhashed, f"requirements without hashes: {unhashed}"


def test_lockfile_covers_every_runtime_dependency() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    declared = project["dependencies"] + project["optional-dependencies"]["cloud"]
    names = {
        re.split(r"[><=!~\[]", item)[0].strip().lower().replace("_", "-")
        for item in declared
    }
    locked = _lock_requirements()

    missing = sorted(name for name in names if name not in locked)
    assert not missing, f"declared but not locked: {missing}"
