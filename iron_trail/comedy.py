"""Comedy module — captions, title clustering, self-roast detection.

The IronTrail Hall of Shame doesn't work without good captions. This module
gives them organisation: tone-tagged caption pools, a smart picker that
matches caption to session characteristics, and a detector that surfaces
genuinely funny workout titles the user has logged in their own data.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


# =====================================================================
# Caption pool — 50+ across tone categories
# =====================================================================

CAPTIONS_SHORT_SESSION = [
    "you stopped by",
    "the gym was on your way somewhere",
    "this barely qualifies as a stop",
    "the gym was a vibe today, not a verb",
    "punched in, punched out",
    "more of a doorway hug than a workout",
    "you commute longer than this",
    "the locker got more action than the rack",
    "you trained, then remembered you had plans",
    "if blinking were a workout",
]

CAPTIONS_MINIMAL_EFFORT = [
    "calling this a workout would be generous",
    "even your warmups were warmups",
    "a noble attempt at minimal effort",
    "the gym sent a missing-person report",
    "your shadow did more reps",
    "you logged it. that's what counts. apparently.",
    "we'll allow it",
    "another fine entry for the Hall",
    "the bench got more rest than you",
    "a documentary in self-discipline, or its absence",
]

CAPTIONS_LOW_INTENSITY = [
    "your phone weighed more than the bar today",
    "you and the warmup weights had a moment",
    "the dumbbells barely noticed",
    "the kids' weights got worried",
    "those weights are still on cooldown",
    "form check or form pass-through?",
    "you trained — the bar trained you back, gently",
    "the rack offered emotional support",
    "today was about volume. the kind that doesn't count.",
    "the iron remained unmoved",
]

CAPTIONS_SARCASTIC_PRAISE = [
    "history will remember this set… briefly",
    "the trainer pretended not to see you",
    "Iron Trail acknowledges your effort. Loosely.",
    "a victorious lap of the water fountain",
    "you trained, technically",
    "this set is in the witness protection program",
    "a generous interpretation of 'leg day'",
    "you brought the energy of a Sunday at 4pm",
    "future-you remembers this fondly. they shouldn't.",
    "the protein shake worked harder than you",
]


# =====================================================================
# Hall of Fame caption pools — gold-glow side
# =====================================================================

HOF_CAPTIONS_HEAVY = [
    "the bar checked into therapy after this",
    "your shadow asked for an autograph",
    "the rack filed a workers' comp claim",
    "iron trembled and history was written",
    "this set was the lecture, the bar was the student",
    "every plate in the gym felt that",
    "the spotter became a fan",
    "the warmup set was someone else's PR",
    "the bumper plates stopped bouncing out of respect",
    "future-you watches the replay",
]

HOF_CAPTIONS_MARATHON = [
    "you brought a whole anatomy textbook to this one",
    "Iron Trail's stats engine asked for overtime pay",
    "the chalk bucket needs a moment",
    "every muscle group filed for attendance",
    "an honest, sweaty masterpiece",
    "the foam roller refused service tomorrow",
    "the gym staff started a tab",
    "no muscle left unconsulted",
    "your shower will be a religious experience",
    "the rest of the week is a victory lap",
]

HOF_CAPTIONS_ALL_ROUND = [
    "balanced, dignified, devastating",
    "this is the photo on the recruiting poster",
    "the dashboard had to double-check the numbers",
    "your future self is taking notes",
    "a quietly brutal piece of work",
    "the kind of day that justifies the alarm clock",
    "the receipts say 'all of the above'",
    "nothing fancy, just complete",
    "a session that earns its own gold star",
    "you're allowed to feel smug about this one",
]


HOF_CAPTION_POOLS = {
    "heavy": HOF_CAPTIONS_HEAVY,
    "marathon": HOF_CAPTIONS_MARATHON,
    "all_round": HOF_CAPTIONS_ALL_ROUND,
}


def caption_for_hof_session(row: dict | pd.Series, rng: np.random.Generator) -> str:
    """Pick a Hall-of-Fame caption matched to the *kind* of best-day this was.

    ``row["kind"]`` is one of: ``heavy`` (a top-weight day), ``marathon``
    (lots of muscles hit), or ``all_round`` (balanced contributions).
    """
    kind = str(row.get("kind", "all_round"))
    pool = HOF_CAPTION_POOLS.get(kind, HOF_CAPTIONS_ALL_ROUND)
    return str(rng.choice(pool))


CAPTION_POOLS = {
    "short_session": CAPTIONS_SHORT_SESSION,
    "minimal_effort": CAPTIONS_MINIMAL_EFFORT,
    "low_intensity": CAPTIONS_LOW_INTENSITY,
    "sarcastic_praise": CAPTIONS_SARCASTIC_PRAISE,
}


def caption_for_session(row: dict | pd.Series, rng: np.random.Generator) -> str:
    """Pick a caption whose tone matches what made the session bad.

    Thresholds tuned for the typical kg/min/sets shape of bad sessions.
    Falls through to sarcastic_praise when nothing in particular stands out.
    """
    duration = float(row.get("duration_min", 0) or 0)
    volume = float(row.get("total_volume", 0) or 0)
    sets = int(row.get("set_count", 0) or 0)

    if duration > 0 and duration < 25:
        pool = CAPTIONS_SHORT_SESSION
    elif sets < 5:
        pool = CAPTIONS_MINIMAL_EFFORT
    elif volume < 1500:
        pool = CAPTIONS_LOW_INTENSITY
    else:
        pool = CAPTIONS_SARCASTIC_PRAISE

    return str(rng.choice(pool))


# =====================================================================
# Funny-title detector — surface what the user already logged
# =====================================================================

_EMOJI_RE = re.compile(
    r"["
    "\U0001F000-\U0001FFFF"
    "\u2600-\u27BF"
    "\u2300-\u23FF"
    "\u2700-\u27BF"
    "\uFE00-\uFE0F"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)

EMOTIONAL_WORDS = {
    "sad", "tired", "why", "ugh", "rough", "fail", "bad", "dead", "ouch",
    "help", "skip", "barely", "quick", "short", "sleepy", "hungry",
    "regret", "rip", "oof", "yikes", "noooo", "no",
}


def _strip_emoji(s: str) -> str:
    return _EMOJI_RE.sub("", s)


def _normalize_title(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = _strip_emoji(s)
    s = re.sub(r"[^\w\s]", " ", s.lower())  # punctuation → space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _emoji_count(s: object) -> int:
    if not isinstance(s, str):
        return 0
    return sum(len(m) for m in _EMOJI_RE.findall(s))


def _is_emotional(s: str) -> bool:
    if not s:
        return False
    stripped = _strip_emoji(s).strip()
    lower = stripped.lower()
    tokens = re.split(r"[\s\W]+", lower)
    if any(w in EMOTIONAL_WORDS for w in tokens if w):
        return True
    # Single-word laments — "Sad", "Why", "Quick"
    if len(stripped) <= 8 and stripped.lower().split() and stripped.istitle():
        if any(w in EMOTIONAL_WORDS for w in stripped.lower().split()):
            return True
    return False


def _is_self_roasting(s: str) -> bool:
    """Long descriptive titles, questions, exclamations, or commentary."""
    if not isinstance(s, str) or not s:
        return False
    if "?" in s or s.count("!") >= 2:
        return True
    lower = _strip_emoji(s).lower()
    if any(kw in lower for kw in ["why", "barely", "trying", "first time", "lol", "rip", "almost", "nearly"]):
        return True
    word_count = len(_strip_emoji(s).split())
    if word_count >= 5:
        return True
    return False


def funny_titles(df: pd.DataFrame) -> dict[str, Any]:
    """Surface clusters of variants, emotional one-word titles, self-roasts,
    and emoji-heavy titles.
    """
    if df.empty:
        return {
            "indecisive_clusters": [],
            "emotional_titles": [],
            "self_roasting": [],
            "emoji_heavy": [],
            "total_sessions": 0,
            "unique_titles": 0,
        }

    titles = df.drop_duplicates("workout_id")[["title", "workout_id", "workout_date"]].copy()
    titles["title"] = titles["title"].fillna("Untitled").astype(str)
    titles["normalized"] = titles["title"].map(_normalize_title)
    titles["emoji_count"] = titles["title"].map(_emoji_count)

    # 1. Indecisive naming — same normalized form, ≥ 2 distinct surface forms
    by_norm: dict[str, list[str]] = defaultdict(list)
    for _, r in titles.iterrows():
        by_norm[r["normalized"]].append(r["title"])

    indecisive = []
    for norm, variants in by_norm.items():
        unique = sorted(set(variants), key=lambda t: t.lower())
        if len(unique) >= 2 and norm:
            indecisive.append({
                "normalized": norm,
                "variants": unique,
                "session_count": len(variants),
                "variant_count": len(unique),
            })
    indecisive.sort(key=lambda c: (-c["variant_count"], -c["session_count"]))

    # 2. Emotional one-word(ish) titles
    emo_titles = (
        titles[titles["title"].map(_is_emotional)]
        .groupby("title").size().sort_values(ascending=False)
        .reset_index().rename(columns={0: "count"})
    )
    emo_titles.columns = ["title", "count"]
    emotional = emo_titles.to_dict("records")

    # 3. Self-roasts (questions, commentary, long descriptive)
    roast_titles = (
        titles[titles["title"].map(_is_self_roasting)]
        .groupby("title").size().sort_values(ascending=False)
        .reset_index()
    )
    roast_titles.columns = ["title", "count"]
    self_roast = roast_titles.to_dict("records")

    # 4. Emoji-heavy
    emoji_titles = (
        titles[titles["emoji_count"] >= 1]
        .groupby("title")["emoji_count"].agg(["max", "count"]).reset_index()
    )
    emoji_titles = emoji_titles.rename(columns={"max": "emoji_count", "count": "session_count"})
    emoji_titles = emoji_titles.sort_values(["emoji_count", "session_count"], ascending=[False, False])
    emoji_heavy = emoji_titles.to_dict("records")

    return {
        "indecisive_clusters": indecisive,
        "emotional_titles": emotional,
        "self_roasting": self_roast,
        "emoji_heavy": emoji_heavy,
        "total_sessions": int(len(titles)),
        "unique_titles": int(titles["title"].nunique()),
    }
