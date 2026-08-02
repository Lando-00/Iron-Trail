"""Functional regression tests for the sidebar bodyweight control.

Drives the real app with Streamlit's AppTest so a widget-lifecycle regression
(the value silently resetting to the config default) fails here.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from iron_trail import config

APP = pathlib.Path(__file__).parents[1] / "streamlit_app.py"


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> pathlib.Path:
    monkeypatch.delenv("IRONTRAIL_MODE", raising=False)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr(config, "PROFILE_JSON", profile)
    return profile


def _run() -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=90)
    app.run()
    return app


def _body_weight(app: AppTest):
    return app.sidebar.number_input(key="it_body_weight")


def test_body_weight_starts_at_the_config_default() -> None:
    app = _run()

    assert not app.exception
    assert _body_weight(app).value == pytest.approx(float(config.BODY_WEIGHT_KG))


def test_body_weight_survives_a_rerun(tmp_path: pathlib.Path) -> None:
    """Regression: the widget had no key and re-seeded from config every run,
    so navigating between pages threw the user's bodyweight away."""
    app = _run()
    _body_weight(app).set_value(71.5).run()

    assert not app.exception
    assert _body_weight(app).value == pytest.approx(71.5)

    app.run()
    assert _body_weight(app).value == pytest.approx(71.5)


def test_body_weight_is_written_to_disk(_local_mode: pathlib.Path) -> None:
    app = _run()
    assert not _local_mode.exists(), "an untouched default must not write a file"

    _body_weight(app).set_value(71.5).run()

    assert json.loads(_local_mode.read_text(encoding="utf-8")) == {"body_weight_kg": 71.5}


def test_saved_body_weight_is_restored_in_a_new_session(_local_mode: pathlib.Path) -> None:
    _local_mode.parent.mkdir(parents=True, exist_ok=True)
    _local_mode.write_text(json.dumps({"body_weight_kg": 66.0}), encoding="utf-8")

    app = _run()

    assert not app.exception
    assert _body_weight(app).value == pytest.approx(66.0)


_CLOUD_SCRIPT = """
import streamlit as st

from iron_trail import sidebar
from iron_trail.cloud_storage import CloudStorageError, InMemoryDatasetRepository


class Failing(InMemoryDatasetRepository):
    def save_profile(self, user_id, body_weight_kg):
        raise CloudStorageError("Unable to save your bodyweight.")


repository = st.session_state.setdefault(
    "repo", Failing() if st.session_state.get("fail") else InMemoryDatasetRepository()
)
with st.sidebar:
    weight = sidebar._render_cloud_body_weight(repository, "user-a")

stored = repository.get_profile("user-a")
st.text(f"weight={weight}")
st.text(f"stored={stored.body_weight_kg if stored else None}")
"""


def _run_cloud(fail: bool = False) -> AppTest:
    app = AppTest.from_string(_CLOUD_SCRIPT, default_timeout=60)
    app.session_state["fail"] = fail
    app.run()
    return app


def test_cloud_body_weight_is_saved_to_the_account() -> None:
    app = _run_cloud()

    assert not app.exception
    assert app.text[1].value == "stored=None", "an untouched default must not be written"

    app.sidebar.number_input(key="it_body_weight").set_value(70.0).run()

    assert app.text[0].value == "weight=70.0"
    assert app.text[1].value == "stored=70.0"

    app.run()
    assert app.sidebar.number_input(key="it_body_weight").value == pytest.approx(70.0)


def test_cloud_body_weight_degrades_gracefully_when_storage_fails() -> None:
    app = _run_cloud(fail=True)
    app.sidebar.number_input(key="it_body_weight").set_value(70.0).run()

    assert not app.exception
    assert app.text[0].value == "weight=70.0", "the session must still use the new value"
    assert any("this session only" in warning.value for warning in app.warning)
