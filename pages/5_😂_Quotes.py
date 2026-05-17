"""Quotes Wall — surface the funniest things the user has actually logged.

A celebration of indecisive naming, single-word laments, self-deprecating
commentary, and emoji-forward energy that shows up in real workout titles.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from iron_trail import comedy, config, sidebar, ui

ui.setup_page("Quotes · IronTrail", "😂")


with st.sidebar:
    df, _, body_weight = sidebar.render_data_source()

st.title("😂 The Quotes Wall")
st.caption(
    "Every workout title you've ever logged, sorted into receipts. "
    "The funniest comedian in your training history is you."
)

result = comedy.funny_titles(df)

c1, c2, c3 = st.columns(3)
with c1:
    ui.mini_metric("Total sessions", f"{result['total_sessions']:,}")
with c2:
    ui.mini_metric("Unique titles", f"{result['unique_titles']:,}")
with c3:
    ui.mini_metric("Variant clusters", f"{len(result['indecisive_clusters']):,}")

# =====================================================================
# 1. INDECISIVE NAMING
# =====================================================================

ui.section_title("📛 You couldn't decide on a name")

if not result["indecisive_clusters"]:
    st.caption("Impressively consistent naming. Suspicious.")
else:
    st.markdown(
        "<div style='color:#8a8a93; font-size:13px; margin-bottom:8px;'>"
        "Same workout, different capitalization, every time. The receipts:"
        "</div>",
        unsafe_allow_html=True,
    )
    for cluster in result["indecisive_clusters"][:10]:
        variants = cluster["variants"]
        meta = f"{cluster['session_count']} sessions · {cluster['variant_count']} variations"
        # Use the most common form as the headline
        ui.quote_card(
            text=f"{cluster['variant_count']} ways to spell the same workout",
            meta=meta,
            kind="cluster",
            variants=variants,
        )

# =====================================================================
# 2. EMOTIONAL TITLES
# =====================================================================

ui.section_title("🆘 The cry for help")

emo = result["emotional_titles"]
if not emo:
    st.caption("No emotional one-word titles. Either you're stoic or you don't title your bad days.")
else:
    st.markdown(
        "<div style='color:#8a8a93; font-size:13px; margin-bottom:8px;'>"
        "Single words that say everything:"
        "</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for i, t in enumerate(emo[:14]):
        with cols[i % 2]:
            meta = f"{t['count']} × logged" if t['count'] > 1 else "once was enough"
            ui.quote_card(text=t["title"], meta=meta, kind="emotional")

# =====================================================================
# 3. SELF-ROASTING
# =====================================================================

ui.section_title("🪞 The self-roast")

roasts = result["self_roasting"]
if not roasts:
    st.caption("You're either too proud or too sad. Probably the latter.")
else:
    st.markdown(
        "<div style='color:#8a8a93; font-size:13px; margin-bottom:8px;'>"
        "Long descriptive titles, questions, and unsolicited commentary:"
        "</div>",
        unsafe_allow_html=True,
    )
    for t in roasts[:16]:
        meta = f"{t['count']} × logged" if t['count'] > 1 else ""
        ui.quote_card(text=t["title"], meta=meta, kind="roast")

# =====================================================================
# 4. EMOJI ENERGY
# =====================================================================

ui.section_title("🫡 Emoji-forward communication")

emojis = result["emoji_heavy"]
if not emojis:
    st.caption("Refreshingly emoji-free. Or your terminal can't render them.")
else:
    st.markdown(
        "<div style='color:#8a8a93; font-size:13px; margin-bottom:8px;'>"
        "When words aren't enough:"
        "</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for i, t in enumerate(emojis[:12]):
        with cols[i % 2]:
            meta = f"{t['session_count']} × logged" if t['session_count'] > 1 else "lone outburst"
            ui.quote_card(text=t["title"], meta=meta, kind="emoji")

# =====================================================================
# Closing tag
# =====================================================================

st.divider()
st.markdown(
    f"<div style='text-align:center; color:#5b5b62; font-size:12px; "
    f"font-family: JetBrains Mono, monospace; margin-top:24px;'>"
    f"{result['unique_titles']} unique titles · {result['total_sessions']} sessions · "
    f"~{result['total_sessions'] / max(result['unique_titles'], 1):.1f} sessions per title<br>"
    f"the funniest one is whichever one you just logged."
    f"</div>",
    unsafe_allow_html=True,
)
