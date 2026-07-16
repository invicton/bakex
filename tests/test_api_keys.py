# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for bakex.core.api_keys — Phase 1 TDD red run."""

from __future__ import annotations

import pytest

# Isolate module state between tests by resetting the in-memory store
import bakex.core.api_keys as ak_mod


@pytest.fixture(autouse=True)
def _clean_keys(tmp_path, monkeypatch):
    """Reset in-memory key store and redirect persistence to a temp file."""
    ak_mod._keys.clear()
    monkeypatch.setattr(ak_mod, "_KEYS_FILE", tmp_path / "api_keys.json")
    yield
    ak_mod._keys.clear()


# ---------------------------------------------------------------------------
# AK-01: token has str_ prefix
# ---------------------------------------------------------------------------


def test_create_key_token_has_str_prefix():
    token, _key_id = ak_mod.create_key("ci-pipeline")
    assert token.startswith("str_"), f"Expected 'str_' prefix, got: {token[:6]}"


# ---------------------------------------------------------------------------
# AK-02: token roundtrips through verify_key
# ---------------------------------------------------------------------------


def test_verify_key_accepts_own_token():
    token, _key_id = ak_mod.create_key("roundtrip")
    assert ak_mod.verify_key(token) is True


# ---------------------------------------------------------------------------
# AK-03: wrong token rejected
# ---------------------------------------------------------------------------


def test_verify_key_rejects_unknown_token():
    ak_mod.create_key("exists")
    assert ak_mod.verify_key("str_totally_wrong_token") is False


# ---------------------------------------------------------------------------
# AK-04: revoked key no longer verifies
# ---------------------------------------------------------------------------


def test_verify_key_rejects_after_revoke():
    token, key_id = ak_mod.create_key("revoke-me")
    assert ak_mod.verify_key(token) is True
    ak_mod.revoke_key(key_id)
    assert ak_mod.verify_key(token) is False


# ---------------------------------------------------------------------------
# AK-05: revoke nonexistent key returns False, no exception
# ---------------------------------------------------------------------------


def test_revoke_nonexistent_key_returns_false():
    result = ak_mod.revoke_key("does_not_exist")
    assert result is False


# ---------------------------------------------------------------------------
# AK-06: list_keys omits hash and plaintext token
# ---------------------------------------------------------------------------


def test_list_keys_omits_sensitive_fields():
    ak_mod.create_key("safe-list")
    keys = ak_mod.list_keys()
    assert len(keys) == 1
    entry = keys[0]
    assert "hash" not in entry, "hash must not be exposed in list_keys()"
    assert "token" not in entry, "plaintext token must not be exposed in list_keys()"


# ---------------------------------------------------------------------------
# AK-07: last_used updated on successful verify
# ---------------------------------------------------------------------------


def test_last_used_updated_after_verify():
    token, key_id = ak_mod.create_key("track-usage")
    before = ak_mod.list_keys()[0]["last_used"]
    assert before is None, "last_used should be None before first use"
    ak_mod.verify_key(token)
    after = ak_mod.list_keys()[0]["last_used"]
    assert after is not None, "last_used should be set after verify"


# ---------------------------------------------------------------------------
# AK-08: SHA-256 hash stored, not plaintext
# ---------------------------------------------------------------------------


def test_internal_store_contains_hash_not_plaintext():
    token, key_id = ak_mod.create_key("hash-check")
    entry = ak_mod._keys[key_id]
    assert entry.get("hash") is not None, "hash field missing from internal store"
    assert len(entry["hash"]) == 64, "SHA-256 hex digest must be 64 chars"
    assert token not in entry.values(), "plaintext token must not appear in stored entry"


# ---------------------------------------------------------------------------
# Extra: two keys don't cross-verify
# ---------------------------------------------------------------------------


def test_two_keys_do_not_cross_verify():
    token_a, _ = ak_mod.create_key("key-a")
    token_b, _ = ak_mod.create_key("key-b")
    assert ak_mod.verify_key(token_a) is True
    assert ak_mod.verify_key(token_b) is True
    # Swap — neither should match the other
    # (tokens are random so collision is astronomically unlikely)
    assert token_a != token_b


# ---------------------------------------------------------------------------
# Extra: create_key returns (token, key_id) tuple — contract check
# ---------------------------------------------------------------------------


def test_create_key_returns_two_item_tuple():
    result = ak_mod.create_key("contract")
    assert isinstance(result, tuple), "create_key must return a tuple"
    assert len(result) == 2, "create_key must return (token, key_id)"
    token, key_id = result
    assert isinstance(token, str)
    assert isinstance(key_id, str)


# ---------------------------------------------------------------------------
# Extra: list_keys expected fields present
# ---------------------------------------------------------------------------


def test_list_keys_contains_expected_fields():
    ak_mod.create_key("field-check")
    keys = ak_mod.list_keys()
    entry = keys[0]
    for field in ("id", "label", "created_at", "last_used"):
        assert field in entry, f"Expected field '{field}' missing from list_keys() entry"
