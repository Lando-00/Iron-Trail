"""UI helpers: CSS injection, hero block, callouts, badges, sparklines.

All Streamlit pages should call :func:`setup_page` near the top — it
applies the page config, injects the IronTrail CSS, and ensures the
Plotly theme is registered.
"""
from __future__ import annotations

from collections.abc import Iterable

import plotly.graph_objects as go
import streamlit as st

from . import theme  # noqa: F401  — importing registers the Plotly template

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Inter Tight', system-ui, -apple-system, sans-serif;
    color: #e7e7e9;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

.stApp {
    background:
      radial-gradient(circle at 0% 0%, rgba(212, 168, 67, 0.05), transparent 38%),
      radial-gradient(circle at 100% 0%, rgba(91, 156, 240, 0.045), transparent 38%),
      radial-gradient(circle at 50% 100%, rgba(155, 135, 245, 0.03), transparent 50%),
      #0a0a0c;
}

/* Quotes page cards */
.it-quote-card {
    background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-left: 3px solid #d4a843;
    border-radius: 12px;
    padding: 18px 22px;
    margin: 10px 0;
    transition: transform 0.18s, border-color 0.18s;
}
.it-quote-card:hover {
    transform: translateX(2px);
    border-left-color: #e8a05b;
}
.it-quote-card.cluster { border-left-color: #5b9cf0; }
.it-quote-card.emotional { border-left-color: #e85a4f; }
.it-quote-card.roast { border-left-color: #9b87f5; }
.it-quote-card.emoji { border-left-color: #5dc77c; }

.it-quote-text {
    font-family: 'Inter Tight', sans-serif;
    font-size: 17px;
    color: #e7e7e9;
    font-weight: 500;
    font-style: italic;
    line-height: 1.4;
}
.it-quote-meta {
    color: #8a8a93;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-top: 8px;
    font-family: 'JetBrains Mono', monospace;
}
.it-quote-variants {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
}
.it-quote-variant {
    background: rgba(91, 156, 240, 0.10);
    border: 1px solid rgba(91, 156, 240, 0.25);
    color: #b5cef5;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-family: 'JetBrains Mono', monospace;
}

/* Coach page — review card */
.it-review-card {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 28px 36px;
    margin: 20px 0;
}
.it-review-card h1,
.it-review-card h2,
.it-review-card h3 { color: #e7e7e9; }
.it-review-card h2 {
    color: #d4a843;
    font-size: 17px;
    margin-top: 24px;
    border-bottom: 1px solid rgba(212, 168, 67, 0.18);
    padding-bottom: 8px;
}

.it-coach-empty {
    border: 1px dashed rgba(255, 255, 255, 0.12);
    border-radius: 14px;
    padding: 60px 24px;
    text-align: center;
    color: #8a8a93;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: rgba(10, 10, 12, 0.6);
    backdrop-filter: blur(20px);
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}

/* Hero */
.it-hero {
    background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 36px 36px 32px;
    margin-bottom: 28px;
    backdrop-filter: blur(20px);
    position: relative;
    overflow: hidden;
}
.it-hero::before {
    content: '';
    position: absolute;
    top: -40%;
    right: -10%;
    width: 280px; height: 280px;
    background: radial-gradient(circle, rgba(212,168,67,0.18), transparent 70%);
    filter: blur(40px);
    pointer-events: none;
}
.it-hero-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.20em;
    color: #8a8a93;
    font-weight: 700;
}
.it-hero-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 72px;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: #e7e7e9;
    line-height: 1.0;
    margin: 8px 0 4px;
    position: relative;
}
.it-hero-unit {
    font-size: 26px;
    color: #5b5b62;
    margin-left: 10px;
    font-weight: 500;
    letter-spacing: 0;
}
.it-hero-subtitle {
    color: #8a8a93;
    font-size: 14px;
    margin-top: 14px;
    max-width: 70ch;
    position: relative;
}

/* Metric card variants — custom HTML used in place of st.metric where space is tight */
.it-mini-metric {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 16px 18px 18px;
    transition: border-color 0.18s;
}
.it-mini-metric:hover { border-color: rgba(212, 168, 67, 0.25); }
.it-mini-metric-label {
    color: #8a8a93;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 10px;
    font-weight: 700;
}
.it-mini-metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
    color: #e7e7e9;
    font-size: 28px;
    line-height: 1.15;
    margin-top: 6px;
    white-space: nowrap;
}
.it-mini-metric-unit {
    font-size: 15px;
    color: #5b5b62;
    margin-left: 5px;
}
.it-mini-metric-sub {
    color: #8a8a93;
    font-size: 11px;
    margin-top: 6px;
    font-family: 'JetBrains Mono', monospace;
}

/* Metric overrides — for regular st.metric usage */
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 18px 22px;
    transition: border-color 0.18s;
}
[data-testid="stMetric"]:hover {
    border-color: rgba(212, 168, 67, 0.25);
}
[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 600;
    color: #e7e7e9 !important;
    font-size: 30px !important;
    line-height: 1.15;
}
[data-testid="stMetricLabel"] {
    color: #8a8a93 !important;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 11px !important;
    font-weight: 700;
}
[data-testid="stMetricDelta"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 11px !important;
}

/* Section title */
.it-section-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.20em;
    color: #8a8a93;
    font-weight: 700;
    margin: 32px 0 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}

