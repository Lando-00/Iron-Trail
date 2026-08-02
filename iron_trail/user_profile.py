"""Durable per-user settings that outlive a single Streamlit session.

Bodyweight drives load substitution for bodyweight/assisted exercises and every
BW-relative badge, so it has to survive page navigation and sign-out. In cloud
mode it lives beside the user's dataset metadata; locally it is a small JSON
file under ``data/processed/`` (already git-ignored).
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config

logger = logging.getLogger("iron_trail.user_profile")

MIN_BODY_WEIGHT_KG = 30.0
MAX_BODY_WEIGHT_KG = 300.0


class ProfileError(ValueError):
    """Raised when a profile value is outside the accepted range."""


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    body_weight_kg: float
    updated_at: datetime


def normalize_body_weight(value: object) -> float:
    """Coerce a bodyweight to a stored value, rejecting absurd input."""
    try:
        weight = round(float(value), 1)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ProfileError("Bodyweight must be a number.") from exc
    if not math.isfinite(weight):
        raise ProfileError("Bodyweight must be a real number.")
    if not MIN_BODY_WEIGHT_KG <= weight <= MAX_BODY_WEIGHT_KG:
        raise ProfileError(
            f"Bodyweight must be between {MIN_BODY_WEIGHT_KG:.0f} and "
            f"{MAX_BODY_WEIGHT_KG:.0f} kg."
        )
    return weight


def default_body_weight() -> float:
    return normalize_body_weight(config.BODY_WEIGHT_KG)


def load_local_body_weight(path: Path | None = None) -> float:
    """Read the locally saved bodyweight, falling back to the config default."""
    target = Path(path) if path is not None else config.PROFILE_JSON
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return normalize_body_weight(payload["body_weight_kg"])
    except FileNotFoundError:
        return default_body_weight()
    except (OSError, ValueError, TypeError, KeyError):
        logger.warning("Ignoring unreadable local profile at %s", target, exc_info=True)
        return default_body_weight()


def save_local_body_weight(value: object, path: Path | None = None) -> float:
    """Write the bodyweight atomically so a crash cannot truncate the file."""
    weight = normalize_body_weight(value)
    target = Path(path) if path is not None else config.PROFILE_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.tmp")
    temp.write_text(json.dumps({"body_weight_kg": weight}, indent=2), encoding="utf-8")
    temp.replace(target)
    return weight
