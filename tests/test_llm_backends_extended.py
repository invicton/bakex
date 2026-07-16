# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Extended tests for LLM backends and factory.

Covers the previously uncovered paths in:
  - statim/core/llm/anthropic_backend.py  (was 28%)
  - statim/core/llm/openai_backend.py     (was 35%)
  - statim/core/llm/bedrock_backend.py    (was 43%)
  - statim/core/llm/factory.py            (was 97%)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from statim.core.llm.base import TextBlock, ToolUseBlock
from statim.core.llm.bedrock_backend import (
    BedrockBackend,
    _messages_to_bedrock,
    _tools_to_bedrock,
)
from statim.core.llm.openai_backend import (
    OpenAICompatBackend,
    _messages_to_openai,
    _messages_to_openai_clean,
    _tools_to_openai,
)

# ---------------------------------------------------------------------------
# Helpers
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

_SIMPLE_MESSAGES = [{"role": "user", "content": "Hello, build this image."}]

_TOOL_USE_MESSAGES = [
    {"role": "user", "content": "Run the build."},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I will validate the blueprint first."},
            {"type": "tool_use", "id": "tu-001", "name": "validate_blueprint", "input": {"yaml_text": "x"}},
        ],
    },
    {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu-001", "content": '{"valid": true}'},
        ],
    },
]


# ===========================================================================
# OpenAI backend — converter functions
# ===========================================================================


class TestToolsToOpenAI:
    def test_wraps_in_function_format(self):
        result = _tools_to_openai(_SIMPLE_TOOLS)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "validate_blueprint"
        assert "parameters" in result[0]["function"]

    def test_empty_tools(self):
        assert _tools_to_openai([]) == []


class TestMessagesToOpenAI:
    def test_simple_user_message(self):
        result = _messages_to_openai([{"role": "user", "content": "hello"}], "sys")
        assert result[0] == {"role": "system", "content": "sys"}
        assert any(m["role"] == "user" and "hello" in m.get("content", "") for m in result)

    def test_tool_result_becomes_tool_message(self):
        result = _messages_to_openai(_TOOL_USE_MESSAGES, "sys")
        roles = [m["role"] for m in result]
        assert "tool" in roles

    def test_assistant_tool_call_gets_tool_calls_field(self):
        result = _messages_to_openai(_TOOL_USE_MESSAGES, "sys")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert any("tool_calls" in m for m in assistant_msgs)


class TestMessagesToOpenAIClean:
    def test_produces_system_first(self):
        result = _messages_to_openai_clean(_SIMPLE_MESSAGES, "system-prompt")
        assert result[0] == {"role": "system", "content": "system-prompt"}

    def test_string_content_passthrough(self):
        result = _messages_to_openai_clean([{"role": "user", "content": "hi"}], "sys")
        assert any(m["content"] == "hi" for m in result)

    def test_tool_results_become_separate_tool_messages(self):
        result = _messages_to_openai_clean(_TOOL_USE_MESSAGES, "sys")
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tu-001"

    def test_assistant_with_tool_calls(self):
        result = _messages_to_openai_clean(_TOOL_USE_MESSAGES, "sys")
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert any("tool_calls" in m for m in assistant_msgs)

    def test_assistant_text_only(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "response"}]},
        ]
        result = _messages_to_openai_clean(msgs, "sys")
        assistant = next(m for m in result if m["role"] == "assistant")
        assert assistant["content"] == "response"


# ===========================================================================
# OpenAI backend — agent_turn
# ===========================================================================


class TestOpenAICompatBackendAgentTurn:
    def _make_chunk(self, delta_content=None, delta_tool_calls=None, finish_reason=None):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = delta_content
        chunk.choices[0].delta.tool_calls = delta_tool_calls
        chunk.choices[0].finish_reason = finish_reason
        return chunk

    @pytest.mark.anyio
    async def test_text_response_end_turn(self):
        import sys

        backend = OpenAICompatBackend(model="gpt-4o", api_key="test-key")

        text_chunk = self._make_chunk(delta_content="Hello world", finish_reason=None)
        end_chunk = self._make_chunk(delta_content=None, finish_reason="stop")

        async def aiter(items):
            for item in items:
                yield item

        mock_stream = MagicMock()
        mock_stream.__aiter__ = lambda self: aiter([text_chunk, end_chunk])

        ctx_mgr = MagicMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=mock_stream)
        ctx_mgr.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=ctx_mgr)

        tokens = []

        async def on_token(t):
            tokens.append(t)

        class _FakeAPIStatusError(Exception):
            status_code = 0
            message = ""

        mock_openai = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client
        mock_openai.APIStatusError = _FakeAPIStatusError

        with patch.dict(sys.modules, {"openai": mock_openai}):
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="system",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "end_turn"
        assert any(isinstance(b, TextBlock) and "Hello" in b.text for b in result.content)
        assert "Hello world" in tokens

    @pytest.mark.anyio
    async def test_missing_openai_package_raises_runtime_error(self):
        import sys

        backend = OpenAICompatBackend(model="gpt-4o", api_key="test-key")

        async def on_token(t):
            pass

        with patch.dict(sys.modules, {"openai": None}):
            with pytest.raises(RuntimeError, match="openai package not installed"):
                await backend.agent_turn(
                    messages=_SIMPLE_MESSAGES,
                    tools=_SIMPLE_TOOLS,
                    system="sys",
                    max_tokens=100,
                    on_token=on_token,
                )


