from __future__ import annotations

from iron_trail import config, ingest


def test_sample_export_loads_into_canonical_dataframe() -> None:
    df = ingest.load_and_clean(config.SAMPLE_CSV)

    assert not df.empty
    assert df["workout_id"].nunique() > 0
    assert {
        "is_working",
        "volume_kg",
        "e1rm_kg",
        "primary_muscle",
        "workout_date",
    }.issubset(df.columns)
    assert (df.loc[~df["is_working"], "volume_kg"] == 0).all()
