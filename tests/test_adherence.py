from __future__ import annotations

import pandas as pd

from iron_trail import adherence


def test_calendar_window_matches_short_history() -> None:
    dates = pd.Series(pd.to_datetime(["2026-02-15", "2026-05-15"]))

    assert adherence.max_calendar_window_weeks(dates) == 16


def test_calendar_window_keeps_minimum_for_small_dataset() -> None:
    dates = pd.Series(pd.to_datetime(["2026-05-01", "2026-05-15"]))

    assert adherence.max_calendar_window_weeks(dates) == 8


def test_calendar_window_caps_long_history() -> None:
    dates = pd.Series(pd.to_datetime(["2020-01-01", "2026-05-15"]))

    assert adherence.max_calendar_window_weeks(dates) == 104


def test_calendar_window_ignores_invalid_dates() -> None:
    dates = pd.Series(["not-a-date", None])

    assert adherence.max_calendar_window_weeks(dates) == 8
