"""CLI for generating IronTrail daily Markdown notes.

Each workout becomes ``<output>/Hevy/Daily/YYYY-MM-DD.md`` with frontmatter
plus a per-exercise breakdown. Designed for Obsidian / Logseq / any
Markdown-based note-taking tool — it's just files in a folder.

Usage::

    python scripts/write_vault_notes.py --vault /path/to/your/vault [--since 2026-01-01] [--csv path/to/export.csv]

On Windows::

    python scripts/write_vault_notes.py --vault "C:/Users/you/Documents/ObsidianVault"
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iron_trail import config, ingest, vault_notes


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Markdown daily notes from a Hevy CSV.")
    p.add_argument(
        "--vault",
        default="vault-output",
        help=(
            "Output directory. Each workout becomes <dir>/Hevy/Daily/YYYY-MM-DD.md. "
            "Point this at your Obsidian vault root, or any folder. "
            "Defaults to ./vault-output/ in the repo for a quick demo."
        ),
    )
    p.add_argument("--csv", help="Hevy CSV path. Defaults to the most recent CSV in data/raw/.")
    p.add_argument("--since", help="Only write notes on or after YYYY-MM-DD.", default=None)
    p.add_argument("--bodyweight", type=float, default=config.BODY_WEIGHT_KG)
    p.add_argument("--no-overwrite", action="store_true", help="Skip existing notes instead of overwriting.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    vault_dir = Path(args.vault)
    if not vault_dir.is_dir():
        print(f"❌ Vault directory not found: {vault_dir}")
        sys.exit(1)

    if args.csv:
        csv_path = Path(args.csv)
    else:
        raw = sorted(config.RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not raw:
            print("❌ No CSV in data/raw/ and --csv not specified.")
            sys.exit(1)
        csv_path = raw[0]

    since = date.fromisoformat(args.since) if args.since else None

    print(f"Reading {csv_path}…")
    df = ingest.load_and_clean(csv_path, body_weight_kg=args.bodyweight)
    print(f"  {len(df):,} rows across {df['workout_id'].nunique()} workouts")

    summary = vault_notes.write_daily_notes(
        df, vault_dir, overwrite=not args.no_overwrite, since=since,
    )
    print(f"✓ {summary['written']} notes written, {summary['skipped']} skipped")
    print(f"  → {summary['target_dir']}")


if __name__ == "__main__":
    main()
