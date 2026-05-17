"""PR Poster generator — 1080×1080 PNG, dark+gold, Pillow.

Auto-detects when a working set is a personal record on its exercise,
then renders a posterable image with:

- A giant weight × reps headline (JetBrains Mono)
- The exercise name + date
- "+X kg vs previous PR" delta line if applicable
- IronTrail watermark in the corner

Useful for sharing PRs on social or pinning to a vault note.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


_BG = (10, 10, 12)
_GOLD = (212, 168, 67)
_GOLD_DIM = (164, 130, 51)
_TEXT_PRIMARY = (231, 231, 233)
_TEXT_SECONDARY = (138, 138, 147)
_TEXT_MUTED = (91, 91, 98)

SIZE = 1080
PADDING = 90


def _try_font(candidates: Iterable[str], size: int) -> ImageFont.FreeTypeFont:
    for cand in candidates:
        try:
            return ImageFont.truetype(cand, size=size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _font_mono(size: int) -> ImageFont.FreeTypeFont:
    return _try_font(
        [
            "JetBrainsMono-Bold.ttf",
            "JetBrainsMono-Regular.ttf",
            "consola.ttf",          # Windows: Consolas
            "DejaVuSansMono-Bold.ttf",
            "DejaVuSansMono.ttf",
        ],
        size,
    )


def _font_sans(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        candidates = [
            "InterTight-Bold.ttf",
            "Inter-Bold.ttf",
            "arialbd.ttf",          # Windows: Arial Bold
            "DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "InterTight-Regular.ttf",
            "Inter-Regular.ttf",
            "arial.ttf",
            "DejaVuSans.ttf",
        ]
    return _try_font(candidates, size)


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_pr_poster(
    exercise: str,
    weight_kg: float,
    reps: int,
    *,
    e1rm_kg: float | None = None,
    prev_e1rm_kg: float | None = None,
    when: date | None = None,
) -> bytes:
    """Render a single PR poster as PNG bytes (1080×1080)."""
    img = Image.new("RGB", (SIZE, SIZE), _BG)
    draw = ImageDraw.Draw(img)

    # Subtle gold gradient overlay in the top-left corner
    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for r in range(560, 0, -8):
        alpha = int(40 * (1 - r / 560))
        odraw.ellipse(
            (-200 - r // 4, -200 - r // 4, r - 200, r - 200),
            fill=(212, 168, 67, alpha),
        )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
    draw = ImageDraw.Draw(img)

    # Header — small label
    label_font = _font_sans(26, bold=True)
    label = "PERSONAL RECORD"
    lw, lh = _measure(draw, label, label_font)
    draw.text((PADDING, PADDING), label, font=label_font, fill=_GOLD)

    # Date in monospace, top-right
    date_str = (when or date.today()).strftime("%d %b %Y").upper()
    date_font = _font_mono(20)
    dw, dh = _measure(draw, date_str, date_font)
    draw.text((SIZE - PADDING - dw, PADDING + 4), date_str, font=date_font, fill=_TEXT_SECONDARY)

    # Headline — exercise name
    headline_font = _font_sans(56, bold=True)
    # Wrap if too wide
    ex_lines = _wrap_text(draw, exercise, headline_font, max_width=SIZE - 2 * PADDING)
    y_cursor = PADDING + 90
    for line in ex_lines:
        draw.text((PADDING, y_cursor), line, font=headline_font, fill=_TEXT_PRIMARY)
        _, line_h = _measure(draw, line, headline_font)
        y_cursor += line_h + 6

    # Main number: weight × reps
    main_font = _font_mono(200)
    reps_font = _font_mono(96)
    unit_font = _font_sans(56, bold=True)

    main_text = f"{int(weight_kg) if weight_kg == int(weight_kg) else weight_kg:g}"
    reps_text = f"× {reps}"

    mw, mh = _measure(draw, main_text, main_font)
    uw, uh = _measure(draw, "kg", unit_font)
    rw, rh = _measure(draw, reps_text, reps_font)

    # Layout: [60] [kg]                  on one row
    #         [× 9]                       on the row below
    main_y = SIZE - PADDING - 280
    draw.text((PADDING, main_y), main_text, font=main_font, fill=_GOLD)
    # "kg" sits to the right of the number, baseline-aligned
    kg_x = PADDING + mw + 18
    kg_y = main_y + mh - uh - 22
    draw.text((kg_x, kg_y), "kg", font=unit_font, fill=_GOLD_DIM)
    # "× 9" sits below, left-aligned with the main number
    reps_y = main_y + mh + 4
    draw.text((PADDING, reps_y), reps_text, font=reps_font, fill=_TEXT_PRIMARY)

    # Bottom info row — e1RM + delta (place below the reps line)
    info_lines = []
    if e1rm_kg is not None:
        info_lines.append(f"Estimated 1RM  {e1rm_kg:.1f} kg")
    if prev_e1rm_kg is not None and e1rm_kg is not None:
        delta = e1rm_kg - prev_e1rm_kg
        sign = "+" if delta >= 0 else ""
        info_lines.append(f"vs previous PR  {sign}{delta:.1f} kg")
    info_font = _font_mono(24)
    info_y = reps_y + rh + 28
    for line in info_lines:
        draw.text((PADDING, info_y), line, font=info_font, fill=_TEXT_SECONDARY)
        info_y += 34

    # IronTrail watermark, bottom-right
    wm_font = _font_sans(22, bold=True)
    wm = "IRONTRAIL"
    ww, wh = _measure(draw, wm, wm_font)
    draw.text((SIZE - PADDING - ww, SIZE - PADDING - wh), wm, font=wm_font, fill=_TEXT_MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        w, _ = _measure(draw, trial, font)
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Helpers that work against the cleaned DataFrame
# ---------------------------------------------------------------------------


def find_recent_prs(df: pd.DataFrame, since: date | None = None) -> pd.DataFrame:
    """Return one row per exercise-level e1RM PR since the given date.

    Each row is the best working set (by e1rm_kg) of the session that set
    the PR, with the previous-PR value attached for delta display.
    """
    working = df[df["is_working"]].copy()
    if working.empty:
        return pd.DataFrame(columns=[
            "exercise_title", "workout_date", "weight_kg_load",
            "reps", "e1rm_kg", "prev_e1rm_kg",
        ])
    working = working.sort_values(["exercise_title", "start_time"])
    working["running_max_e1rm"] = working.groupby("exercise_title")["e1rm_kg"].cummax()
    working["is_pr"] = working["e1rm_kg"] >= working["running_max_e1rm"]
    pr_rows = working[working["is_pr"]].copy()
    if since is not None:
        pr_rows = pr_rows[pr_rows["workout_date"] >= since]
    pr_rows["prev_e1rm_kg"] = pr_rows.groupby("exercise_title")["e1rm_kg"].shift(1)
    # Keep only the PR-setting row per exercise per session (best in the session)
    pr_rows = (
        pr_rows.sort_values("e1rm_kg", ascending=False)
        .drop_duplicates(subset=["exercise_title", "workout_id"])
        .sort_values("start_time", ascending=False)
    )
    return pr_rows


def render_pr_poster_for_row(row: pd.Series) -> bytes:
    """Convenience wrapper that takes a PR row and returns poster bytes."""
    when = pd.to_datetime(row["workout_date"]).date() if pd.notna(row["workout_date"]) else None
    prev = row.get("prev_e1rm_kg")
    prev_val = None if pd.isna(prev) else float(prev)
    return render_pr_poster(
        exercise=str(row["exercise_title"]),
        weight_kg=float(row["weight_kg_load"]),
        reps=int(row["reps"]),
        e1rm_kg=float(row["e1rm_kg"]),
        prev_e1rm_kg=prev_val,
        when=when,
    )
