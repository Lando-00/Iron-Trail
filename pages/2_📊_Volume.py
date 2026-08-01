"""Volume page — weekly tonnage by muscle, push:pull ratio, movement radar."""
from __future__ import annotations


import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from iron_trail import analytics, metrics, sidebar, theme, ui

ui.setup_page("Volume · IronTrail", "📊")


with st.sidebar:
    df, _, body_weight = sidebar.render_data_source()

st.title("📊 Volume & Balance")
st.caption("Tonnage = Σ(working-set weight × reps). Bodyweight substituted from sidebar. Warmups excluded.")

window = st.radio(
    "Window",
    ["Last 12 weeks", "Last 6 months", "Last 12 months", "All time"],
    horizontal=True, index=2,
)
window_map = {"Last 12 weeks": 12, "Last 6 months": 26, "Last 12 months": 52, "All time": None}
weeks = window_map[window]

vol = metrics.weekly_volume_by_muscle(df)
if vol.empty:
    st.info("No working sets to plot.")
    st.stop()

if weeks is not None:
    end_week = vol["week"].max()
    start_week = end_week - pd.Timedelta(weeks=weeks)
    vol = vol[vol["week"] >= start_week]

ui.section_title("Weekly tonnage by muscle")
fig = px.bar(
    vol, x="week", y="volume_kg", color="primary_muscle",
    labels={"week": "Week", "volume_kg": "Tonnage (kg)", "primary_muscle": "Muscle"},
    color_discrete_sequence=px.colors.qualitative.Vivid,
)
fig.update_layout(barmode="stack")
ui.plotly_chart(fig, "tonnage", size="xtall", date_axis=True)

ui.section_title("Push : Pull ratio")
pp = metrics.weekly_push_pull(df)
if weeks is not None and not pp.empty:
    end_week = pp["week"].max()
    start_week = end_week - pd.Timedelta(weeks=weeks)
    pp = pp[pp["week"] >= start_week]

if pp.empty or "push_pull_ratio" not in pp.columns:
    st.info("Need both push and pull sessions to compute the ratio.")
else:
    plot_pp = pp.dropna(subset=["push_pull_ratio"]).copy()
    if plot_pp.empty:
        st.info("Need at least one week with both push and pull volume.")
    else:
        fig2 = go.Figure()
        fig2.add_scatter(
            x=plot_pp["week"], y=plot_pp["push_pull_ratio"], mode="lines+markers",
            line=dict(color=theme.COLORS["accent_blue"], width=2.2, shape="spline", smoothing=0.4),
            marker=dict(size=6), name="Pull ÷ Push",
            hovertemplate="%{x|%b %d}: %{y:.2f}<extra></extra>",
        )
        fig2.add_hline(y=1.0, line=dict(color=theme.COLORS["text_muted"], width=1, dash="dash"),
                       annotation_text="1:1 balance", annotation_position="top right",
                       annotation_font=dict(color=theme.COLORS["text_secondary"]))
        fig2.update_layout(xaxis_title="Week")
        st.caption("Pull ÷ Push volume per week — 1.0 is balanced.")
        ui.plotly_chart(fig2, "pushpull", size="standard", date_axis=True)

        avg_ratio = plot_pp["push_pull_ratio"].mean()
        if 0.9 <= avg_ratio <= 1.3:
            ui.callout("success", f"Average push:pull ratio over this window: {avg_ratio:.2f} — well balanced.")
        elif avg_ratio < 0.9:
            ui.callout("warning", f"Average push:pull ratio: {avg_ratio:.2f}. Pull volume lags — add rows / pulldowns / curls.")
        else:
            ui.callout("info", f"Average push:pull ratio: {avg_ratio:.2f}. Pull-heavy — common for postural correction, fine if intentional.")

ui.section_title("Movement Radar — last 12 weeks")
radar = analytics.movement_radar_data(df, weeks_back=12)
if radar["working_sets"].sum() == 0:
    st.info("No mapped movements in the last 12 weeks.")
else:
    target_sets_per_week = 8
    fig3 = go.Figure()
    fig3.add_trace(go.Scatterpolar(
        r=[target_sets_per_week] * len(radar) + [target_sets_per_week],
        theta=list(radar["label"]) + [radar["label"].iloc[0]],
        mode="lines",
        line=dict(color=theme.COLORS["text_muted"], width=1, dash="dash"),
        name=f"Target ({target_sets_per_week}/wk)",
        hoverinfo="skip",
    ))
    fig3.add_trace(go.Scatterpolar(
        r=list(radar["sets_per_week"]) + [radar["sets_per_week"].iloc[0]],
        theta=list(radar["label"]) + [radar["label"].iloc[0]],
        fill="toself",
        fillcolor="rgba(212, 168, 67, 0.18)",
        line=dict(color=theme.COLORS["accent_gold"], width=2.4),
        marker=dict(size=8, color=theme.COLORS["accent_gold"]),
        name="Sets / week",
        hovertemplate="%{theta}: %{r:.1f} sets/wk<extra></extra>",
    ))
    max_r = max(target_sets_per_week, float(radar["sets_per_week"].max())) * 1.15
    fig3.update_layout(
        polar=dict(radialaxis=dict(range=[0, max_r], showticklabels=True)),
        showlegend=True,
    )
    ui.plotly_chart(fig3, "radar", size="xtall")

    neglected = radar[radar["sets_per_week"] < 4].sort_values("sets_per_week")
    if not neglected.empty:
        neglected_text = ", ".join(
            f"{row['label']} ({row['sets_per_week']:.1f}/wk)"
            for _, row in neglected.iterrows()
        )
        ui.callout("warning", f"Under 4 sets/week (typical minimum effective volume): {neglected_text}")
