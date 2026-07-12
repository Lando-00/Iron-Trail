from __future__ import annotations

import io
import json
import zipfile

import pandas as pd
import pytest

from iron_trail.cloud_storage import (
    CloudStorageError,
    InMemoryDatasetRepository,
    sanitize_filename,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"exercise_title": ["Bench Press"], "reps": [5]})


def test_dataset_repository_enforces_user_partition() -> None:
    repo = InMemoryDatasetRepository()
    record = repo.save_hevy_dataset("user-a", b"private-a", "a.csv", _frame())
    repo.save_hevy_dataset("user-b", b"private-b", "b.csv", _frame())

    assert [item.dataset_id for item in repo.list_datasets("user-a")] == [record.dataset_id]
    with pytest.raises(CloudStorageError, match="not found"):
        repo.load_dataset("user-b", record.dataset_id)


def test_export_contains_only_requesting_users_data() -> None:
    repo = InMemoryDatasetRepository()
    own = repo.save_hevy_dataset("user-a", b"private-a", "a.csv", _frame())
    repo.save_hevy_dataset("user-b", b"private-b", "b.csv", _frame())

    with zipfile.ZipFile(io.BytesIO(repo.export_user_archive("user-a"))) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))

    assert any(name.startswith(own.dataset_id) for name in names)
    assert b"private-b" not in repo.export_user_archive("user-a")
    assert {item["user_id"] for item in manifest["datasets"]} == {"user-a"}


def test_delete_all_is_scoped_to_user() -> None:
    repo = InMemoryDatasetRepository()
    repo.save_hevy_dataset("user-a", b"a", "a.csv", _frame())
    other = repo.save_hevy_dataset("user-b", b"b", "b.csv", _frame())

    assert repo.delete_all("user-a") == 1
    assert repo.list_datasets("user-a") == []
    assert repo.load_dataset("user-b", other.dataset_id).equals(_frame())


def test_filename_is_reduced_to_safe_basename() -> None:
    assert sanitize_filename("../../My export (final).csv") == "My_export_final_.csv"

