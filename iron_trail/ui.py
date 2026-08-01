"""UI helpers: CSS injection, hero block, callouts, badges, sparklines.

All Streamlit pages should call :func:`setup_page` near the top — it
applies the page config, injects the IronTrail CSS, and ensures the
Plotly theme is registered.
"""
from __future__ import annotations

import html
import math
import re
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

/* Tabs — render as a real segmented control. Streamlit's default is small
   grey text that reads like a caption, so whole sections go unnoticed. */
[data-testid="stTabs"] [role="tablist"] {
    gap: 8px;
    flex-wrap: wrap;
    border-bottom: none !important;
    margin-bottom: 8px;
}
[data-testid="stTab"] {
    min-height: 44px;
    padding: 9px 15px !important;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 11px;
    background: rgba(255, 255, 255, 0.028);
    font-weight: 600;
    transition: border-color 0.18s, background 0.18s, color 0.18s;
}
[data-testid="stTab"],
[data-testid="stTab"] * { color: #b9b9c2 !important; }
[data-testid="stTab"]:hover {
    border-color: rgba(212, 168, 67, 0.45);
    background: rgba(255, 255, 255, 0.05);
}
[data-testid="stTab"]:hover * { color: #e7e7e9 !important; }
[data-testid="stTab"][aria-selected="true"] {
    border-color: rgba(212, 168, 67, 0.75);
    background: linear-gradient(135deg, rgba(212, 168, 67, 0.16), rgba(212, 168, 67, 0.05));
    box-shadow: 0 4px 18px rgba(212, 168, 67, 0.12);
}
[data-testid="stTab"][aria-selected="true"] * { color: #d4a843 !important; }
/* Hide the default underline indicator — the pill carries the state now. */
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none !important; }

/* Suggested starter prompts for the Coach chat. */
.it-chat-hint {
    color: #8a8a93;
    font-size: 12.5px;
    margin: 2px 0 8px;
}

/* Hall of Fame highlight card (gold-glow inverse of lowlight) */
.it-highlight {
    background: linear-gradient(135deg, rgba(212, 168, 67, 0.07), rgba(212, 168, 67, 0.015));
    border: 1px solid rgba(212, 168, 67, 0.30);
    border-left: 3px solid #d4a843;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 8px 0;
    box-shadow: 0 4px 18px rgba(212, 168, 67, 0.06);
}
.it-highlight-date {
    font-family: 'JetBrains Mono', monospace;
    color: #d4a843;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 700;
}
.it-highlight-title { color: #e7e7e9; font-weight: 600; margin-top: 4px; }
.it-highlight-caption { color: #e6c887; font-style: italic; font-size: 13px; margin-top: 6px; }
.it-highlight-stats {
    font-family: 'JetBrains Mono', monospace;
    color: #8a8a93;
    font-size: 11px;
    margin-top: 8px;
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
    color: #7d7d86;
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
    color: #7d7d86;
    margin-left: 5px;
}
.it-mini-metric-sub {
    color: #8a8a93;
    font-size: 11px;
    margin-top: 6px;
    font-family: 'JetBrains Mono', monospace;
}

.it-sparkline-wrap {
    height: 56px;
    margin-top: 5px;
}
.it-sparkline {
    display: block;
    height: 100%;
    width: 100%;
}
@media (max-width: 720px) {
    .it-sparkline-wrap {
        height: 42px;
    }
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

/* Chart heights are driven by CSS so one server-rendered figure can be tall on
   desktop and short on a phone. ui.plotly_chart() wraps each chart in a
   container keyed `it-chart-<size>-<name>`, and the figure itself is rendered
   with autosize so Plotly measures this box instead of a hardcoded height. */
[class*="st-key-it-chart-"] [data-testid="stPlotlyChart"] {
    height: var(--it-chart-h, 400px) !important;
}
[class*="st-key-it-chart-xtall"] { --it-chart-h: 460px; }
[class*="st-key-it-chart-tall"] { --it-chart-h: 440px; }
[class*="st-key-it-chart-standard"] { --it-chart-h: 320px; }
[class*="st-key-it-chart-compact"] { --it-chart-h: 260px; }

/* Tighter top padding for the main content area */
.block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1280px; }

/* Dataframes get the mono treatment */
[data-testid="stDataFrame"] table { font-family: 'JetBrains Mono', monospace !important; font-size: 12px; }

/* Strip the Streamlit chrome we don't want, but keep the sidebar toggle.
   The expand-sidebar button lives inside <header>, and Streamlit auto-collapses
   the sidebar on narrow screens — hiding the header outright would strand
   mobile users with no navigation and no uploader. */
header[data-testid="stHeader"] {
    background: transparent !important;
    box-shadow: none !important;
    height: 0 !important;
    min-height: 0 !important;
    pointer-events: none !important;
}
header[data-testid="stHeader"] [data-testid="stToolbar"] { pointer-events: none !important; }
[data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"],
[data-testid="stMainMenu"],
[data-testid="stStatusWidget"],
#MainMenu { display: none !important; }
footer { display: none !important; }

[data-testid="stExpandSidebarButton"] {
    pointer-events: auto !important;
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: fixed !important;
    top: 10px !important;
    left: 12px !important;
    z-index: 1000000 !important;
    gap: 6px !important;
    align-items: center !important;
    padding: 6px 10px !important;
    border: 1px solid rgba(212, 168, 67, 0.55) !important;
    border-radius: 10px !important;
    background: rgba(10, 10, 12, 0.85) !important;
    backdrop-filter: blur(12px);
}
[data-testid="stExpandSidebarButton"]::after {
    content: 'Menu';
    font-family: 'Inter Tight', sans-serif;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #d4a843;
}
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] { color: #d4a843 !important; }

/* ---------------------------------------------------------------
   Mobile. Measured at 390x844: default tap targets were 24-38px
   (below the 44px guideline), the hero number wrapped to two lines,
   and the Plotly modebar was unusable at 24x22.
   --------------------------------------------------------------- */
@media (max-width: 720px) {
    /* Leave room for the floating Menu button where the sidebar starts collapsed. */
    .block-container { padding-top: 4.25rem; }

    [data-testid="stExpandSidebarButton"] {
        min-height: 44px !important;
        padding: 8px 12px !important;
        top: calc(env(safe-area-inset-top, 0px) + 10px) !important;
    }
    [data-testid="stSidebarNavLink"] {
        min-height: 44px !important;
        padding: 10px 14px !important;
        align-items: center !important;
    }
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapseButton"] button {
        min-width: 44px !important;
        min-height: 44px !important;
    }
    .stButton > button,
    [data-testid="stSidebar"] button,
    [data-testid="stDownloadButton"] > button,
    [data-baseweb="select"] > div,
    [data-baseweb="select"] button,
    [data-testid="stNumberInputField"] {
        min-height: 44px !important;
    }

    /* The modebar is too small to hit and overlaps the plot on phones. */
    .modebar-container { display: none !important; }

    /* Desktop chart heights waste most of a 844px-tall viewport. */
    [class*="st-key-it-chart-xtall"] { --it-chart-h: 380px; }
    [class*="st-key-it-chart-tall"] { --it-chart-h: 360px; }
    [class*="st-key-it-chart-standard"] { --it-chart-h: 300px; }
    [class*="st-key-it-chart-compact"] { --it-chart-h: 240px; }

    .it-hero { padding: 24px 22px 22px; border-radius: 16px; }
    .it-hero-value {
        font-size: clamp(40px, 12vw, 72px);
        white-space: nowrap;
        letter-spacing: -0.05em;
    }
    .it-hero-unit { font-size: clamp(16px, 4.8vw, 26px); margin-left: 6px; }
    .it-hero-subtitle { font-size: 13px; max-width: none; }

    .it-review-card { padding: 20px 18px; }
}
</style>
"""


def setup_page(title: str, icon: str, *, layout: str = "wide") -> None:
    """Page-config + theme + CSS in one call. Call once at the top of every page."""
    st.set_page_config(page_title=title, page_icon=icon, layout=layout)
    st.markdown(_CSS, unsafe_allow_html=True)
    from .telemetry import configure_telemetry

    configure_telemetry()
    from .auth import require_invited_user

    require_invited_user()


PLOT_CONFIG = {"displayModeBar": False, "responsive": True}

CHART_SIZES = ("xtall", "tall", "standard", "compact")

# Only override the month-to-year tick band. Day-level ticks (what desktop
# picks) keep Plotly's automatic format, so the desktop axis is untouched while
# a phone shows `Mar '26` (~45px) instead of `Mar 2026` (57.6px measured).
_DATE_TICKFORMATSTOPS = ({"dtickrange": [2419200000, "M12"], "value": "%b '%y"},)


def _is_polar(fig: go.Figure) -> bool:
    return any(getattr(trace, "type", "").endswith("polar") for trace in fig.data)


def _chart_key(size: str, name: str) -> str:
    """Container key whose ``st-key-`` class carries the CSS height token."""
    if size not in CHART_SIZES:
        raise ValueError(f"unknown chart size {size!r}; expected one of {CHART_SIZES}")
    return f"it-chart-{size}-{name}"


def chart_layout(fig: go.Figure, *, date_axis: bool = False) -> go.Figure:
    """Strip the hardcoded height and apply the shared responsive layout."""
    polar = _is_polar(fig)
    has_legend = fig.layout.showlegend is not False and (len(fig.data) > 1 or polar)
    fig.update_layout(
        autosize=True,
        height=None,
        margin={
            "l": 24 if polar else 36,
            "r": 24 if polar else 12,
            "t": 24,
            "b": 64 if has_legend else 40,
        },
        legend={"orientation": "h", "yanchor": "top", "y": -0.24, "x": 0, "xanchor": "left"},
    )
    if not polar:
        fig.update_xaxes(automargin=True)
        fig.update_yaxes(automargin=True)
        if date_axis:
            fig.update_xaxes(tickformatstops=_DATE_TICKFORMATSTOPS)
    return fig


def plotly_chart(fig: go.Figure, name: str, *, size: str = "tall", date_axis: bool = False) -> None:
    """Render ``fig`` with mobile-friendly defaults and a CSS-driven height.

    Streamlit renders server-side and cannot see the viewport, so the figure
    carries no height of its own: ``autosize`` makes Plotly measure the wrapper
    box, whose height comes from ``--it-chart-h`` and flips at the 720px
    breakpoint. Plotly reflows the SVG live on resize.

    ``size`` picks one of :data:`CHART_SIZES`; ``date_axis`` shortens month-level
    tick labels; ``name`` only has to be unique within a page.
    """
    key = _chart_key(size, name)
    chart_layout(fig, date_axis=date_axis)
    with st.container(key=key):
        st.plotly_chart(fig, width="stretch", height="stretch", config=PLOT_CONFIG)


def mini_metric(label: str, value: str, unit: str = "", sub: str = "") -> None:
    """Compact metric card with controlled font sizing — for tight grids."""
    safe_label, safe_value = _escape(label), _escape(value)
    unit_html = f'<span class="it-mini-metric-unit">{_escape(unit)}</span>' if unit else ""
    sub_html = f'<div class="it-mini-metric-sub">{_escape(sub)}</div>' if sub else ""
    st.markdown(
        f'<div class="it-mini-metric">'
        f'<div class="it-mini-metric-label">{safe_label}</div>'
        f'<div class="it-mini-metric-value">{safe_value}{unit_html}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def hero(label: str, value: str, subtitle: str = "", unit: str = "") -> None:
    unit_html = f'<span class="it-hero-unit">{_escape(unit)}</span>' if unit else ""
    sub_html = f'<div class="it-hero-subtitle">{_escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="it-hero">'
        f'<div class="it-hero-label">{_escape(label)}</div>'
        f'<div class="it-hero-value">{_escape(value)}{unit_html}</div>'
        f"{sub_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="it-section-title">{_escape(text)}</div>', unsafe_allow_html=True)


def callout(kind: str, message: str, icon: str = "") -> None:
    safe_kind = kind if kind in {"success", "warning", "info", "gold"} else "info"
    icon_html = f'<span class="it-callout-icon">{_escape(icon)}</span>' if icon else ""
    st.markdown(
        f'<div class="it-callout {safe_kind}">{icon_html}{_escape(message)}</div>',
        unsafe_allow_html=True,
    )


def badge_card(icon: str, name: str, criteria: str, progress_text: str, unlocked: bool) -> None:
    klass = "unlocked" if unlocked else "locked"
    st.markdown(
        f'<div class="it-badge {klass}">'
        f'<div class="it-badge-icon">{_escape(icon)}</div>'
        f'<div class="it-badge-name">{_escape(name)}</div>'
        f'<div class="it-badge-criteria">{_escape(criteria)}</div>'
        f'<div class="it-badge-progress">{_escape(progress_text)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def lowlight_card(date_str: str, title: str, caption: str, stats: str) -> None:
    st.markdown(
        f'<div class="it-lowlight">'
        f'<div class="it-lowlight-date">{_escape(date_str)}</div>'
        f'<div class="it-lowlight-title">{_escape(title)}</div>'
        f'<div class="it-lowlight-caption">"{_escape(caption)}"</div>'
        f'<div class="it-lowlight-stats">{_escape(stats)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def highlight_card(date_str: str, title: str, caption: str, stats: str) -> None:
    """Gold-glow inverse of lowlight_card — for Hall of Fame entries."""
    st.markdown(
        f'<div class="it-highlight">'
        f'<div class="it-highlight-date">{_escape(date_str)}</div>'
        f'<div class="it-highlight-title">{_escape(title)}</div>'
        f'<div class="it-highlight-caption">"{_escape(caption)}"</div>'
        f'<div class="it-highlight-stats">{_escape(stats)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def quote_card(text: str, meta: str = "", kind: str = "default", variants: list[str] | None = None) -> None:
    """Big-quote card for the Quotes page."""
    safe_kind = kind if kind in {"cluster", "emotional", "roast", "emoji"} else "default"
    klass = f"it-quote-card {safe_kind}" if safe_kind != "default" else "it-quote-card"
    variants_html = ""
    if variants:
        chips = "".join(
            f'<span class="it-quote-variant">{_escape(variant)}</span>'
            for variant in variants
        )
        variants_html = f'<div class="it-quote-variants">{chips}</div>'
    meta_html = f'<div class="it-quote-meta">{_escape(meta)}</div>' if meta else ""
    st.markdown(
        f'<div class="{klass}">'
        f'<div class="it-quote-text">"{_escape(text)}"</div>'
        f"{variants_html}"
        f"{meta_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def sparkline_svg(values: Iterable[float], color: str | None = None) -> None:
    """Render a lightweight, module-free sparkline for compact metric cards."""
    st.markdown(
        _sparkline_svg_markup(values, color=color),
        unsafe_allow_html=True,
    )


def _sparkline_svg_markup(values: Iterable[float], color: str | None = None) -> str:
    clean_values = [
        number
        for value in values
        if math.isfinite(number := float(value))
    ]
    if not clean_values:
        return ""

    safe_color = color or theme.COLORS["accent_gold"]
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", safe_color):
        safe_color = theme.COLORS["accent_gold"]

    minimum = min(clean_values)
    maximum = max(clean_values)
    span = maximum - minimum
    if span == 0:
        points = [(0.0, 16.0), (100.0, 16.0)]
    else:
        denominator = max(len(clean_values) - 1, 1)
        points = [
            (
                100 * index / denominator,
                28 - ((value - minimum) / span * 24),
            )
            for index, value in enumerate(clean_values)
        ]
    point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return (
        '<div class="it-sparkline-wrap">'
        '<svg class="it-sparkline" viewBox="0 0 100 32" '
        'preserveAspectRatio="none" role="img" aria-label="Recent trend">'
        f'<polyline points="{point_text}" fill="none" stroke="{safe_color}" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg></div>"
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
