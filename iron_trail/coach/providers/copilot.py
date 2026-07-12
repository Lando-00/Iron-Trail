"""Real Copilot SDK provider.

Wraps the asynchronous ``CopilotClient`` from the official Python SDK into
a synchronous ``chat()`` call so the rest of the Coach module (and the
Streamlit page) can stay sync. The CLI server is spawned on first call
and shut down when ``close()`` is called or the program exits.

The client is cached on the class — re-using the same provider object
across calls avoids re-spawning the 1–3s CLI server for every prompt.
"""
from __future__ import annotations

import asyncio
import atexit
import threading
from typing import Any

from . import Message, TokenUsage


_PromptText = str


class CopilotProvider:
    name = "copilot"
    last_usage: TokenUsage | None = None

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any | None = None
        self._lock = threading.Lock()
        atexit.register(self._sync_close)

    def chat(self, messages: list[Message], *, timeout: float = 120.0) -> str:
        prompt = self._messages_to_prompt(messages)
        with self._lock:
            loop = self._ensure_loop()
            return loop.run_until_complete(self._send(prompt, timeout=timeout))

    def close(self) -> None:
        self._sync_close()

    # -------------------------------------------------------------------
    # internals
    # -------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    async def _ensure_client(self) -> Any:
        if self._client is None:
            from copilot import CopilotClient

            client = CopilotClient()
            await client.__aenter__()
            self._client = client
        return self._client

    async def _send(self, prompt: _PromptText, *, timeout: float) -> str:
        from copilot.session import PermissionHandler
        from copilot.generated.session_events import AssistantMessageData

        client = await self._ensure_client()
        session = await client.create_session(
            on_permission_request=PermissionHandler.approve_all,
        )
        response = await session.send_and_wait(prompt, timeout=timeout)
        if response is None:
            raise RuntimeError("No assistant message returned from Copilot.")
        if isinstance(response.data, AssistantMessageData):
            return response.data.content
        raise RuntimeError(
            f"Unexpected response data: {type(response.data).__name__}"
        )

    def _messages_to_prompt(self, messages: list[Message]) -> str:
        # The Copilot session.send_and_wait API takes a single string
        # prompt. We render the message list as a labelled transcript so
        # the model gets the full context but the system prompt drives the
        # behaviour.
        parts: list[str] = []
        for m in messages:
            if m.role == "system":
                parts.append(m.content.strip())
            elif m.role == "user":
                parts.append(f"\n[User]\n{m.content.strip()}")
            elif m.role == "assistant":
                parts.append(f"\n[Assistant]\n{m.content.strip()}")
        return "\n\n".join(parts).strip()

    def _sync_close(self) -> None:
        if self._client is None or self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.run_until_complete(self._client.__aexit__(None, None, None))
        except Exception:
            pass
        finally:
            self._client = None
            self._loop.close()
            self._loop = None
