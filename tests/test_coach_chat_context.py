from __future__ import annotations

import pandas as pd
import pytest

from iron_trail import config, ingest
from iron_trail.coach import chat as coach_chat

EXERCISES = [
    "Squat (Barbell)",
    "Bulgarian Split Squat",
    "Bench Press (Barbell)",
    "Incline Bench Press (Dumbbell)",
    "Leg Press",
    "Pull Up",
    "Face Pull (Cable)",
    "Romanian Deadlift (Barbell)",
]


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.load_and_clean(config.SAMPLE_CSV, body_weight_kg=84.0)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is my best Bulgarian split squats?", ["Bulgarian Split Squat"]),
        ("my bulgarians", ["Bulgarian Split Squat"]),
        ("how are my squats", ["Squat (Barbell)"]),
        ("romanian deadlifts?", ["Romanian Deadlift (Barbell)"]),
    ],
)
def test_named_exercises_resolve_to_the_specific_lift(
    question: str, expected: list[str]
) -> None:
    assert coach_chat.find_mentioned_exercises(question, EXERCISES) == expected


@pytest.mark.parametrize(
    "question",
    [
        "is my push pull balance okay",
        "whats the trend for the last 4 months",
        "how consistent have I been lately",
    ],
)
def test_generic_questions_match_no_exercise(question: str) -> None:
    """A lone shared word like "pull" must not drag in an unrelated lift —
    injecting the wrong exercise's history is worse than injecting none."""
    assert coach_chat.find_mentioned_exercises(question, EXERCISES) == []


def test_a_shared_generic_word_does_not_pull_in_other_lifts() -> None:
    matches = coach_chat.find_mentioned_exercises("how is my bench press going", EXERCISES)

    assert "Bench Press (Barbell)" in matches
    assert "Leg Press" not in matches


def test_context_exposes_all_time_bests_not_just_recent_form(frame: pd.DataFrame) -> None:
    """plateau_status already computes the all-time best and last PR date; an
    earlier context dropped both, so the coach could not answer "what's my
    best" even though the app had the number."""
    context = coach_chat.build_chat_context(frame)

    assert context["exercise_catalog"], "expected a catalog of every lift"
    entry = context["exercise_catalog"][0]
    for field in ("all_time_best_e1rm_kg", "current_e1rm_kg", "days_since_pr", "status"):
        assert field in entry

    for item in context["plateau_watch"]:
        assert "all_time_best_e1rm_kg" in item
        assert "last_pr_date" in item


def test_context_covers_more_than_the_last_thirty_days(frame: pd.DataFrame) -> None:
    context = coach_chat.build_chat_context(frame)

    assert context["monthly_totals"], "expected a multi-month volume trend"
    assert context["lifetime_sessions"] > context["session_count_30d"]
    assert context["muscle_volume_90d"], "expected muscle-group volume"
    assert context["weekly_push_pull"], "expected push:pull history"


def test_naming_an_exercise_attaches_its_monthly_trend(frame: pd.DataFrame) -> None:
    context = coach_chat.build_chat_context(frame, question="how are my squats going?")

    focus = context.get("focus_exercises")
    assert focus, "expected focus detail for a named exercise"
    detail = focus[0]
    assert detail["monthly_best_e1rm"], "expected a month-by-month trend"
    assert "all_time_best_e1rm_kg" in detail
    assert "last_pr_date" in detail


def test_followups_inherit_the_exercise_from_the_conversation(frame: pd.DataFrame) -> None:
    """"and what's the trend?" names no lift. Without carry-over the coach
    answered "that isn't in the loaded summary" mid-conversation."""
    history = [
        ("user", "What is my best squat?"),
        ("assistant", "Your best squat is 136.2 kg."),
    ]

    context = coach_chat.build_chat_context(
        frame, question="what was my best, and whats the trend for the last 4 months", history=history
    )

    focus = context.get("focus_exercises")
    assert focus, "a follow-up should inherit the last discussed exercise"
    assert focus[0]["exercise"] == "Squat (Barbell)"
    assert focus[0]["monthly_best_e1rm"]


def test_context_without_a_question_has_no_focus(frame: pd.DataFrame) -> None:
    assert "focus_exercises" not in coach_chat.build_chat_context(frame)


def test_context_stays_well_inside_the_input_budget(frame: pd.DataFrame) -> None:
    from iron_trail.usage_limits import UsagePolicy, estimate_tokens

    context = coach_chat.build_chat_context(frame, question="how are my squats?")
    history = [("user", "tell me more " * 20), ("assistant", "a long reply " * 60)] * 8
    messages = coach_chat.build_chat_messages(history, "and the trend?", context, "default")

    assert estimate_tokens(messages) < UsagePolicy().max_input_tokens


def test_empty_frame_still_returns_a_context() -> None:
    assert coach_chat.build_chat_context(pd.DataFrame()) == {"empty": True}
