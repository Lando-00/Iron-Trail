from __future__ import annotations

import json
from pathlib import Path

import pytest

from iron_trail import user_profile
from iron_trail.cloud_storage import (
    CloudStorageError,
    InMemoryDatasetRepository,
    _entity_to_profile,
    _profile_to_entity,
)


def test_local_body_weight_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "profile.json"
    user_profile.save_local_body_weight(82.5, target)

    assert user_profile.load_local_body_weight(target) == 82.5


def test_local_body_weight_falls_back_when_missing(tmp_path: Path) -> None:
    assert user_profile.load_local_body_weight(tmp_path / "nope.json") == (
        user_profile.default_body_weight()
    )


def test_local_body_weight_survives_a_corrupt_file(tmp_path: Path) -> None:
    target = tmp_path / "profile.json"
    target.write_text("{not json", encoding="utf-8")

    assert user_profile.load_local_body_weight(target) == user_profile.default_body_weight()


def test_local_body_weight_rejects_out_of_range_stored_value(tmp_path: Path) -> None:
    target = tmp_path / "profile.json"
    target.write_text(json.dumps({"body_weight_kg": 5.0}), encoding="utf-8")

    assert user_profile.load_local_body_weight(target) == user_profile.default_body_weight()


def test_save_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    target = tmp_path / "profile.json"
    user_profile.save_local_body_weight(90.0, target)

    assert [p.name for p in tmp_path.iterdir()] == ["profile.json"]


@pytest.mark.parametrize("value", [29.9, 300.1, "heavy", None, float("nan")])
def test_normalize_rejects_impossible_bodyweights(value: object) -> None:
    with pytest.raises(user_profile.ProfileError):
        user_profile.normalize_body_weight(value)


def test_normalize_rounds_to_one_decimal() -> None:
    assert user_profile.normalize_body_weight(84.26) == 84.3


def test_cloud_profile_round_trips() -> None:
    repo = InMemoryDatasetRepository()
    assert repo.get_profile("user-a") is None

    repo.save_profile("user-a", 78.5)
    stored = repo.get_profile("user-a")

    assert stored is not None
    assert stored.body_weight_kg == 78.5


def test_cloud_profile_is_scoped_to_one_user() -> None:
    repo = InMemoryDatasetRepository()
    repo.save_profile("user-a", 78.5)
    repo.save_profile("user-b", 101.0)

    assert repo.get_profile("user-a").body_weight_kg == 78.5
    assert repo.get_profile("user-b").body_weight_kg == 101.0


def test_cloud_profile_survives_dataset_replacement() -> None:
    """Uploading a new CSV must not wipe the saved bodyweight."""
    import pandas as pd

    repo = InMemoryDatasetRepository()
    repo.save_profile("user-a", 78.5)
    frame = pd.DataFrame({"exercise_title": ["Squat"], "reps": [5]})
    repo.save_single_dataset("user-a", b"one", "one.csv", frame)
    repo.save_single_dataset("user-a", b"two", "two.csv", frame)

    assert repo.get_profile("user-a").body_weight_kg == 78.5


def test_delete_all_also_removes_the_profile() -> None:
    repo = InMemoryDatasetRepository()
    repo.save_profile("user-a", 78.5)
    repo.save_profile("user-b", 90.0)

    repo.delete_all("user-a")

    assert repo.get_profile("user-a") is None
    assert repo.get_profile("user-b") is not None


def test_profile_entity_round_trips() -> None:
    repo = InMemoryDatasetRepository()
    record = repo.save_profile("user-a", 78.5)

    restored = _entity_to_profile(_profile_to_entity(record))

    assert restored == record


def test_profile_row_is_never_listed_as_a_dataset() -> None:
    """The profile shares the user's table partition; it must not look like data."""
    import pandas as pd
    from azure.core.exceptions import ResourceNotFoundError

    from iron_trail import cloud_storage

    entities: dict[tuple[str, str], dict] = {}

    class Table:
        def upsert_entity(self, entity, mode=None):
            entities[(entity["PartitionKey"], entity["RowKey"])] = entity

        def create_entity(self, entity):
            entities[(entity["PartitionKey"], entity["RowKey"])] = entity

        def get_entity(self, partition, row):
            try:
                return entities[(partition, row)]
            except KeyError as exc:
                raise ResourceNotFoundError("missing") from exc

        def query_entities(self, query):
            # Deliberately ignores the filter to prove the caller also guards.
            return list(entities.values())

        def delete_entity(self, partition, row):
            entities.pop((partition, row), None)

    class Container:
        def upload_blob(self, name, content, overwrite):
            return None

        def delete_blob(self, name, delete_snapshots=None):
            return None

    repo = cloud_storage.AzureDatasetRepository(Container(), Table())
    repo.save_profile("user-a", 78.5)
    repo.save_hevy_dataset(
        "user-a", b"raw", "one.csv", pd.DataFrame({"exercise_title": ["Squat"], "reps": [5]})
    )

    records = repo.list_datasets("user-a")

    assert len(records) == 1
    assert records[0].filename == "one.csv"
    assert repo.get_profile("user-a").body_weight_kg == 78.5


def test_unreadable_profile_entity_is_ignored_not_fatal() -> None:
    from azure.core.exceptions import ResourceNotFoundError

    from iron_trail import cloud_storage

    class Table:
        def get_entity(self, partition, row):
            return {"PartitionKey": partition, "RowKey": row, "bodyWeightKg": "junk"}

        def delete_entity(self, partition, row):
            raise ResourceNotFoundError("missing")

    repo = cloud_storage.AzureDatasetRepository(object(), Table())

    assert repo.get_profile("user-a") is None
    repo.delete_profile("user-a")


def test_save_profile_wraps_azure_failures() -> None:
    from azure.core.exceptions import ServiceRequestError

    from iron_trail import cloud_storage

    class Table:
        def upsert_entity(self, entity, mode=None):
            raise ServiceRequestError("boom")

    repo = cloud_storage.AzureDatasetRepository(object(), Table())

    with pytest.raises(CloudStorageError):
        repo.save_profile("user-a", 78.5)
