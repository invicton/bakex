# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/webhooks endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# WH-API-01: POST valid URL + event → 201, secret in response
# ---------------------------------------------------------------------------


def test_create_webhook_returns_201_with_secret(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["scan.complete"],
            "label": "my-hook",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "secret" in body, "Secret must be returned on creation"
    assert len(body["secret"]) > 0


# ---------------------------------------------------------------------------
# WH-API-02: POST with invalid event name → 422 with valid events listed
# ---------------------------------------------------------------------------


def test_create_webhook_invalid_event_returns_422(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["not.a.real.event"],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Unknown events" in detail or "not.a.real.event" in detail


# ---------------------------------------------------------------------------
# WH-API-03: POST with non-http URL → 422
# ---------------------------------------------------------------------------


def test_create_webhook_invalid_url_returns_422(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "ftp://not-allowed.com/hook",
            "events": ["scan.complete"],
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WH-API-03b: POST with relative URL → 422
# ---------------------------------------------------------------------------


def test_create_webhook_relative_url_returns_422(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "/relative/path",
            "events": ["scan.complete"],
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WH-API-03c: POST with a URL resolving to the cloud metadata IP → 422 (SSRF)
# ---------------------------------------------------------------------------


def test_create_webhook_ssrf_target_returns_422(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "http://169.254.169.254/latest/meta-data/",
            "events": ["scan.complete"],
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WH-API-04: GET after creating → secret absent from list items
# ---------------------------------------------------------------------------


def test_list_webhooks_omits_secret(client):
    client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["scan.complete"],
        },
    )
    resp = client.get("/api/webhooks")
    assert resp.status_code == 200
    hooks = resp.json()
    assert len(hooks) == 1
    assert "secret" not in hooks[0], "Secret must not be exposed in list"


# ---------------------------------------------------------------------------
# WH-API-05: DELETE existing webhook → 204
# ---------------------------------------------------------------------------


def test_delete_existing_webhook_returns_204(client):
    create_resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["build.complete"],
        },
    )
    hook_id = create_resp.json()["id"]

    resp = client.delete(f"/api/webhooks/{hook_id}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# WH-API-05b: DELETE then GET → hook no longer listed
# ---------------------------------------------------------------------------


def test_deleted_webhook_absent_from_list(client):
    create_resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["scan.failed"],
        },
    )
    hook_id = create_resp.json()["id"]
    client.delete(f"/api/webhooks/{hook_id}")

    hooks = client.get("/api/webhooks").json()
    assert all(h["id"] != hook_id for h in hooks)


# ---------------------------------------------------------------------------
# WH-API-06: DELETE nonexistent webhook → 404
# ---------------------------------------------------------------------------


def test_delete_nonexistent_webhook_returns_404(client):
    resp = client.delete("/api/webhooks/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WH-API-07: POST /{id}/test → 200, fired=true
# ---------------------------------------------------------------------------


def test_test_webhook_fires_and_returns_200(client):
    create_resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["scan.complete"],
        },
    )
    hook_id = create_resp.json()["id"]

    with patch("bakex.api.webhooks.fire_webhook", new=AsyncMock(return_value=None)):
        resp = client.post(f"/api/webhooks/{hook_id}/test")

    assert resp.status_code == 200
    body = resp.json()
    assert body["fired"] is True
    assert body["hook_id"] == hook_id


# ---------------------------------------------------------------------------
# WH-API-08: POST /{id}/test on nonexistent hook → 404
# ---------------------------------------------------------------------------


def test_test_nonexistent_webhook_returns_404(client):
    with patch("bakex.api.webhooks.fire_webhook", new=AsyncMock(return_value=None)):
        resp = client.post("/api/webhooks/does-not-exist/test")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Extra: GET on fresh store → empty list
# ---------------------------------------------------------------------------


def test_list_webhooks_empty_on_fresh_store(client):
    resp = client.get("/api/webhooks")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Extra: multiple events accepted
# ---------------------------------------------------------------------------


def test_create_webhook_multiple_events(client):
    resp = client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["scan.complete", "build.complete", "scan.failed"],
        },
    )
    assert resp.status_code == 201
    assert set(resp.json()["events"]) == {"scan.complete", "build.complete", "scan.failed"}
