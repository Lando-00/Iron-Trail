"""Batch-render PR posters from a Hevy CSV.

Usage::

    python scripts/render_pr_poster.py --since 2026-01-01 --out output/posters

Writes one PNG per recent PR.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iron_trail import config, ingest
from iron_trail.posters import find_recent_prs, render_pr_poster_for_row


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render PR posters from a Hevy CSV.")
    p.add_argument("--csv", help="Hevy CSV path. Defaults to most-recent in data/raw/.")
    p.add_argument("--since", help="Only render PRs on or after YYYY-MM-DD.", default=None)
    p.add_argument("--bodyweight", type=float, default=config.BODY_WEIGHT_KG)
    p.add_argument("--out", default="output/posters", help="Output directory.")
    p.add_argument("--limit", type=int, default=20, help="Max posters to render.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    csv_path: Path
    if args.csv:
        csv_path = Path(args.csv)
    else:
        candidates = sorted(config.RAW_DIR.glob("*.csv"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            csv_path = config.SAMPLE_CSV
        else:
            csv_path = candidates[0]
    print(f"Reading {csv_path}…")
    df = ingest.load_and_clean(csv_path, body_weight_kg=args.bodyweight)
    since = date.fromisoformat(args.since) if args.since else None
    prs = find_recent_prs(df, since=since)
    if prs.empty:
        print("No PRs found in window.")
        return
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {min(len(prs), args.limit)} of {len(prs)} PRs → {out_dir}")
    rendered = 0
    for _, row in prs.head(args.limit).iterrows():
        png = render_pr_poster_for_row(row)
        safe_ex = "".join(c if c.isalnum() else "_" for c in str(row["exercise_title"]))
        fn = out_dir / f"{row['workout_date']}_{safe_ex}.png"
        fn.write_bytes(png)
        print(f"  · {fn.name}  ({row['e1rm_kg']:.1f} kg e1RM)")
        rendered += 1
    print(f"Done: {rendered} posters in {out_dir}")


if __name__ == "__main__":
    main()
