"""Load and clean a Hevy CSV export.

The CSV from `Profile → Settings → Export Workout Data` has one row per set.
This module:

- parses the locale-dependent `start_time` / `end_time` strings,
- joins each exercise to its muscle / equipment / movement type via the
  user-maintained lookup at `data/lookups/exercise_muscle_map.csv`,
- substitutes bodyweight load for bodyweight + bodyweight-assisted exercises,
- flags warmup vs working sets and derives per-set `volume_kg` and `e1rm_kg`.

The returned DataFrame is the canonical wide table used by every page.
"""
from __future__ import annotations

import functools
from pathlib import Path

import dateparser
import pandas as pd

from . import config
from .normalize import normalize_exercise_title

WORKING_SET_TYPES = {"normal", "failure", "dropset"}


@functools.lru_cache(maxsize=4096)
def _parse_dt_cached(s: str) -> pd.Timestamp | None:
    if not s:
        return None
    parsed = dateparser.parse(s)
    if parsed is None:
        return None
    return pd.Timestamp(parsed)


def _parse_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).map(_parse_dt_cached)


def load_exercise_map(path: Path | None = None) -> pd.DataFrame:
    path = path or config.EXERCISE_MAP_PATH
    if not path.exists():
        raise FileNotFoundError(f"Exercise map missing at {path}")
    return pd.read_csv(path)


def load_hevy_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["exercise_title"] = df["exercise_title"].astype(str).map(normalize_exercise_title)
    return df


def clean(
    df: pd.DataFrame,
    exercise_map: pd.DataFrame,
    body_weight_kg: float = config.BODY_WEIGHT_KG,
) -> pd.DataFrame:
    out = df.copy()

    out["start_time"] = _parse_series(out["start_time"])
    out["end_time"] = _parse_series(out["end_time"])
    out = out.dropna(subset=["start_time"]).reset_index(drop=True)

    out["duration_min"] = (out["end_time"] - out["start_time"]).dt.total_seconds() / 60

    out = out.merge(exercise_map, on="exercise_title", how="left")
    out["primary_muscle"] = out["primary_muscle"].fillna("unmapped")
    out["movement_type"] = out["movement_type"].fillna("unmapped")
    out["equipment"] = out["equipment"].fillna("unknown")
    out["load_type"] = out["load_type"].fillna("weighted")

    out["is_warmup"] = out["set_type"] == "warmup"
    out["is_working"] = out["set_type"].isin(WORKING_SET_TYPES)

    raw_weight = pd.to_numeric(out["weight_kg"], errors="coerce")
    bw_load = out["load_type"] == "bodyweight"
    assisted_load = out["load_type"] == "assisted"

    load = raw_weight.copy()
    load = load.mask(bw_load, body_weight_kg)
    load = load.mask(assisted_load, body_weight_kg - raw_weight.fillna(0))
    out["weight_kg_load"] = load

    out["reps"] = pd.to_numeric(out["reps"], errors="coerce").fillna(0).astype(int)

    working_mask = out["is_working"]
    out["volume_kg"] = (out["weight_kg_load"].fillna(0) * out["reps"]).where(working_mask, 0.0)

    e1rm = out["weight_kg_load"] * (1 + out["reps"] / 30)
    out["e1rm_kg"] = e1rm.where(working_mask & (out["reps"] > 0) & out["weight_kg_load"].notna())

    out["workout_id"] = out["start_time"].dt.floor("min").astype("int64") // 10**9
    out["workout_date"] = out["start_time"].dt.date

    return out


def load_and_clean(
    csv_path: Path | None = None,
    body_weight_kg: float = config.BODY_WEIGHT_KG,
) -> pd.DataFrame:
    csv_path = Path(csv_path) if csv_path else config.SAMPLE_CSV
    raw = load_hevy_csv(csv_path)
    emap = load_exercise_map()
    return clean(raw, emap, body_weight_kg=body_weight_kg)
