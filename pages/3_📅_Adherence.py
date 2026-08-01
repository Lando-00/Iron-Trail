"""Adherence — archetype-coloured calendar, streaks, time-of-day, archetype mix."""
from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from iron_trail import adherence, analytics, metrics, sidebar, theme, ui

ui.setup_page("Adherence · IronTrail", "📅")


with st.sidebar:
    df, _, body_weight = sidebar.render_data_source()

st.title("📅 Adherence")

c1, c2, c3 = st.columns(3)
c1.metric("Current streak", f"{metrics.current_streak(df)} d")
c2.metric("Longest streak", f"{metrics.longest_streak(df)} d")
c3.metric("Total workouts", df["workout_id"].nunique())

ui.section_title("Calendar — coloured by session archetype")

arch = analytics.session_archetype(df)
if arch.empty:
    st.info("No sessions to classify.")
    st.stop()

arch["date"] = pd.to_datetime(arch["workout_date"], errors="coerce")
arch = arch.dropna(subset=["date"])
if arch.empty:
    st.info("No dated sessions to display.")
    st.stop()

max_window_weeks = adherence.max_calendar_window_weeks(arch["date"])
if max_window_weeks == adherence.MIN_WINDOW_WEEKS:
    window_weeks = adherence.MIN_WINDOW_WEEKS
    st.caption("All available sessions fit within the last 8 weeks.")
else:
    window_weeks = st.slider(
        "Weeks to show",
        min_value=adherence.MIN_WINDOW_WEEKS,
        max_value=max_window_weeks,
        value=min(adherence.DEFAULT_WINDOW_WEEKS, max_window_weeks),
        step=adherence.WINDOW_STEP_WEEKS,
        help="The range is limited to the workout history currently loaded.",
    )

end = arch["date"].max()
start = end - pd.Timedelta(weeks=window_weeks)
arch_window = arch.copy()
arch_window = arch_window[arch_window["date"] >= start]

if arch_window.empty:
    st.info("No sessions in selected window.")
else:
    visible_start = arch_window["date"].min()
    st.caption(
        f"Showing {len(arch_window)} of {len(arch)} sessions from "
        f"{visible_start:%d %b %Y} to {end:%d %b %Y}."
    )
    arch_window["week_start"] = arch_window["date"].dt.to_period("W-SUN").dt.start_time
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    arch_window["dow_idx"] = arch_window["date"].dt.dayofweek
    arch_window["dow_name"] = arch_window["dow_idx"].map(dict(enumerate(day_names)))
    axis_start = start.to_period("W-SUN").start_time
    axis_end = end.to_period("W-SUN").start_time + pd.Timedelta(days=7)

    fig = go.Figure()
    for arche, sub in arch_window.groupby("archetype"):
        color = theme.ARCHETYPE_COLORS.get(arche, theme.COLORS["accent_gold"])
        fig.add_trace(go.Scatter(
            x=sub["week_start"], y=sub["dow_idx"],
            mode="markers",
            marker=dict(
                size=18, color=color, symbol="square",
                line=dict(color=theme.COLORS["bg"], width=2),
            ),
            name=arche,
            customdata=sub[["title", "total_volume", "duration_min", "avg_reps"]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{x|%a %d %b %Y}<br>"
                "Volume: %{customdata[1]:,.0f} kg<br>"
                "Duration: %{customdata[2]:.0f} min<br>"
                "Avg reps: %{customdata[3]:.1f}<extra></extra>"
            ),
        ))
    fig.update_layout(
        xaxis=dict(title="", range=[axis_start, axis_end]),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(7)),
            ticktext=day_names,
            autorange="reversed",
            title="",
        ),
    )
    ui.plotly_chart(fig, "calendar", size="standard", date_axis=True)

ui.section_title("Archetype distribution")

dist = arch["archetype"].value_counts().reset_index()
dist.columns = ["archetype", "count"]
dist["color"] = dist["archetype"].map(theme.ARCHETYPE_COLORS).fillna(theme.COLORS["accent_gold"])

fig2 = go.Figure(go.Bar(
    x=dist["archetype"], y=dist["count"],
    marker=dict(color=dist["color"]),
    hovertemplate="%{x}: %{y} sessions<extra></extra>",
))
fig2.update_layout(yaxis_title="Sessions", xaxis_title="")
ui.plotly_chart(fig2, "archetypes", size="compact")

ui.section_title("Time of day")

tod = metrics.time_of_day_distribution(df)
if tod.empty:
    st.info("No workout times available.")
else:
    fig3 = go.Figure(go.Bar(
        x=tod["hour"], y=tod["count"],
        marker=dict(color=theme.COLORS["accent_blue"]),
        hovertemplate="%{x}:00 — %{y} workouts<extra></extra>",
    ))
    fig3.update_layout(
        xaxis=dict(title="Hour of day (workout start)", dtick=1, range=[-0.5, 23.5]),
        yaxis_title="Workouts",
        bargap=0.12,
    )
    ui.plotly_chart(fig3, "timeofday", size="compact")

    peak_hour = int(tod.sort_values("count", ascending=False).iloc[0]["hour"])
    bucket = (
        "early morning (5–8 am)" if 5 <= peak_hour < 8
        else "morning (8–11 am)" if 8 <= peak_hour < 11
        else "midday (11 am–2 pm)" if 11 <= peak_hour < 14
        else "afternoon (2–5 pm)" if 14 <= peak_hour < 17
        else "evening (5–8 pm)" if 17 <= peak_hour < 20
        else "night (8 pm+)"
    )
    article = "an" if bucket[0] in "aeiou" else "a"
    ui.callout("info", f"Peak training hour: {peak_hour}:00 — you're {article} {bucket} lifter.")
