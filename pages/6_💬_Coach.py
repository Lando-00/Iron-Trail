"""Coach — the AI Training Coach.

Generates weekly + monthly LLM-written reviews and offers an "ask your
data" chat. Reviews live inside the dashboard; exporting them to your
Obsidian vault (or downloading as Markdown / PDF) is one click away.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from iron_trail import auth, runtime, sidebar, ui
from iron_trail.coach import prompts, render, summary
from iron_trail.coach.export.vault import save_monthly_review, save_weekly_review
from iron_trail.coach.providers import Message
from iron_trail.coach.providers.mock import MockProvider
from iron_trail.usage_limits import (
    CallKind,
    LimitedProvider,
    UsageLimiter,
    UsageLimitExceeded,
    UsageRepositoryError,
    get_usage_repository,
)

ui.setup_page("Coach · IronTrail", "💬")
logger = logging.getLogger(__name__)


with st.sidebar:
    df, source_label, body_weight = sidebar.render_data_source()


@st.cache_resource(show_spinner=False)
def _get_copilot_provider():
    # Cached so the Copilot CLI server isn't re-spawned on every Streamlit rerun.
    from iron_trail.coach.providers.copilot import CopilotProvider

    return CopilotProvider()


@st.cache_resource(show_spinner=False)
def _get_foundry_provider():
    from iron_trail.coach.providers.azure_foundry import AzureFoundryProvider

    return AzureFoundryProvider()


@st.cache_resource(show_spinner=False)
def _get_usage_limiter():
    return UsageLimiter(get_usage_repository())


def get_provider(kind: CallKind):
    if runtime.is_cloud():
        return LimitedProvider(
            _get_foundry_provider(),
            _get_usage_limiter(),
            auth.current_user().user_id,
            kind,
        )
    if os.environ.get("COACH_LLM", "").lower() == "mock":
        return MockProvider()
    return _get_copilot_provider()


def call_coach(messages: list[Message], kind: CallKind, timeout: float) -> str:
    try:
        return get_provider(kind).chat(messages, timeout=timeout)
    except UsageLimitExceeded as exc:
        st.warning(str(exc))
    except UsageRepositoryError:
        logger.exception("Coach usage ledger failed")
        st.error("The hosted Coach could not verify its usage allowance.")
    except Exception as exc:
        logger.exception("Coach provider call failed")
        if runtime.is_cloud():
            st.error("The hosted Coach is temporarily unavailable.")
        else:
            st.error(f"Coach call failed: {exc}")
    st.stop()


# Personality dropdown
PERSONALITIES = list(prompts.PERSONALITY_LABELS.keys())
if "coach_personality" not in st.session_state:
    st.session_state["coach_personality"] = "default"

st.title("💬 Coach")
st.caption(
    "AI-written training reviews and an 'ask your data' chat — "
    "all backed by your loaded Hevy data, powered by "
    f"{'Microsoft Foundry' if runtime.is_cloud() else 'Copilot'}."
)

header_l, header_r = st.columns([3, 1])
with header_r:
    personality = st.selectbox(
        "Personality",
        PERSONALITIES,
        index=PERSONALITIES.index(st.session_state["coach_personality"]),
        format_func=lambda k: prompts.PERSONALITY_LABELS[k],
        key="coach_personality_picker",
    )
    if personality != st.session_state["coach_personality"]:
        st.session_state["coach_personality"] = personality

tabs = st.tabs(["📅 Weekly", "🗓️ Monthly", "💬 Ask Your Data", "🎭 Settings"])

# =====================================================================
# WEEKLY TAB
# =====================================================================
with tabs[0]:
    ctrl_l, ctrl_r = st.columns([3, 1])
    with ctrl_l:
        default_week = summary.last_complete_week()
        st.markdown(
            f"**Target week:** `{default_week.label}` "
            f"({default_week.week_start} → {default_week.week_end})"
        )
        st.caption(
            "Defaults to the last complete ISO week. The current week becomes "
            "the target on Mondays."
        )
    with ctrl_r:
        gen_weekly = st.button("Generate weekly review", type="primary",
                               use_container_width=True, key="gen_weekly")

    if gen_weekly:
        with st.spinner("Building summary…"):
            week_summary = summary.build_weekly(df, default_week)
        with st.spinner("Asking the coach…"):
            prompt = prompts.weekly_review_prompt(
                week_summary, personality=st.session_state["coach_personality"]
            )
            body = call_coach(
                [Message(role="system", content=prompt)],
                CallKind.REVIEW,
                180.0,
            )
        md = render.weekly_review_md(
            week_summary, body,
            personality=st.session_state["coach_personality"],
        )
        st.session_state["coach_weekly_md"] = md
        st.session_state["coach_weekly_label"] = default_week.label

    # Render the most recent review (if any) so it survives reruns
    md = st.session_state.get("coach_weekly_md")
    label = st.session_state.get("coach_weekly_label")
    if md:
        # Strip frontmatter for display — it's only useful in the saved file
        display_md = md
        if display_md.startswith("---"):
            end = display_md.find("\n---", 3)
            if end != -1:
                display_md = display_md[end + 4 :].lstrip()
        st.markdown('<div class="it-review-card">', unsafe_allow_html=True)
        st.markdown(display_md, unsafe_allow_html=False)
        st.markdown("</div>", unsafe_allow_html=True)

        ui.section_title("Export")
        if runtime.is_cloud():
            ec2, ec3, ec4 = st.columns(3)
        else:
            ec1, ec2, ec3, ec4 = st.columns([2, 1, 1, 1])
            with ec1:
                vault_path = st.text_input(
                    "Vault path",
                    value="vault-output",
                    key="coach_vault_path",
                    help="Saves to <vault>/Hevy/Reviews/YYYY-Www.md",
                )
                if st.button(
                    "💾 Save to Vault",
                    use_container_width=True,
                    key="save_weekly_vault",
                ):
                    try:
                        out = save_weekly_review(md, Path(vault_path), label)
                        st.success(f"✓ Saved → `{out}`")
                    except OSError as exc:
                        st.error(f"Save failed: {exc}")
        with ec2:
            st.download_button(
                "⬇️ .md",
                data=md.encode("utf-8"),
                file_name=f"{label}.md",
                mime="text/markdown",
                use_container_width=True,
                key="dl_weekly_md",
            )
        with ec3:
            try:
                from iron_trail.coach.export.pdf import markdown_to_pdf

                pdf_bytes = markdown_to_pdf(md, title=f"Weekly Review · {label}")
                st.download_button(
                    "📄 PDF",
                    data=pdf_bytes,
                    file_name=f"{label}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_weekly_pdf",
                )
            except Exception as e:
                st.button("📄 PDF (n/a)", disabled=True, use_container_width=True,
                          help=f"PDF export unavailable: {e}", key="dl_weekly_pdf_disabled")
        with ec4:
            with st.popover("📋 Copy"):
                st.code(md, language="markdown")
    else:
        st.markdown(
            '<div class="it-coach-empty">Click <b>Generate weekly review</b> '
            'to ask the coach about this week\'s training.</div>',
            unsafe_allow_html=True,
        )

# =====================================================================
# MONTHLY TAB
# =====================================================================
with tabs[1]:
    ctrl_l, ctrl_r = st.columns([3, 1])
    with ctrl_l:
        # Default: last complete month
        today = date.today()
        first_of_this = today.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        default_month = summary.MonthRange.from_end(last_of_prev)
        st.markdown(
            f"**Target month:** `{default_month.label}` "
            f"({default_month.month_start} → {default_month.month_end})"
        )
    with ctrl_r:
        gen_monthly = st.button("Generate monthly recap", type="primary",
                                use_container_width=True, key="gen_monthly")

    if gen_monthly:
        with st.spinner("Building summary…"):
            month_summary = summary.build_monthly(df, default_month)
        with st.spinner("Asking the coach…"):
            prompt = prompts.monthly_review_prompt(
                month_summary, personality=st.session_state["coach_personality"]
            )
            body = call_coach(
                [Message(role="system", content=prompt)],
                CallKind.REVIEW,
                240.0,
            )
        md = render.monthly_review_md(
            month_summary, body,
            personality=st.session_state["coach_personality"],
        )
        st.session_state["coach_monthly_md"] = md
        st.session_state["coach_monthly_label"] = default_month.label

    md = st.session_state.get("coach_monthly_md")
    label = st.session_state.get("coach_monthly_label")
    if md:
        display_md = md
        if display_md.startswith("---"):
            end = display_md.find("\n---", 3)
            if end != -1:
                display_md = display_md[end + 4 :].lstrip()
        st.markdown('<div class="it-review-card">', unsafe_allow_html=True)
        st.markdown(display_md, unsafe_allow_html=False)
        st.markdown("</div>", unsafe_allow_html=True)

        ui.section_title("Export")
        if runtime.is_cloud():
            ec2, ec3, ec4 = st.columns(3)
        else:
            ec1, ec2, ec3, ec4 = st.columns([2, 1, 1, 1])
            with ec1:
                vault_path = st.text_input(
                    "Vault path",
                    value="vault-output",
                    key="coach_monthly_vault_path",
                )
                if st.button(
                    "💾 Save to Vault",
                    use_container_width=True,
                    key="save_monthly_vault",
                ):
                    try:
                        out = save_monthly_review(md, Path(vault_path), label)
                        st.success(f"✓ Saved → `{out}`")
                    except OSError as exc:
                        st.error(f"Save failed: {exc}")
        with ec2:
            st.download_button(
                "⬇️ .md",
                data=md.encode("utf-8"),
                file_name=f"{label}.md",
                mime="text/markdown",
                use_container_width=True,
                key="dl_monthly_md",
            )
        with ec3:
            try:
                from iron_trail.coach.export.pdf import markdown_to_pdf

                pdf_bytes = markdown_to_pdf(md, title=f"Monthly Recap · {label}")
                st.download_button(
                    "📄 PDF",
                    data=pdf_bytes,
                    file_name=f"{label}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_monthly_pdf",
                )
            except Exception:
                st.button("📄 PDF (n/a)", disabled=True, use_container_width=True,
                          key="dl_monthly_pdf_disabled")
        with ec4:
            with st.popover("📋 Copy"):
                st.code(md, language="markdown")
    else:
        st.markdown(
            '<div class="it-coach-empty">Click <b>Generate monthly recap</b> '
            'for a deeper retrospective with strength trajectories.</div>',
            unsafe_allow_html=True,
        )

# =====================================================================
# ASK YOUR DATA TAB
# =====================================================================
with tabs[2]:
    from iron_trail.coach import chat as coach_chat

    st.caption(
        "Conversational interface scoped to your data. The coach only knows "
        "what's in the loaded CSV — it'll say so if you ask about something "
        "outside that scope."
    )

    if "coach_chat_history" not in st.session_state:
        st.session_state["coach_chat_history"] = []

    c1, c2 = st.columns([4, 1])
    with c2:
        if st.button("🧹 Clear chat", use_container_width=True):
            st.session_state["coach_chat_history"] = []
            st.rerun()

    # Render history
    for role, content in st.session_state["coach_chat_history"]:
        with st.chat_message(role):
            st.markdown(content)

    user_input = st.chat_input("Ask the coach about your training…")
    if user_input:
        st.session_state["coach_chat_history"].append(("user", user_input))
        with st.chat_message("user"):
            st.markdown(user_input)

        ctx = coach_chat.build_chat_context(df)
        messages = coach_chat.build_chat_messages(
            history=st.session_state["coach_chat_history"][:-1],  # exclude the just-added user message
            user_input=user_input,
            context=ctx,
            personality=st.session_state["coach_personality"],
        )
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                reply = call_coach(messages, CallKind.CHAT, 180.0)
            st.markdown(reply)
        st.session_state["coach_chat_history"].append(("assistant", reply))

# =====================================================================
# SETTINGS TAB
# =====================================================================
with tabs[3]:
    st.markdown("### Personality")
    st.caption(
        "Pick the voice the coach should write in. The factual contract is "
        "identical across all five — only the tone shifts."
    )
    for key, label in prompts.PERSONALITY_LABELS.items():
        st.markdown(f"- **{label}** (`{key}`)")

    st.divider()
    st.markdown("### Provider")
    if runtime.is_cloud():
        deployment = os.environ.get("IRONTRAIL_AZURE_OPENAI_DEPLOYMENT", "not configured")
        st.success(f"Using **Microsoft Foundry** deployment `{deployment}`.")
        try:
            usage = _get_usage_limiter().snapshot(auth.current_user().user_id)
        except UsageRepositoryError:
            st.warning("Usage counters are temporarily unavailable.")
        else:
            st.markdown(
                f"- Reviews today/month: **{usage.review_daily} / {usage.review_monthly}**\n"
                f"- Chat calls today/month: **{usage.chat_daily} / {usage.chat_monthly}**\n"
                f"- Estimated global AI spend this month: "
                f"**€{usage.global_monthly_cost_eur:.4f}**"
            )
    else:
        provider_name = os.environ.get("COACH_LLM", "real")
        if provider_name == "mock":
            st.warning(
                "Currently using the **MOCK** provider "
                "(set `COACH_LLM=real` to use Copilot)."
            )
        else:
            st.success("Using the **Copilot SDK** via your Copilot subscription.")
        st.caption(
            "Set `COACH_LLM=mock` before launching Streamlit to develop without "
            "using Copilot. The mock returns a deterministic response."
        )

    st.divider()
    st.markdown("### Data source")
    st.markdown(f"- **Loaded CSV:** `{source_label}`")
    st.markdown(f"- **Bodyweight:** {body_weight:.1f} kg")
