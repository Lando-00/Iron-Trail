"""Per-model Coach configuration.

A single global price pair silently mis-bills as soon as more than one model is
in play — the spread across the catalogue is 40x on input — so pricing, and the
reasoning-effort each model actually accepts, live here per deployment.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .. import runtime


@dataclass(frozen=True)
class ModelProfile:
    """Everything that varies per deployment."""

    deployment: str
    input_eur_per_million: float
    output_eur_per_million: float
    reasoning_effort: str | None = None


# USD per million tokens, treated as EUR at parity like the original defaults.
# reasoning_effort is not cosmetic: gpt-5.6-luna rejects 'minimal' with a 400,
# while the gpt-5 reasoning models burn their whole output budget without it.
MODEL_CATALOG: dict[str, ModelProfile] = {
    "gpt-5-mini": ModelProfile("gpt-5-mini", 0.25, 2.00, "minimal"),
    "gpt-5-nano": ModelProfile("gpt-5-nano", 0.05, 0.40, "minimal"),
    "gpt-5.6-luna": ModelProfile("gpt-5.6-luna", 1.00, 6.00, "low"),
    "gpt-4.1-mini": ModelProfile("gpt-4.1-mini", 0.40, 1.60, None),
    "gpt-4.1-nano": ModelProfile("gpt-4.1-nano", 0.10, 0.40, None),
    "claude-haiku-4-5": ModelProfile("claude-haiku-4-5", 1.00, 5.00, None),
    "claude-sonnet-5": ModelProfile("claude-sonnet-5", 2.00, 10.00, None),
}

REVIEW_DEPLOYMENT_ENV = "IRONTRAIL_AI_REVIEW_DEPLOYMENT"
CHAT_DEPLOYMENT_ENV = "IRONTRAIL_AI_CHAT_DEPLOYMENT"
FALLBACK_DEPLOYMENT_ENV = "IRONTRAIL_AZURE_OPENAI_DEPLOYMENT"


def resolve_profile(kind_value: str, environ: Mapping[str, str] | None = None) -> ModelProfile:
    """Profile for a call kind: per-kind override, else the shared deployment.

    An unknown deployment still works — it falls back to the legacy global
    price envs so a newly deployed model bills conservatively rather than
    silently costing nothing.
    """
    env = environ if environ is not None else os.environ
    specific = REVIEW_DEPLOYMENT_ENV if kind_value == "review" else CHAT_DEPLOYMENT_ENV
    deployment = (env.get(specific) or env.get(FALLBACK_DEPLOYMENT_ENV) or "").strip()
    if not deployment:
        raise runtime.ConfigurationError(
            f"{specific} or {FALLBACK_DEPLOYMENT_ENV} is required"
        )

    known = MODEL_CATALOG.get(deployment)
    if known is not None:
        return known

    return ModelProfile(
        deployment=deployment,
        input_eur_per_million=runtime.env_float(
            "IRONTRAIL_AI_INPUT_EUR_PER_MILLION", 0.25, minimum=0.0, environ=env
        ),
        output_eur_per_million=runtime.env_float(
            "IRONTRAIL_AI_OUTPUT_EUR_PER_MILLION", 2.0, minimum=0.0, environ=env
        ),
        reasoning_effort=(env.get("IRONTRAIL_AI_REASONING_EFFORT", "").strip() or None),
    )
