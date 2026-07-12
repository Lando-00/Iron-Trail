"""IronTrail — Overview (entry point).

Hero stat + last-30-day metrics with sparklines, plateau alerts,
achievements preview, lowlights, and recent workouts.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from iron_trail import analytics, metrics, runtime, sidebar, theme, ui

ui.setup_page("IronTrail", "🏋️")


with st.sidebar:
    df, source_label, body_weight = sidebar.render_data_source()
    if not runtime.is_cloud():
        st.divider()
        st.markdown("**Markdown writeback**")
        vault_path = st.text_input(
            "Output directory",
            value="vault-output",
            help=(
                "Each workout becomes <dir>/Hevy/Daily/YYYY-MM-DD.md. "
                "Point this at your Obsidian vault (or Logseq, or any folder). "
                "Defaults to ./vault-output/ in the repo for a quick demo."
            ),
        )
        vault_since = st.date_input(
            "From date",
            value=pd.Timestamp.now().normalize().date() - pd.Timedelta(days=30),
        )
        do_vault_write = st.button("📝 Generate daily notes")
    else:
        do_vault_write = False

if do_vault_write:
    from iron_trail import vault_notes
    try:
        result = vault_notes.write_daily_notes(
            df, Path(vault_path), overwrite=True, since=vault_since,
        )
        st.sidebar.success(f"✓ {result['written']} notes written → `{result['target_dir']}`")
    except Exception as e:
        st.sidebar.error(f"Failed: {e}")

if df.empty:
    st.warning("No rows parsed from the selected CSV.")
    st.stop()

# =====================================================================
# HERO
# =====================================================================

total_volume = float(df.loc[df["is_working"], "volume_kg"].sum())
total_workouts = int(df["workout_id"].nunique())
date_range = df["workout_date"].dropna()
date_min, date_max = min(date_range), max(date_range)
years_active = (date_max - date_min).days / 365.25

ui.hero(
    label="Lifetime tonnage",
    value=f"{total_volume:,.0f}",
    unit="kg",
    subtitle=(
        f"{total_workouts} workouts across {years_active:.1f} years of training — "
        f"{source_label}"
    ),
)

# =====================================================================
# LAST 30 DAYS METRICS + SPARKLINES
# =====================================================================

stats = metrics.overview_stats(df, window_days=30)

ui.section_title("Last 30 days")

# Helper to humanize kg
def fmt_kg(v: float) -> tuple[str, str]:
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}", "M kg"
    if v >= 10_000:
        return f"{v/1_000:.1f}", "k kg"
    if v >= 1_000:
        return f"{v:,.0f}", "kg"
    return f"{v:.0f}", "kg"


c1, c2, c3, c4, c5 = st.columns(5)

working = df[df["is_working"]].copy()
if not working.empty:
    working["week"] = pd.to_datetime(working["workout_date"]).dt.to_period("W-SUN").dt.start_time
    weekly = working.groupby("week").agg(tonnage=("volume_kg", "sum")).reset_index().tail(12)
    workouts_per_week = (
        df.drop_duplicates("workout_id").assign(
            week=lambda d: pd.to_datetime(d["workout_date"]).dt.to_period("W-SUN").dt.start_time
        )
        .groupby("week").size().tail(12)
    )
    durations = (
        df.drop_duplicates("workout_id").assign(
            week=lambda d: pd.to_datetime(d["workout_date"]).dt.to_period("W-SUN").dt.start_time
        )
        .groupby("week")["duration_min"].mean().tail(12)
    )
else:
    weekly = pd.DataFrame({"week": [], "tonnage": []})
    workouts_per_week = pd.Series([], dtype=int)
    durations = pd.Series([], dtype=float)

ton_val, ton_unit = fmt_kg(stats["tonnage_kg"])

with c1:
    ui.mini_metric("Workouts", f"{stats['workouts']}")
    if len(workouts_per_week) >= 4:
        st.plotly_chart(ui.sparkline(workouts_per_week.values, theme.COLORS["accent_blue"]),
                        use_container_width=True, config={"displayModeBar": False})

with c2:
    ui.mini_metric("Tonnage", ton_val, ton_unit)
    if len(weekly) >= 4:
        st.plotly_chart(ui.sparkline(weekly["tonnage"].values, theme.COLORS["accent_gold"]),
                        use_container_width=True, config={"displayModeBar": False})

with c3:
    ui.mini_metric("Training time", f"{stats['training_hours']:.1f}", "h")
    if len(durations) >= 4:
        st.plotly_chart(ui.sparkline(durations.values, theme.COLORS["accent_blue"]),
                        use_container_width=True, config={"displayModeBar": False})

with c4:
    ui.mini_metric("Current streak", f"{stats['current_streak']}", "d")

with c5:
    ui.mini_metric("Longest streak", f"{stats['longest_streak']}", "d")

# =====================================================================
# PLATEAU ALERTS
# =====================================================================

ui.section_title("Plateau watch")

plateaus = analytics.all_plateaus(df, min_sessions=5)
significant = [
    p for p in plateaus
    if p.status in ("plateaued", "regressing") and p.all_time_max_e1rm >= 40
]
significant.sort(key=lambda p: -p.all_time_max_e1rm)

if not significant:
    ui.callout("success", "No active plateaus on your top lifts. 🔥")
else:
    for p in significant[:3]:
        kind = "warning" if p.status == "regressing" else "gold"
        ui.callout(kind, f"<strong>{p.exercise}</strong> — {p.message}")
    remaining = len(significant) - 3
    if remaining > 0:
        st.caption(f"+ {remaining} more plateau{'s' if remaining > 1 else ''} flagged. See **Strength** page per-exercise.")

# =====================================================================
# ACHIEVEMENTS PREVIEW
# =====================================================================

ui.section_title("Recent unlocks & next targets")

badges = analytics.awards_earned(df, body_weight_kg=body_weight)
unlocked = [b for b in badges if b["unlocked"]]
locked = sorted([b for b in badges if not b["unlocked"]], key=lambda b: -b["progress"])

preview = unlocked[-4:] + locked[:4]
cols = st.columns(min(len(preview), 8))
for col, b in zip(cols, preview):
    with col:
        progress = f"{b['current_str']} / {b['target_str']}" if not b["unlocked"] else "✓ unlocked"
        ui.badge_card(b["icon"], b["name"], b["criteria"], progress, b["unlocked"])

st.caption(f"{len(unlocked)} / {len(badges)} achievements unlocked — see full wall on **Achievements**.")

# =====================================================================
# LOWLIGHTS
# =====================================================================

with st.expander("💀 Hall of Shame — the least-productive sessions"):
    worst = analytics.worst_sessions(df, n=5)
    if worst.empty:
        st.caption("No bad days found. Either you're a machine or you don't log them.")
    else:
        for _, row in worst.iterrows():
            ui.lowlight_card(
                date_str=pd.to_datetime(row["workout_date"]).strftime("%a, %d %b %Y"),
                title=row["title"] or "Untitled",
                caption=row["caption"],
                stats=f"{row['total_volume']:,.0f} kg · {row['set_count']} sets · {row['duration_min']:.0f} min",
            )

with st.expander("🏆 Hall of Fame — the sessions to remember"):
    best = analytics.best_sessions(df, n=5)
    if best.empty:
        st.caption("Train more, come back. The Hall accepts applications.")
    else:
        for _, row in best.iterrows():
            stats = (
                f"{row['total_volume']:,.0f} kg · {row['set_count']} sets · "
                f"{row['duration_min']:.0f} min · top {row['top_weight_kg']:.0f} kg · "
                f"{row['muscles_hit']} muscles"
            )
            ui.highlight_card(
                date_str=pd.to_datetime(row["workout_date"]).strftime("%a, %d %b %Y"),
                title=row["title"] or "Untitled",
                caption=row["caption"],
                stats=stats,
            )

# =====================================================================
# RECENT WORKOUTS
# =====================================================================

ui.section_title("Recent workouts")

recent = (
    df.drop_duplicates("workout_id")
    .sort_values("start_time", ascending=False)
    .head(15)
    [["start_time", "title", "duration_min"]]
    .rename(columns={"start_time": "Start", "title": "Workout", "duration_min": "Duration (min)"})
)
recent["Duration (min)"] = recent["Duration (min)"].fillna(0).round(0).astype(int)
recent["Start"] = pd.to_datetime(recent["Start"]).dt.strftime("%Y-%m-%d %H:%M")
st.dataframe(recent, use_container_width=True, hide_index=True)

with st.expander("Unmapped exercises (add to data/lookups/exercise_muscle_map.csv)"):
    unmapped = (
        df[df["primary_muscle"] == "unmapped"]["exercise_title"]
        .value_counts()
        .reset_index()
    )
    unmapped.columns = ["Exercise", "Set count"]
    if unmapped.empty:
        st.success("All exercises mapped.")
    else:
        st.dataframe(unmapped, use_container_width=True, hide_index=True)
        st.caption(
            f"{len(unmapped)} unmapped exercises across {unmapped['Set count'].sum()} sets — "
            "these still appear in raw stats but are skipped in muscle and movement breakdowns."
        )
