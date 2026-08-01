from __future__ import annotations

import pathlib
import re

import pytest

from iron_trail import config, ingest, runtime
from iron_trail.coach import chat as coach_chat
from iron_trail.coach.models import (
    CHAT_DEPLOYMENT_ENV,
    FALLBACK_DEPLOYMENT_ENV,
    LUNA_SUPPORTED_EFFORTS,
    MODEL_CATALOG,
    REVIEW_DEPLOYMENT_ENV,
    resolve_profile,
)
from iron_trail.usage_limits import UsagePolicy, token_cost_eur


def test_per_kind_routing_prefers_the_specific_deployment() -> None:
    env = {
        REVIEW_DEPLOYMENT_ENV: "gpt-5-mini",
        CHAT_DEPLOYMENT_ENV: "gpt-5.6-luna",
        FALLBACK_DEPLOYMENT_ENV: "gpt-4.1-nano",
    }

    assert resolve_profile("review", env).deployment == "gpt-5-mini"
    assert resolve_profile("chat", env).deployment == "gpt-5.6-luna"


def test_routing_falls_back_to_the_shared_deployment() -> None:
    env = {FALLBACK_DEPLOYMENT_ENV: "gpt-5-mini"}

    assert resolve_profile("review", env).deployment == "gpt-5-mini"
    assert resolve_profile("chat", env).deployment == "gpt-5-mini"


def test_routing_requires_a_deployment() -> None:
    with pytest.raises(runtime.ConfigurationError):
        resolve_profile("chat", {})


def test_unknown_deployment_falls_back_to_the_legacy_global_prices() -> None:
    """A newly deployed model must bill conservatively, never at zero."""
    profile = resolve_profile(
        "chat",
        {
            CHAT_DEPLOYMENT_ENV: "some-new-model",
            "IRONTRAIL_AI_INPUT_EUR_PER_MILLION": "0.9",
            "IRONTRAIL_AI_OUTPUT_EUR_PER_MILLION": "7.5",
        },
    )

    assert profile.deployment == "some-new-model"
    assert profile.input_eur_per_million == 0.9
    assert profile.output_eur_per_million == 7.5


def test_luna_never_requests_the_minimal_reasoning_effort() -> None:
    """Verified against the live deployment: gpt-5.6-luna returns 400 with
    "Supported values are: 'none', 'low', 'medium', 'high', and 'xhigh'"."""
    luna = MODEL_CATALOG["gpt-5.6-luna"]
    assert luna.reasoning_effort == "high"
    assert luna.reasoning_effort in LUNA_SUPPORTED_EFFORTS
    assert "minimal" not in LUNA_SUPPORTED_EFFORTS
    assert MODEL_CATALOG["gpt-5-mini"].reasoning_effort == "minimal"


def test_a_model_without_reasoning_effort_sends_none() -> None:
    """Passing None would let the global IRONTRAIL_AI_REASONING_EFFORT leak in
    and 400 on models that reject it. The page passes "" instead."""
    from iron_trail.coach.providers.azure_foundry import AzureFoundryProvider

    claude = MODEL_CATALOG["claude-sonnet-5"]
    assert claude.reasoning_effort is None

    provider = AzureFoundryProvider(
        endpoint="https://example.invalid/",
        deployment=claude.deployment,
        reasoning_effort=claude.reasoning_effort or "",
        client=object(),
    )
    assert provider.reasoning_effort is None


def test_a_model_with_reasoning_effort_keeps_it() -> None:
    from iron_trail.coach.providers.azure_foundry import AzureFoundryProvider

    luna = MODEL_CATALOG["gpt-5.6-luna"]
    provider = AzureFoundryProvider(
        endpoint="https://example.invalid/",
        deployment=luna.deployment,
        reasoning_effort=luna.reasoning_effort or "",
        client=object(),
    )
    assert provider.reasoning_effort == "high"


def test_costs_are_billed_per_model_not_globally() -> None:
    base = UsagePolicy()
    mini = MODEL_CATALOG["gpt-5-mini"]
    luna = MODEL_CATALOG["gpt-5.6-luna"]

    mini_cost = token_cost_eur(
        1_000_000, 1_000_000, base.with_prices(mini.input_eur_per_million, mini.output_eur_per_million)
    )
    luna_cost = token_cost_eur(
        1_000_000, 1_000_000, base.with_prices(luna.input_eur_per_million, luna.output_eur_per_million)
    )

    assert mini_cost == pytest.approx(2.25)
    assert luna_cost == pytest.approx(7.00)
    assert luna_cost > mini_cost, "a single global price pair would mis-bill here"


def test_with_prices_keeps_every_other_limit() -> None:
    base = UsagePolicy()
    swapped = base.with_prices(9.0, 9.0)

    assert swapped.review_daily == base.review_daily
    assert swapped.chat_monthly == base.chat_monthly
    assert swapped.max_input_tokens == base.max_input_tokens
    assert swapped.global_monthly_cost_eur == base.global_monthly_cost_eur


def test_every_starter_prompt_is_answerable_from_the_chat_context() -> None:
    """A starter that returns "that isn't in the summary" is worse than none.
    Each prompt must map to a field build_chat_context actually provides."""
    source = (
        pathlib.Path(__file__).parents[1] / "pages" / "6_💬_Coach.py"
    ).read_text(encoding="utf-8")
    block = re.search(r"STARTER_PROMPTS = \[(.*?)\]", source, re.DOTALL)
    assert block is not None
    starters = re.findall(r'"([^"]+)"', block.group(1))
    assert len(starters) >= 3

    supported = {
        "consistent": "session_count_30d",
        "strongest": "exercise_catalog",
        "streak": "current_streak_days",
        "stalling": "plateau_watch",
    }

    for starter in starters:
        matched = [key for key in supported if key in starter.lower()]
        assert matched, f"starter not grounded in the chat context: {starter!r}"

    frame = ingest.load_and_clean(config.SAMPLE_CSV, body_weight_kg=84.0)
    context = coach_chat.build_chat_context(frame)
    for field in supported.values():
        assert field in context, f"chat context is missing {field}"