/* Badges */
.it-badge {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 20px 16px 16px;
    text-align: center;
    transition: transform 0.18s, border-color 0.18s, box-shadow 0.18s;
    height: 100%;
}
.it-badge:hover { transform: translateY(-2px); }
.it-badge.unlocked {
    border-color: rgba(212, 168, 67, 0.50);
    background: linear-gradient(135deg, rgba(212, 168, 67, 0.10), rgba(212, 168, 67, 0.03));
    box-shadow: 0 6px 28px rgba(212, 168, 67, 0.10);
}
.it-badge.locked { opacity: 0.42; filter: grayscale(0.5); }
.it-badge-icon { font-size: 36px; margin-bottom: 10px; line-height: 1.0; }
.it-badge-name { font-weight: 700; color: #e7e7e9; margin-bottom: 4px; font-size: 13px; }
.it-badge-criteria { color: #8a8a93; font-size: 10.5px; line-height: 1.4; min-height: 28px; }
.it-badge-progress {
    font-family: 'JetBrains Mono', monospace;
    color: #d4a843;
    font-size: 11px;
    margin-top: 10px;
    font-weight: 600;
}
.it-badge.locked .it-badge-progress { color: #8a8a93; }

/* Callouts */
.it-callout {
    border-radius: 14px;
    padding: 16px 22px;
    margin: 12px 0;
    border: 1px solid;
    font-size: 13.5px;
    line-height: 1.55;
}
.it-callout-icon {
    font-size: 18px;
    margin-right: 10px;
    vertical-align: middle;
}
.it-callout.warning {
    background: rgba(232, 90, 79, 0.06);
    border-color: rgba(232, 90, 79, 0.28);
    color: #f4a99f;
}
.it-callout.success {
    background: rgba(93, 199, 124, 0.06);
    border-color: rgba(93, 199, 124, 0.28);
    color: #a6e3b8;
}
.it-callout.info {
    background: rgba(91, 156, 240, 0.06);
    border-color: rgba(91, 156, 240, 0.28);
    color: #a3c4f0;
}
.it-callout.gold {
    background: rgba(212, 168, 67, 0.09);
    border-color: rgba(212, 168, 67, 0.34);
    color: #e6c887;
}

/* Worst-day card */
.it-lowlight {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-left: 3px solid #e85a4f;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 8px 0;
}
.it-lowlight-date {
    font-family: 'JetBrains Mono', monospace;
    color: #8a8a93;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.it-lowlight-title { color: #e7e7e9; font-weight: 600; margin-top: 4px; }
.it-lowlight-caption { color: #f4a99f; font-style: italic; font-size: 13px; margin-top: 6px; }
.it-lowlight-stats {
    font-family: 'JetBrains Mono', monospace;
    color: #8a8a93;
    font-size: 11px;
    margin-top: 8px;
}

/* Headers */
h1, h2, h3, h4 {
    font-family: 'Inter Tight', sans-serif;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #e7e7e9;
}
h1 { font-size: 28px; }
h2 { font-size: 20px; }
h3 { font-size: 15px; color: #b5b5b9; font-weight: 600; }

/* Buttons */
.stButton > button {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    color: #e7e7e9;
    border-radius: 10px;
    font-family: 'Inter Tight', sans-serif;
    font-weight: 600;
    transition: all 0.18s;
}
.stButton > button:hover {
    border-color: #d4a843;
    color: #d4a843;
}

/* Tighter top padding for the main content area */
.block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1280px; }

/* Dataframes get the mono treatment */
[data-testid="stDataFrame"] table { font-family: 'JetBrains Mono', monospace !important; font-size: 12px; }

/* Hide the default Streamlit header chrome */
header { display: none !important; }
#MainMenu { display: none !important; }
footer { display: none !important; }
</style>
"""


def setup_page(title: str, icon: str, *, layout: str = "wide") -> None:
    """Page-config + theme + CSS in one call. Call once at the top of every page."""
    st.set_page_config(page_title=title, page_icon=icon, layout=layout)
    st.markdown(_CSS, unsafe_allow_html=True)


def mini_metric(label: str, value: str, unit: str = "", sub: str = "") -> None:
    """Compact metric card with controlled font sizing — for tight grids."""
    unit_html = f'<span class="it-mini-metric-unit">{unit}</span>' if unit else ""
    sub_html = f'<div class="it-mini-metric-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="it-mini-metric">'
        f'<div class="it-mini-metric-label">{label}</div>'
        f'<div class="it-mini-metric-value">{value}{unit_html}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def hero(label: str, value: str, subtitle: str = "", unit: str = "") -> None:
    unit_html = f'<span class="it-hero-unit">{unit}</span>' if unit else ""
    sub_html = f'<div class="it-hero-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="it-hero">'
        f'<div class="it-hero-label">{label}</div>'
        f'<div class="it-hero-value">{value}{unit_html}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="it-section-title">{text}</div>', unsafe_allow_html=True)


def callout(kind: str, message: str, icon: str = "") -> None:
    icon_html = f'<span class="it-callout-icon">{icon}</span>' if icon else ""
    st.markdown(f'<div class="it-callout {kind}">{icon_html}{message}</div>', unsafe_allow_html=True)


def badge_card(icon: str, name: str, criteria: str, progress_text: str, unlocked: bool) -> None:
    klass = "unlocked" if unlocked else "locked"
    st.markdown(
        f'<div class="it-badge {klass}">'
        f'<div class="it-badge-icon">{icon}</div>'
        f'<div class="it-badge-name">{name}</div>'
        f'<div class="it-badge-criteria">{criteria}</div>'
        f'<div class="it-badge-progress">{progress_text}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def lowlight_card(date_str: str, title: str, caption: str, stats: str) -> None:
    st.markdown(
        f'<div class="it-lowlight">'
        f'<div class="it-lowlight-date">{date_str}</div>'
        f'<div class="it-lowlight-title">{title}</div>'
        f'<div class="it-lowlight-caption">"{caption}"</div>'
        f'<div class="it-lowlight-stats">{stats}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def quote_card(text: str, meta: str = "", kind: str = "default", variants: list[str] | None = None) -> None:
    """Big-quote card for the Quotes page."""
    klass = f"it-quote-card {kind}" if kind != "default" else "it-quote-card"
    variants_html = ""
    if variants:
        chips = "".join(f'<span class="it-quote-variant">{v}</span>' for v in variants)
        variants_html = f'<div class="it-quote-variants">{chips}</div>'
    meta_html = f'<div class="it-quote-meta">{meta}</div>' if meta else ""
    # Escape doublequotes in text to avoid breaking the markup
    safe_text = text.replace('"', '&quot;')
    st.markdown(
        f'<div class="{klass}">'
        f'<div class="it-quote-text">"{safe_text}"</div>'
        f"{variants_html}"
        f"{meta_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def sparkline(values: Iterable[float], color: str | None = None, height: int = 56) -> go.Figure:
    color = color or theme.COLORS["accent_gold"]
    vals = list(values)
    fillcolor = (
        "rgba(212, 168, 67, 0.16)" if color == theme.COLORS["accent_gold"]
        else "rgba(91, 156, 240, 0.14)"
    )
    fig = go.Figure(
        go.Scatter(
            y=vals,
            mode="lines",
            line=dict(color=color, width=2.2, shape="spline", smoothing=0.6),
            fill="tozeroy",
            fillcolor=fillcolor,
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=height,
        xaxis_visible=False,
        yaxis_visible=False,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
