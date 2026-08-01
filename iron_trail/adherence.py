"""Helpers for the Adherence calendar window."""
from __future__ import annotations

from math import ceil

import pandas as pd

MIN_WINDOW_WEEKS = 8
MAX_WINDOW_WEEKS = 104
WINDOW_STEP_WEEKS = 4
# 52 weeks gives ~7px per week on a 358px-wide phone chart, which is unreadable.
# 26 weeks stays legible on mobile; the slider still reaches 104.
DEFAULT_WINDOW_WEEKS = 26


def max_calendar_window_weeks(dates: pd.Series) -> int:
    """Return a step-aligned window that does not exceed available history."""
    parsed = pd.to_datetime(dates, errors="coerce").dropna()
    if parsed.empty:
        return MIN_WINDOW_WEEKS

    span_days = max((parsed.max().normalize() - parsed.min().normalize()).days + 1, 1)
    span_weeks = ceil(span_days / 7)
    aligned_weeks = ceil(span_weeks / WINDOW_STEP_WEEKS) * WINDOW_STEP_WEEKS
    return min(MAX_WINDOW_WEEKS, max(MIN_WINDOW_WEEKS, aligned_weeks))
