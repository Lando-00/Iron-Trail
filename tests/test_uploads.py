from __future__ import annotations

import io
import zipfile

import pytest

from iron_trail import ingest
from iron_trail.uploads import (
    ArchiveLimits,
    UploadValidationError,
    inspect_zip,
    read_bounded_bytes,
)


def _minimal_hevy_csv(extra_rows: int = 0) -> bytes:
    header = (
        "title,start_time,end_time,exercise_title,set_index,set_type,weight_kg,reps\n"
    )
    row = "Session,2026-07-01 10:00,2026-07-01 11:00,Bench Press (Barbell),0,normal,80,5\n"
    return (header + row * (1 + extra_rows)).encode()


def test_hevy_csv_rejects_oversized_upload() -> None:
    with pytest.raises(UploadValidationError, match="limit"):
        ingest.load_hevy_csv(io.BytesIO(_minimal_hevy_csv()), max_bytes=10)


def test_hevy_csv_rejects_missing_required_columns() -> None:
    with pytest.raises(UploadValidationError, match="missing required columns"):
        ingest.load_hevy_csv(io.BytesIO(b"title,start_time\nA,2026-01-01\n"))


def test_hevy_csv_rejects_excess_rows() -> None:
    with pytest.raises(UploadValidationError, match="row limit"):
        ingest.load_hevy_csv(io.BytesIO(_minimal_hevy_csv(extra_rows=2)), max_rows=2)


def test_bounded_reader_stops_after_limit() -> None:
    with pytest.raises(UploadValidationError, match="limit"):
        read_bounded_bytes(io.BytesIO(b"x" * 101), max_bytes=100)


def test_zip_rejects_path_traversal() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.csv", "unsafe")

    with pytest.raises(UploadValidationError, match="unsafe file path"):
        inspect_zip(payload.getvalue())


def test_zip_rejects_excessive_expansion() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("health.csv", "x" * 10_000)

    with pytest.raises(UploadValidationError, match="expanded ZIP"):
        inspect_zip(
            payload.getvalue(),
            ArchiveLimits(
                max_archive_bytes=1_000_000,
                max_entries=5,
                max_uncompressed_bytes=1_000,
                max_compression_ratio=10_000,
            ),
        )


def test_zip_reports_safe_archive_shape() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("health/heart_rate.csv", "timestamp,bpm\n1,60\n")

    result = inspect_zip(payload.getvalue())

    assert result.entries == 1
    assert result.uncompressed_bytes > 0

