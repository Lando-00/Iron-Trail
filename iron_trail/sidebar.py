"""Shared Streamlit sidebar.

All five pages render the same data-source picker (drag-and-drop CSV
uploader + dropdown of existing files in ``data/raw/`` + the bundled
sample) and bodyweight input. State is held in ``st.session_state`` so an
uploaded file persists as the user navigates between pages.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from . import config, ingest


def _csv_choices() -> list[str]:
    raw = sorted(config.RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = [str(p) for p in raw]
    if config.SAMPLE_CSV.exists():
        items.append(str(config.SAMPLE_CSV))
    return items or [str(config.SAMPLE_CSV)]


@st.cache_data(show_spinner="Parsing Hevy CSV…")
def _load_from_path(path: str, body_weight_kg: float) -> pd.DataFrame:
    return ingest.load_and_clean(Path(path), body_weight_kg=body_weight_kg)


@st.cache_data(show_spinner="Parsing Hevy CSV…")
def _load_from_bytes(content: bytes, _filename: str, body_weight_kg: float) -> pd.DataFrame:
    """Cache-keyed on `content` + `_filename` so re-uploading the same file is a cache hit."""
    return ingest.load_and_clean(io.BytesIO(content), body_weight_kg=body_weight_kg)


def render_data_source() -> tuple[pd.DataFrame, str, float]:
    """Render the IronTrail sidebar. Returns (df, source_label, body_weight_kg)."""
    st.markdown("### 🏋️ IronTrail")
    st.caption("Personal training dashboard")
    st.divider()

    uploaded = st.file_uploader(
        "Drag & drop your Hevy CSV",
        type=["csv"],
        help=(
            "In the Hevy app: **Profile → Settings → Export Workout Data**. "
            "Drop the CSV here — it stays in browser memory, never written to disk. "
            "Persists across pages within the session."
        ),
        key="csv_upload_widget",
    )

    # Sync the widget into our own session-state slot so the upload survives
    # page navigation (st.file_uploader's visible state resets per page,
    # but session_state persists across the whole session).
    if uploaded is not None:
        st.session_state["it_upload_bytes"] = uploaded.getvalue()
        st.session_state["it_upload_name"] = uploaded.name

    has_upload = bool(st.session_state.get("it_upload_bytes"))

    if has_upload:
        st.success(f"📤 Using **{st.session_state['it_upload_name']}**")
        if st.button("✖ Clear upload", use_container_width=True):
            for k in ("it_upload_bytes", "it_upload_name", "csv_upload_widget"):
                st.session_state.pop(k, None)
            st.rerun()

    options = _csv_choices()
    selected = st.selectbox(
        "…or pick an existing file",
        options,
        index=0,
        format_func=lambda p: Path(p).name,
        disabled=has_upload,
        help="Files in `data/raw/` plus the bundled sample.",
    )

    body_weight = st.number_input(
        "Bodyweight (kg)",
        value=float(config.BODY_WEIGHT_KG),
        step=0.5,
        min_value=30.0,
        help="Powers bodyweight + assisted-exercise load calculations and BW-relative badges.",
    )

    if has_upload:
        df = _load_from_bytes(
            st.session_state["it_upload_bytes"],
            st.session_state["it_upload_name"],
            body_weight,
        )
        label = f"📤 {st.session_state['it_upload_name']}"
    else:
        df = _load_from_path(selected, body_weight)
        label = Path(selected).name

    return df, label, body_weight
