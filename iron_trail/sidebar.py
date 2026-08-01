"""Shared Streamlit sidebar.

All five pages render the same data-source picker (drag-and-drop CSV
uploader + dropdown of existing files in ``data/raw/`` + the bundled
sample) and bodyweight input. State is held in ``st.session_state`` so an
uploaded file persists as the user navigates between pages.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from . import auth, config, ingest, runtime, theme, ui
from .cloud_storage import CloudStorageError, get_dataset_repository
from .uploads import UploadValidationError


def _csv_choices() -> list[str]:
    raw = sorted(config.RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = [str(p) for p in raw]
    if config.SAMPLE_CSV.exists():
        items.append(str(config.SAMPLE_CSV))
    return items or [str(config.SAMPLE_CSV)]


@st.cache_data(show_spinner="Parsing Hevy CSV…")
def _load_from_path(path: str, body_weight_kg: float) -> pd.DataFrame:
    return ingest.load_and_clean(Path(path), body_weight_kg=body_weight_kg)


def _load_from_bytes(content: bytes, _filename: str, body_weight_kg: float) -> pd.DataFrame:
    """Parse uploaded bytes without placing private data in Streamlit's global cache."""
    return ingest.load_and_clean(io.BytesIO(content), body_weight_kg=body_weight_kg)


def render_theme_picker() -> None:
    """Palette selector. Persisted per session and mirrored into the URL."""
    names = list(theme.PALETTES)
    current = ui.active_palette()
    choice = st.selectbox(
        "Theme",
        names,
        index=names.index(current),
        format_func=lambda name: theme.PALETTE_LABELS.get(name, name),
        key="it_theme_choice",
        help="High contrast brightens text and accents; AMOLED uses true black.",
    )
    if choice != current:
        ui.select_palette(choice)
        st.rerun()


def render_data_source() -> tuple[pd.DataFrame, str, float]:
    """Render the IronTrail sidebar. Returns (df, source_label, body_weight_kg)."""
    try:
        if runtime.is_cloud():
            source = _render_cloud_data_source()
        else:
            source = _render_local_data_source()
    except (CloudStorageError, UploadValidationError, runtime.ConfigurationError) as exc:
        st.error(str(exc))
        st.stop()
    render_theme_picker()
    return source


