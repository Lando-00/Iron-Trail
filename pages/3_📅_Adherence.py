"""Adherence — archetype-coloured calendar, streaks, time-of-day, archetype mix."""
from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from iron_trail import analytics, metrics, sidebar, theme, ui

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

window_weeks = st.slider("Weeks to show", min_value=8, max_value=104, value=52, step=4)
end = pd.to_datetime(arch["workout_date"]).max()
start = end - pd.Timedelta(weeks=window_weeks)
arch_window = arch.copy()
arch_window["date"] = pd.to_datetime(arch_window["workout_date"])
arch_window = arch_window[arch_window["date"] >= start]

if arch_window.empty:
    st.info("No sessions in selected window.")
else:
    arch_window["week_start"] = arch_window["date"].dt.to_period("W-SUN").dt.start_time
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    arch_window["dow_idx"] = arch_window["date"].dt.dayofweek
    arch_window["dow_name"] = arch_window["dow_idx"].map(dict(enumerate(day_names)))

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
        height=320,
        xaxis=dict(title=""),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(7)),
            ticktext=day_names,
            autorange="reversed",
            title="",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)

ui.section_title("Archetype distribution")

dist = arch["archetype"].value_counts().reset_index()
dist.columns = ["archetype", "count"]
dist["color"] = dist["archetype"].map(theme.ARCHETYPE_COLORS).fillna(theme.COLORS["accent_gold"])

fig2 = go.Figure(go.Bar(
    x=dist["archetype"], y=dist["count"],
    marker=dict(color=dist["color"]),
    hovertemplate="%{x}: %{y} sessions<extra></extra>",
))
fig2.update_layout(height=260, yaxis_title="Sessions", xaxis_title="")
st.plotly_chart(fig2, use_container_width=True)

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
        height=260,
        xaxis=dict(title="Hour of day (workout start)", dtick=1, range=[-0.5, 23.5]),
        yaxis_title="Workouts",
        bargap=0.12,
    )
    st.plotly_chart(fig3, use_container_width=True)

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
