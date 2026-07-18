"""Private-beta landing page and its cosmetic reveal interaction."""
from __future__ import annotations

import hashlib
import html
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from textwrap import dedent

import streamlit as st

EMOJIS = ("😉", "👀", "🥷", "🚀", "🎆")
CONTROL_KEYS = ("signal", "orbit", "beacon")
REQUIRED_CONTROL_HITS = 5
REVEAL_TIMEOUT = timedelta(minutes=10)
WELCOME_MESSAGE = (
    "Welcome, if you figured this out without being told how to, wow, good job, "
    "but this is the end of the road. If you know what to do, continue with "
    "assigned steps"
)

_STATE_KEY = "beta_reveal_state"
_EMOJI_BUTTON_KEY = "beta_reveal_emoji_button"
_CONTROL_BUTTON_PREFIX = "beta_reveal_control_"
_TARGET_SEED_DOMAIN = "irontrail-private-beta-reveal-v1"

_CONTROL_LABELS = (
    ("signal", "SIGNAL", "✦"),
    ("orbit", "ORBIT", "◈"),
    ("beacon", "BEACON", "◆"),
)

_LANDING_CSS = """
<style>
.stApp {
    background:
        radial-gradient(circle at 50% -10%, rgba(212, 168, 67, 0.13), transparent 34%),
        linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        #07080b;
    background-size: auto, 42px 42px, 42px 42px, auto;
}

[data-testid="stSidebar"],
[data-testid="stSidebarNav"],
[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}

.block-container {
    max-width: 1280px;
}

.it-beta-shell {
    position: relative;
    min-height: 470px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 28px;
    background:
        linear-gradient(145deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.012)),
        rgba(8, 9, 13, 0.88);
    box-shadow:
        0 36px 90px rgba(0, 0, 0, 0.48),
        inset 0 1px rgba(255, 255, 255, 0.05);
    padding: clamp(38px, 7vw, 92px);
}

.it-beta-shell::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
        linear-gradient(115deg, transparent 0 47%, rgba(91, 156, 240, 0.08) 47.2% 47.5%, transparent 47.7%),
        linear-gradient(160deg, transparent 0 71%, rgba(212, 168, 67, 0.08) 71.2% 71.5%, transparent 71.7%);
}

.it-beta-copy {
    position: relative;
    z-index: 2;
    max-width: 860px;
}

.it-beta-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    color: #8c929e;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
}

.it-beta-eyebrow::before {
    content: "";
    width: 34px;
    height: 1px;
    background: #d4a843;
    box-shadow: 0 0 16px rgba(212, 168, 67, 0.75);
}

.it-beta-title {
    margin: 24px 0 16px;
    color: #f4f2eb;
    font-size: clamp(54px, 9vw, 118px);
    font-weight: 800;
    line-height: 0.84;
    letter-spacing: -0.065em;
    text-transform: uppercase;
}

.it-beta-title span {
    display: block;
    color: transparent;
    -webkit-text-stroke: 1px rgba(244, 242, 235, 0.42);
    text-stroke: 1px rgba(244, 242, 235, 0.42);
}

.it-beta-ga {
    margin: 0;
    color: #b8bdc8;
    font-size: clamp(17px, 2.2vw, 25px);
    line-height: 1.45;
}

.it-beta-watch {
    margin-top: 14px;
    color: #d4a843;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}

.it-beta-status {
    position: absolute;
    right: clamp(24px, 5vw, 64px);
    bottom: clamp(24px, 5vw, 56px);
    z-index: 2;
    color: #747b88;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.13em;
    text-align: right;
    text-transform: uppercase;
}

.it-beta-status strong {
    display: block;
    margin-bottom: 5px;
    color: #5dc77c;
    font-size: 12px;
}

.it-beta-fireworks {
    position: absolute;
    inset: 0;
    z-index: 1;
    overflow: hidden;
    pointer-events: none;
}

.it-beta-firework {
    --burst: #d4a843;
    position: absolute;
    left: var(--x);
    top: var(--y);
    width: 4px;
    height: 4px;
    border-radius: 50%;
    box-shadow:
        0 -34px var(--burst),
        24px -24px var(--burst),
        34px 0 var(--burst),
        24px 24px var(--burst),
        0 34px var(--burst),
        -24px 24px var(--burst),
        -34px 0 var(--burst),
        -24px -24px var(--burst);
    animation: it-beta-burst 4.8s ease-out infinite;
    animation-delay: var(--delay);
    opacity: 0;
}

.it-beta-firework.blue { --burst: #5b9cf0; }
.it-beta-firework.green { --burst: #5dc77c; }
.it-beta-firework.ember { --burst: #e8794a; }

@keyframes it-beta-burst {
    0%, 60% { opacity: 0; transform: scale(0.1) rotate(0deg); }
    66% { opacity: 0.9; transform: scale(0.25) rotate(8deg); }
    82% { opacity: 0.75; transform: scale(1) rotate(22deg); }
    100% { opacity: 0; transform: scale(1.45) rotate(32deg); }
}

.st-key-beta-emoji-stage {
    margin: 28px auto 6px;
    max-width: 220px;
}

.st-key-beta-emoji-stage [data-testid="stButton"] {
    display: flex;
    justify-content: center;
}

.st-key-beta-emoji-stage button {
    width: 132px !important;
    height: 132px !important;
    border: 1px solid rgba(212, 168, 67, 0.38) !important;
    border-radius: 50% !important;
    background:
        radial-gradient(circle at 35% 25%, rgba(255, 255, 255, 0.13), transparent 35%),
        rgba(15, 16, 22, 0.94) !important;
    box-shadow:
        0 0 0 10px rgba(212, 168, 67, 0.035),
        0 20px 55px rgba(0, 0, 0, 0.42) !important;
    color: #ffffff !important;
    font-size: 58px !important;
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease !important;
}

.st-key-beta-emoji-stage button:hover {
    transform: translateY(-4px) rotate(-3deg);
    border-color: #d4a843 !important;
    box-shadow:
        0 0 0 10px rgba(212, 168, 67, 0.06),
        0 24px 70px rgba(0, 0, 0, 0.5),
        0 0 42px rgba(212, 168, 67, 0.18) !important;
}

.it-beta-instruction {
    color: #6f7580;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    letter-spacing: 0.12em;
    text-align: center;
    text-transform: uppercase;
}

.st-key-beta-signal-stage {
    max-width: 620px;
    margin: 24px auto 0;
}

.st-key-beta-signal-stage button {
    min-height: 48px;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 999px !important;
    background: rgba(255, 255, 255, 0.018) !important;
    color: #737a86 !important;
    font-family: "JetBrains Mono", monospace !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.14em !important;
}

.st-key-beta-signal-stage button:hover {
    border-color: rgba(91, 156, 240, 0.45) !important;
    color: #a9c8f4 !important;
    background: rgba(91, 156, 240, 0.055) !important;
}

.it-beta-access {
    max-width: 780px;
    margin: 34px auto 0;
    padding: 26px 28px 28px;
    border: 1px solid rgba(93, 199, 124, 0.26);
    border-radius: 18px;
    background:
        linear-gradient(135deg, rgba(93, 199, 124, 0.08), rgba(91, 156, 240, 0.035)),
        rgba(10, 12, 16, 0.88);
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.34);
}

.it-beta-access-label {
    color: #5dc77c;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}

.it-beta-access-message {
    margin: 12px 0 22px;
    color: #d9dde5;
    font-size: 15px;
    line-height: 1.65;
}

.it-beta-login {
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    min-width: 250px;
    gap: 36px;
    padding: 13px 17px;
    border: 1px solid rgba(212, 168, 67, 0.42);
    border-radius: 11px;
    background: #d4a843;
    color: #0a0b0e !important;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-decoration: none !important;
    text-transform: uppercase;
}

.it-beta-login:hover {
    background: #e5bd5d;
    border-color: #e5bd5d;
    color: #0a0b0e !important;
    transform: translateY(-1px);
}

.it-beta-access-note {
    margin-top: 14px;
    color: #777e89;
    font-size: 11px;
}

@media (max-width: 720px) {
    .it-beta-shell { min-height: 520px; padding: 34px 24px 100px; }
    .it-beta-title { font-size: clamp(48px, 17vw, 78px); }
    .it-beta-status { left: 24px; right: auto; text-align: left; }
    .st-key-beta-signal-stage button { letter-spacing: 0.06em !important; }
}

@media (prefers-reduced-motion: reduce) {
    .it-beta-firework { animation: none !important; opacity: 0.28; transform: scale(0.55); }
    .st-key-beta-emoji-stage button { transition: none !important; }
    .st-key-beta-emoji-stage button:hover { transform: none; }
    .it-beta-login:hover { transform: none; }
}
</style>
"""

