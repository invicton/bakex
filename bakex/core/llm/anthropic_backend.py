# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Anthropic API backend for the BakeX agentic build system.

Env vars:
  ANTHROPIC_API_KEY     — required
  BAKEX_LLM_MODEL     — model ID override (default: claude-opus-5)
  BAKEX_LLM_THINKING  — set to "0" to disable extended thinking (default: enabled)
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from .base import AgentTurnResult, TextBlock, ToolUseBlock


class AnthropicBackend:
    """LLM backend backed by the Anthropic Messages API (direct)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("BAKEX_LLM_MODEL", "claude-opus-5")
        self.use_thinking = os.environ.get("BAKEX_LLM_THINKING", "1") not in ("0", "false", "no")

    async def agent_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
    ) -> AgentTurnResult:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic package not installed — run: uv add anthropic") from exc

        client = anthropic.AsyncAnthropic()

        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        # Always send `thinking` explicitly, in both directions. Omitting it used to mean
        # "off" (Opus 4.6/4.7/4.8), but on Opus 5 thinking is on by default — so an implicit
        # opt-out silently stopped opting out. `disabled` is accepted only at effort `high`
        # or below; we don't set `effort`, and its default is `high`.
        kwargs["thinking"] = {"type": "adaptive"} if self.use_thinking else {"type": "disabled"}

        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if (
                        hasattr(event, "type")
                        and event.type == "content_block_delta"
                        and hasattr(event, "delta")
                        and hasattr(event.delta, "type")
                        and event.delta.type == "text_delta"
                    ):
                        await on_token(event.delta.text)
                response = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc

        content: list[TextBlock | ToolUseBlock] = []
        for block in response.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(ToolUseBlock(id=block.id, name=block.name, input=block.input))

        return AgentTurnResult(stop_reason=response.stop_reason, content=content)
