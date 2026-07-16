# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""OpenAI-compatible API backend for the Statim agentic build system.

Works with any OpenAI-compatible endpoint:
  • OpenAI (api.openai.com)
  • Groq, Together AI, Fireworks
  • vLLM / LiteLLM self-hosted
  • Ollama  — set STATIM_LLM_PROVIDER=ollama or pass base_url manually

Env vars:
  STATIM_LLM_MODEL     — model name (default: gpt-4o for openai, llama3.3:70b for ollama)
  STATIM_LLM_API_KEY   — API key (falls back to OPENAI_API_KEY; for Ollama use "ollama")
  STATIM_LLM_BASE_URL  — base URL override (e.g. http://localhost:11434/v1 for Ollama)
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable

from .base import AgentTurnResult, TextBlock, ToolUseBlock

# ---------------------------------------------------------------------------
# Format converters  (Anthropic canonical → OpenAI wire format)
# ---------------------------------------------------------------------------


def _tools_to_openai(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _messages_to_openai(messages: list[dict], system: str) -> list[dict]:
    """Convert Anthropic-format message history to OpenAI chat format.

    Key differences:
    - System prompt is a leading {"role": "system"} message in OpenAI
    - Tool results are separate {"role": "tool"} messages, not nested in "user"
    - Assistant tool calls live in message["tool_calls"], not content blocks
    """
    result: list[dict] = [{"role": "system", "content": system}]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if role == "user":
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    # Tool results become separate "tool" messages in OpenAI format
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        }
                    )
            if text_content := "".join(text_parts).strip():
                result.insert(
                    -len([b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]) or len(result),
                    {"role": "user", "content": text_content},
                )  # noqa: E501 — handled below

        elif role == "assistant":
            text_parts = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        }
                    )
            msg_dict: dict = {"role": "assistant"}
            if text_content := "".join(text_parts):
                msg_dict["content"] = text_content
            else:
                msg_dict["content"] = None
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            result.append(msg_dict)

    return result


def _messages_to_openai_clean(messages: list[dict], system: str) -> list[dict]:
    """Cleaner implementation of _messages_to_openai with correct ordering.

    OpenAI requires tool results to appear AFTER the assistant message that
    requested them — so we process each message pair as a unit.
    """
    result: list[dict] = [{"role": "system", "content": system}]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if role == "user":
            # Split into plain text and tool results
            text_parts: list[str] = []
            tool_results: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_result":
                    tool_results.append(block)

            # Plain text user message (if any)
            if text_content := "".join(text_parts).strip():
                result.append({"role": "user", "content": text_content})

            # Tool results as separate tool messages (must follow the assistant message)
            for tr in tool_results:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr.get("content", ""),
                    }
                )

        elif role == "assistant":
            text_parts = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        }
                    )
            msg_dict: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            result.append(msg_dict)

    return result


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------


class OpenAICompatBackend:
    """LLM backend for any OpenAI-compatible chat completions API."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model or os.environ.get("STATIM_LLM_MODEL", "gpt-4o")
        self.base_url = base_url or os.environ.get("STATIM_LLM_BASE_URL")
        self.api_key = api_key or os.environ.get("STATIM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")

    async def agent_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
    ) -> AgentTurnResult:
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError("openai package not installed — run: uv add openai") from exc

        client_kwargs: dict = {"api_key": self.api_key or "placeholder"}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = openai.AsyncOpenAI(**client_kwargs)
        oai_messages = _messages_to_openai_clean(messages, system)
        oai_tools = _tools_to_openai(tools)

        # Accumulate streaming deltas
        text_acc = ""
        # tool_calls_acc: index → {id, name, arguments}
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = "stop"

        try:
            async with await client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=oai_messages,
                tools=oai_tools,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta

                    if delta.content:
                        text_acc += delta.content
                        await on_token(delta.content)

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments

                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

        except openai.APIStatusError as exc:
            raise RuntimeError(f"OpenAI API error {exc.status_code}: {exc.message}") from exc

        # Build canonical content blocks
        content: list[TextBlock | ToolUseBlock] = []
        if text_acc:
            content.append(TextBlock(text=text_acc))

        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                input_dict = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                input_dict = {"_raw": tc["arguments"]}
            content.append(ToolUseBlock(id=tc["id"], name=tc["name"], input=input_dict))

        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
        return AgentTurnResult(stop_reason=stop_reason, content=content)