_FIREWORKS_HTML = """
<div class="it-beta-fireworks" aria-hidden="true">
  <span class="it-beta-firework" style="--x:14%;--y:24%;--delay:-0.4s"></span>
  <span class="it-beta-firework blue" style="--x:84%;--y:20%;--delay:-2.2s"></span>
  <span class="it-beta-firework green" style="--x:72%;--y:68%;--delay:-3.5s"></span>
  <span class="it-beta-firework ember" style="--x:30%;--y:78%;--delay:-1.5s"></span>
  <span class="it-beta-firework blue" style="--x:54%;--y:18%;--delay:-4.1s"></span>
</div>
"""


@dataclass(frozen=True)
class RevealTarget:
    emoji_index: int
    control_key: str


@dataclass(frozen=True)
class RevealState:
    emoji_index: int = 0
    control_hits: int = 0
    revealed: bool = False
    updated_at: datetime | None = None


def resolve_target(environ: Mapping[str, str] | None = None) -> RevealTarget:
    """Derive the private target without exposing it in client-rendered markup."""
    env = environ or os.environ
    seed = env.get("IRONTRAIL_BETA_REVEAL_SEED", "").strip()
    if not seed:
        seed = env.get("IRONTRAIL_OWNER_OBJECT_ID", "").strip()
    if not seed:
        seed = "irontrail-local-preview"
    digest = hashlib.sha256(f"{_TARGET_SEED_DOMAIN}:{seed}".encode("utf-8")).digest()
    return RevealTarget(
        emoji_index=digest[0] % len(EMOJIS),
        control_key=CONTROL_KEYS[digest[1] % len(CONTROL_KEYS)],
    )


