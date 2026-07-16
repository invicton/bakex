# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Canonical types and LLMBackend protocol for Statim's agentic build system.

All backends translate to/from these types so the agent loop stays
provider-agnostic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass
class TextBlock:
    text: str
    type: Literal["text"] = field(default="text", init=False)


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: Literal["tool_use"] = field(default="tool_use", init=False)


ContentBlock = TextBlock | ToolUseBlock


@dataclass
class AgentTurnResult:
    """Canonical result of one LLM turn in the agent loop."""

    stop_reason: str  # "end_turn" or "tool_use"
    content: list[ContentBlock]


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol every LLM backend must satisfy.

    Messages are passed in Anthropic format (canonical internal representation).
    Each backend translates to/from its native wire format.
    """

    async def agent_turn(
        self,
        messages: list[dict],
        tools: list[dict],  # Anthropic tool schema format
        system: str,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
    ) -> AgentTurnResult: ...
