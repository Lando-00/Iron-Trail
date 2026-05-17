"""Exercise name normalization.

Hevy CSVs use free-text exercise titles. This module trims whitespace and
collapses repeated spaces so that join keys are stable. Fuzzy mapping for
typos / renames is intentionally deferred — add explicit entries to
`data/lookups/exercise_muscle_map.csv` instead.
"""
from __future__ import annotations

import re


def normalize_exercise_title(s: object) -> str:
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s).strip()
