"""Generate a deterministic synthetic Hevy CSV for testing.

Run: `python scripts/generate_sample_data.py`

Produces ~90 days of workouts in a Push / Pull / Legs rotation with
realistic progression, one plateaued lift, warmups, supersets, and
bodyweight + bodyweight-assisted exercises. Output goes to
`data/sample/sample_hevy_export.csv`.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample" / "sample_hevy_export.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

SEED = 42
random.seed(SEED)

END_DATE = datetime(2026, 5, 16, 8, 0)
TOTAL_DAYS = 90


def _round_kg(v: float) -> float:
    return round(v / 2.5) * 2.5


# Each entry: (exercise_title, base_weight_kg or None for bodyweight,
#   progression kg/week, sets pattern, base_reps)
PUSH = [
    ("Bench Press (Barbell)", 70.0, 1.1, ["warmup", "normal", "normal", "normal"], 8),
    ("Overhead Press (Barbell)", 45.0, 0.2, ["warmup", "normal", "normal", "normal"], 6),
    ("Incline Bench Press (Dumbbell)", 22.5, 0.4, ["normal", "normal", "normal"], 10),
    ("Lateral Raise (Dumbbell)", 10.0, 0.15, ["normal", "normal", "normal"], 12),
    ("Triceps Pushdown", 25.0, 0.5, ["normal", "normal", "normal"], 12),
]

PULL = [
    ("Deadlift (Barbell)", 110.0, 2.0, ["warmup", "warmup", "normal", "normal", "normal"], 5),
    ("Lat Pulldown (Cable)", 60.0, 1.0, ["normal", "normal", "normal", "normal"], 10),
    ("Bent Over Row (Barbell)", 50.0, 0.6, ["normal", "normal", "normal"], 8),
    ("Pull Up", None, 0.0, ["normal", "normal", "normal"], 7),
    ("Bicep Curl (Dumbbell)", 12.5, 0.25, ["normal", "normal", "normal"], 10),
    ("Face Pull (Cable)", 15.0, 0.3, ["normal", "normal", "normal"], 15),
]

LEGS = [
    ("Squat (Barbell)", 90.0, 1.5, ["warmup", "warmup", "normal", "normal", "normal"], 6),
    ("Romanian Deadlift (Barbell)", 70.0, 1.2, ["normal", "normal", "normal"], 8),
    ("Leg Press", 120.0, 2.5, ["normal", "normal", "normal"], 12),
    ("Leg Curl (Lying)", 25.0, 0.4, ["normal", "normal", "normal"], 12),
    ("Calf Raise (Standing)", 60.0, 0.6, ["normal", "normal", "normal"], 15),
    ("Plank", None, 0.0, ["normal", "normal"], 1),
]

ROTATION = [
    ("Push Day", PUSH),
    ("Pull Day", PULL),
    ("Leg Day", LEGS),
]


def reps_for(set_type: str, base: int) -> int:
    if set_type == "warmup":
        return random.randint(5, 10)
    return max(3, base + random.randint(-2, 2))


def build_sessions() -> list[tuple[str, datetime, datetime, list]]:
    sessions: list[tuple[str, datetime, datetime, list]] = []
    rotation_idx = 0
    day = END_DATE - timedelta(days=TOTAL_DAYS)
    missed_week_start = (END_DATE - timedelta(days=45)).date()
    while day < END_DATE:
        in_missed_week = missed_week_start <= day.date() < missed_week_start + timedelta(days=7)
        skip_chance = 1.0 if in_missed_week else 0.55
        if random.random() < skip_chance:
            day += timedelta(days=1)
            continue
        title, plan = ROTATION[rotation_idx % 3]
        rotation_idx += 1
        start_hour = random.choice([7, 8, 18, 19])
        start_dt = day.replace(hour=start_hour, minute=random.randint(0, 30))
        duration = timedelta(minutes=random.randint(55, 95))
        sessions.append((title, start_dt, start_dt + duration, plan))
        day += timedelta(days=1)
    return sessions


def make_rows() -> list[dict]:
    rows: list[dict] = []
    program_start = END_DATE - timedelta(days=TOTAL_DAYS)
    for title, start_dt, end_dt, plan in build_sessions():
        weeks = (start_dt - program_start).days / 7
        for ex_name, base_weight, prog, pattern, base_reps in plan:
            for set_idx, set_type in enumerate(pattern):
                if base_weight is None:
                    weight_val: float | None = None
                    if set_type == "warmup":
                        reps = random.randint(5, 8)
                    else:
                        reps = max(3, base_reps + int(weeks / 4) + random.randint(-2, 2))
                else:
                    if set_type == "warmup":
                        weight_val = _round_kg(max(20.0, base_weight * 0.55))
                        reps = reps_for(set_type, base_reps)
                    else:
                        target = base_weight + prog * weeks
                        if random.random() < 0.15:
                            target -= 2.5
                        weight_val = _round_kg(max(base_weight - 5.0, target))
                        reps = reps_for(set_type, base_reps)
                rows.append({
                    "title": title,
                    "start_time": start_dt.strftime("%d %b %Y, %H:%M"),
                    "end_time": end_dt.strftime("%d %b %Y, %H:%M"),
                    "description": "",
                    "exercise_title": ex_name,
                    "superset_id": "",
                    "exercise_notes": "",
                    "set_index": set_idx,
                    "set_type": set_type,
                    "weight_kg": "" if weight_val is None else f"{weight_val:.2f}",
                    "weight_lbs": "" if weight_val is None else f"{weight_val * 2.20462:.2f}",
                    "reps": reps,
                    "distance_km": "",
                    "distance_miles": "",
                    "duration_seconds": "",
                    "rpe": "",
                })
    return rows


def main() -> None:
    rows = make_rows()
    headers = list(rows[0].keys())
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    workouts = len({(r["start_time"], r["title"]) for r in rows})
    print(f"Wrote {len(rows)} rows across {workouts} workouts → {OUT}")


if __name__ == "__main__":
    main()
