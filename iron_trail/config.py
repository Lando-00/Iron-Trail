"""Project-wide configuration constants.

This is the one file you should edit before running IronTrail with your own
data. Two settings matter:

1. ``BODY_WEIGHT_KG`` — the bodyweight the app starts at before you set one
   in the sidebar. The sidebar value is saved (per account in cloud mode,
   in ``data/processed/profile.json`` locally) and wins from then on.
2. (optional) Override path constants below if you store data elsewhere.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SAMPLE_DIR = DATA_DIR / "sample"
LOOKUPS_DIR = DATA_DIR / "lookups"
PROCESSED_DIR = DATA_DIR / "processed"

EXERCISE_MAP_PATH = LOOKUPS_DIR / "exercise_muscle_map.csv"
SAMPLE_CSV = SAMPLE_DIR / "sample_hevy_export.csv"
PROCESSED_PARQUET = PROCESSED_DIR / "clean.parquet"

# Where the locally saved bodyweight lives (git-ignored with the rest of
# data/processed/). In cloud mode the value is stored per account instead.
PROFILE_JSON = PROCESSED_DIR / "profile.json"

# ⚠️ Starting bodyweight in kg, used until you set one in the sidebar.
# Used for bodyweight + assisted-exercise load calculation and for badges
# like "Bodyweight Bench" / "Double-BW Deadlift".
BODY_WEIGHT_KG: float = 84.0
