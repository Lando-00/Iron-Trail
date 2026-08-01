"""Aggregations + derived metrics over the cleaned Hevy table."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

REST_DAY_TOLERANCE = 2


def workout_dates(df: pd.DataFrame) -> list[date]:
    return sorted({d for d in df["workout_date"].dropna()})


def current_streak(df: pd.DataFrame, today: date | None = None) -> int:
    """Days with at least one workout, anchored on the most recent training day.

    Tolerance: a streak survives up to `REST_DAY_TOLERANCE` rest days between
    sessions. Defaults to today's date; for test purposes pass `today` explicitly.
    """
    today = today or date.today()
    dates = set(workout_dates(df))
    if not dates:
        return 0
    d = today
    while d not in dates and (today - d).days <= REST_DAY_TOLERANCE:
        d -= timedelta(days=1)
    if d not in dates:
        return 0
    streak = 0
    while d in dates:
        streak += 1
        candidate = d - timedelta(days=1)
        while candidate not in dates and (d - candidate).days <= REST_DAY_TOLERANCE:
            candidate -= timedelta(days=1)
        if candidate in dates:
            d = candidate
        else:
            break
    return streak


def longest_streak(df: pd.DataFrame) -> int:
    dates = workout_dates(df)
    if not dates:
        return 0
    longest = current = 1
    for prev, nxt in zip(dates, dates[1:]):
        if (nxt - prev).days <= REST_DAY_TOLERANCE + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def overview_stats(df: pd.DataFrame, window_days: int = 30) -> dict:
    if df.empty or df["workout_date"].dropna().empty:
        return {
            "window_days": window_days,
            "workouts": 0,
            "tonnage_kg": 0.0,
            "training_hours": 0.0,
            "current_streak": 0,
            "longest_streak": 0,
        }
    end = max(df["workout_date"].dropna())
    start = end - timedelta(days=window_days)
    recent = df[(df["workout_date"] >= start) & (df["workout_date"] <= end)]

    workouts = recent["workout_id"].nunique()
    tonnage = float(recent.loc[recent["is_working"], "volume_kg"].sum())
    sessions = recent.drop_duplicates("workout_id")
    duration_min = float(sessions["duration_min"].fillna(0).sum())

    return {
        "window_days": window_days,
        "workouts": int(workouts),
        "tonnage_kg": tonnage,
        "training_hours": duration_min / 60,
        "current_streak": current_streak(df, today=end),
        "longest_streak": longest_streak(df),
    }


def per_session_top_e1rm(df: pd.DataFrame, exercise: str) -> pd.DataFrame:
    rows = df[(df["is_working"]) & (df["exercise_title"] == exercise) & df["e1rm_kg"].notna()]
    if rows.empty:
        return pd.DataFrame(columns=["workout_date", "e1rm_kg", "running_max", "is_pr"])
    by = (
        rows.groupby("workout_date", as_index=False)["e1rm_kg"]
        .max()
        .sort_values("workout_date")
        .reset_index(drop=True)
    )
    by["running_max"] = by["e1rm_kg"].cummax()
    by["is_pr"] = by["e1rm_kg"] >= by["running_max"]
    return by


def weekly_volume_by_muscle(df: pd.DataFrame) -> pd.DataFrame:
    rows = df[df["is_working"]].copy()
    if rows.empty:
        return pd.DataFrame(columns=["week", "primary_muscle", "volume_kg"])
    rows["week"] = pd.to_datetime(rows["workout_date"]).dt.to_period("W-SUN").dt.start_time
    return (
        rows.groupby(["week", "primary_muscle"], as_index=False)["volume_kg"].sum()
    )


def group_minor_muscles(
    volume: pd.DataFrame, top_n: int = 6, other_label: str = "other"
) -> pd.DataFrame:
    """Collapse the long tail of muscles into a single ``other`` series.

    The stacked tonnage chart legend measured 247x121 on a 358px-wide phone —
    a third of the chart — because every mapped muscle got its own entry. The
    ``top_n`` biggest muscles by total volume stay named; the rest are summed.
    """
    if volume.empty or volume["primary_muscle"].nunique() <= top_n:
        return volume

    totals = volume.groupby("primary_muscle")["volume_kg"].sum()
    keep = set(totals.nlargest(top_n).index)
    grouped = volume.copy()
    grouped["primary_muscle"] = grouped["primary_muscle"].where(
        grouped["primary_muscle"].isin(keep), other_label
    )
    return grouped.groupby(["week", "primary_muscle"], as_index=False)["volume_kg"].sum()


def weekly_push_pull(df: pd.DataFrame) -> pd.DataFrame:
    rows = df[df["is_working"]].copy()
    if rows.empty:
        return pd.DataFrame(columns=["week", "push", "pull", "push_pull_ratio"])
    rows["week"] = pd.to_datetime(rows["workout_date"]).dt.to_period("W-SUN").dt.start_time
    pivot = (
        rows.groupby(["week", "movement_type"])["volume_kg"]
        .sum()
        .unstack(fill_value=0.0)
        .reset_index()
    )
    if "push" not in pivot.columns:
        pivot["push"] = 0.0
    if "pull" not in pivot.columns:
        pivot["pull"] = 0.0
    pivot["push_pull_ratio"] = pivot["pull"] / pivot["push"].replace(0, pd.NA)
    return pivot


def exercise_list(df: pd.DataFrame) -> list[str]:
    return sorted(df.loc[df["is_working"], "exercise_title"].dropna().unique().tolist())


def time_of_day_distribution(df: pd.DataFrame) -> pd.DataFrame:
    workouts = df.drop_duplicates("workout_id").copy()
    if workouts.empty:
        return pd.DataFrame(columns=["hour", "count"])
    workouts["hour"] = pd.to_datetime(workouts["start_time"]).dt.hour
    return workouts.groupby("hour").size().rename("count").reset_index()


def session_volume_per_workout(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["workout_id", "workout_date", "session_volume"])
    base = df.drop_duplicates("workout_id")[["workout_id", "workout_date"]].copy()
    vol = (
        df[df["is_working"]]
        .groupby("workout_id", as_index=False)["volume_kg"]
        .sum()
        .rename(columns={"volume_kg": "session_volume"})
    )
    out = base.merge(vol, on="workout_id", how="left").fillna({"session_volume": 0.0})
    out["workout_date"] = pd.to_datetime(out["workout_date"])
    return out
