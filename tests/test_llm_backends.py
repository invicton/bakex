# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for LLM backend message/tool format converters.

All tests are offline — no API calls, no mock patches needed.
"""

import json

import pytest

from bakex.core.llm.bedrock_backend import _messages_to_bedrock, _tools_to_bedrock
from bakex.core.llm.factory import get_backend, provider_status
from bakex.core.llm.openai_backend import _messages_to_openai_clean, _tools_to_openai

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TOOLS = [
    {
        "name": "validate_blueprint",
        "description": "Validate a blueprint YAML.",
        "input_schema": {
            "type": "object",
            "properties": {"yaml_text": {"type": "string"}},
            "required": ["yaml_text"],
        },
    }
]

ANTHROPIC_MESSAGES = [
    {"role": "user", "content": "Build me an image on aws."},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Starting validation..."},
            {
                "type": "tool_use",
                "id": "tu_001",
                "name": "validate_blueprint",
                "input": {"yaml_text": "kind: HardeningBlueprint"},
            },
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tu_001",
                "content": json.dumps({"valid": True, "profile_name": "test"}),
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# OpenAI tool schema conversion
# ---------------------------------------------------------------------------


class TestToolsToOpenAI:
    def test_wraps_in_function_type(self):
        result = _tools_to_openai(SAMPLE_TOOLS)
        assert result[0]["type"] == "function"

    def test_moves_input_schema_to_parameters(self):
        result = _tools_to_openai(SAMPLE_TOOLS)
        fn = result[0]["function"]
        assert "parameters" in fn
        assert fn["parameters"]["properties"]["yaml_text"]["type"] == "string"
        assert "input_schema" not in fn

    def test_preserves_name_and_description(self):
        result = _tools_to_openai(SAMPLE_TOOLS)
        fn = result[0]["function"]
        assert fn["name"] == "validate_blueprint"
        assert "Validate" in fn["description"]

    def test_empty_tools(self):
        assert _tools_to_openai([]) == []


# ---------------------------------------------------------------------------
# OpenAI message format conversion
# ---------------------------------------------------------------------------


class TestMessagesToOpenAI:
    def test_system_is_first_message(self):
        result = _messages_to_openai_clean([], "You are an agent.")
        assert result[0] == {"role": "system", "content": "You are an agent."}

    def test_plain_user_string_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _messages_to_openai_clean(msgs, "sys")
        user_msgs = [m for m in result if m["role"] == "user"]
        assert user_msgs[0]["content"] == "hello"

    def test_assistant_tool_use_becomes_tool_calls(self):
        result = _messages_to_openai_clean(ANTHROPIC_MESSAGES, "sys")
        asst = next(m for m in result if m["role"] == "assistant")
        assert "tool_calls" in asst
        assert asst["tool_calls"][0]["function"]["name"] == "validate_blueprint"

    def test_tool_result_becomes_tool_role_message(self):
        result = _messages_to_openai_clean(ANTHROPIC_MESSAGES, "sys")
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tu_001"

    def test_tool_result_content_is_string(self):
        result = _messages_to_openai_clean(ANTHROPIC_MESSAGES, "sys")
        tool_msg = next(m for m in result if m["role"] == "tool")
        assert isinstance(tool_msg["content"], str)

    def test_assistant_arguments_are_json_string(self):
        result = _messages_to_openai_clean(ANTHROPIC_MESSAGES, "sys")
        asst = next(m for m in result if m["role"] == "assistant")
        args = asst["tool_calls"][0]["function"]["arguments"]
        parsed = json.loads(args)
        assert parsed["yaml_text"] == "kind: HardeningBlueprint"


# ---------------------------------------------------------------------------
# Bedrock tool schema conversion
# ---------------------------------------------------------------------------


class TestToolsToBedrock:
    def test_wraps_in_tool_spec(self):
        result = _tools_to_bedrock(SAMPLE_TOOLS)
        assert "toolSpec" in result[0]

    def test_input_schema_wrapped_in_json_key(self):
        result = _tools_to_bedrock(SAMPLE_TOOLS)
        schema = result[0]["toolSpec"]["inputSchema"]
        assert "json" in schema
        assert schema["json"]["properties"]["yaml_text"]["type"] == "string"

    def test_empty_tools(self):
        assert _tools_to_bedrock([]) == []


# ---------------------------------------------------------------------------
# Bedrock message format conversion
# ---------------------------------------------------------------------------


class TestMessagesToBedrock:
    def test_plain_string_content(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _messages_to_bedrock(msgs)
        assert result[0]["content"] == [{"text": "hello"}]

    def test_text_block(self):
        msgs = [{"role": "assistant", "content": [{"type": "text", "text": "thinking..."}]}]
        result = _messages_to_bedrock(msgs)
        assert result[0]["content"] == [{"text": "thinking..."}]

    def test_tool_use_block(self):
        result = _messages_to_bedrock(ANTHROPIC_MESSAGES)
        asst = next(m for m in result if m["role"] == "assistant")
        tool_block = next(b for b in asst["content"] if "toolUse" in b)
        assert tool_block["toolUse"]["toolUseId"] == "tu_001"
        assert tool_block["toolUse"]["name"] == "validate_blueprint"

    def test_tool_result_block(self):
        result = _messages_to_bedrock(ANTHROPIC_MESSAGES)
        user_with_result = next(
            m
            for m in result
            if m["role"] == "user" and any("toolResult" in b for b in m["content"] if isinstance(b, dict))
        )
        tr = next(b["toolResult"] for b in user_with_result["content"] if "toolResult" in b)
        assert tr["toolUseId"] == "tu_001"
        assert tr["content"][0]["json"]["valid"] is True

    def test_invalid_tool_result_json_falls_back(self):
        msgs = [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "x1", "content": "not-json"}],
            }
        ]
        result = _messages_to_bedrock(msgs)
        tr = result[0]["content"][0]["toolResult"]
        assert tr["content"][0]["json"] == {"raw": "not-json"}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_default_provider_is_anthropic(self, monkeypatch):
        monkeypatch.delenv("BAKEX_LLM_PROVIDER", raising=False)
        from bakex.core.llm.anthropic_backend import AnthropicBackend

        backend = get_backend()
        assert isinstance(backend, AnthropicBackend)

    def test_openai_provider(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "openai")
        from bakex.core.llm.openai_backend import OpenAICompatBackend

        backend = get_backend()
        assert isinstance(backend, OpenAICompatBackend)

    def test_ollama_provider_uses_openai_compat(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "ollama")
        from bakex.core.llm.openai_backend import OpenAICompatBackend

        backend = get_backend()
        assert isinstance(backend, OpenAICompatBackend)
        assert "11434" in backend.base_url

    def test_bedrock_provider(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "bedrock")
        from bakex.core.llm.bedrock_backend import BedrockBackend

        backend = get_backend()
        assert isinstance(backend, BedrockBackend)

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "grok")
        with pytest.raises(ValueError, match="Unknown BAKEX_LLM_PROVIDER"):
            get_backend()

    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("BAKEX_LLM_MODEL", "claude-haiku-4-5-20251001")
        backend = get_backend()
        assert backend.model == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# provider_status
# ---------------------------------------------------------------------------


class TestProviderStatus:
    def test_anthropic_without_key(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        status = provider_status()
        assert status["available"] is False
        assert status["provider"] == "anthropic"

    def test_anthropic_with_key(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        status = provider_status()
        assert status["available"] is True

    def test_ollama_always_available(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "ollama")
        status = provider_status()
        assert status["available"] is True

    def test_openai_without_key(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "openai")
        monkeypatch.delenv("BAKEX_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        status = provider_status()
        assert status["available"] is False

    def test_bedrock_with_aws_profile(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "bedrock")
        monkeypatch.setenv("AWS_PROFILE", "default")
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        status = provider_status()
        assert status["available"] is True

    def test_status_includes_model(self, monkeypatch):
        monkeypatch.setenv("BAKEX_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("BAKEX_LLM_MODEL", "claude-sonnet-4-6")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        status = provider_status()
        assert status["model"] == "claude-sonnet-4-6"
