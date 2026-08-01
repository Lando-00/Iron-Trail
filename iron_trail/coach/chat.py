"""Multi-turn chat helper.

Builds the per-session context dict the chat provider uses to ground every
reply, and provides helpers for running a conversation against any
``Provider``.

The context is deliberately generous. An early version sent only the last 30
days, the top 8 lifts by e1RM, and a plateau list stripped of its PR values —
so the coach answered most real questions with "that isn't in the loaded
summary" even though the app had already computed the answer. Input is capped
at 20k tokens, and a full context measures a small fraction of that, so the
limit was never the constraint.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pandas as pd

from .. import analytics, metrics
from .providers import Message
from .providers.base import *  # noqa: F401,F403 — only here for protocol
from . import prompts as _prompts


MAX_HISTORY_TURNS = 8

# Exercises named in a question get a full monthly history attached.
_MAX_FOCUS_EXERCISES = 3
_TREND_MONTHS = 6
# The catalogue must stay bounded. A real 3.7-year export has 142 exercises;
# sending detail for all of them measured 10,198 input tokens, which alone
# exceeds the deployment's 10k tokens-per-minute quota and 429s every call.
# Detail goes to the heaviest lifts; every other name is still listed cheaply
# so the coach can tell what exists and never invents a lift.
_MAX_CATALOG_DETAIL = 25
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def find_mentioned_exercises(question: str, exercises: list[str]) -> list[str]:
    """Exercises the question refers to, best match first.

    Only strong matches count. A single shared generic word like "press" would
    otherwise drag Leg Press into a question about the bench, and injecting the
    wrong lift's history is worse than injecting none. A lone word is accepted
    when it names the whole exercise ("squats") or when it appears in exactly
    one exercise in this user's data ("bulgarians").
    """
    asked = {_singular(word) for word in _words(question)}
    if not asked:
        return []

    stems: dict[str, set[str]] = {}
    for exercise in exercises:
        for word in _words(exercise):
            stems.setdefault(_singular(word), set()).add(exercise)

    scored: list[tuple[int, int, str]] = []
    for exercise in exercises:
        terms = {_singular(word) for word in _words(exercise)}
        # Equipment words appear in most names and carry no signal on their own.
        distinctive = terms - {"barbell", "dumbbell", "machine", "cable", "smith"}
        distinctive = distinctive or terms
        overlap = distinctive & asked
        if not overlap:
            continue
        unique_hit = any(len(stems.get(word, ())) == 1 for word in overlap)
        if len(overlap) < 2 and len(distinctive) > 1 and not unique_hit:
            continue
        scored.append((len(overlap), -len(distinctive), exercise))

    if not scored:
        return []

    scored.sort(reverse=True)
    best = scored[0][0]
    return [exercise for score, _, exercise in scored[:_MAX_FOCUS_EXERCISES] if score == best]


def _monthly_e1rm(df: pd.DataFrame, exercise: str, months: int) -> list[dict[str, Any]]:
    sessions = metrics.per_session_top_e1rm(df, exercise)
    if sessions.empty:
        return []
    sessions = sessions.copy()
    sessions["month"] = pd.to_datetime(sessions["workout_date"]).dt.to_period("M")
    grouped = (
        sessions.groupby("month")
        .agg(best_e1rm_kg=("e1rm_kg", "max"), sessions=("e1rm_kg", "size"))
        .reset_index()
        .tail(months)
    )
    return [
        {
            "month": str(row.month),
            "best_e1rm_kg": round(float(row.best_e1rm_kg), 1),
            "sessions": int(row.sessions),
        }
        for row in grouped.itertuples()
    ]


def _exercise_detail(df: pd.DataFrame, exercise: str, today) -> dict[str, Any]:
    status = analytics.plateau_status(df, exercise, today=today)
    rows = df[(df["exercise_title"] == exercise) & df["is_working"]]
    detail: dict[str, Any] = {
        "exercise": exercise,
        "monthly_best_e1rm": _monthly_e1rm(df, exercise, _TREND_MONTHS),
    }
    if not rows.empty:
        detail["total_sessions"] = int(rows["workout_id"].nunique())
        detail["heaviest_weight_kg"] = round(float(rows["weight_kg_load"].max()), 1)
        detail["last_performed"] = str(rows["workout_date"].max())
    if status is not None:
        detail.update(
            {
                "current_e1rm_kg": round(status.current_e1rm, 1),
                "all_time_best_e1rm_kg": round(status.all_time_max_e1rm, 1),
                "last_pr_date": str(status.last_pr_date) if status.last_pr_date else None,
                "days_since_pr": status.days_since_pr,
                "status": status.status,
            }
        )
    return detail


def build_chat_context(
    df: pd.DataFrame,
    question: str | None = None,
    history: list[tuple[str, str]] | None = None,
) -> dict:
    """Grounding context for one chat turn.

    When ``question`` names an exercise, that exercise's full history is
    attached so questions like "what's my best, and the trend" are answerable.
    Follow-ups rarely repeat the name ("and what's the trend?"), so the most
    recently discussed lift is carried over from ``history``.
    """
    if df.empty:
        return {"empty": True}

    working_all = df[df["is_working"]]
    today = pd.to_datetime(df["workout_date"]).max().date()
    last30_start = today - timedelta(days=30)

    win = df[df["workout_date"] >= last30_start]
    working = win[win["is_working"]] if not win.empty else win
    sessions = win.drop_duplicates("workout_id")

    # Detail for the heaviest lifts, names only for the rest — the full list
    # keeps the coach honest about what does and does not exist.
    all_names = metrics.exercise_list(df)
    catalog: list[dict[str, Any]] = []
    for exercise in all_names:
        status = analytics.plateau_status(df, exercise, today=today)
        if status is None:
            continue
        catalog.append(
            {
                "exercise": exercise,
                "all_time_best_e1rm_kg": round(status.all_time_max_e1rm, 1),
                "current_e1rm_kg": round(status.current_e1rm, 1),
                "days_since_pr": status.days_since_pr,
                "status": status.status,
            }
        )
    catalog.sort(key=lambda item: -item["all_time_best_e1rm_kg"])
    detailed = catalog[:_MAX_CATALOG_DETAIL]
    detailed_names = {item["exercise"] for item in detailed}
    other_names = [name for name in all_names if name not in detailed_names]

    # Volume by muscle over the last 90 days.
    muscle_volume: list[dict[str, Any]] = []
    recent = working_all[working_all["workout_date"] >= today - timedelta(days=90)]
    if not recent.empty:
        totals = recent.groupby("primary_muscle")["volume_kg"].sum().sort_values(ascending=False)
        muscle_volume = [
            {"muscle": muscle, "volume_kg_90d": round(float(value), 1)}
            for muscle, value in totals.items()
        ]

    # Push:pull over the last 8 weeks.
    push_pull: list[dict[str, Any]] = []
    pp = metrics.weekly_push_pull(df)
    if not pp.empty:
        for row in pp.tail(8).itertuples():
            ratio = getattr(row, "push_pull_ratio", None)
            push_pull.append(
                {
                    "week": str(pd.to_datetime(row.week).date()),
                    "push_kg": round(float(row.push), 1),
                    "pull_kg": round(float(row.pull), 1),
                    "pull_per_push": None if pd.isna(ratio) else round(float(ratio), 2),
                }
            )

    # Monthly training volume, so "what's my trend" has something to stand on.
    monthly: list[dict[str, Any]] = []
    if not working_all.empty:
        by_month = working_all.copy()
        by_month["month"] = pd.to_datetime(by_month["workout_date"]).dt.to_period("M")
        grouped = (
            by_month.groupby("month")
            .agg(volume_kg=("volume_kg", "sum"), sessions=("workout_id", "nunique"))
            .reset_index()
            .tail(_TREND_MONTHS)
        )
        monthly = [
            {
                "month": str(row.month),
                "volume_kg": round(float(row.volume_kg), 1),
                "sessions": int(row.sessions),
            }
            for row in grouped.itertuples()
        ]

    plateaus = analytics.all_plateaus(df, min_sessions=5, today=today)
    plateau_brief = [
        {
            "exercise": item.exercise,
            "status": item.status,
            "current_e1rm_kg": round(item.current_e1rm, 1),
            "all_time_best_e1rm_kg": round(item.all_time_max_e1rm, 1),
            "last_pr_date": str(item.last_pr_date) if item.last_pr_date else None,
            "days_since_pr": item.days_since_pr,
        }
        for item in plateaus
        if item.status in ("plateaued", "regressing") and item.all_time_max_e1rm >= 40
    ][:10]

    context: dict[str, Any] = {
        "today": today.isoformat(),
        "history_starts": str(df["workout_date"].min()),
        "lifetime_sessions": int(df["workout_id"].nunique()),
        "lifetime_volume_kg": round(float(working_all["volume_kg"].sum()), 1),
        "session_count_30d": int(len(sessions)),
        "total_volume_kg_30d": float(working["volume_kg"].sum()) if not working.empty else 0.0,
        "current_streak_days": metrics.current_streak(df, today=today),
        "longest_streak_days": metrics.longest_streak(df),
        "monthly_totals": monthly,
        "exercise_catalog": detailed,
        "other_exercises_logged": other_names,
        "muscle_volume_90d": muscle_volume,
        "weekly_push_pull": push_pull,
        "plateau_watch": plateau_brief,
    }

    if question:
        exercises = all_names
        focus = find_mentioned_exercises(question, exercises)
        if not focus and history:
            # "and what's the trend?" refers to whatever was last discussed.
            for _, content in reversed(history[-6:]):
                focus = find_mentioned_exercises(content, exercises)
                if focus:
                    break
        if focus:
            context["focus_exercises"] = [
                _exercise_detail(df, exercise, today) for exercise in focus
            ]

    return context


def build_chat_messages(
    history: list[tuple[str, str]],
    user_input: str,
    context: dict,
    personality: str = "default",
) -> list[Message]:
    """history is a list of (role, content) tuples where role is 'user' or 'assistant'."""
    msgs: list[Message] = [
        Message(role="system", content=_prompts.chat_system_prompt(context, personality)),
    ]
    capped = history[-(MAX_HISTORY_TURNS * 2):]
    for role, content in capped:
        if role not in ("user", "assistant"):
            continue
        msgs.append(Message(role=role, content=content))  # type: ignore[arg-type]
    msgs.append(Message(role="user", content=user_input))
    return msgs
