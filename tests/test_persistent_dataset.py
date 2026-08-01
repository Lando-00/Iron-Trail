from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from iron_trail import runtime
from iron_trail.cloud_storage import (
    CloudStorageError,
    DatasetRecord,
    InMemoryDatasetRepository,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"exercise_title": ["Bench Press"], "reps": [5]})


def test_single_slot_replaces_the_previous_dataset() -> None:
    repo = InMemoryDatasetRepository()
    first = repo.save_single_dataset("user-a", b"first", "first.csv", _frame())
    second = repo.save_single_dataset("user-a", b"second", "second.csv", _frame())

    records = repo.list_datasets("user-a")
    assert [item.dataset_id for item in records] == [second.dataset_id]
    assert records[0].filename == "second.csv"
    assert first.dataset_id != second.dataset_id


def test_single_slot_does_not_touch_other_users() -> None:
    repo = InMemoryDatasetRepository()
    other = repo.save_single_dataset("user-b", b"theirs", "theirs.csv", _frame())
    repo.save_single_dataset("user-a", b"mine", "mine.csv", _frame())
    repo.save_single_dataset("user-a", b"mine2", "mine2.csv", _frame())

    assert [item.dataset_id for item in repo.list_datasets("user-b")] == [other.dataset_id]
    assert len(repo.list_datasets("user-a")) == 1


def test_failed_prune_still_keeps_the_new_dataset() -> None:
    """Save-then-prune: a prune failure must never lose the just-saved data."""
    repo = InMemoryDatasetRepository()
    repo.save_single_dataset("user-a", b"old", "old.csv", _frame())

    def _explode(user_id: str, dataset_id: str) -> None:
        raise CloudStorageError("delete failed")

    repo.delete_dataset = _explode  # type: ignore[method-assign]
    record = repo.save_single_dataset("user-a", b"new", "new.csv", _frame())

    stored = [item for item in repo.list_datasets("user-a") if item.dataset_id == record.dataset_id]
    assert stored, "the newly saved dataset must survive a prune failure"
    assert repo.load_dataset("user-a", record.dataset_id) is not None


def test_saved_dataset_round_trips() -> None:
    repo = InMemoryDatasetRepository()
    frame = pd.DataFrame({"exercise_title": ["Squat", "Squat"], "reps": [5, 3]})
    record = repo.save_single_dataset("user-a", b"raw", "squats.csv", frame)

    restored = repo.load_dataset("user-a", record.dataset_id)
    pd.testing.assert_frame_equal(restored, frame)


def test_restore_prefers_the_most_recent_record() -> None:
    """The sidebar restores records[0], so list_datasets must sort newest-first."""
    repo = InMemoryDatasetRepository()
    older = repo.save_hevy_dataset("user-a", b"old", "old.csv", _frame())
    newer = repo.save_hevy_dataset("user-a", b"new", "new.csv", _frame())

    # Force distinct timestamps: real uploads are seconds apart, but two saves
    # in one test tick can land on the same microsecond and tie the sort.
    now = datetime.now(UTC)
    repo.records[("user-a", older.dataset_id)] = replace(
        older, created_at=now - timedelta(hours=1)
    )
    repo.records[("user-a", newer.dataset_id)] = replace(newer, created_at=now)

    assert repo.list_datasets("user-a")[0].dataset_id == newer.dataset_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("true", True),
        ("1", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("off", False),
    ],
)
def test_auto_persist_flag_parsing(value: str | None, expected: bool) -> None:
    environ = {} if value is None else {"IRONTRAIL_AUTO_PERSIST_UPLOADS": value}
    assert runtime.auto_persist_uploads(environ) is expected


def test_auto_persist_flag_rejects_nonsense() -> None:
    with pytest.raises(runtime.ConfigurationError):
        runtime.auto_persist_uploads({"IRONTRAIL_AUTO_PERSIST_UPLOADS": "maybe"})


def test_dataset_record_is_immutable() -> None:
    repo = InMemoryDatasetRepository()
    record = repo.save_single_dataset("user-a", b"x", "x.csv", _frame())

    assert isinstance(record, DatasetRecord)
    with pytest.raises(FrozenInstanceError):
        record.filename = "other.csv"  # type: ignore[misc]
