"""Managed-identity provider for Azure OpenAI models in Microsoft Foundry."""
from __future__ import annotations

import os
import threading
from typing import Any

from ... import runtime
from ...cloud_storage import azure_credential
from . import Message, TokenUsage


class AzureFoundryProvider:
    name = "azure-foundry"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
        max_output_tokens: int | None = None,
        client: Any | None = None,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("IRONTRAIL_AZURE_OPENAI_ENDPOINT", "")
        self.deployment = deployment or os.environ.get(
            "IRONTRAIL_AZURE_OPENAI_DEPLOYMENT", ""
        )
        self.api_version = api_version or os.environ.get(
            "IRONTRAIL_AZURE_OPENAI_API_VERSION", "2025-04-01-preview"
        )
        self.max_output_tokens = max_output_tokens or runtime.env_int(
            "IRONTRAIL_AI_MAX_OUTPUT_TOKENS", 1200, minimum=1
        )
        if not self.endpoint:
            raise runtime.ConfigurationError("IRONTRAIL_AZURE_OPENAI_ENDPOINT is required")
        if not self.deployment:
            raise runtime.ConfigurationError("IRONTRAIL_AZURE_OPENAI_DEPLOYMENT is required")

        self._client = client or self._build_client()
        self._lock = threading.Lock()
        self.last_usage: TokenUsage | None = None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        self.last_usage = None
        request_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        with self._lock:
            response = self._client.with_options(timeout=timeout).chat.completions.create(
                model=self.deployment,
                messages=request_messages,
                max_completion_tokens=self.max_output_tokens,
            )
            if not response.choices or not response.choices[0].message.content:
                raise RuntimeError("No assistant message returned from Microsoft Foundry.")
            usage = response.usage
            if usage is not None:
                self.last_usage = TokenUsage(
                    input_tokens=int(usage.prompt_tokens or 0),
                    output_tokens=int(usage.completion_tokens or 0),
                )
            return response.choices[0].message.content

    def _build_client(self) -> Any:
        from azure.identity import get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            azure_credential(),
            "https://cognitiveservices.azure.com/.default",
        )
        return AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_ad_token_provider=token_provider,
            max_retries=2,
        )

