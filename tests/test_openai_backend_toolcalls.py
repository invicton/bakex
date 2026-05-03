# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for OpenAI backend tool-call streaming and edge cases.

Covers openai_backend.py uncovered lines:
  215     — base_url passthrough to client_kwargs
  237     — empty chunk.choices → continue
  246-256 — tool-call delta accumulation (id, name, arguments)
  261-262 — APIStatusError → RuntimeError
  270-275 — ToolUseBlock building (valid JSON + invalid JSON fallback)
  66,69,78,85,102,132,135,141,156 — _messages_to_openai list-content edge cases
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stratum.core.llm.base import ToolUseBlock
from stratum.core.llm.openai_backend import (
    OpenAICompatBackend,
    _messages_to_openai,
    _messages_to_openai_clean,
)

# ---------------------------------------------------------------------------
# Reusable helpers
# ---------------------------------------------------------------------------

_SIMPLE_TOOLS = [
    {
        "name": "validate_blueprint",
        "description": "Validate a blueprint",
        "input_schema": {
            "type": "object",
            "properties": {"yaml_text": {"type": "string"}},
            "required": ["yaml_text"],
        },
    }
]

_SIMPLE_MESSAGES = [{"role": "user", "content": "Build this."}]


def _make_chunk(content=None, tool_calls=None, finish_reason=None, empty_choices=False):
    chunk = MagicMock()
    if empty_choices:
        chunk.choices = []
        return chunk
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.tool_calls = tool_calls
    chunk.choices[0].finish_reason = finish_reason
    return chunk


def _make_tool_call_delta(index, tool_id=None, func_name=None, func_args=None):
    tc = MagicMock()
    tc.index = index
    tc.id = tool_id
    tc.function = MagicMock()
    tc.function.name = func_name
    tc.function.arguments = func_args
    return tc


def _make_openai_module_and_client(mock_stream, raise_api_error=None):
    """Build a mock openai sys module + client. Returns (sys_patch, FakeAPIStatusError)."""

    class _FakeAPIStatusError(Exception):
        def __init__(self, msg, *, response=None, body=None):
            super().__init__(msg)
            self.status_code = getattr(response, "status_code", 429)
            self.message = msg

    async def aiter(items):
        for item in items:
            yield item

    if raise_api_error:
        mock_stream.get_final_message = AsyncMock(side_effect=raise_api_error)

    ctx_mgr = MagicMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=mock_stream)
    ctx_mgr.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=ctx_mgr)

    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI.return_value = mock_client
    mock_openai.APIStatusError = _FakeAPIStatusError

    return patch.dict(sys.modules, {"openai": mock_openai}), mock_client, _FakeAPIStatusError


# ===========================================================================
# Tool-call streaming
# ===========================================================================


class TestOpenAIToolCallStreaming:
    @pytest.mark.anyio
    async def test_tool_call_response_builds_tool_use_block(self):
        """Streaming tool-call deltas are accumulated into a ToolUseBlock."""
        backend = OpenAICompatBackend(model="gpt-4o", api_key="test")

        tc1 = _make_tool_call_delta(0, tool_id="tc-001", func_name="validate_blueprint")
        tc2 = _make_tool_call_delta(0, func_args='{"yaml_text": "hello"}')
        chunks = [
            _make_chunk(tool_calls=[tc1]),
            _make_chunk(tool_calls=[tc2]),
            _make_chunk(finish_reason="tool_calls"),
        ]

        async def aiter(items):
            for item in items:
                yield item

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda s: aiter(chunks)

        sys_patch, mock_client, _ = _make_openai_module_and_client(mock_stream)
        with sys_patch:
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=1000,
                on_token=AsyncMock(),
            )

        assert result.stop_reason == "tool_use"
        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].id == "tc-001"
        assert tool_blocks[0].name == "validate_blueprint"
        assert tool_blocks[0].input == {"yaml_text": "hello"}

    @pytest.mark.anyio
    async def test_tool_call_invalid_json_uses_raw_fallback(self):
        """When accumulated arguments are not valid JSON, _raw key is used."""
        backend = OpenAICompatBackend(model="gpt-4o", api_key="test")

        tc1 = _make_tool_call_delta(0, tool_id="tc-bad", func_name="validate_blueprint")
        tc2 = _make_tool_call_delta(0, func_args="{bad json")
        chunks = [
            _make_chunk(tool_calls=[tc1]),
            _make_chunk(tool_calls=[tc2]),
            _make_chunk(finish_reason="tool_calls"),
        ]

        async def aiter(items):
            for item in items:
                yield item

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda s: aiter(chunks)

        sys_patch, _, _ = _make_openai_module_and_client(mock_stream)
        with sys_patch:
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=1000,
                on_token=AsyncMock(),
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert "_raw" in tool_blocks[0].input

    @pytest.mark.anyio
    async def test_empty_choices_chunk_is_skipped(self):
        """Chunks with empty choices list are skipped without error."""
        backend = OpenAICompatBackend(model="gpt-4o", api_key="test")

        chunks = [
            _make_chunk(empty_choices=True),
            _make_chunk(content="Hello", finish_reason=None),
            _make_chunk(finish_reason="stop"),
        ]

        async def aiter(items):
            for item in items:
                yield item

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda s: aiter(chunks)

        tokens = []

        async def on_token(t):
            tokens.append(t)

        sys_patch, _, _ = _make_openai_module_and_client(mock_stream)
        with sys_patch:
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "end_turn"
        assert "Hello" in tokens

    @pytest.mark.anyio
    async def test_api_status_error_raises_runtime_error(self):
        """APIStatusError during streaming is re-raised as RuntimeError."""
        backend = OpenAICompatBackend(model="gpt-4o", api_key="test")

        async def aiter(items):
            for item in items:
                yield item

        class FakeStatusError(Exception):
            def __init__(self, msg):
                super().__init__(msg)
                self.status_code = 429
                self.message = msg

        class _FakeStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise FakeStatusError("rate limited")

        mock_stream = _FakeStream()
        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=mock_stream)
        ctx_mgr.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=ctx_mgr)

        mock_openai = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client
        mock_openai.APIStatusError = FakeStatusError

        with patch.dict(sys.modules, {"openai": mock_openai}):
            with pytest.raises(RuntimeError, match="OpenAI API error"):
                await backend.agent_turn(
                    messages=_SIMPLE_MESSAGES,
                    tools=_SIMPLE_TOOLS,
                    system="sys",
                    max_tokens=1000,
                    on_token=AsyncMock(),
                )

    @pytest.mark.anyio
    async def test_base_url_passed_to_client(self):
        """When base_url is set, it's passed as a kwarg to AsyncOpenAI."""
        backend = OpenAICompatBackend(model="llama3", api_key="test", base_url="http://localhost:11434/v1")

        chunks = [_make_chunk(content="Hi", finish_reason="stop")]

        async def aiter(items):
            for item in items:
                yield item

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda s: aiter(chunks)

        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=mock_stream)
        ctx_mgr.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=ctx_mgr)

        captured = {}
        mock_openai = MagicMock()
        mock_openai.AsyncOpenAI.side_effect = lambda **kw: (captured.update(kw), mock_client)[1]
        mock_openai.APIStatusError = Exception

        with patch.dict(sys.modules, {"openai": mock_openai}):
            await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=1000,
                on_token=AsyncMock(),
            )

        assert captured.get("base_url") == "http://localhost:11434/v1"


