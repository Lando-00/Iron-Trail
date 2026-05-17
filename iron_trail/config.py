"""Project-wide configuration constants.

Edit `BODY_WEIGHT_KG` to match your bodyweight — it's used to compute
load for bodyweight + bodyweight-assisted exercises.
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

BODY_WEIGHT_KG: float = 84.0
