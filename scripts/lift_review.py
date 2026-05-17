"""Headless CLI: generate a coach review and save it to a vault directory.

Used both by humans (cron, ad-hoc) and by the ``/lift-review`` Copilot CLI
slash-command extension. Output paths follow the same convention as the
Streamlit Save-to-Vault button.

Examples::

    python scripts/lift_review.py --vault D:/Dev/Quartz/Vault
    python scripts/lift_review.py --vault D:/Dev/Quartz/Vault --monthly
    python scripts/lift_review.py --vault D:/Dev/Quartz/Vault --personality goggins
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iron_trail import config, ingest
from iron_trail.coach import prompts, render, summary
from iron_trail.coach.export.vault import save_weekly_review, save_monthly_review
from iron_trail.coach.providers import Message
from iron_trail.coach.providers.mock import MockProvider


PERSONALITIES = ("default", "rp", "sbs", "therapist", "goggins")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate an IronTrail coach review.")
    p.add_argument(
        "--vault",
        default="vault-output",
        help="Vault root. Reviews go in <vault>/Hevy/Reviews/ (weekly) or /Monthly/.",
    )
    p.add_argument("--csv", help="Hevy CSV path. Defaults to the most-recent CSV in data/raw/.")
    p.add_argument("--monthly", action="store_true", help="Generate a monthly recap (default: weekly).")
    p.add_argument("--since", help="Week or month anchor date (YYYY-MM-DD). Defaults to last complete period.")
    p.add_argument("--personality", choices=PERSONALITIES, default="default")
    p.add_argument("--bodyweight", type=float, default=config.BODY_WEIGHT_KG)
    return p.parse_args()


def _resolve_csv(args: argparse.Namespace) -> Path:
    if args.csv:
        return Path(args.csv)
    candidates = sorted(config.RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    return config.SAMPLE_CSV


def _get_provider():
    if os.environ.get("COACH_LLM", "").lower() == "mock":
        return MockProvider()
    from iron_trail.coach.providers.copilot import CopilotProvider

    return CopilotProvider()


def main() -> int:
    args = parse_args()
    csv_path = _resolve_csv(args)
    print(f"[lift_review] reading {csv_path}", flush=True)

    df = ingest.load_and_clean(csv_path, body_weight_kg=args.bodyweight)
    print(f"[lift_review] {len(df):,} rows, {df['workout_id'].nunique()} workouts", flush=True)

    provider = _get_provider()
    vault_dir = Path(args.vault)

    if args.monthly:
        if args.since:
            anchor = date.fromisoformat(args.since)
            month = summary.MonthRange.from_end(anchor)
        else:
            today = date.today()
            first_of_this = today.replace(day=1)
            month = summary.MonthRange.from_end(first_of_this - timedelta(days=1))
        print(f"[lift_review] target month: {month.label}", flush=True)
        s = summary.build_monthly(df, month)
        prompt = prompts.monthly_review_prompt(s, personality=args.personality)
        print(f"[lift_review] calling provider ({provider.name})…", flush=True)
        body = provider.chat([Message(role="system", content=prompt)], timeout=240.0)
        md = render.monthly_review_md(s, body, personality=args.personality)
        out = save_monthly_review(md, vault_dir, month.label)
    else:
        if args.since:
            anchor = date.fromisoformat(args.since)
            week = summary.WeekRange.from_end(anchor)
        else:
            week = summary.last_complete_week()
        print(f"[lift_review] target week: {week.label}", flush=True)
        s = summary.build_weekly(df, week)
        prompt = prompts.weekly_review_prompt(s, personality=args.personality)
        print(f"[lift_review] calling provider ({provider.name})…", flush=True)
        body = provider.chat([Message(role="system", content=prompt)], timeout=180.0)
        md = render.weekly_review_md(s, body, personality=args.personality)
        out = save_weekly_review(md, vault_dir, week.label)

    print(f"[lift_review] wrote {out}", flush=True)
    print(out)  # the last printed line is the path — extension reads it
    return 0


if __name__ == "__main__":
    sys.exit(main())
