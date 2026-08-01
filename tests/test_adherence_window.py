from __future__ import annotations

import pandas as pd

from iron_trail import adherence


def test_calendar_default_window_is_mobile_legible() -> None:
    """52 weeks gives ~7px per week on a 358px-wide phone chart. 26 keeps the
    calendar readable while the slider still reaches 104."""
    assert adherence.DEFAULT_WINDOW_WEEKS == 26
    assert adherence.MIN_WINDOW_WEEKS <= adherence.DEFAULT_WINDOW_WEEKS
    assert adherence.DEFAULT_WINDOW_WEEKS <= adherence.MAX_WINDOW_WEEKS


def test_default_window_still_respects_short_history() -> None:
    dates = pd.Series(pd.date_range("2026-06-01", periods=14, freq="D"))
    available = adherence.max_calendar_window_weeks(dates)

    assert available == adherence.MIN_WINDOW_WEEKS
    assert min(adherence.DEFAULT_WINDOW_WEEKS, available) == adherence.MIN_WINDOW_WEEKS


def test_long_history_allows_the_full_default() -> None:
    dates = pd.Series(pd.date_range("2023-01-01", periods=1000, freq="D"))

    assert adherence.max_calendar_window_weeks(dates) >= adherence.DEFAULT_WINDOW_WEEKS
