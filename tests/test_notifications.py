# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for stratum.core.notifications — Phase 1 TDD red run."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import stratum.core.notifications as notif_mod


@pytest.fixture(autouse=True)
def _clean_webhooks(tmp_path, monkeypatch):
    """Reset in-memory webhook store and redirect persistence to a temp file."""
    notif_mod._webhooks.clear()
    monkeypatch.setattr(notif_mod, "_WEBHOOKS_FILE", tmp_path / "webhooks.json")
    yield
    notif_mod._webhooks.clear()


# ---------------------------------------------------------------------------
# WH-01: register_webhook returns entry with secret
# ---------------------------------------------------------------------------


def test_register_returns_secret():
    entry = notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])
    assert "secret" in entry, "register_webhook must return secret in response"
    assert len(entry["secret"]) > 0


# ---------------------------------------------------------------------------
# WH-02: list_webhooks omits secret
# ---------------------------------------------------------------------------


def test_list_webhooks_omits_secret():
    notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])
    listed = notif_mod.list_webhooks()
    assert len(listed) == 1
    assert "secret" not in listed[0], "list_webhooks must not expose the secret"


# ---------------------------------------------------------------------------
# WH-03: remove_webhook on nonexistent ID returns False
# ---------------------------------------------------------------------------


def test_remove_nonexistent_returns_false():
    result = notif_mod.remove_webhook("does_not_exist")
    assert result is False


# ---------------------------------------------------------------------------
# WH-04: invalid event filtered out on registration
# ---------------------------------------------------------------------------


def test_invalid_event_filtered_on_register():
    entry = notif_mod.register_webhook(
        "https://example.com/hook",
        ["scan.complete", "not.real.event"],
    )
    assert "scan.complete" in entry["events"]
    assert "not.real.event" not in entry["events"], "Invalid events must be filtered out"


# ---------------------------------------------------------------------------
# WH-05: HMAC-SHA256 signature header is correct
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_hmac_signature_correct():
    entry = notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])
    secret = entry["secret"]

    captured_headers = {}
    captured_body = {}

    async def mock_post(url, *, content, headers, **kwargs):
        captured_headers.update(headers)
        captured_body["raw"] = content
        response = MagicMock()
        response.status_code = 200
        return response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("scan.complete", {"job_id": "test-001"})

    assert "X-Stratum-Signature" in captured_headers, "X-Stratum-Signature header missing"

    sig_header = captured_headers["X-Stratum-Signature"]
    assert sig_header.startswith("sha256="), "Signature must start with 'sha256='"

    body_bytes = captured_body["raw"].encode() if isinstance(captured_body["raw"], str) else captured_body["raw"]
    expected_sig = "sha256=" + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    assert sig_header == expected_sig, f"HMAC mismatch.\nGot:      {sig_header}\nExpected: {expected_sig}"


# ---------------------------------------------------------------------------
# WH-06: fire_webhook only fires to subscribed events
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_only_fires_to_subscribed():
    notif_mod.register_webhook("https://scan-hook.example.com", ["scan.complete"])
    notif_mod.register_webhook("https://build-hook.example.com", ["build.complete"])

    fired_urls = []

    async def mock_post(url, **kwargs):
        fired_urls.append(url)
        return MagicMock(status_code=200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("scan.complete", {"job_id": "x"})

    assert len(fired_urls) == 1, f"Expected 1 webhook fired, got {len(fired_urls)}"
    assert "scan-hook" in fired_urls[0]


# ---------------------------------------------------------------------------
# WH-07: disabled webhook does not receive POST
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_disabled_webhook_not_fired():
    entry = notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])
    hook_id = entry["id"]
    notif_mod._webhooks[hook_id]["enabled"] = False

    fired = []

    async def mock_post(url, **kwargs):
        fired.append(url)
        return MagicMock(status_code=200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("scan.complete", {"job_id": "x"})

    assert fired == [], "Disabled webhook must not receive any POST"


# ---------------------------------------------------------------------------
# WH-08: fire_webhook swallows HTTP errors, does not raise
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_swallows_connection_error():
    notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])

    async def mock_post(url, **kwargs):
        raise ConnectionError("simulated network failure")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        # Must not raise — fire_webhook is best-effort
        await notif_mod.fire_webhook("scan.complete", {"job_id": "x"})


# ---------------------------------------------------------------------------
# WH-09: payload includes event name and timestamp
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_payload_contains_event_and_timestamp():
    notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])

    received_body = {}

    async def mock_post(url, *, content, **kwargs):
        received_body.update(json.loads(content))
        return MagicMock(status_code=200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("scan.complete", {"job_id": "test-999"})

    assert "event" in received_body, "Payload must contain 'event' key"
    assert received_body["event"] == "scan.complete"
    assert "timestamp" in received_body, "Payload must contain 'timestamp' key"


# ---------------------------------------------------------------------------
# Extra: X-Stratum-Event header matches fired event
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_event_header_matches():
    notif_mod.register_webhook("https://example.com/hook", ["build.complete"])

    captured_headers = {}

    async def mock_post(url, *, headers, **kwargs):
        captured_headers.update(headers)
        return MagicMock(status_code=200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("build.complete", {"build_id": "b-1"})

    assert captured_headers.get("X-Stratum-Event") == "build.complete"


# ---------------------------------------------------------------------------
# Extra: no registered webhooks — fire is a no-op, no httpx imported
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_noop_when_no_matching_webhooks():
    """fire_webhook should return silently when there are no matching subscribers."""
    # No webhooks registered — should not import or call httpx at all
    with patch("stratum.core.notifications.httpx", side_effect=AssertionError("httpx must not be called")):
        await notif_mod.fire_webhook("scan.complete", {"job_id": "x"})
