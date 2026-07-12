"""Bounded validation helpers for user-supplied CSV and ZIP files."""
from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class UploadValidationError(ValueError):
    """Raised when an upload is too large, malformed, or unsafe."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 50 * 1024 * 1024
    max_entries: int = 250
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_compression_ratio: float = 100.0


@dataclass(frozen=True)
class ArchiveInspection:
    entries: int
    compressed_bytes: int
    uncompressed_bytes: int


def read_bounded_bytes(source, *, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise UploadValidationError("The selected file could not be read.") from exc
        if size > max_bytes:
            raise UploadValidationError(_size_message(max_bytes))
        try:
            return path.read_bytes()
        except OSError as exc:
            raise UploadValidationError("The selected file could not be read.") from exc

    if isinstance(source, bytes):
        payload = source
    elif isinstance(source, bytearray):
        payload = bytes(source)
    elif hasattr(source, "read"):
        payload = _read_stream(source, max_bytes)
    else:
        raise TypeError("Upload source must be a path, bytes, or binary file-like object")

    if len(payload) > max_bytes:
        raise UploadValidationError(_size_message(max_bytes))
    return payload


def inspect_zip(content: bytes, limits: ArchiveLimits | None = None) -> ArchiveInspection:
    active_limits = limits or ArchiveLimits()
    if len(content) > active_limits.max_archive_bytes:
        raise UploadValidationError(_size_message(active_limits.max_archive_bytes))

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("The health export is not a valid ZIP archive.") from exc

    with archive:
        members = archive.infolist()
        if len(members) > active_limits.max_entries:
            raise UploadValidationError("The ZIP archive contains too many files.")

        names: set[str] = set()
        total_uncompressed = 0
        total_compressed = 0
        for member in members:
            normalized = member.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if (
                not normalized
                or "\x00" in normalized
                or normalized.startswith("/")
                or ".." in path.parts
                or any(":" in part for part in path.parts)
            ):
                raise UploadValidationError("The ZIP archive contains an unsafe file path.")
            if normalized in names:
                raise UploadValidationError("The ZIP archive contains duplicate file names.")
            names.add(normalized)
            if member.flag_bits & 0x1:
                raise UploadValidationError("Encrypted ZIP entries are not supported.")
            if member.is_dir():
                continue

            total_uncompressed += member.file_size
            total_compressed += member.compress_size
            if total_uncompressed > active_limits.max_uncompressed_bytes:
                raise UploadValidationError("The expanded ZIP archive is too large.")

            ratio = (
                math.inf
                if member.file_size and member.compress_size == 0
                else member.file_size / max(member.compress_size, 1)
            )
            if ratio > active_limits.max_compression_ratio:
                raise UploadValidationError(
                    "The ZIP archive has an unsafe compression ratio."
                )

        return ArchiveInspection(
            entries=len(members),
            compressed_bytes=total_compressed,
            uncompressed_bytes=total_uncompressed,
        )


def _read_stream(stream: BinaryIO, max_bytes: int) -> bytes:
    try:
        payload = stream.read(max_bytes + 1)
    except OSError as exc:
        raise UploadValidationError("The uploaded file could not be read.") from exc
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("Upload streams must return bytes")
    return bytes(payload)


def _size_message(max_bytes: int) -> str:
    max_mb = max_bytes / (1024 * 1024)
    return f"The uploaded file exceeds the {max_mb:g} MB limit."

