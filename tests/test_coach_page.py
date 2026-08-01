"""Functional regression tests for the Coach chat tab.

These drive the real page with Streamlit's AppTest rather than asserting on
source text, so they fail if the widget lifecycle regresses for any reason.
"""
from __future__ import annotations

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

COACH_PAGE = pathlib.Path(__file__).parents[1] / "pages" / "6_💬_Coach.py"


def _run_coach() -> AppTest:
    app = AppTest.from_file(str(COACH_PAGE), default_timeout=60)
    app.run()
    return app


@pytest.fixture(autouse=True)
def _local_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COACH_LLM", "mock")
    monkeypatch.delenv("IRONTRAIL_MODE", raising=False)


def test_chat_input_is_present_before_any_interaction() -> None:
    app = _run_coach()

    assert not app.exception
    assert len(app.chat_input) == 1


def test_chat_input_survives_clicking_a_starter_prompt() -> None:
    """Regression: `starter_click or st.chat_input(...)` short-circuits, so a
    starter click skipped the widget and the input disappeared until the next
    unrelated rerun."""
    app = _run_coach()
    starters = [button for button in app.button if button.key and button.key.startswith("coach_starter_")]
    assert starters, "expected starter prompt buttons on a fresh chat"

    starters[0].click().run()

    assert not app.exception
    assert len(app.chat_input) == 1, "chat input vanished after using a starter prompt"


def test_starter_click_produces_a_conversation() -> None:
    app = _run_coach()
    starters = [button for button in app.button if button.key and button.key.startswith("coach_starter_")]
    label = starters[0].label

    starters[0].click().run()

    history = app.session_state["coach_chat_history"]
    assert history[0] == ("user", label)
    assert history[1][0] == "assistant"
    assert history[1][1].strip()


def test_chat_input_still_present_after_a_typed_message() -> None:
    app = _run_coach()

    app.chat_input[0].set_value("How consistent have I been lately?").run()

    assert not app.exception
    assert len(app.chat_input) == 1
    assert app.session_state["coach_chat_history"][0][0] == "user"
