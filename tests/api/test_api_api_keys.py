# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/api-keys endpoints."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AK-API-01: POST with valid label → 201 + token/id/label
# ---------------------------------------------------------------------------


def test_create_key_returns_201_with_fields(client):
    resp = client.post("/api/api-keys", json={"label": "my-key"})
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "label" in body
    assert "token" in body
    assert body["label"] == "my-key"
    assert body["token"].startswith("str_")


# ---------------------------------------------------------------------------
# AK-API-02: POST with empty label → 422
# ---------------------------------------------------------------------------


def test_create_key_empty_label_returns_422(client):
    resp = client.post("/api/api-keys", json={"label": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AK-API-03: POST with whitespace-only label → 422
# ---------------------------------------------------------------------------


def test_create_key_whitespace_label_returns_422(client):
    resp = client.post("/api/api-keys", json={"label": "   "})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AK-API-04: GET after creating two keys → list with 2 items, no token/hash
# ---------------------------------------------------------------------------


def test_list_keys_after_two_creates(client):
    client.post("/api/api-keys", json={"label": "key-one"})
    client.post("/api/api-keys", json={"label": "key-two"})

    resp = client.get("/api/api-keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 2

    for entry in keys:
        assert "token" not in entry, "token must not be exposed in list"
        assert "hash" not in entry, "hash must not be exposed in list"
        assert "id" in entry
        assert "label" in entry


# ---------------------------------------------------------------------------
# AK-API-05: DELETE existing key → 204
# ---------------------------------------------------------------------------


def test_delete_existing_key_returns_204(client):
    create_resp = client.post("/api/api-keys", json={"label": "delete-me"})
    key_id = create_resp.json()["id"]

    resp = client.delete(f"/api/api-keys/{key_id}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# AK-API-05b: DELETE then GET → key no longer in list
# ---------------------------------------------------------------------------


def test_deleted_key_absent_from_list(client):
    create_resp = client.post("/api/api-keys", json={"label": "gone"})
    key_id = create_resp.json()["id"]
    client.delete(f"/api/api-keys/{key_id}")

    keys = client.get("/api/api-keys").json()
    assert all(k["id"] != key_id for k in keys)


# ---------------------------------------------------------------------------
# AK-API-06: DELETE nonexistent key → 404
# ---------------------------------------------------------------------------


def test_delete_nonexistent_key_returns_404(client):
    resp = client.delete("/api/api-keys/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Extra: GET on fresh store → empty list
# ---------------------------------------------------------------------------


def test_list_keys_empty_on_fresh_store(client):
    resp = client.get("/api/api-keys")
    assert resp.status_code == 200
    assert resp.json() == []
