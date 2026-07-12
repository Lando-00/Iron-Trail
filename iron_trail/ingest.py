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

import csv
import functools
import io
from pathlib import Path

import dateparser
import pandas as pd

from . import config, runtime
from .normalize import normalize_exercise_title
from .uploads import UploadValidationError, read_bounded_bytes

WORKING_SET_TYPES = {"normal", "failure", "dropset"}
HEVY_REQUIRED_COLUMNS = {
    "title",
    "start_time",
    "end_time",
    "exercise_title",
    "set_index",
    "set_type",
    "weight_kg",
    "reps",
}
HEVY_OPTIONAL_DEFAULTS = {
    "description": "",
    "exercise_notes": "",
    "superset_id": pd.NA,
}


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


def load_hevy_csv(
    source,
    *,
    max_bytes: int | None = None,
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Load a Hevy export from a path, string, or file-like / BytesIO source."""
    byte_limit = max_bytes or runtime.env_int(
        "IRONTRAIL_MAX_CSV_BYTES", 25 * 1024 * 1024, minimum=1
    )
    row_limit = max_rows or runtime.env_int(
        "IRONTRAIL_MAX_CSV_ROWS", 250_000, minimum=1
    )
    payload = read_bounded_bytes(source, max_bytes=byte_limit)
    _validate_header(payload)
    try:
        df = pd.read_csv(io.BytesIO(payload), nrows=row_limit + 1)
    except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise UploadValidationError("The file is not a valid Hevy CSV export.") from exc
    if len(df) > row_limit:
        raise UploadValidationError(f"The Hevy export exceeds the {row_limit:,}-row limit.")

    missing = sorted(HEVY_REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise UploadValidationError(
            "The Hevy CSV is missing required columns: " + ", ".join(missing)
        )
    for column, default in HEVY_OPTIONAL_DEFAULTS.items():
        if column not in df.columns:
            df[column] = default
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
    csv_source=None,
    body_weight_kg: float = config.BODY_WEIGHT_KG,
) -> pd.DataFrame:
    """Load and clean a Hevy CSV from any source pandas understands.

    ``csv_source`` may be a ``Path``, ``str``, file-like object, or
    ``BytesIO`` (e.g. from ``st.file_uploader``). Defaults to the bundled
    sample if ``None``.
    """
    if csv_source is None:
        csv_source = config.SAMPLE_CSV
    if isinstance(csv_source, str):
        csv_source = Path(csv_source)
    raw = load_hevy_csv(csv_source)
    emap = load_exercise_map()
    return clean(raw, emap, body_weight_kg=body_weight_kg)


def _validate_header(payload: bytes) -> None:
    try:
        first_line = payload.decode("utf-8-sig").splitlines()[0]
        columns = next(csv.reader([first_line]))
    except (UnicodeDecodeError, IndexError, csv.Error) as exc:
        raise UploadValidationError("The file is not a valid UTF-8 CSV export.") from exc
    normalized = [column.strip() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise UploadValidationError("The CSV header contains duplicate column names.")
