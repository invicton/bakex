# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""AWS Bedrock Converse API backend for the Statim agentic build system.

Uses existing AWS credentials (same creds Statim uses for EC2/AMI operations).
No additional API key required — just needs bedrock:InvokeModelWithResponseStream
permission on the target model.

Env vars:
  STATIM_LLM_MODEL     — Bedrock model ID
                          (default: us.anthropic.claude-opus-4-5-20251101-v1:0)
  AWS_DEFAULT_REGION    — region (default: us-east-1)
  AWS_PROFILE / AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY — standard AWS auth

Note: boto3 has no native async client, so the streaming call runs in a thread
via asyncio.to_thread. Text tokens are buffered and delivered as one chunk after
the full response arrives — this is a known limitation vs. true token streaming.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable

from .base import AgentTurnResult, TextBlock, ToolUseBlock

# ---------------------------------------------------------------------------
# Format converters  (Anthropic canonical → Bedrock Converse wire format)
# ---------------------------------------------------------------------------


def _tools_to_bedrock(tools: list[dict]) -> list[dict]:
    return [
        {
            "toolSpec": {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {"json": t.get("input_schema", {"type": "object", "properties": {}})},
            }
        }
        for t in tools
    ]


def _messages_to_bedrock(messages: list[dict]) -> list[dict]:
    """Convert Anthropic message format to Bedrock Converse message format."""
    result: list[dict] = []

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            result.append({"role": role, "content": [{"text": content}]})
            continue

        bedrock_content: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "text":
                bedrock_content.append({"text": block["text"]})

            elif btype == "tool_use":
                bedrock_content.append(
                    {
                        "toolUse": {
                            "toolUseId": block["id"],
                            "name": block["name"],
                            "input": block["input"],
                        }
                    }
                )

            elif btype == "tool_result":
                try:
                    result_json = json.loads(block.get("content", "{}"))
                except (json.JSONDecodeError, TypeError):
                    result_json = {"raw": block.get("content", "")}
                bedrock_content.append(
                    {
                        "toolResult": {
                            "toolUseId": block["tool_use_id"],
                            "content": [{"json": result_json}],
                        }
                    }
                )

        if bedrock_content:
            result.append({"role": role, "content": bedrock_content})

    return result


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------


class BedrockBackend:
    """LLM backend backed by AWS Bedrock Converse streaming API."""

    DEFAULT_MODEL = "us.anthropic.claude-opus-4-5-20251101-v1:0"

    def __init__(self, model: str | None = None, region: str | None = None) -> None:
        self.model = model or os.environ.get("STATIM_LLM_MODEL", self.DEFAULT_MODEL)
        self.region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    async def agent_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
    ) -> AgentTurnResult:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 not installed — run: uv add boto3") from exc

        bedrock_messages = _messages_to_bedrock(messages)
        bedrock_tools = _tools_to_bedrock(tools)

        # boto3 has no async client; run the blocking stream in a thread
        def _call() -> tuple[str, list[TextBlock | ToolUseBlock]]:
            client = boto3.client("bedrock-runtime", region_name=self.region)
            response = client.converse_stream(
                modelId=self.model,
                system=[{"text": system}],
                messages=bedrock_messages,
                toolConfig={"tools": bedrock_tools},
                inferenceConfig={"maxTokens": max_tokens},
            )

            text_parts: list[str] = []
            tool_uses: list[dict] = []
            stop_reason = "end_turn"
            current_tool: dict | None = None
            tool_input_acc = ""

            for event in response["stream"]:
                if "contentBlockStart" in event:
                    start = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start:
                        current_tool = {
                            "id": start["toolUse"]["toolUseId"],
                            "name": start["toolUse"]["name"],
                        }
                        tool_input_acc = ""

                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        text_parts.append(delta["text"])
                    elif "toolInput" in delta:
                        # toolInput delta is {"input": "<partial_json>"} or just a str
                        raw = delta["toolInput"]
                        tool_input_acc += raw.get("input", raw) if isinstance(raw, dict) else raw

                elif "contentBlockStop" in event:
                    if current_tool is not None:
                        try:
                            current_tool["input"] = json.loads(tool_input_acc) if tool_input_acc else {}
                        except json.JSONDecodeError:
                            current_tool["input"] = {"_raw": tool_input_acc}
                        tool_uses.append(current_tool)
                        current_tool = None
                        tool_input_acc = ""

                elif "messageStop" in event:
                    bedrock_stop = event["messageStop"].get("stopReason", "end_turn")
                    stop_reason = "tool_use" if bedrock_stop == "tool_use" else "end_turn"

            content_blocks: list[TextBlock | ToolUseBlock] = []
            full_text = "".join(text_parts)
            if full_text:
                content_blocks.append(TextBlock(text=full_text))
            for tu in tool_uses:
                content_blocks.append(ToolUseBlock(id=tu["id"], name=tu["name"], input=tu["input"]))

            return stop_reason, content_blocks

        stop_reason, content_blocks = await asyncio.to_thread(_call)

        # Deliver accumulated text to the SSE stream
        for block in content_blocks:
            if isinstance(block, TextBlock) and block.text:
                await on_token(block.text)

        return AgentTurnResult(stop_reason=stop_reason, content=content_blocks)