# ===========================================================================
# Bedrock backend — converter functions
# ===========================================================================


class TestToolsToBedrock:
    def test_wraps_in_tool_spec(self):
        result = _tools_to_bedrock(_SIMPLE_TOOLS)
        assert len(result) == 1
        assert "toolSpec" in result[0]
        assert result[0]["toolSpec"]["name"] == "validate_blueprint"

    def test_empty_tools(self):
        assert _tools_to_bedrock([]) == []


class TestMessagesToBedrock:
    def test_simple_string_content(self):
        result = _messages_to_bedrock([{"role": "user", "content": "hello"}])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["text"] == "hello"

    def test_tool_use_block(self):
        msgs = [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "tu-1", "name": "validate_blueprint", "input": {"x": 1}}],
            }
        ]
        result = _messages_to_bedrock(msgs)
        assert result[0]["content"][0]["toolUse"]["toolUseId"] == "tu-1"

    def test_tool_result_block_valid_json(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": '{"valid": true}'}],
            }
        ]
        result = _messages_to_bedrock(msgs)
        tool_result = result[0]["content"][0]["toolResult"]
        assert tool_result["toolUseId"] == "tu-1"
        assert tool_result["content"][0]["json"]["valid"] is True

    def test_tool_result_block_invalid_json_falls_back(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "not json{{"}],
            }
        ]
        result = _messages_to_bedrock(msgs)
        tool_result = result[0]["content"][0]["toolResult"]
        assert "raw" in tool_result["content"][0]["json"]

    def test_empty_content_not_added(self):
        msgs = [{"role": "user", "content": []}]
        result = _messages_to_bedrock(msgs)
        assert len(result) == 0

    def test_non_dict_blocks_skipped(self):
        msgs = [{"role": "user", "content": ["not a dict", {"type": "text", "text": "real"}]}]
        result = _messages_to_bedrock(msgs)
        assert result[0]["content"][0]["text"] == "real"


# ===========================================================================
# Bedrock backend — agent_turn with mocked boto3
# ===========================================================================


class TestBedrockBackendAgentTurn:
    def _make_stream_events(self, text="Hello from Bedrock", stop_reason="end_turn"):
        return [
            {"contentBlockDelta": {"delta": {"text": text}}},
            {"messageStop": {"stopReason": stop_reason}},
        ]

    @pytest.mark.anyio
    async def test_text_response(self):
        backend = BedrockBackend(model="claude-3", region="us-east-1")

        events = self._make_stream_events("Bedrock response")

        mock_client = MagicMock()
        mock_client.converse_stream.return_value = {"stream": events}

        tokens = []

        async def on_token(t):
            tokens.append(t)

        with patch("boto3.client", return_value=mock_client):
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="system",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "end_turn"
        assert any(isinstance(b, TextBlock) and "Bedrock" in b.text for b in result.content)
        assert "Bedrock response" in tokens

    @pytest.mark.anyio
    async def test_tool_use_response(self):
        backend = BedrockBackend(model="claude-3", region="us-east-1")

        events = [
            {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "tu-bd-1", "name": "validate_blueprint"}}}},
            {"contentBlockDelta": {"delta": {"toolInput": '{"yaml_text": "test"}'}}},
            {"contentBlockStop": {}},
            {"messageStop": {"stopReason": "tool_use"}},
        ]

        mock_client = MagicMock()
        mock_client.converse_stream.return_value = {"stream": events}

        async def on_token(t):
            pass

        with patch("boto3.client", return_value=mock_client):
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="system",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "tool_use"
        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "validate_blueprint"
        assert tool_blocks[0].id == "tu-bd-1"

    @pytest.mark.anyio
    async def test_missing_boto3_raises_runtime_error(self):
        backend = BedrockBackend()

        async def on_token(t):
            pass

        with patch.dict("sys.modules", {"boto3": None}):
            with pytest.raises(RuntimeError, match="boto3 not installed"):
                await backend.agent_turn(
                    messages=_SIMPLE_MESSAGES,
                    tools=_SIMPLE_TOOLS,
                    system="sys",
                    max_tokens=100,
                    on_token=on_token,
                )

    @pytest.mark.anyio
    async def test_tool_input_invalid_json_uses_raw_fallback(self):
        backend = BedrockBackend(model="claude-3", region="us-east-1")

        events = [
            {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "tu-2", "name": "validate_blueprint"}}}},
            {"contentBlockDelta": {"delta": {"toolInput": "{bad json"}}},
            {"contentBlockStop": {}},
            {"messageStop": {"stopReason": "tool_use"}},
        ]

        mock_client = MagicMock()
        mock_client.converse_stream.return_value = {"stream": events}

        async def on_token(t):
            pass

        with patch("boto3.client", return_value=mock_client):
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=100,
                on_token=on_token,
            )

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert "_raw" in tool_blocks[0].input