def normalize_state(
    state: RevealState,
    now: datetime,
    *,
    timeout: timedelta = REVEAL_TIMEOUT,
) -> RevealState:
    if state.updated_at is not None and now - state.updated_at > timeout:
        return RevealState()
    return state


def cycle_emoji(state: RevealState, now: datetime) -> RevealState:
    state = normalize_state(state, now)
    return RevealState(
        emoji_index=(state.emoji_index + 1) % len(EMOJIS),
        control_hits=0,
        revealed=state.revealed,
        updated_at=now,
    )


def activate_control(
    state: RevealState,
    control_key: str,
    target: RevealTarget,
    now: datetime,
) -> RevealState:
    state = normalize_state(state, now)
    if state.revealed:
        return state
    correct = (
        state.emoji_index == target.emoji_index
        and control_key == target.control_key
    )
    hits = state.control_hits + 1 if correct else 0
    return RevealState(
        emoji_index=state.emoji_index,
        control_hits=hits,
        revealed=hits >= REQUIRED_CONTROL_HITS,
        updated_at=now,
    )


def reset_session_state(
    session_state: MutableMapping[str, object] | None = None,
) -> None:
    state = session_state if session_state is not None else st.session_state
    state.pop(_STATE_KEY, None)
    state.pop(_EMOJI_BUTTON_KEY, None)
    for control_key in CONTROL_KEYS:
        state.pop(f"{_CONTROL_BUTTON_PREFIX}{control_key}", None)


def render_login(providers: tuple[str, ...]) -> None:
    st.html(_LANDING_CSS)
    hero_html = (
        '<section class="it-beta-shell">'
        f"{_FIREWORKS_HTML}"
        '<div class="it-beta-copy">'
        '<div class="it-beta-eyebrow">IronTrail // Early access channel</div>'
        '<div class="it-beta-title">Private Beta<span>in Progress</span></div>'
        '<p class="it-beta-ga">GA will be coming soon.</p>'
        '<div class="it-beta-watch">Keep an Eye out</div>'
        "</div>"
        '<div class="it-beta-status">'
        "<strong>● Systems nominal</strong>"
        "One assigned operator<br>Public launch pending"
        "</div>"
        "</section>"
    )
    st.html(hero_html)

    now = datetime.now(UTC)
    target = resolve_target()
    stored = st.session_state.get(_STATE_KEY)
    state = stored if isinstance(stored, RevealState) else RevealState()
    state = normalize_state(state, now)
    st.session_state[_STATE_KEY] = state

    with st.container(key="beta-emoji-stage"):
        if st.button(
            EMOJIS[state.emoji_index],
            key=_EMOJI_BUTTON_KEY,
            help="Keep an eye out. This dial changes every time.",
        ):
            st.session_state[_STATE_KEY] = cycle_emoji(state, now)
            st.rerun()

    st.html(
        '<div class="it-beta-instruction">'
        "Early access is assigned, not requested"
        "</div>"
    )

    with st.container(key="beta-signal-stage"):
        columns = st.columns(len(_CONTROL_LABELS))
        for column, (control_key, label, glyph) in zip(
            columns,
            _CONTROL_LABELS,
            strict=True,
        ):
            with column:
                if st.button(
                    f"{glyph} {label}",
                    key=f"{_CONTROL_BUTTON_PREFIX}{control_key}",
                    use_container_width=True,
                    help=f"{label.title()} status control",
                ):
                    st.session_state[_STATE_KEY] = activate_control(
                        state,
                        control_key,
                        target,
                        now,
                    )
                    st.rerun()

    current = st.session_state[_STATE_KEY]
    if isinstance(current, RevealState) and current.revealed:
        _render_access_panel(providers)


def _render_access_panel(providers: tuple[str, ...]) -> None:
    links: list[str] = []
    if "aad" in providers:
        links.append(
            '<a class="it-beta-login" '
            'href="/.auth/login/aad?post_login_redirect_uri=/">'
            "<span>Continue with Microsoft</span><span>↗</span></a>"
        )
    if "google" in providers:
        links.append(
            '<a class="it-beta-login" '
            'href="/.auth/login/google?post_login_redirect_uri=/">'
            "<span>Continue with Google</span><span>↗</span></a>"
        )
    st.html(
        dedent(
            f"""
        <section class="it-beta-access">
          <div class="it-beta-access-label">Access channel discovered</div>
          <div class="it-beta-access-message">{html.escape(WELCOME_MESSAGE)}</div>
          {''.join(links)}
          <div class="it-beta-access-note">
            Approved identities continue through secure authentication. A
            one-time beta code is requested after sign-in only when assigned.
          </div>
        </section>
        """
        ).strip()
    )