# ===========================================================================
# _messages_to_openai — list-content edge cases (lines 66, 69, 78, 85, 102)
# ===========================================================================


class TestMessagesToOpenAIEdgeCases:
    def test_non_dict_blocks_skipped_in_user_content(self):
        """Non-dict items in a user message content list are skipped."""
        msgs = [{"role": "user", "content": ["not-a-dict", {"type": "text", "text": "real"}]}]
        result = _messages_to_openai(msgs, "sys")
        user_msgs = [m for m in result if m["role"] == "user"]
        assert any("real" in str(m) for m in user_msgs)

    def test_text_block_in_user_content_extracted(self):
        """A text block in user list content is extracted as plain text."""
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
        result = _messages_to_openai(msgs, "sys")
        user_msgs = [m for m in result if m["role"] == "user"]
        assert any("hello" in str(m) for m in user_msgs)

    def test_non_dict_blocks_skipped_in_assistant_content(self):
        """Non-dict items in assistant content list are skipped."""
        msgs = [{"role": "assistant", "content": ["not-a-dict", {"type": "text", "text": "hi"}]}]
        result = _messages_to_openai(msgs, "sys")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1

    def test_assistant_with_no_text_gets_null_content(self):
        """Assistant message with only tool_use (no text) gets content=None."""
        msgs = [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "tu-1", "name": "validate_blueprint", "input": {"x": 1}}],
            }
        ]
        result = _messages_to_openai(msgs, "sys")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert assistant_msgs[0]["content"] is None
        assert "tool_calls" in assistant_msgs[0]


class TestMessagesToOpenAICleanEdgeCases:
    def test_non_dict_blocks_skipped_in_user_content(self):
        """Non-dict items in clean version's user content are skipped."""
        msgs = [{"role": "user", "content": ["not-a-dict", {"type": "text", "text": "real"}]}]
        result = _messages_to_openai_clean(msgs, "sys")
        user_msgs = [m for m in result if m["role"] == "user"]
        assert any("real" in str(m) for m in user_msgs)

    def test_user_text_plus_tool_result(self):
        """Text and tool_result in the same user message are split correctly."""
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "extra context"},
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": '{"ok": true}'},
                ],
            },
        ]
        result = _messages_to_openai_clean(msgs, "sys")
        user_msgs = [m for m in result if m["role"] == "user"]
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(user_msgs) == 1
        assert len(tool_msgs) == 1
        assert "extra context" in user_msgs[0]["content"]

    def test_non_dict_blocks_skipped_in_assistant_content(self):
        """Non-dict items in clean assistant content are skipped."""
        msgs = [{"role": "assistant", "content": ["not-a-dict", {"type": "text", "text": "ok"}]}]
        result = _messages_to_openai_clean(msgs, "sys")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "ok"
