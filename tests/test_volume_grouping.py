from __future__ import annotations

import pandas as pd

from iron_trail import metrics


def _volume_frame(muscles: dict[str, float]) -> pd.DataFrame:
    weeks = pd.to_datetime(["2026-01-05", "2026-01-12"])
    rows = [
        {"week": week, "primary_muscle": muscle, "volume_kg": volume}
        for week in weeks
        for muscle, volume in muscles.items()
    ]
    return pd.DataFrame(rows)


def test_group_minor_muscles_keeps_the_top_six_and_sums_the_rest() -> None:
    """11 muscles produced a 247x121 legend on a 358px phone chart."""
    frame = _volume_frame(
        {f"muscle_{index}": float(100 - index) for index in range(11)}
    )

    grouped = metrics.group_minor_muscles(frame)

    muscles = set(grouped["primary_muscle"])
    assert len(muscles) == 7
    assert "other" in muscles
    assert {"muscle_0", "muscle_5"} <= muscles
    assert "muscle_6" not in muscles
    # The tail is summed, not dropped.
    assert grouped["volume_kg"].sum() == frame["volume_kg"].sum()


def test_group_minor_muscles_leaves_short_frames_untouched() -> None:
    frame = _volume_frame({"chest": 100.0, "back": 90.0})

    grouped = metrics.group_minor_muscles(frame)

    assert grouped.equals(frame)
    assert metrics.group_minor_muscles(
        pd.DataFrame(columns=["week", "primary_muscle", "volume_kg"])
    ).empty


def test_group_minor_muscles_merges_the_tail_per_week() -> None:
    frame = _volume_frame({f"muscle_{index}": float(index + 1) for index in range(8)})

    grouped = metrics.group_minor_muscles(frame)
    other = grouped[grouped["primary_muscle"] == "other"]

    assert len(other) == 2  # one row per week, not one per tail muscle
    assert other["volume_kg"].tolist() == [3.0, 3.0]  # muscle_0 + muscle_1
