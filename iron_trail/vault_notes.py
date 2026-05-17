"""Write per-session Markdown notes into the Obsidian vault.

Each workout becomes ``Vault/Hevy/Daily/YYYY-MM-DD.md`` with frontmatter
(workout title, tonnage, e1RM highs, set count) plus a per-exercise
breakdown. Idempotent — re-running overwrites notes with the latest data.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import metrics


def _frontmatter(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _session_to_markdown(g: pd.DataFrame) -> tuple[str, str]:
    """Return (filename, markdown content) for a single workout group."""
    workout_date = pd.to_datetime(g["workout_date"].iloc[0]).date()
    title = (g["title"].iloc[0] or "Untitled").strip()
    start_time = pd.to_datetime(g["start_time"].iloc[0])
    end_time = pd.to_datetime(g["end_time"].iloc[0]) if pd.notna(g["end_time"].iloc[0]) else None
    duration_min = float(g["duration_min"].iloc[0] or 0)

    working = g[g["is_working"]]
    total_volume = float(working["volume_kg"].sum())
    set_count = int(len(working))
    exercises_used = sorted(working["exercise_title"].unique().tolist())

    # Per-exercise summary
    ex_lines: list[str] = []
    for ex in exercises_used:
        ex_rows = working[working["exercise_title"] == ex].sort_values("set_index")
        top_e1rm = ex_rows["e1rm_kg"].max()
        sets = []
        for _, r in ex_rows.iterrows():
            w = r["weight_kg_load"]
            sets.append(f"{w:g}kg × {int(r['reps'])}" if pd.notna(w) and w > 0 else f"BW × {int(r['reps'])}")
        line = f"- **{ex}** — {' · '.join(sets)}"
        if pd.notna(top_e1rm):
            line += f"  _(top e1RM {top_e1rm:.1f} kg)_"
        ex_lines.append(line)

    notes = (g["description"].dropna().astype(str).str.strip().unique())
    notes_md = "\n\n".join(n for n in notes if n)
    exercise_notes = []
    for ex in exercises_used:
        en = (g[g["exercise_title"] == ex]["exercise_notes"].dropna().astype(str).str.strip().unique())
        for n in en:
            if n:
                exercise_notes.append(f"- **{ex}:** {n}")

    fm = _frontmatter({
        "date": workout_date.isoformat(),
        "title": f'"{title}"',
        "duration_min": int(duration_min),
        "tonnage_kg": int(total_volume),
        "set_count": set_count,
        "exercises_logged": len(exercises_used),
        "tags": ["hevy/session"],
    })

    content = [fm, ""]
    content.append(f"# {title}")
    content.append(f"`{start_time:%Y-%m-%d %H:%M}` — {duration_min:.0f} min · "
                   f"**{total_volume:,.0f} kg** · {set_count} working sets · {len(exercises_used)} exercises")
    content.append("")
    if notes_md:
        content.append("## Notes")
        content.append(notes_md)
        content.append("")
    content.append("## Exercises")
    content.extend(ex_lines)
    if exercise_notes:
        content.append("")
        content.append("## Per-exercise notes")
        content.extend(exercise_notes)
    content.append("")

    filename = f"{workout_date.isoformat()}.md"
    return filename, "\n".join(content)


def write_daily_notes(
    df: pd.DataFrame,
    vault_dir: Path,
    *,
    overwrite: bool = True,
    since: date | None = None,
) -> dict:
    """Generate ``Vault/Hevy/Daily/`` notes for every workout in ``df``.

    Returns a summary dict ``{written, skipped, total}``.
    """
    target_dir = Path(vault_dir) / "Hevy" / "Daily"
    target_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for wid, g in df.groupby("workout_id"):
        d = pd.to_datetime(g["workout_date"].iloc[0]).date() if pd.notna(g["workout_date"].iloc[0]) else None
        if d is None:
            skipped += 1
            continue
        if since is not None and d < since:
            skipped += 1
            continue
        filename, content = _session_to_markdown(g)
        path = target_dir / filename
        if path.exists() and not overwrite:
            skipped += 1
            continue
        path.write_text(content, encoding="utf-8")
        written += 1

    return {
        "written": written,
        "skipped": skipped,
        "total": int(df["workout_id"].nunique()),
        "target_dir": str(target_dir),
    }
