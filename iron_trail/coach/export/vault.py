"""Write a generated review to the user's Obsidian / markdown vault."""
from __future__ import annotations

from pathlib import Path


def save_weekly_review(md: str, vault_dir: Path | str, week_label: str) -> Path:
    """Write to ``<vault>/Hevy/Reviews/{week_label}.md`` and return the path."""
    out_dir = Path(vault_dir) / "Hevy" / "Reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{week_label}.md"
    target.write_text(md, encoding="utf-8")
    return target


def save_monthly_review(md: str, vault_dir: Path | str, month_label: str) -> Path:
    """Write to ``<vault>/Hevy/Monthly/{month_label}.md`` and return the path."""
    out_dir = Path(vault_dir) / "Hevy" / "Monthly"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{month_label}.md"
    target.write_text(md, encoding="utf-8")
    return target