# ===========================================================================
# Anthropic backend — agent_turn with mocked client
# ===========================================================================


def _make_mock_anthropic(mock_client):
    """Inject a fake 'anthropic' module into sys.modules so agent_turn's
    lazy `import anthropic` resolves to our mock regardless of which Python
    interpreter is running the tests.
    """
    import sys

    class _FakeAPIStatusError(Exception):
        def __init__(self, msg, *, response=None, body=None):
            super().__init__(msg)
            self.status_code = getattr(response, "status_code", 0)
            self.message = msg

    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.return_value = mock_client
    mock_anthropic.APIStatusError = _FakeAPIStatusError
    return patch.dict(sys.modules, {"anthropic": mock_anthropic}), _FakeAPIStatusError


class TestAnthropicBackendAgentTurn:
    @pytest.mark.anyio
    async def test_text_response(self):
        from statim.core.llm.anthropic_backend import AnthropicBackend

        backend = AnthropicBackend(model="claude-3-5-sonnet-20241022")

        text_event = MagicMock()
        text_event.type = "content_block_delta"
        text_event.delta = MagicMock()
        text_event.delta.type = "text_delta"
        text_event.delta.text = "Narration chunk"

        final_msg = MagicMock()
        final_msg.stop_reason = "end_turn"
        final_msg.content = [MagicMock(type="text", text="Final response")]

        async def aiter_events(events):
            for e in events:
                yield e

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda s: aiter_events([text_event])
        mock_stream.get_final_message = AsyncMock(return_value=final_msg)

        mock_messages = MagicMock()
        mock_messages.stream.return_value.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_messages.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        tokens = []

        async def on_token(t):
            tokens.append(t)

        sys_patch, _ = _make_mock_anthropic(mock_client)
        with sys_patch:
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="system",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "end_turn"
        assert any(isinstance(b, TextBlock) for b in result.content)
        assert "Narration chunk" in tokens

    @pytest.mark.anyio
    async def test_tool_use_response(self):
        from statim.core.llm.anthropic_backend import AnthropicBackend

        backend = AnthropicBackend(model="claude-3-5-sonnet-20241022")

        final_msg = MagicMock()
        final_msg.stop_reason = "tool_use"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool-ant-001"
        tool_block.name = "validate_blueprint"
        tool_block.input = {"yaml_text": "test"}
        final_msg.content = [tool_block]

        async def aiter_events(events):
            for e in events:
                yield e

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda s: aiter_events([])
        mock_stream.get_final_message = AsyncMock(return_value=final_msg)

        mock_messages = MagicMock()
        mock_messages.stream.return_value.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_messages.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        async def on_token(t):
            pass

        sys_patch, _ = _make_mock_anthropic(mock_client)
        with sys_patch:
            result = await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="system",
                max_tokens=1000,
                on_token=on_token,
            )

        assert result.stop_reason == "tool_use"
        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "validate_blueprint"

    @pytest.mark.anyio
    async def test_api_status_error_raises_runtime_error(self):
        from statim.core.llm.anthropic_backend import AnthropicBackend

        backend = AnthropicBackend(model="claude-3-5-sonnet-20241022")

        async def aiter_events(events):
            for e in events:
                yield e

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda s: aiter_events([])

        mock_messages = MagicMock()
        mock_messages.stream.return_value.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_messages.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_client = MagicMock()
        mock_client.messages = mock_messages

        sys_patch, FakeAPIStatusError = _make_mock_anthropic(mock_client)
        mock_stream.get_final_message = AsyncMock(
            side_effect=FakeAPIStatusError("Auth error", response=MagicMock(status_code=401))
        )

        async def on_token(t):
            pass

        with sys_patch:
            with pytest.raises(RuntimeError, match="Anthropic API error"):
                await backend.agent_turn(
                    messages=_SIMPLE_MESSAGES,
                    tools=_SIMPLE_TOOLS,
                    system="sys",
                    max_tokens=100,
                    on_token=on_token,
                )

    @pytest.mark.anyio
    async def test_thinking_disabled_does_not_pass_thinking_kwarg(self):
        from statim.core.llm.anthropic_backend import AnthropicBackend

        backend = AnthropicBackend(model="claude-3-5-sonnet-20241022")
        backend.use_thinking = False

        final_msg = MagicMock()
        final_msg.stop_reason = "end_turn"
        final_msg.content = []

        async def aiter_events(events):
            for e in events:
                yield e

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda s: aiter_events([])
        mock_stream.get_final_message = AsyncMock(return_value=final_msg)

        captured_kwargs = {}
        orig_stream = MagicMock()
        orig_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        orig_stream.__aexit__ = AsyncMock(return_value=None)

        def capture_stream(**kwargs):
            captured_kwargs.update(kwargs)
            return orig_stream

        mock_messages = MagicMock()
        mock_messages.stream = capture_stream
        mock_client = MagicMock()
        mock_client.messages = mock_messages

        async def on_token(t):
            pass

        sys_patch, _ = _make_mock_anthropic(mock_client)
        with sys_patch:
            await backend.agent_turn(
                messages=_SIMPLE_MESSAGES,
                tools=_SIMPLE_TOOLS,
                system="sys",
                max_tokens=100,
                on_token=on_token,
            )

        assert "thinking" not in captured_kwargs


