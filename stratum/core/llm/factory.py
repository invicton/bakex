# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Factory that returns the configured LLM backend.

Control via env vars:

  STRATUM_LLM_PROVIDER  — anthropic (default) | openai | ollama | bedrock
  STRATUM_LLM_MODEL     — model override (provider-specific default if unset)
  STRATUM_LLM_API_KEY   — API key for openai-compatible backends
  STRATUM_LLM_BASE_URL  — base URL for openai-compatible backends
  STRATUM_LLM_THINKING  — "0" to disable Claude extended thinking (default: "1")

Provider defaults:
  anthropic  →  claude-opus-4-6           (ANTHROPIC_API_KEY)
  openai     →  gpt-4o                    (STRATUM_LLM_API_KEY or OPENAI_API_KEY)
  ollama     →  llama3.3:70b              (no key; needs Ollama running locally)
  bedrock    →  us.anthropic.claude-opus-4-5-20251101-v1:0  (AWS credentials)
"""

from __future__ import annotations

import os

from .base import LLMBackend


def get_backend() -> LLMBackend:
    provider = os.environ.get("STRATUM_LLM_PROVIDER", "anthropic").lower()

    if provider == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend()

    if provider == "openai":
        from .openai_backend import OpenAICompatBackend

        return OpenAICompatBackend()

    if provider == "ollama":
        from .openai_backend import OpenAICompatBackend

        return OpenAICompatBackend(
            model=os.environ.get("STRATUM_LLM_MODEL", "llama3.3:70b"),
            base_url=os.environ.get("STRATUM_LLM_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.environ.get("STRATUM_LLM_API_KEY", "ollama"),
        )

    if provider == "bedrock":
        from .bedrock_backend import BedrockBackend

        return BedrockBackend()

    raise ValueError(f"Unknown STRATUM_LLM_PROVIDER: {provider!r}. Valid values: anthropic, openai, ollama, bedrock")


def provider_status() -> dict:
    """Return availability info for the configured provider (used by /api/agent/status)."""
    provider = os.environ.get("STRATUM_LLM_PROVIDER", "anthropic").lower()
    model = os.environ.get("STRATUM_LLM_MODEL", "")

    if provider == "anthropic":
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        effective_model = model or "claude-opus-4-6"
        return {
            "available": has_key,
            "provider": "anthropic",
            "model": effective_model,
            "message": (
                f"AI Builder is ready (Anthropic / {effective_model})."
                if has_key
                else "Set ANTHROPIC_API_KEY in your .env file to enable the AI Builder."
            ),
        }

    if provider == "openai":
        has_key = bool(os.environ.get("STRATUM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))
        effective_model = model or "gpt-4o"
        return {
            "available": has_key,
            "provider": "openai",
            "model": effective_model,
            "message": (
                f"AI Builder is ready (OpenAI / {effective_model})."
                if has_key
                else "Set STRATUM_LLM_API_KEY (or OPENAI_API_KEY) in your .env file."
            ),
        }

    if provider == "ollama":
        effective_model = model or "llama3.3:70b"
        base_url = os.environ.get("STRATUM_LLM_BASE_URL", "http://localhost:11434/v1")
        return {
            "available": True,  # no key check needed; failure surfaces at runtime
            "provider": "ollama",
            "model": effective_model,
            "message": f"AI Builder configured for Ollama ({effective_model} at {base_url}). Ensure Ollama is running.",
        }

    if provider == "bedrock":
        has_creds = bool(
            os.environ.get("AWS_ACCESS_KEY_ID")
            or os.environ.get("AWS_PROFILE")
            or os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")  # ECS task role
            or os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")  # IRSA / OIDC
        )
        effective_model = model or "us.anthropic.claude-opus-4-5-20251101-v1:0"
        return {
            "available": has_creds,
            "provider": "bedrock",
            "model": effective_model,
            "message": (
                f"AI Builder is ready (Bedrock / {effective_model})."
                if has_creds
                else "AWS credentials not found. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY or AWS_PROFILE."
            ),
        }

    return {
        "available": False,
        "provider": provider,
        "model": model,
        "message": f"Unknown STRATUM_LLM_PROVIDER: {provider!r}. Valid: anthropic, openai, ollama, bedrock",
    }
