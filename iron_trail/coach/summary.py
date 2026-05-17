"""Build structured summary dicts that get fed to the LLM.

The Coach module never lets the LLM make up numbers — it gets the
structured summary as input, then writes prose around the numbers we
already know. Everything in the rendered review's *Stats* block comes
from these functions; the LLM only writes the *Reflections* block.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from .. import analytics, metrics


@dataclass(frozen=True)
class WeekRange:
    week_start: date     # Monday
    week_end: date       # Sunday
    iso_year: int
    iso_week: int
    label: str           # "2026-W20"

    @classmethod
    def from_end(cls, end_date: date) -> "WeekRange":
        # Snap to the Sunday of the ISO week containing end_date
        # ISO weeks: Monday=0, Sunday=6
        weekday = end_date.weekday()
        days_to_sunday = (6 - weekday) % 7
        week_end = end_date + timedelta(days=days_to_sunday)
        if week_end > end_date:
            # If end_date isn't Sunday, snap to the current week's Sunday
            # (which may be in the future); for the purpose of weekly review
            # we usually want the most recent complete week — caller can pass
            # last_sunday() if so.
            pass
        week_start = week_end - timedelta(days=6)
        iso_year, iso_week, _ = week_end.isocalendar()
        return cls(
            week_start=week_start,
            week_end=week_end,
            iso_year=iso_year,
            iso_week=iso_week,
            label=f"{iso_year}-W{iso_week:02d}",
        )


def last_complete_week(today: date | None = None) -> WeekRange:
    """The most recently *completed* ISO week (Monday–Sunday)."""
    today = today or date.today()
    # Step back to last Sunday (inclusive of today if it IS Sunday)
    weekday = today.weekday()
    days_since_sunday = (weekday + 1) % 7
    last_sunday = today - timedelta(days=days_since_sunday)
    return WeekRange.from_end(last_sunday)


def _filter_to_window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    return df[
        (df["workout_date"] >= start)
        & (df["workout_date"] <= end)
    ].copy()


def _safe(value: Any, default: Any = None) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return value


def build_weekly(df: pd.DataFrame, week: WeekRange | None = None) -> dict:
    """Return a structured summary of the given week for the LLM + the render layer."""
    if week is None:
        week = last_complete_week()

    win = _filter_to_window(df, week.week_start, week.week_end)
    prev_end = week.week_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    prev = _filter_to_window(df, prev_start, prev_end)

    working = win[win["is_working"]] if not win.empty else win
    prev_working = prev[prev["is_working"]] if not prev.empty else prev

    # Sessions
    sessions = win.drop_duplicates("workout_id").sort_values("start_time")
    session_count = int(len(sessions))
    total_volume_kg = float(working["volume_kg"].sum()) if not working.empty else 0.0
    training_min = float(sessions["duration_min"].fillna(0).sum()) if not sessions.empty else 0.0

    prev_volume_kg = float(prev_working["volume_kg"].sum()) if not prev_working.empty else 0.0
    volume_delta_kg = total_volume_kg - prev_volume_kg
    volume_delta_pct = (
        (total_volume_kg - prev_volume_kg) / prev_volume_kg * 100
        if prev_volume_kg > 0 else None
    )

    # Per-exercise top e1RM + delta vs prior week
    top_e1rm_this: dict[str, float] = {}
    if not working.empty:
        for ex, g in working.groupby("exercise_title"):
            v = g["e1rm_kg"].max()
            if pd.notna(v):
                top_e1rm_this[ex] = float(v)
    top_e1rm_prev: dict[str, float] = {}
    if not prev_working.empty:
        for ex, g in prev_working.groupby("exercise_title"):
            v = g["e1rm_kg"].max()
            if pd.notna(v):
                top_e1rm_prev[ex] = float(v)

    exercise_deltas = []
    for ex, this_e1rm in sorted(top_e1rm_this.items(), key=lambda kv: -kv[1]):
        prev_e1rm = top_e1rm_prev.get(ex)
        delta = (this_e1rm - prev_e1rm) if prev_e1rm is not None else None
        exercise_deltas.append({
            "exercise": ex,
            "e1rm_kg": this_e1rm,
            "prev_week_e1rm_kg": prev_e1rm,
            "delta_kg": delta,
        })

    # Plateaus on the full df (not just this week — plateaus are cumulative)
    all_plateaus = analytics.all_plateaus(df, min_sessions=5, today=week.week_end)
    plateau_callouts = []
    for p in all_plateaus:
        if p.status in ("plateaued", "regressing") and p.all_time_max_e1rm >= 40:
            plateau_callouts.append({
                "exercise": p.exercise,
                "status": p.status,
                "current_e1rm_kg": p.current_e1rm,
                "peak_e1rm_kg": p.all_time_max_e1rm,
                "days_since_pr": p.days_since_pr,
                "message": p.message,
            })

    # Push:pull ratio
    pp_all = metrics.weekly_push_pull(df)
    pp_this = pp_all[pp_all["week"].dt.date == week.week_start] if not pp_all.empty else pp_all
    push_pull_ratio = None
    if not pp_this.empty and "push_pull_ratio" in pp_this.columns:
        v = pp_this["push_pull_ratio"].iloc[0]
        if pd.notna(v):
            push_pull_ratio = float(v)

    # Archetype mix for the window
    archetype_mix: dict[str, int] = {}
    if not sessions.empty:
        full_arch = analytics.session_archetype(df)
        window_ids = set(sessions["workout_id"].tolist())
        arch_window = full_arch[full_arch["workout_id"].isin(window_ids)]
        if not arch_window.empty:
            archetype_mix = arch_window["archetype"].value_counts().to_dict()
            archetype_mix = {str(k): int(v) for k, v in archetype_mix.items()}

    # Movement radar deltas (this week vs prev week)
    def radar_for(window_df: pd.DataFrame) -> dict[str, int]:
        if window_df.empty:
            return {p: 0 for p in analytics.RADAR_PATTERNS}
        rows = window_df[
            window_df["is_working"]
            & window_df["movement_pattern"].isin(analytics.RADAR_PATTERNS)
        ]
        counts = rows.groupby("movement_pattern").size().to_dict()
        return {p: int(counts.get(p, 0)) for p in analytics.RADAR_PATTERNS}

    radar_this = radar_for(win)
    radar_prev = radar_for(prev)
    radar_deltas = {
        p: {
            "this_week_sets": radar_this[p],
            "prev_week_sets": radar_prev[p],
            "delta_sets": radar_this[p] - radar_prev[p],
        }
        for p in analytics.RADAR_PATTERNS
    }

    # Streak (anchored at the end of the window)
    current_streak = metrics.current_streak(df, today=week.week_end)
    longest_streak = metrics.longest_streak(df)

    # Sessions detail list (lightweight — title, date, vol, archetype if known)
    arch_lookup: dict[int, str] = {}
    if archetype_mix:
        full_arch = analytics.session_archetype(df)
        arch_lookup = dict(zip(
            full_arch["workout_id"].tolist(),
            full_arch["archetype"].tolist(),
        ))

    session_summaries = []
    for _, s in sessions.iterrows():
        wid = s["workout_id"]
        wrk = working[working["workout_id"] == wid] if not working.empty else working
        session_summaries.append({
            "date": pd.to_datetime(s["workout_date"]).date().isoformat(),
            "title": str(s["title"]) if pd.notna(s["title"]) else "Untitled",
            "duration_min": int(_safe(s["duration_min"], 0)),
            "volume_kg": float(wrk["volume_kg"].sum()) if not wrk.empty else 0.0,
            "set_count": int(len(wrk)),
            "archetype": arch_lookup.get(wid),
        })

    return {
        "kind": "weekly",
        "week_label": week.label,
        "week_start": week.week_start.isoformat(),
        "week_end": week.week_end.isoformat(),
        "session_count": session_count,
        "training_minutes": int(training_min),
        "total_volume_kg": total_volume_kg,
        "prev_volume_kg": prev_volume_kg,
        "volume_delta_kg": volume_delta_kg,
        "volume_delta_pct": volume_delta_pct,
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "push_pull_ratio": push_pull_ratio,
        "archetype_mix": archetype_mix,
        "exercise_top_e1rm": exercise_deltas,
        "plateau_callouts": plateau_callouts,
        "movement_radar": radar_deltas,
        "sessions": session_summaries,
    }


# ---------------------------------------------------------------------------
# Monthly summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthRange:
    month_start: date
    month_end: date
    label: str  # "2026-05"

    @classmethod
    def from_end(cls, end_date: date) -> "MonthRange":
        month_end = end_date
        month_start = end_date.replace(day=1)
        return cls(
            month_start=month_start,
            month_end=month_end,
            label=f"{end_date.year}-{end_date.month:02d}",
        )


def build_monthly(df: pd.DataFrame, month: MonthRange | None = None) -> dict:
    """Same shape as build_weekly but over a calendar month, plus a trajectory."""
    if month is None:
        today = date.today()
        # Last day of the previous month
        first_of_this = today.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        month = MonthRange.from_end(last_of_prev)

    win = _filter_to_window(df, month.month_start, month.month_end)
    working = win[win["is_working"]] if not win.empty else win

    sessions = win.drop_duplicates("workout_id").sort_values("start_time")
    session_count = int(len(sessions))
    total_volume_kg = float(working["volume_kg"].sum()) if not working.empty else 0.0
    training_min = float(sessions["duration_min"].fillna(0).sum()) if not sessions.empty else 0.0

    # Trajectory: top e1RM per exercise, per ISO week, within the month
    trajectory: list[dict] = []
    if not working.empty:
        win_copy = working.copy()
        win_copy["iso_week"] = pd.to_datetime(win_copy["workout_date"]).dt.isocalendar().week
        for ex, g in win_copy.groupby("exercise_title"):
            wk_max = g.groupby("iso_week")["e1rm_kg"].max().dropna()
            if len(wk_max) >= 2:
                trajectory.append({
                    "exercise": str(ex),
                    "weeks": [int(w) for w in wk_max.index.tolist()],
                    "e1rm_kg": [float(v) for v in wk_max.values.tolist()],
                    "start_e1rm_kg": float(wk_max.iloc[0]),
                    "end_e1rm_kg": float(wk_max.iloc[-1]),
                    "change_kg": float(wk_max.iloc[-1] - wk_max.iloc[0]),
                })
    trajectory.sort(key=lambda t: -t["end_e1rm_kg"])
    trajectory = trajectory[:10]

    # Archetype mix
    archetype_mix: dict[str, int] = {}
    if not sessions.empty:
        full_arch = analytics.session_archetype(df)
        window_ids = set(sessions["workout_id"].tolist())
        arch_window = full_arch[full_arch["workout_id"].isin(window_ids)]
        if not arch_window.empty:
            archetype_mix = arch_window["archetype"].value_counts().to_dict()
            archetype_mix = {str(k): int(v) for k, v in archetype_mix.items()}

    # Plateaus
    all_plateaus = analytics.all_plateaus(df, min_sessions=5, today=month.month_end)
    plateau_callouts = []
    for p in all_plateaus:
        if p.status in ("plateaued", "regressing") and p.all_time_max_e1rm >= 40:
            plateau_callouts.append({
                "exercise": p.exercise,
                "status": p.status,
                "current_e1rm_kg": p.current_e1rm,
                "peak_e1rm_kg": p.all_time_max_e1rm,
                "days_since_pr": p.days_since_pr,
                "message": p.message,
            })

    return {
        "kind": "monthly",
        "month_label": month.label,
        "month_start": month.month_start.isoformat(),
        "month_end": month.month_end.isoformat(),
        "session_count": session_count,
        "training_minutes": int(training_min),
        "total_volume_kg": total_volume_kg,
        "trajectory": trajectory,
        "archetype_mix": archetype_mix,
        "plateau_callouts": plateau_callouts,
    }
