# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Security tests for API key storage and verification (SEC-04–SEC-07)."""

from __future__ import annotations

import secrets

import pytest

import stratum.core.api_keys as ak_mod


@pytest.fixture(autouse=True)
def _clean_keys(tmp_path, monkeypatch):
    ak_mod._keys.clear()
    monkeypatch.setattr(ak_mod, "_KEYS_FILE", tmp_path / "api_keys.json")
    yield
    ak_mod._keys.clear()


# ---------------------------------------------------------------------------
# SEC-04: Plaintext token never stored in _keys dict
# ---------------------------------------------------------------------------


def test_plaintext_token_never_stored():
    """The raw token must never appear as any value in the internal key store."""
    token, key_id = ak_mod.create_key("sec-04")
    entry = ak_mod._keys[key_id]
    # Check every value in the entry — none may equal the plaintext token
    for field, value in entry.items():
        assert value != token, f"Plaintext token found in _keys['{key_id}']['{field}'] — must not be stored"


# ---------------------------------------------------------------------------
# SEC-05: list_keys() response contains no "hash" field
# ---------------------------------------------------------------------------


def test_list_keys_exposes_no_hash_field():
    """The public list_keys() API must never expose the SHA-256 hash."""
    ak_mod.create_key("sec-05")
    for entry in ak_mod.list_keys():
        assert "hash" not in entry, "list_keys() must not expose the 'hash' field"


# ---------------------------------------------------------------------------
# SEC-06: Stripping the "str_" prefix makes the token invalid
# ---------------------------------------------------------------------------


def test_token_without_prefix_fails_verification():
    """The SHA-256 hash is computed on the full 'str_XXXX' token.
    Verifying with just the suffix (no prefix) must fail."""
    token, _key_id = ak_mod.create_key("sec-06")
    assert token.startswith("str_"), "Precondition: token must have str_ prefix"
    stripped = token[4:]  # remove "str_" prefix
    assert ak_mod.verify_key(stripped) is False, (
        "Token without 'str_' prefix must not verify — hash covers the full token"
    )


# ---------------------------------------------------------------------------
# SEC-07: A short brute-forced token is rejected
# ---------------------------------------------------------------------------


def test_short_random_token_rejected():
    """An 8-character random string must not pass verification."""
    ak_mod.create_key("sec-07")
    brute = secrets.token_urlsafe(6)[:8]  # short candidate
    assert ak_mod.verify_key(brute) is False, (
        f"Short brute-forced token '{brute}' must not verify against any stored key"
    )
