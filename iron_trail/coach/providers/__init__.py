"""Provider abstraction — base protocol all coach LLM providers implement.

A provider takes a list of OpenAI-style chat messages and returns the
assistant's text response. The Coach module never reaches outside this
abstraction, which lets us swap in mock/real/test providers freely.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    """Synchronous interface for a chat-completion-style LLM call."""

    name: str
    last_usage: TokenUsage | None

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        """Send messages, return the assistant's reply text."""
        ...
