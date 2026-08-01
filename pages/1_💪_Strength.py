"""Per-exercise estimated 1RM (e1RM) progression."""
from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from iron_trail import analytics, metrics, posters, sidebar, theme, ui

ui.setup_page("Strength · IronTrail", "💪")


with st.sidebar:
    df, _, body_weight = sidebar.render_data_source()

st.title("💪 Strength Progression")
st.caption("Estimated 1RM via Epley `weight × (1 + reps / 30)` on the top working set per session. Warmups excluded.")

exercises = metrics.exercise_list(df)
if not exercises:
    st.info("No working sets found.")
    st.stop()

top_choice = (
    df.loc[df["is_working"], "exercise_title"]
    .value_counts()
    .index.tolist()
)
default_idx = exercises.index(top_choice[0]) if top_choice else 0

ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])
with ctrl1:
    exercise = st.selectbox("Exercise", exercises, index=default_idx)
with ctrl2:
    show_forecast = st.checkbox("Show forecast", value=True)
with ctrl3:
    show_yoy = st.checkbox("Year-over-year", value=False)

session_data = metrics.per_session_top_e1rm(df, exercise)
if session_data.empty:
    st.warning("No e1RM-eligible working sets for this exercise.")
    st.stop()

# Plateau status callout
ps = analytics.plateau_status(df, exercise)
if ps is not None:
    kind = {
        "fresh_pr": "gold",
        "progressing": "success",
        "plateaued": "gold",
        "regressing": "warning",
        "new": "info",
    }[ps.status]
    ui.callout(kind, f"{exercise} — {ps.message}")

# Main chart
session_data["date"] = pd.to_datetime(session_data["workout_date"])
prs = session_data[session_data["is_pr"]]

fig = go.Figure()

if show_yoy:
    yoy = analytics.year_over_year(df, exercise, weeks=16)
    if yoy is not None and not yoy["last_year"].empty:
        fig.add_scatter(
            x=yoy["last_year"]["date"], y=yoy["last_year"]["e1rm_kg"],
            mode="lines", name="Last year (shifted)",
            line=dict(color=theme.COLORS["text_muted"], width=1.5, dash="dot"),
            hovertemplate="%{x|%b %d}: %{y:.1f} kg (last yr)<extra></extra>",
        )

fig.add_scatter(
    x=session_data["date"], y=session_data["e1rm_kg"],
    mode="lines+markers", name="e1RM",
    line=dict(color=theme.COLORS["accent_blue"], width=2.4, shape="spline", smoothing=0.4),
    marker=dict(size=6, color=theme.COLORS["accent_blue"]),
    hovertemplate="%{x|%b %d %Y}: %{y:.1f} kg<extra></extra>",
)

if not prs.empty:
    fig.add_scatter(
        x=pd.to_datetime(prs["workout_date"]), y=prs["e1rm_kg"],
        mode="markers", name="PR",
        marker=dict(size=14, color=theme.COLORS["accent_gold"], symbol="star",
                    line=dict(color="#fff", width=1)),
        hovertemplate="PR · %{x|%b %d %Y}: %{y:.1f} kg<extra></extra>",
    )

if show_forecast:
    fc = analytics.e1rm_forecast(df, exercise, weeks_ahead=4)
    if fc is not None and not fc.empty:
        anchor_date = session_data["date"].iloc[-1]
        anchor_value = session_data["e1rm_kg"].iloc[-1]
        fx = pd.concat([pd.Series([anchor_date]), fc["workout_date"]], ignore_index=True)
        fy = pd.concat([pd.Series([anchor_value]), fc["e1rm_kg"]], ignore_index=True)
        flo = pd.concat([pd.Series([anchor_value]), fc["lower"]], ignore_index=True)
        fhi = pd.concat([pd.Series([anchor_value]), fc["upper"]], ignore_index=True)
        fig.add_scatter(
            x=fx, y=fy, mode="lines", name="Forecast",
            line=dict(color=theme.COLORS["accent_gold"], width=2, dash="dash"),
            hovertemplate="Forecast · %{x|%b %d}: %{y:.1f} kg<extra></extra>",
        )
        fig.add_scatter(
            x=list(fx) + list(fx[::-1]),
            y=list(fhi) + list(flo[::-1]),
            fill="toself", fillcolor="rgba(212,168,67,0.10)",
            line=dict(color="rgba(212,168,67,0)"),
            hoverinfo="skip", name="Forecast CI", showlegend=False,
        )

fig.update_layout(xaxis_title="Date")
st.caption("e1RM in kg — estimated one-rep max per session.")
ui.plotly_chart(fig, "e1rm", size="tall", date_axis=True)

first = session_data["e1rm_kg"].iloc[0]
last = session_data["e1rm_kg"].iloc[-1]
maxv = session_data["e1rm_kg"].max()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sessions", len(session_data))
c2.metric("Max e1RM", f"{maxv:.1f} kg")
c3.metric("Latest e1RM", f"{last:.1f} kg")
c4.metric("Change since first", f"{last - first:+.1f} kg")

# =====================================================================
# PR Poster
ui.section_title("📸 PR Poster")

prs_for_ex = posters.find_recent_prs(df)
prs_for_ex = prs_for_ex[prs_for_ex["exercise_title"] == exercise]
if prs_for_ex.empty:
    st.caption("No PR-eligible working sets recorded for this exercise yet.")
else:
    latest_pr = prs_for_ex.iloc[0]
    pc1, pc2 = st.columns([2, 1])
    with pc1:
        prev_str = (
            f"+{latest_pr['e1rm_kg'] - latest_pr['prev_e1rm_kg']:.1f} kg vs previous"
            if pd.notna(latest_pr["prev_e1rm_kg"]) else "first recorded PR"
        )
        st.markdown(
            f"**Latest PR:** {latest_pr['weight_kg_load']:.0f} kg × "
            f"{int(latest_pr['reps'])} (e1RM {latest_pr['e1rm_kg']:.1f} kg) — "
            f"{prev_str}, on "
            f"{pd.to_datetime(latest_pr['workout_date']).strftime('%d %b %Y')}."
        )
    with pc2:
        try:
            png_bytes = posters.render_pr_poster_for_row(latest_pr)
            safe_ex = "".join(c if c.isalnum() else "_" for c in exercise)
            st.download_button(
                "📸 Download 1080×1080",
                data=png_bytes,
                file_name=f"PR_{safe_ex}_{latest_pr['workout_date']}.png",
                mime="image/png",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"Poster render failed: {e}")

if show_yoy:
    yoy = analytics.year_over_year(df, exercise, weeks=16)
    if yoy is None or yoy["last_year"].empty:
        st.info("Not enough history yet — need at least 1 year of data on this exercise.")
    elif yoy.get("current_delta") is not None:
        delta = yoy["current_delta"]
        kind = "success" if delta > 0 else "warning" if delta < 0 else "info"
        sign = "+" if delta > 0 else ""
        ui.callout(kind, f"You vs same point last year: {sign}{delta:.1f} kg")
