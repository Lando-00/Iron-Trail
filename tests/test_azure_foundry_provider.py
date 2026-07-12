from __future__ import annotations

from types import SimpleNamespace

from iron_trail.coach.providers import Message, TokenUsage
from iron_trail.coach.providers.azure_foundry import AzureFoundryProvider


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="grounded response"))],
            usage=SimpleNamespace(prompt_tokens=321, completion_tokens=123),
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
    assert provider.last_usage == TokenUsage(321, 123)

