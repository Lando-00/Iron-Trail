from __future__ import annotations

import io
import zipfile
from datetime import date

from iron_trail import config, ingest, vault_notes


def test_daily_notes_archive_stays_in_memory() -> None:
    df = ingest.load_and_clean(config.SAMPLE_CSV)
    since = max(df["workout_date"])

    payload = vault_notes.daily_notes_archive(df, since=since)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        content = archive.read(names[0]).decode()

    assert names
    assert all(name.startswith("Hevy/Daily/") for name in names)
    assert f"date: {date.fromisoformat(str(since)).isoformat()}" in content