# ===========================================================================
# Factory — provider_status and get_backend for all providers
# ===========================================================================


class TestFactory:
    def test_provider_status_anthropic_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "anthropic")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["provider"] == "anthropic"
        assert status["available"] is False

    def test_provider_status_anthropic_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "anthropic")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["available"] is True

    def test_provider_status_openai_no_key(self, monkeypatch):
        monkeypatch.delenv("STATIM_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "openai")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["provider"] == "openai"
        assert status["available"] is False

    def test_provider_status_openai_with_key(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_API_KEY", "sk-test")
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "openai")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["available"] is True

    def test_provider_status_ollama_always_available(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "ollama")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["provider"] == "ollama"
        assert status["available"] is True

    def test_provider_status_bedrock_with_key(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "bedrock")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA000")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["provider"] == "bedrock"
        assert status["available"] is True

    def test_provider_status_bedrock_no_creds(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "bedrock")
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
        monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["available"] is False

    def test_provider_status_unknown_provider(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "groq")
        from statim.core.llm.factory import provider_status

        status = provider_status()
        assert status["available"] is False
        assert "groq" in status["message"].lower() or "unknown" in status["message"].lower()

    def test_get_backend_anthropic(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "anthropic")
        from statim.core.llm.anthropic_backend import AnthropicBackend
        from statim.core.llm.factory import get_backend

        backend = get_backend()
        assert isinstance(backend, AnthropicBackend)

    def test_get_backend_openai(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "openai")
        from statim.core.llm.factory import get_backend
        from statim.core.llm.openai_backend import OpenAICompatBackend

        backend = get_backend()
        assert isinstance(backend, OpenAICompatBackend)

    def test_get_backend_ollama(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "ollama")
        from statim.core.llm.factory import get_backend
        from statim.core.llm.openai_backend import OpenAICompatBackend

        backend = get_backend()
        assert isinstance(backend, OpenAICompatBackend)

    def test_get_backend_bedrock(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "bedrock")
        from statim.core.llm.bedrock_backend import BedrockBackend
        from statim.core.llm.factory import get_backend

        backend = get_backend()
        assert isinstance(backend, BedrockBackend)

    def test_get_backend_unknown_raises(self, monkeypatch):
        monkeypatch.setenv("STATIM_LLM_PROVIDER", "invalid_provider")
        from statim.core.llm.factory import get_backend

        with pytest.raises(ValueError, match="Unknown STATIM_LLM_PROVIDER"):
            get_backend()
