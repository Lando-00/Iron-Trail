"""Higher-level analytics: plateau detection, session archetypes, movement radar,
e1RM forecast, year-over-year comparison, achievement badges, worst sessions.

These complement the simpler aggregations in ``metrics.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import metrics

RADAR_PATTERNS = [
    "horizontal_push",
    "vertical_push",
    "horizontal_pull",
    "vertical_pull",
    "hinge",
    "squat",
    "single_leg",
    "core",
]

RADAR_LABELS = {
    "horizontal_push": "Horizontal Push",
    "vertical_push": "Vertical Push",
    "horizontal_pull": "Horizontal Pull",
    "vertical_pull": "Vertical Pull",
    "hinge": "Hinge",
    "squat": "Squat",
    "single_leg": "Single Leg",
    "core": "Core",
}


# =====================================================================
# Plateau detection
# =====================================================================

@dataclass
class PlateauStatus:
    exercise: str
    last_pr_date: date | None
    days_since_pr: int
    current_e1rm: float
    all_time_max_e1rm: float
    status: str               # fresh_pr | progressing | plateaued | regressing | new
    message: str


def plateau_status(df: pd.DataFrame, exercise: str, today: date | None = None) -> PlateauStatus | None:
    session_data = metrics.per_session_top_e1rm(df, exercise)
    if session_data.empty:
        return None

    session_data = session_data.sort_values("workout_date").reset_index(drop=True)
    today = today or session_data["workout_date"].max()

    current = float(session_data["e1rm_kg"].iloc[-1])
    all_max = float(session_data["e1rm_kg"].max())

    pr_rows = session_data[session_data["is_pr"]]
    last_pr = pr_rows["workout_date"].max() if not pr_rows.empty else session_data["workout_date"].iloc[0]
    days_since = (today - last_pr).days

    pct_of_max = current / all_max if all_max > 0 else 0

    if len(session_data) < 3:
        status, msg = (
            "new",
            f"Only {len(session_data)} session(s) logged for {exercise} — keep going.",
        )
    elif days_since <= 7:
        status = "fresh_pr"
        msg = "🔥 Fresh PR within the last week. Ride it."
    elif days_since <= 21:
        status = "progressing"
        msg = f"↗ Progressing. Last PR {days_since} days ago. Stay the course."
    elif pct_of_max < 0.90:
        status = "regressing"
        msg = (
            f"⚠ {exercise} is {(1 - pct_of_max) * 100:.0f}% off your peak. "
            f"Could be a deload, could be life — sleep and food first."
        )
    else:
        status = "plateaued"
        msg = (
            f"💤 {exercise} has been napping for {days_since} days at {current:.1f} kg. "
            f"Time for a deload, a new rep range, or a sternly-worded internal monologue."
        )

    return PlateauStatus(
        exercise=exercise,
        last_pr_date=last_pr,
        days_since_pr=days_since,
        current_e1rm=current,
        all_time_max_e1rm=all_max,
        status=status,
        message=msg,
    )


def all_plateaus(df: pd.DataFrame, min_sessions: int = 5, today: date | None = None) -> list[PlateauStatus]:
    """Return plateau statuses for every exercise with at least ``min_sessions`` sessions."""
    out: list[PlateauStatus] = []
    for ex in metrics.exercise_list(df):
        e1rm = metrics.per_session_top_e1rm(df, ex)
        if len(e1rm) < min_sessions:
            continue
        ps = plateau_status(df, ex, today=today)
        if ps is not None:
            out.append(ps)
    return out


# =====================================================================
# Session archetypes — K-Means over per-session features
# =====================================================================

def _build_session_features(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wid, g in df.groupby("workout_id"):
        working = g[g["is_working"]]
        if working.empty:
            continue
        avg_reps = float(working["reps"].mean())
        total_volume = float(working["volume_kg"].sum())
        set_count = int(len(working))
        duration = float(g["duration_min"].iloc[0] or 0)
        muscles = int(working["primary_muscle"].nunique())
        top_weight = float(working["weight_kg_load"].max() or 0)
        rows.append({
            "workout_id": wid,
            "workout_date": g["workout_date"].iloc[0],
            "title": g["title"].iloc[0],
            "avg_reps": avg_reps,
            "total_volume": total_volume,
            "set_count": set_count,
            "duration_min": duration,
            "muscles_trained": muscles,
            "top_weight_kg": top_weight,
        })
    return pd.DataFrame(rows)


def session_archetype(df: pd.DataFrame, n_clusters: int = 4, random_state: int = 42) -> pd.DataFrame:
    """Cluster sessions via K-Means, then label clusters by their feature profile.

    Labels in order of preference: Strength, Hypertrophy, Pump, Quick, Mixed.
    """
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    sessions = _build_session_features(df)
    if sessions.empty:
        sessions["archetype"] = pd.Series(dtype="object")
        return sessions

    if len(sessions) < n_clusters:
        sessions["archetype"] = "Mixed"
        return sessions

    features = sessions[["avg_reps", "total_volume", "duration_min", "top_weight_kg"]].fillna(0)
    X = StandardScaler().fit_transform(features)
    labels = KMeans(n_clusters=n_clusters, n_init=10, random_state=random_state).fit_predict(X)
    sessions["cluster"] = labels

    cluster_stats = (
        sessions.groupby("cluster")
        .agg(avg_reps=("avg_reps", "mean"),
             total_volume=("total_volume", "mean"),
             duration=("duration_min", "mean"),
             top_weight=("top_weight_kg", "mean"))
        .reset_index()
    )

    median_volume = sessions["total_volume"].median()
    label_map: dict[int, str] = {}
    available = ["Strength", "Hypertrophy", "Pump", "Quick", "Mixed"]
    used: set[str] = set()

    for _, row in cluster_stats.sort_values("avg_reps").iterrows():
        c = int(row["cluster"])
        if row["avg_reps"] < 7 and "Strength" not in used:
            label = "Strength"
        elif row["avg_reps"] > 11 and "Pump" not in used:
            label = "Pump"
        elif row["total_volume"] < median_volume * 0.7 and "Quick" not in used:
            label = "Quick"
        elif "Hypertrophy" not in used:
            label = "Hypertrophy"
        else:
            label = next((a for a in available if a not in used), "Mixed")
        used.add(label)
        label_map[c] = label

    sessions["archetype"] = sessions["cluster"].map(label_map)
    return sessions


# =====================================================================
# Movement radar
# =====================================================================

def movement_radar_data(df: pd.DataFrame, weeks_back: int = 12) -> pd.DataFrame:
    """Working-set counts per movement pattern over the last ``weeks_back`` weeks."""
    if df.empty:
        return pd.DataFrame(columns=["movement_pattern", "label", "working_sets", "sets_per_week"])

    end = max(df["workout_date"].dropna())
    start = end - timedelta(weeks=weeks_back)
    window = df[
        (df["workout_date"] >= start)
        & (df["workout_date"] <= end)
        & df["is_working"]
        & df["movement_pattern"].isin(RADAR_PATTERNS)
    ]
    counts = (
        window.groupby("movement_pattern")
        .size()
        .reindex(RADAR_PATTERNS, fill_value=0)
        .rename("working_sets")
        .reset_index()
    )
    counts["sets_per_week"] = counts["working_sets"] / weeks_back
    counts["label"] = counts["movement_pattern"].map(RADAR_LABELS)
    return counts


# =====================================================================
# e1RM forecast
# =====================================================================

def e1rm_forecast(
    df: pd.DataFrame,
    exercise: str,
    weeks_ahead: int = 4,
    fit_last_n: int = 12,
) -> pd.DataFrame | None:
    """Linear extrapolation of e1RM with a widening confidence band.

    Returns ``None`` if there aren't enough sessions to fit (< 4).
    """
    session_data = metrics.per_session_top_e1rm(df, exercise)
    if len(session_data) < 4:
        return None

    fit = session_data.tail(fit_last_n).copy().reset_index(drop=True)
    fit["date"] = pd.to_datetime(fit["workout_date"])
    anchor = fit["date"].iloc[0]
    fit["day_num"] = (fit["date"] - anchor).dt.days.astype(float)

    x = fit["day_num"].to_numpy()
    y = fit["e1rm_kg"].astype(float).to_numpy()

    if np.allclose(x.std(), 0):
        return None

    slope, intercept = np.polyfit(x, y, 1)
    in_sample = slope * x + intercept
    residuals = y - in_sample
    sigma = float(np.std(residuals)) if len(residuals) > 1 else 0.0
    x_mean = float(x.mean())
    sx2 = float(np.sum((x - x_mean) ** 2))

    last_day = float(x[-1])
    forecast_days = np.arange(last_day + 7, last_day + 7 * (weeks_ahead + 1), 7)
    forecast_y = slope * forecast_days + intercept
    if sx2 > 0 and sigma > 0:
        band = sigma * 1.96 * np.sqrt(1 + 1 / len(x) + (forecast_days - x_mean) ** 2 / sx2)
    else:
        band = np.zeros_like(forecast_y)

    return pd.DataFrame({
        "workout_date": [anchor + pd.Timedelta(days=int(d)) for d in forecast_days],
        "e1rm_kg": forecast_y,
        "lower": forecast_y - band,
        "upper": forecast_y + band,
        "weeks_ahead": np.arange(1, weeks_ahead + 1),
    })


# =====================================================================
# Year-over-year overlay
# =====================================================================

def year_over_year(df: pd.DataFrame, exercise: str, weeks: int = 12) -> dict | None:
    """Return current vs same-window-last-year e1RM series for overlay rendering."""
    session_data = metrics.per_session_top_e1rm(df, exercise)
    if session_data.empty:
        return None

    session_data["date"] = pd.to_datetime(session_data["workout_date"])
    end = session_data["date"].max()
    current_start = end - pd.Timedelta(weeks=weeks)
    current = session_data[session_data["date"] >= current_start].copy()

    last_end = end - pd.Timedelta(days=365)
    last_start = last_end - pd.Timedelta(weeks=weeks)
    last = session_data[(session_data["date"] >= last_start) & (session_data["date"] <= last_end)].copy()

    if last.empty:
        return None

    last["date_shifted"] = last["date"] + pd.Timedelta(days=365)
    return {
        "current": current[["date", "e1rm_kg"]],
        "last_year": last[["date_shifted", "e1rm_kg"]].rename(columns={"date_shifted": "date"}),
        "current_delta": float(current["e1rm_kg"].iloc[-1] - last["e1rm_kg"].iloc[-1])
        if not current.empty else None,
    }


# =====================================================================
# Achievement badges
# =====================================================================

def _safe_max(series: pd.Series) -> float:
    series = pd.to_numeric(series, errors="coerce").dropna()
    return float(series.max()) if not series.empty else 0.0


def awards_earned(df: pd.DataFrame, body_weight_kg: float = 84.0) -> list[dict]:
    if df.empty:
        return []

    working = df[df["is_working"]]
    total_workouts = int(df["workout_id"].nunique())
    total_volume = float(working["volume_kg"].sum())
    longest = metrics.longest_streak(df)
    n_exercises = int(df["exercise_title"].nunique())

    def best_for(pattern: str) -> float:
        mask = working["exercise_title"].astype(str).str.contains(pattern, regex=False, na=False)
        return _safe_max(working.loc[mask, "e1rm_kg"])

    bench = best_for("Bench Press (Barbell)")
    squat = best_for("Squat (Barbell)")
    deadlift = best_for("Deadlift (Barbell)")

    weekly = working.copy()
    if not weekly.empty:
        weekly["week"] = pd.to_datetime(weekly["workout_date"]).dt.to_period("W")
        max_week_vol = float(weekly.groupby("week")["volume_kg"].sum().max())
    else:
        max_week_vol = 0.0

    dates = df["workout_date"].dropna()
    if not dates.empty:
        years_active = (max(dates) - min(dates)).days / 365.25
    else:
        years_active = 0.0

    def b(name: str, icon: str, criteria: str, current: float, target: float, kind: str = "num"):
        unlocked = current >= target
        progress = min(current / target, 1.0) if target > 0 else 0.0
        if kind == "kg":
            cur_s, tgt_s = f"{current:,.0f}kg", f"{target:,.0f}kg"
        elif kind == "days":
            cur_s, tgt_s = f"{int(current)}d", f"{int(target)}d"
        elif kind == "count":
            cur_s, tgt_s = f"{int(current)}", f"{int(target)}"
        elif kind == "year":
            cur_s, tgt_s = f"{current:.1f}y", f"{target:.1f}y"
        else:
            cur_s, tgt_s = f"{current:.1f}", f"{target:.1f}"
        return {
            "name": name, "icon": icon, "criteria": criteria,
            "current": current, "target": target, "progress": progress,
            "unlocked": unlocked, "current_str": cur_s, "target_str": tgt_s,
        }

    badges = [
        b("First Plate", "🥏", "Bench Press e1RM ≥ 60 kg", bench, 60, "kg"),
        b("Bodyweight Bench", "🪞", f"Bench Press ≥ {body_weight_kg:.0f} kg (bodyweight)", bench, body_weight_kg, "kg"),
        b("Three-Plate Pressed", "💯", "Bench Press e1RM ≥ 100 kg", bench, 100, "kg"),
        b("Bodyweight Squat", "🦵", f"Squat e1RM ≥ {body_weight_kg:.0f} kg", squat, body_weight_kg, "kg"),
        b("Heavy Squatter", "🏔", "Squat e1RM ≥ 1.5× bodyweight", squat, body_weight_kg * 1.5, "kg"),
        b("Deadlifter", "🪦", f"Deadlift e1RM ≥ {body_weight_kg:.0f} kg", deadlift, body_weight_kg, "kg"),
        b("1.5× Deadlift", "🪨", "Deadlift e1RM ≥ 1.5× bodyweight", deadlift, body_weight_kg * 1.5, "kg"),
        b("Double-BW Deadlift", "🗿", "Deadlift e1RM ≥ 2× bodyweight", deadlift, body_weight_kg * 2, "kg"),
        b("Streak Survivor", "🔥", "Longest streak ≥ 14 days", longest, 14, "days"),
        b("Streak Master", "🔥🔥", "Longest streak ≥ 30 days", longest, 30, "days"),
        b("Century Club", "💯", "100 workouts logged", total_workouts, 100, "count"),
        b("Three Centuries", "🏛", "300 workouts logged", total_workouts, 300, "count"),
        b("Ten-K Week", "🌊", "Single-week volume ≥ 10,000 kg", max_week_vol, 10_000, "kg"),
        b("Twenty-K Week", "🌊🌊", "Single-week volume ≥ 20,000 kg", max_week_vol, 20_000, "kg"),
        b("Lifetime Million", "💎", "1,000,000 kg lifetime tonnage", total_volume, 1_000_000, "kg"),
        b("Two-Million Mountain", "💎💎", "2,000,000 kg lifetime tonnage", total_volume, 2_000_000, "kg"),
        b("Variety King", "🌈", "30+ distinct exercises", n_exercises, 30, "count"),
        b("Library Builder", "📚", "60+ distinct exercises", n_exercises, 60, "count"),
        b("1 Year Strong", "🌱", "1 year of training history", years_active, 1.0, "year"),
        b("3 Years Strong", "🌳", "3 years of training history", years_active, 3.0, "year"),
    ]
    return badges


# =====================================================================
# Worst sessions
# =====================================================================

_LOWLIGHT_CAPTIONS = [
    "your phone weighed more than the bar today",
    "even your warmups were warmups",
    "history will remember this set… briefly",
    "the gym sent a missing-person report",
    "a noble attempt at minimal effort",
    "calling this a workout would be generous",
    "the trainer pretended not to see you",
    "a victorious lap of the water fountain",
    "the bar got off lightly today",
    "you trained, technically",
]


def worst_sessions(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    rows = []
    for wid, g in df.groupby("workout_id"):
        working = g[g["is_working"]]
        if working.empty:
            continue
        total_vol = float(working["volume_kg"].sum())
        if total_vol < 50:
            continue
        rows.append({
            "workout_id": wid,
            "workout_date": g["workout_date"].iloc[0],
            "title": g["title"].iloc[0],
            "total_volume": total_vol,
            "set_count": int(len(working)),
            "duration_min": float(g["duration_min"].iloc[0] or 0),
        })
    s = pd.DataFrame(rows)
    if s.empty:
        return s

    median_vol = s["total_volume"].median()
    s["volume_pct_of_median"] = s["total_volume"] / median_vol * 100
    worst = s.nsmallest(n, "total_volume").reset_index(drop=True)

    from . import comedy
    rng = np.random.default_rng(seed=42)
    worst["caption"] = [comedy.caption_for_session(row, rng) for _, row in worst.iterrows()]
    return worst


def best_sessions(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """The inverse of worst_sessions — top N by an "underrated metric" score.

    Score combines:
      - total working-set volume (z-score)
      - number of distinct muscle groups hit (z-score)
      - heaviest top set (z-score)
      - biggest e1RM jump within the session vs the user's running max
    """
    rows = []
    for wid, g in df.groupby("workout_id"):
        working = g[g["is_working"]]
        if working.empty:
            continue
        total_vol = float(working["volume_kg"].sum())
        if total_vol < 100:
            continue
        rows.append({
            "workout_id": wid,
            "workout_date": g["workout_date"].iloc[0],
            "title": g["title"].iloc[0],
            "total_volume": total_vol,
            "set_count": int(len(working)),
            "duration_min": float(g["duration_min"].iloc[0] or 0),
            "muscles_hit": int(working["primary_muscle"].nunique()),
            "top_weight_kg": float(working["weight_kg_load"].max() or 0),
            "top_e1rm_kg": float(working["e1rm_kg"].max() or 0),
        })
    s = pd.DataFrame(rows)
    if s.empty:
        return s

    # z-score each contributing column (guard against zero std)
    def z(col: str) -> pd.Series:
        std = s[col].std()
        if std == 0 or pd.isna(std):
            return pd.Series(0.0, index=s.index)
        return (s[col] - s[col].mean()) / std

    s["score"] = (
        1.0 * z("total_volume")
        + 0.7 * z("muscles_hit")
        + 1.0 * z("top_weight_kg")
        + 0.6 * z("top_e1rm_kg")
    )

    best = s.nlargest(n, "score").reset_index(drop=True)

    # Classify "what kind of best day" each was, used by the smart caption picker
    def kind_for(row) -> str:
        if row["top_weight_kg"] >= s["top_weight_kg"].quantile(0.90):
            return "heavy"
        if row["muscles_hit"] >= s["muscles_hit"].quantile(0.85):
            return "marathon"
        return "all_round"

    best["kind"] = best.apply(kind_for, axis=1)

    from . import comedy
    rng = np.random.default_rng(seed=11)
    best["caption"] = [comedy.caption_for_hof_session(row, rng) for _, row in best.iterrows()]
    return best
