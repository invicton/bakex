# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for file-persistence paths in api_keys and notifications.

Covers the previously uncovered lines:
  api_keys.py     lines 24-25  (_persist write failure → warning)
  api_keys.py     lines 31-35  (load_keys corrupt JSON → warning)
  notifications.py lines 32-33 (_persist write failure → warning)
  notifications.py lines 39-43 (load_webhooks corrupt JSON → warning)
  notifications.py lines 84-85 (fire_webhook httpx=None path)
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

import statim.core.api_keys as ak_mod
import statim.core.notifications as notif_mod

# ---------------------------------------------------------------------------
# api_keys — _persist failure (lines 24-25)
# ---------------------------------------------------------------------------


def test_persist_api_keys_logs_warning_on_write_error(tmp_path, caplog):
    """If the data directory can't be written, _persist logs a warning."""
    orig_file = ak_mod._KEYS_FILE
    ak_mod._KEYS_FILE = tmp_path / "no_dir" / "api_keys.json"

    # Make mkdir raise PermissionError
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
        with caplog.at_level(logging.WARNING, logger="statim.core.api_keys"):
            ak_mod._persist()

    ak_mod._KEYS_FILE = orig_file
    assert any("Could not persist API keys" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# api_keys — load_keys corrupt file (lines 31-35)
# ---------------------------------------------------------------------------


def test_load_keys_logs_warning_on_corrupt_json(tmp_path, caplog):
    """load_keys must log a warning and not raise when the file has invalid JSON."""
    keys_file = tmp_path / "api_keys.json"
    keys_file.write_text("{corrupt json{{")

    orig_file = ak_mod._KEYS_FILE
    ak_mod._KEYS_FILE = keys_file

    with caplog.at_level(logging.WARNING, logger="statim.core.api_keys"):
        ak_mod.load_keys()

    ak_mod._KEYS_FILE = orig_file
    assert any("Could not load API keys" in r.message for r in caplog.records)


def test_load_keys_populates_store_from_valid_file(tmp_path):
    """load_keys reads a valid JSON file and populates the in-memory store."""
    data = {
        "abc123": {
            "label": "ci-key",
            "hash": "deadbeef",
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used": None,
        }
    }
    keys_file = tmp_path / "api_keys.json"
    keys_file.write_text(json.dumps(data))

    orig_file = ak_mod._KEYS_FILE
    orig_keys = dict(ak_mod._keys)
    ak_mod._keys.clear()
    ak_mod._KEYS_FILE = keys_file

    ak_mod.load_keys()

    assert "abc123" in ak_mod._keys
    assert ak_mod._keys["abc123"]["label"] == "ci-key"

    # Restore state
    ak_mod._keys.clear()
    ak_mod._keys.update(orig_keys)
    ak_mod._KEYS_FILE = orig_file


# ---------------------------------------------------------------------------
# notifications — _persist failure (lines 32-33)
# ---------------------------------------------------------------------------


def test_persist_webhooks_logs_warning_on_write_error(tmp_path, caplog):
    """If the data directory can't be written, _persist logs a warning."""
    orig_file = notif_mod._WEBHOOKS_FILE
    notif_mod._WEBHOOKS_FILE = tmp_path / "no_dir" / "webhooks.json"

    with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
        with caplog.at_level(logging.WARNING, logger="statim.core.notifications"):
            notif_mod._persist()

    notif_mod._WEBHOOKS_FILE = orig_file
    assert any("Could not persist webhooks" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# notifications — load_webhooks corrupt file (lines 39-43)
# ---------------------------------------------------------------------------


def test_load_webhooks_logs_warning_on_corrupt_json(tmp_path, caplog):
    """load_webhooks must log a warning and not raise on invalid JSON."""
    hooks_file = tmp_path / "webhooks.json"
    hooks_file.write_text("{not: valid: json")

    orig_file = notif_mod._WEBHOOKS_FILE
    notif_mod._WEBHOOKS_FILE = hooks_file

    with caplog.at_level(logging.WARNING, logger="statim.core.notifications"):
        notif_mod.load_webhooks()

    notif_mod._WEBHOOKS_FILE = orig_file
    assert any("Could not load webhooks" in r.message for r in caplog.records)


def test_load_webhooks_populates_store_from_valid_file(tmp_path):
    """load_webhooks reads a valid JSON file and populates the in-memory store."""
    hook_id = "hook001"
    data = {
        hook_id: {
            "id": hook_id,
            "url": "https://example.com/hook",
            "label": "test",
            "events": ["scan.complete"],
            "secret": "s3cr3t",
            "enabled": True,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    }
    hooks_file = tmp_path / "webhooks.json"
    hooks_file.write_text(json.dumps(data))

    orig_file = notif_mod._WEBHOOKS_FILE
    orig_hooks = dict(notif_mod._webhooks)
    notif_mod._webhooks.clear()
    notif_mod._WEBHOOKS_FILE = hooks_file

    notif_mod.load_webhooks()

    assert hook_id in notif_mod._webhooks

    notif_mod._webhooks.clear()
    notif_mod._webhooks.update(orig_hooks)
    notif_mod._WEBHOOKS_FILE = orig_file


# ---------------------------------------------------------------------------
# notifications — fire_webhook with httpx=None (lines 84-85)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_logs_warning_when_httpx_none(caplog):
    """When httpx module is None (not installed), fire_webhook logs a warning."""
    notif_mod._webhooks.clear()
    notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])

    with patch.object(notif_mod, "httpx", None):
        with caplog.at_level(logging.WARNING, logger="statim.core.notifications"):
            await notif_mod.fire_webhook("scan.complete", {"job_id": "test"})

    notif_mod._webhooks.clear()
    assert any("httpx not available" in r.message for r in caplog.records)
