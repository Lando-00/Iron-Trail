"""Achievements — full badge wall with unlocked + locked + progress."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from iron_trail import analytics, config, sidebar, ui

ui.setup_page("Achievements · IronTrail", "🏆")


with st.sidebar:
    df, _, body_weight = sidebar.render_data_source()

st.title("🏆 Achievements")

badges = analytics.awards_earned(df, body_weight_kg=body_weight)
unlocked = [b for b in badges if b["unlocked"]]
locked = sorted([b for b in badges if not b["unlocked"]], key=lambda b: -b["progress"])

c1, c2, c3 = st.columns(3)
c1.metric("Unlocked", f"{len(unlocked)} / {len(badges)}")
c2.metric("Completion", f"{len(unlocked) / len(badges) * 100:.0f}%")
c3.metric("Total badges", f"{len(badges)}")

if locked:
    ui.callout(
        "gold",
        f"<strong>Closest to unlock:</strong> {locked[0]['icon']} {locked[0]['name']} — "
        f"{locked[0]['current_str']} / {locked[0]['target_str']} ({locked[0]['progress']*100:.0f}% there)",
    )

# =====================================================================
# Unlocked
# =====================================================================
ui.section_title(f"✓ Unlocked ({len(unlocked)})")

if not unlocked:
    st.caption("Get to work.")
else:
    rows = [unlocked[i:i + 4] for i in range(0, len(unlocked), 4)]
    for row in rows:
        cols = st.columns(4)
        for col, b in zip(cols, row):
            with col:
                progress = f"{b['current_str']} / {b['target_str']}"
                ui.badge_card(b["icon"], b["name"], b["criteria"], progress, unlocked=True)

# =====================================================================
# Locked
# =====================================================================
ui.section_title(f"🔒 Locked ({len(locked)})")

if not locked:
    st.caption("Wall complete. Build more badges or go outside.")
else:
    rows = [locked[i:i + 4] for i in range(0, len(locked), 4)]
    for row in rows:
        cols = st.columns(4)
        for col, b in zip(cols, row):
            with col:
                progress = f"{b['current_str']} / {b['target_str']} · {b['progress']*100:.0f}%"
                ui.badge_card(b["icon"], b["name"], b["criteria"], progress, unlocked=False)