def _render_local_data_source() -> tuple[pd.DataFrame, str, float]:
    st.markdown("### 🏋️ IronTrail")
    st.caption("Personal training dashboard")
    st.divider()

    uploaded = st.file_uploader(
        "Drag & drop your Hevy CSV",
        type=["csv"],
        help=(
            "In the Hevy app: **Profile → Settings → Export Workout Data**. "
            "The CSV is processed in this local Streamlit session and is not uploaded "
            "to a third-party service. "
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


def _render_cloud_data_source() -> tuple[pd.DataFrame, str, float]:
    user = auth.current_user()
    repository = get_dataset_repository()

    st.markdown("### IronTrail")
    st.caption("Private training dashboard")
    auth.render_account_controls(user)
    st.divider()

    uploaded = st.file_uploader(
        "Upload a Hevy CSV",
        type=["csv"],
        help=(
            "The file is sent to the IronTrail server for this session. It is stored in "
            "Azure only when you explicitly choose Save privately."
        ),
        key="csv_upload_widget",
    )
    if uploaded is not None:
        st.session_state["it_upload_bytes"] = uploaded.getvalue()
        st.session_state["it_upload_name"] = uploaded.name

    has_upload = bool(st.session_state.get("it_upload_bytes"))
    if has_upload:
        st.success(f"Using **{st.session_state['it_upload_name']}**")
        if st.button("Clear session upload", use_container_width=True):
            for key in (
                "it_upload_bytes",
                "it_upload_name",
                "csv_upload_widget",
                "it_saved_upload_id",
            ):
                st.session_state.pop(key, None)
            st.rerun()

    body_weight = st.number_input(
        "Bodyweight (kg)",
        value=float(config.BODY_WEIGHT_KG),
        step=0.5,
        min_value=30.0,
        help="Used for bodyweight exercises and relative-strength achievements.",
    )

    if has_upload:
        content = st.session_state["it_upload_bytes"]
        filename = st.session_state["it_upload_name"]
        df = _load_from_bytes(content, filename, body_weight)
        label = f"Session upload: {filename}"

        if runtime.auto_persist_uploads():
            df, label = _auto_persist_upload(
                repository, user.user_id, content, filename, df, label
            )
        else:
            persist = st.checkbox(
                "Save privately",
                value=False,
                help=(
                    "Active raw data expires after 30 days and active normalized data after "
                    "60 days. Deleted blobs may remain recoverable by privileged Azure "
                    "operators for up to 7 additional days."
                ),
            )
            if persist and st.button(
                "Save this dataset", type="primary", use_container_width=True
            ):
                try:
                    record = repository.save_single_dataset(
                        user.user_id,
                        content,
                        filename,
                        df,
                    )
                except CloudStorageError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["it_saved_upload_id"] = record.dataset_id
                    st.session_state.pop("it_data_export_bytes", None)
                    st.success("Saved privately with automatic expiry.")
    else:
        df, label = _render_saved_dataset_picker(repository, user.user_id, body_weight)

    _render_cloud_data_controls(user.user_id, repository)
    return df, label, body_weight


def _auto_persist_upload(
    repository,
    user_id: str,
    content: bytes,
    filename: str,
    df: pd.DataFrame,
    label: str,
) -> tuple[pd.DataFrame, str]:
    """Save the upload into the user's single slot, replacing any previous one."""
    fingerprint = f"{filename}:{len(content)}:{hashlib.sha256(content).hexdigest()[:16]}"
    if st.session_state.get("it_persisted_fingerprint") == fingerprint:
        return df, f"Saved dataset: {filename}"

    try:
        record = repository.save_single_dataset(user_id, content, filename, df)
    except CloudStorageError as exc:
        st.warning(f"{exc} Using this file for the current session only.")
        return df, label

    st.session_state["it_persisted_fingerprint"] = fingerprint
    st.session_state["it_saved_upload_id"] = record.dataset_id
    st.session_state.pop("it_data_export_bytes", None)
    st.success("Saved to your account — it will be here next time you sign in.")
    st.caption(
        "This replaced any previously saved CSV. Remove it any time under "
        "**My saved data**."
    )
    return df, f"Saved dataset: {filename}"


def _render_saved_dataset_picker(
    repository,
    user_id: str,
    body_weight: float,
) -> tuple[pd.DataFrame, str]:
    """Restore the user's saved dataset by default, falling back to the sample."""
    records = repository.list_datasets(user_id)
    if not records:
        st.caption("No saved CSV yet — showing the synthetic sample.")
        return (
            ingest.load_and_clean(config.SAMPLE_CSV, body_weight_kg=body_weight),
            config.SAMPLE_CSV.name,
        )

    saved = records[0]
    use_sample = st.toggle(
        "Show synthetic sample instead",
        value=False,
        help="Your saved CSV stays in your account either way.",
    )
    if use_sample:
        return (
            ingest.load_and_clean(config.SAMPLE_CSV, body_weight_kg=body_weight),
            config.SAMPLE_CSV.name,
        )

    st.success(f"Restored **{saved.filename}** from your account.")
    return repository.load_dataset(user_id, saved.dataset_id), saved.filename


def _render_cloud_data_controls(user_id: str, repository) -> None:
    with st.expander("My saved data"):
        records = repository.list_datasets(user_id)
        if not records:
            st.caption("No cloud datasets saved.")
            return

        selected = st.selectbox(
            "Manage dataset",
            records,
            format_func=lambda record: f"{record.filename} ({record.created_at:%Y-%m-%d})",
            key="manage_cloud_dataset",
        )
        st.caption(
            f"Active raw data expires {selected.raw_expires_at:%Y-%m-%d}; "
            f"active normalized data expires {selected.normalized_expires_at:%Y-%m-%d}. "
            "Deleted blobs may remain recoverable by privileged Azure operators for "
            "up to 7 days."
        )
        if st.button("Delete selected dataset", key="delete_cloud_dataset"):
            repository.delete_dataset(user_id, selected.dataset_id)
            st.session_state.pop("it_data_export_bytes", None)
            st.rerun()

        if st.button("Prepare data export", key="prepare_cloud_export"):
            st.session_state["it_data_export_bytes"] = repository.export_user_archive(
                user_id
            )
        archive = st.session_state.get("it_data_export_bytes")
        if archive:
            st.download_button(
                "Download all saved data",
                data=archive,
                file_name="irontrail-data-export.zip",
                mime="application/zip",
                use_container_width=True,
            )

        confirm = st.checkbox(
            "I understand this removes all datasets from active IronTrail access; "
            "deleted blobs may remain recoverable by privileged Azure operators for "
            "up to 7 days."
        )
        if st.button(
            "Delete all active saved data",
            disabled=not confirm,
            key="delete_all_cloud_data",
            use_container_width=True,
        ):
            repository.delete_all(user_id)
            st.session_state.pop("it_data_export_bytes", None)
            st.rerun()
