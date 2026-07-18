from __future__ import annotations

from types import SimpleNamespace

import pytest

from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.coach.providers.azure_foundry import (
    AzureFoundryProvider,
    EmptyAssistantResponseError,
)


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="grounded response"))],
            usage=SimpleNamespace(prompt_tokens=321, completion_tokens=123),
            id="completion-123",
            _request_id="request-123",
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.timeout = None

    def with_options(self, *, timeout):
        self.timeout = timeout
        return self


def test_foundry_provider_uses_deployment_and_tracks_usage() -> None:
    client = FakeClient()
    provider = AzureFoundryProvider(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5-mini",
        client=client,
        max_output_tokens=700,
    )

    response = provider.chat(
        [Message("system", "Use only supplied facts."), Message("user", "Review this.")],
        timeout=42,
    )

    assert response == "grounded response"
    assert client.timeout == 42
    assert client.completions.kwargs["model"] == "gpt-5-mini"
    assert client.completions.kwargs["max_completion_tokens"] == 700
    assert "tools" not in client.completions.kwargs
    assert "reasoning_effort" not in client.completions.kwargs
    assert provider.last_usage == TokenUsage(321, 123)
    assert provider.last_request_id == "request-123"
    assert provider.last_response_id == "completion-123"


def test_foundry_provider_passes_reasoning_effort() -> None:
    client = FakeClient()
    provider = AzureFoundryProvider(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5-mini",
        client=client,
        reasoning_effort="minimal",
    )

    provider.chat([Message("user", "Format this synthetic object.")])

    assert client.completions.kwargs["reasoning_effort"] == "minimal"


def test_foundry_provider_reads_cloud_controls_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("IRONTRAIL_AI_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("IRONTRAIL_AI_MAX_RETRIES", "0")
    monkeypatch.setenv("IRONTRAIL_AI_MAX_OUTPUT_TOKENS", "1200")
    client = FakeClient()

    provider = AzureFoundryProvider(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5-mini",
        client=client,
    )
    provider.chat([Message("user", "Format this synthetic object.")])

    assert provider.reasoning_effort == "minimal"
    assert provider.max_retries == 0
    assert provider.max_output_tokens == 1200
    assert client.completions.kwargs["reasoning_effort"] == "minimal"


def test_foundry_provider_tracks_usage_before_empty_response_error() -> None:
    client = FakeClient()
    client.completions.create = lambda **_kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
        usage=SimpleNamespace(prompt_tokens=111, completion_tokens=300),
        id="completion-empty",
        _request_id="request-empty",
    )
    provider = AzureFoundryProvider(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5-mini",
        client=client,
    )

    with pytest.raises(EmptyAssistantResponseError):
        provider.chat([Message("user", "Format this synthetic object.")])

    assert provider.last_usage == TokenUsage(111, 300)
    assert provider.last_request_id == "request-empty"
    assert provider.last_response_id == "completion-empty"
