# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Security tests for HMAC webhook signature verification (SEC-01–SEC-03)."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import stratum.core.notifications as notif_mod


@pytest.fixture(autouse=True)
def _clean_webhooks(tmp_path, monkeypatch):
    notif_mod._webhooks.clear()
    monkeypatch.setattr(notif_mod, "_WEBHOOKS_FILE", tmp_path / "webhooks.json")
    yield
    notif_mod._webhooks.clear()


def _compute_sig(secret: str, body: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# SEC-01: Tampered payload body changes the signature
# ---------------------------------------------------------------------------


def test_tampered_body_invalidates_signature():
    """Changing even one byte of the body must produce a different signature."""
    secret = "super-secret-key"
    original_body = json.dumps({"event": "scan.complete", "job_id": "abc"})
    tampered_body = json.dumps({"event": "scan.complete", "job_id": "xyz"})

    original_sig = _compute_sig(secret, original_body)
    tampered_sig = _compute_sig(secret, tampered_body)

    assert original_sig != tampered_sig, "Tampered body must produce a different HMAC signature"
    assert not hmac.compare_digest(original_sig, tampered_sig)


# ---------------------------------------------------------------------------
# SEC-02: Wrong secret produces a different (non-matching) signature
# ---------------------------------------------------------------------------


def test_wrong_secret_produces_different_signature():
    """HMAC computed with the wrong secret must not match the original."""
    correct_secret = "correct-secret-24chars-long!"
    wrong_secret = "wrong-secret-24chars-long!!"
    body = json.dumps({"event": "scan.complete", "job_id": "abc"})

    correct_sig = _compute_sig(correct_secret, body)
    wrong_sig = _compute_sig(wrong_secret, body)

    assert not hmac.compare_digest(correct_sig, wrong_sig), "Wrong secret must not produce a matching HMAC signature"


# ---------------------------------------------------------------------------
# SEC-03: Signature header starts with "sha256="
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_signature_header_has_sha256_prefix():
    """The X-Stratum-Signature header must start with 'sha256='."""
    notif_mod.register_webhook("https://example.com/hook", ["scan.complete"])

    captured_headers: dict = {}

    async def mock_post(url, *, content, headers, **kwargs):
        captured_headers.update(headers)
        return MagicMock(status_code=200)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("stratum.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        await notif_mod.fire_webhook("scan.complete", {"job_id": "sec-03"})

    assert "X-Stratum-Signature" in captured_headers, "X-Stratum-Signature header must be present"
    sig = captured_headers["X-Stratum-Signature"]
    assert sig.startswith("sha256="), f"Signature must start with 'sha256=', got: {sig[:20]!r}"
    # Verify the hex portion is a valid 64-char SHA-256 digest
    hex_part = sig[len("sha256=") :]
    assert len(hex_part) == 64, f"SHA-256 hex digest must be 64 chars, got {len(hex_part)}"
    assert all(c in "0123456789abcdef" for c in hex_part), "Hex portion of signature must be lowercase hex"
