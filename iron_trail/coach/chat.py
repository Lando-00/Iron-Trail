"""Multi-turn chat helper.

Builds a slim per-session context dict (smaller than the full weekly
summary, so token usage stays bounded over many turns) and provides
helpers for running a conversation against any ``Provider``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from .. import analytics, metrics
from .providers import Message
from .providers.base import *  # noqa: F401,F403 — only here for protocol
from . import prompts as _prompts


MAX_HISTORY_TURNS = 8


def build_chat_context(df: pd.DataFrame) -> dict[str, Any]:
    """Compact context the chat provider uses to ground every reply.

    Sized to fit comfortably in <2k tokens.
    """
    if df.empty:
        return {"empty": True}

    today = pd.to_datetime(df["workout_date"]).max().date()
    last30_start = today - timedelta(days=30)

    win = df[df["workout_date"] >= last30_start]
    working = win[win["is_working"]] if not win.empty else win

    sessions = win.drop_duplicates("workout_id")

    # Top 8 exercises by recent e1RM
    top_e1rm = []
    if not working.empty:
        for ex, g in working.groupby("exercise_title"):
            v = g["e1rm_kg"].max()
            if pd.notna(v):
                top_e1rm.append({"exercise": ex, "e1rm_kg": float(v)})
        top_e1rm.sort(key=lambda r: -r["e1rm_kg"])
        top_e1rm = top_e1rm[:8]

    # Plateaus (only the worst)
    plateaus = analytics.all_plateaus(df, min_sessions=5, today=today)
    plateau_brief = [
        {
            "exercise": p.exercise,
            "status": p.status,
            "current_e1rm_kg": p.current_e1rm,
            "days_since_pr": p.days_since_pr,
        }
        for p in plateaus
        if p.status in ("plateaued", "regressing") and p.all_time_max_e1rm >= 40
    ][:6]

    return {
        "today": today.isoformat(),
        "window": "last_30_days",
        "session_count_30d": int(len(sessions)),
        "total_volume_kg_30d": float(working["volume_kg"].sum()) if not working.empty else 0.0,
        "current_streak_days": metrics.current_streak(df, today=today),
        "longest_streak_days": metrics.longest_streak(df),
        "top_e1rm_exercises": top_e1rm,
        "plateau_watch": plateau_brief,
    }


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
