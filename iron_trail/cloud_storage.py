"""Private Azure storage adapters for identities, datasets, and exports."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import threading
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from . import runtime
from .auth import (
    AuthRepository,
    AuthRepositoryError,
    Identity,
    InvitationError,
    User,
    hash_invite_code,
)

_AUTH_PARTITION = "auth"
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class CloudStorageError(RuntimeError):
    """Raised when private cloud storage cannot complete an operation."""


class DatasetNotFoundError(CloudStorageError):
    """Raised when a dataset does not belong to the requesting user."""


@dataclass(frozen=True)
class DatasetRecord:
    user_id: str
    dataset_id: str
    filename: str
    created_at: datetime
    raw_expires_at: datetime
    normalized_expires_at: datetime
    raw_blob: str
    normalized_blob: str
    size_bytes: int


def azure_credential() -> Any:
    if runtime.is_cloud():
        from azure.identity import ManagedIdentityCredential

        client_id = os.environ.get("AZURE_CLIENT_ID")
        return ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()

    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=False)


class AzureAuthRepository(AuthRepository):
    def __init__(self, table_client: Any) -> None:
        self._table = table_client
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "AzureAuthRepository":
        table_url = _required_env("IRONTRAIL_STORAGE_TABLE_URL")
        table_name = os.environ.get("IRONTRAIL_AUTH_TABLE", "IronTrailAuth")
        return cls(_table_client(table_url, table_name))

    def get_user(self, user_id: str) -> User | None:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        try:
            entity = self._table.get_entity(_AUTH_PARTITION, f"user:{user_id}")
        except ResourceNotFoundError:
            return None
        except AzureError as exc:
            raise AuthRepositoryError("The authorization store is unavailable.") from exc
        return _entity_to_user(entity)

    def redeem(
        self,
        identity: Identity,
        code: str,
        *,
        bootstrap_hash: str,
        max_users: int,
    ) -> User:
        from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
        from azure.data.tables import UpdateMode

        try:
            with self._lock:
                existing = self.get_user(identity.user_id)
                if existing is not None:
                    return existing

                users = self._users()
                if len(users) >= max_users:
                    raise InvitationError("The private beta is full.")

                code_hash = hash_invite_code(code)
                role = "member"
                invite_entity: dict[str, Any] | None = None
                if not users and bootstrap_hash and secrets.compare_digest(
                    code_hash, bootstrap_hash
                ):
                    role = "admin"
                else:
                    try:
                        invite_entity = dict(
                            self._table.get_entity(_AUTH_PARTITION, f"invite:{code_hash}")
                        )
                    except ResourceNotFoundError as exc:
                        raise InvitationError("That invite code is invalid or expired.") from exc
                    expires_at = _as_utc(invite_entity["expiresAt"])
                    if invite_entity.get("usedBy") or expires_at <= datetime.now(UTC):
                        raise InvitationError("That invite code is invalid or expired.")

                user = _new_user(identity, role)
                user_entity = _user_to_entity(user)
                if invite_entity is None:
                    self._table.create_entity(user_entity)
                else:
                    invite_entity["usedBy"] = user.user_id
                    invite_entity["usedAt"] = datetime.now(UTC)
                    self._table.submit_transaction(
                        [
                            ("create", user_entity),
                            ("update", invite_entity, {"mode": UpdateMode.REPLACE}),
                        ]
                    )
                return user
        except ResourceExistsError:
            winner = self.get_user(identity.user_id)
            if winner is not None:
                return winner
            raise InvitationError("That invite was already redeemed.") from None
        except InvitationError:
            raise
        except AzureError as exc:
            raise AuthRepositoryError("The authorization store is unavailable.") from exc

    def issue_invite(self, actor: User, *, ttl: timedelta, max_users: int) -> str:
        from azure.core.exceptions import AzureError

        try:
            with self._lock:
                stored_actor = self.get_user(actor.user_id)
                if stored_actor is None or not stored_actor.is_admin:
                    raise InvitationError("Only the beta administrator can issue invites.")
                users = self._users()
                active_invites = self._active_invites()
                if len(users) + len(active_invites) >= max_users:
                    raise InvitationError("All beta places are already assigned.")

                code = secrets.token_urlsafe(24)
                code_hash = hash_invite_code(code)
                self._table.create_entity(
                    {
                        "PartitionKey": _AUTH_PARTITION,
                        "RowKey": f"invite:{code_hash}",
                        "expiresAt": datetime.now(UTC) + ttl,
                        "createdAt": datetime.now(UTC),
                        "createdBy": actor.user_id,
                        "usedBy": "",
                    }
                )
                return code
        except InvitationError:
            raise
        except AzureError as exc:
            raise AuthRepositoryError("The authorization store is unavailable.") from exc

    def _users(self) -> list[User]:
        entities = self._table.query_entities(
            "PartitionKey eq 'auth' and RowKey ge 'user:' and RowKey lt 'user;'"
        )
        return [_entity_to_user(entity) for entity in entities]

    def _active_invites(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        entities = self._table.query_entities(
            "PartitionKey eq 'auth' and RowKey ge 'invite:' and RowKey lt 'invite;'"
        )
        return [
            dict(entity)
            for entity in entities
            if not entity.get("usedBy") and _as_utc(entity["expiresAt"]) > now
        ]


class AzureDatasetRepository:
    def __init__(self, container_client: Any, table_client: Any) -> None:
        self._container = container_client
        self._table = table_client

    @classmethod
    def from_environment(cls) -> "AzureDatasetRepository":
        blob_url = _required_env("IRONTRAIL_STORAGE_BLOB_URL")
        table_url = _required_env("IRONTRAIL_STORAGE_TABLE_URL")
        container_name = os.environ.get("IRONTRAIL_DATA_CONTAINER", "datasets")
        table_name = os.environ.get("IRONTRAIL_DATA_TABLE", "IronTrailData")
        return cls(
            _container_client(blob_url, container_name),
            _table_client(table_url, table_name),
        )

    def save_hevy_dataset(
        self,
        user_id: str,
        content: bytes,
        filename: str,
        dataframe: pd.DataFrame,
    ) -> DatasetRecord:
        from azure.core.exceptions import AzureError

        now = datetime.now(UTC)
        dataset_id = hashlib.sha256(content).hexdigest()[:24]
        safe_name = sanitize_filename(filename)
        raw_blob = f"raw/{user_id}/{dataset_id}/{safe_name}"
        normalized_blob = f"normalized/{user_id}/{dataset_id}/workouts.parquet"
        parquet = io.BytesIO()
        dataframe.to_parquet(parquet, index=False)

        try:
            self._container.upload_blob(raw_blob, content, overwrite=True)
            self._container.upload_blob(normalized_blob, parquet.getvalue(), overwrite=True)
        except AzureError as exc:
            raise CloudStorageError("Unable to save the private dataset.") from exc

        record = DatasetRecord(
            user_id=user_id,
            dataset_id=dataset_id,
            filename=safe_name,
            created_at=now,
            raw_expires_at=now
            + timedelta(days=runtime.env_int("IRONTRAIL_RAW_RETENTION_DAYS", 30, minimum=1)),
            normalized_expires_at=now
            + timedelta(
                days=runtime.env_int("IRONTRAIL_NORMALIZED_RETENTION_DAYS", 60, minimum=1)
            ),
            raw_blob=raw_blob,
            normalized_blob=normalized_blob,
            size_bytes=len(content),
        )
        try:
            self._table.upsert_entity(_dataset_to_entity(record))
        except AzureError as exc:
            raise CloudStorageError("Unable to save dataset metadata.") from exc
        return record

    def list_datasets(self, user_id: str) -> list[DatasetRecord]:
        from azure.core.exceptions import AzureError

        try:
            entities = list(
                self._table.query_entities(f"PartitionKey eq '{_odata(user_id)}'")
            )
        except AzureError as exc:
            raise CloudStorageError("Unable to list saved datasets.") from exc
        records = sorted(
            (_entity_to_dataset(entity) for entity in entities),
            key=lambda item: item.created_at,
            reverse=True,
        )
        current: list[DatasetRecord] = []
        for record in records:
            if record.normalized_expires_at <= datetime.now(UTC):
                self.delete_dataset(user_id, record.dataset_id)
            else:
                current.append(record)
        return current

    def load_dataset(self, user_id: str, dataset_id: str) -> pd.DataFrame:
        from azure.core.exceptions import AzureError

        record = self._get_dataset(user_id, dataset_id)
        try:
            payload = self._container.download_blob(record.normalized_blob).readall()
        except AzureError as exc:
            raise CloudStorageError("Unable to load the saved dataset.") from exc
        return pd.read_parquet(io.BytesIO(payload))

    def delete_dataset(self, user_id: str, dataset_id: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            record = self._get_dataset(user_id, dataset_id)
        except DatasetNotFoundError:
            return
        for name in (record.raw_blob, record.normalized_blob):
            try:
                self._container.delete_blob(name, delete_snapshots="include")
            except ResourceNotFoundError:
                pass
        try:
            self._table.delete_entity(user_id, dataset_id)
        except ResourceNotFoundError:
            pass

    def delete_all(self, user_id: str) -> int:
        records = self.list_datasets(user_id)
        for record in records:
            self.delete_dataset(user_id, record.dataset_id)
        return len(records)

    def export_user_archive(self, user_id: str) -> bytes:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        output = io.BytesIO()
        missing: list[str] = []
        records = self.list_datasets(user_id)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                for label, blob_name in (
                    ("raw", record.raw_blob),
                    ("normalized", record.normalized_blob),
                ):
                    try:
                        payload = self._container.download_blob(blob_name).readall()
                    except ResourceNotFoundError:
                        missing.append(blob_name)
                        continue
                    except AzureError as exc:
                        raise CloudStorageError("Unable to export saved data.") from exc
                    archive.writestr(f"{record.dataset_id}/{label}/{Path(blob_name).name}", payload)
            manifest = {
                "exported_at": datetime.now(UTC).isoformat(),
                "datasets": [_record_json(record) for record in records],
                "missing_blobs": missing,
            }
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        return output.getvalue()

    def _get_dataset(self, user_id: str, dataset_id: str) -> DatasetRecord:
        from azure.core.exceptions import AzureError, ResourceNotFoundError

        try:
            entity = self._table.get_entity(user_id, dataset_id)
        except ResourceNotFoundError as exc:
            raise DatasetNotFoundError("Dataset not found for this user.") from exc
        except AzureError as exc:
            raise CloudStorageError("Unable to read dataset metadata.") from exc
        return _entity_to_dataset(entity)


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], DatasetRecord] = {}
        self.raw: dict[tuple[str, str], bytes] = {}
        self.frames: dict[tuple[str, str], pd.DataFrame] = {}

    def save_hevy_dataset(
        self,
        user_id: str,
        content: bytes,
        filename: str,
        dataframe: pd.DataFrame,
    ) -> DatasetRecord:
        now = datetime.now(UTC)
        dataset_id = hashlib.sha256(content).hexdigest()[:24]
        record = DatasetRecord(
            user_id=user_id,
            dataset_id=dataset_id,
            filename=sanitize_filename(filename),
            created_at=now,
            raw_expires_at=now + timedelta(days=30),
            normalized_expires_at=now + timedelta(days=60),
            raw_blob=f"raw/{user_id}/{dataset_id}/{sanitize_filename(filename)}",
            normalized_blob=f"normalized/{user_id}/{dataset_id}/workouts.parquet",
            size_bytes=len(content),
        )
        key = (user_id, dataset_id)
        self.records[key] = record
        self.raw[key] = content
        self.frames[key] = dataframe.copy()
        return record

    def list_datasets(self, user_id: str) -> list[DatasetRecord]:
        return sorted(
            (record for (owner, _), record in self.records.items() if owner == user_id),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def load_dataset(self, user_id: str, dataset_id: str) -> pd.DataFrame:
        try:
            return self.frames[(user_id, dataset_id)].copy()
        except KeyError as exc:
            raise DatasetNotFoundError("Dataset not found for this user.") from exc

    def delete_dataset(self, user_id: str, dataset_id: str) -> None:
        key = (user_id, dataset_id)
        self.records.pop(key, None)
        self.raw.pop(key, None)
        self.frames.pop(key, None)

    def delete_all(self, user_id: str) -> int:
        records = self.list_datasets(user_id)
        for record in records:
            self.delete_dataset(user_id, record.dataset_id)
        return len(records)

    def export_user_archive(self, user_id: str) -> bytes:
        output = io.BytesIO()
        records = self.list_datasets(user_id)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                key = (user_id, record.dataset_id)
                archive.writestr(f"{record.dataset_id}/raw/{record.filename}", self.raw[key])
                parquet = io.BytesIO()
                self.frames[key].to_parquet(parquet, index=False)
                archive.writestr(
                    f"{record.dataset_id}/normalized/workouts.parquet", parquet.getvalue()
                )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "datasets": [_record_json(record) for record in records],
                        "missing_blobs": [],
                    },
                    indent=2,
                ),
            )
        return output.getvalue()


@st.cache_resource(show_spinner=False)
def get_dataset_repository() -> AzureDatasetRepository:
    return AzureDatasetRepository.from_environment()


def azure_table_client(table_name: str) -> Any:
    return _table_client(_required_env("IRONTRAIL_STORAGE_TABLE_URL"), table_name)


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name[:120]
    cleaned = _SAFE_FILENAME.sub("_", name).strip("._")
    return cleaned or "hevy-export.csv"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise runtime.ConfigurationError(f"{name} is required in cloud mode")
    return value.rstrip("/")


def _table_client(table_url: str, table_name: str) -> Any:
    from azure.data.tables import TableServiceClient

    return TableServiceClient(
        endpoint=table_url.rstrip("/"), credential=azure_credential()
    ).get_table_client(
        table_name
    )


def _container_client(blob_url: str, container_name: str) -> Any:
    from azure.storage.blob import BlobServiceClient

    return BlobServiceClient(
        account_url=blob_url, credential=azure_credential()
    ).get_container_client(container_name)


def _new_user(identity: Identity, role: str) -> User:
    return User(
        user_id=identity.user_id,
        provider=identity.provider,
        principal_id=identity.principal_id,
        display_name=identity.display_name,
        role=role,
        created_at=datetime.now(UTC),
    )


def _user_to_entity(user: User) -> dict[str, Any]:
    return {
        "PartitionKey": _AUTH_PARTITION,
        "RowKey": f"user:{user.user_id}",
        "provider": user.provider,
        "principalId": user.principal_id,
        "displayName": user.display_name,
        "role": user.role,
        "createdAt": user.created_at,
    }


def _entity_to_user(entity: Any) -> User:
    return User(
        user_id=str(entity["RowKey"]).removeprefix("user:"),
        provider=str(entity["provider"]),
        principal_id=str(entity["principalId"]),
        display_name=str(entity.get("displayName") or "IronTrail user"),
        role=str(entity["role"]),
        created_at=_as_utc(entity["createdAt"]),
    )


def _dataset_to_entity(record: DatasetRecord) -> dict[str, Any]:
    return {
        "PartitionKey": record.user_id,
        "RowKey": record.dataset_id,
        "filename": record.filename,
        "createdAt": record.created_at,
        "rawExpiresAt": record.raw_expires_at,
        "normalizedExpiresAt": record.normalized_expires_at,
        "rawBlob": record.raw_blob,
        "normalizedBlob": record.normalized_blob,
        "sizeBytes": record.size_bytes,
    }


def _entity_to_dataset(entity: Any) -> DatasetRecord:
    return DatasetRecord(
        user_id=str(entity["PartitionKey"]),
        dataset_id=str(entity["RowKey"]),
        filename=str(entity["filename"]),
        created_at=_as_utc(entity["createdAt"]),
        raw_expires_at=_as_utc(entity["rawExpiresAt"]),
        normalized_expires_at=_as_utc(entity["normalizedExpiresAt"]),
        raw_blob=str(entity["rawBlob"]),
        normalized_blob=str(entity["normalizedBlob"]),
        size_bytes=int(entity["sizeBytes"]),
    )


def _record_json(record: DatasetRecord) -> dict[str, Any]:
    data = asdict(record)
    for key in ("created_at", "raw_expires_at", "normalized_expires_at"):
        data[key] = data[key].isoformat()
    return data


def _as_utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _odata(value: str) -> str:
    return value.replace("'", "''")
