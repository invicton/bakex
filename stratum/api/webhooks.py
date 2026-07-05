# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Webhook management API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stratum.core.notifications import (
    VALID_EVENTS,
    fire_webhook,
    is_safe_webhook_url,
    list_webhooks,
    register_webhook,
    remove_webhook,
)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: str
    events: list[str]
    label: str = ""


@router.post("", status_code=201)
async def create_webhook(body: WebhookCreate) -> dict:
    """Register a new webhook. Returns entry including secret (shown once)."""
    invalid = [e for e in body.events if e not in VALID_EVENTS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown events: {invalid}. Valid: {sorted(VALID_EVENTS)}")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must start with http:// or https://")
    safe, reason = is_safe_webhook_url(body.url)
    if not safe:
        raise HTTPException(status_code=422, detail=reason)
    return register_webhook(body.url, body.events, body.label)


@router.get("")
async def get_webhooks() -> list[dict]:
    """List registered webhooks (secret not included)."""
    return list_webhooks()


@router.delete("/{hook_id}", status_code=204)
async def delete_webhook(hook_id: str) -> None:
    if not remove_webhook(hook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")


@router.post("/{hook_id}/test")
async def test_webhook(hook_id: str) -> dict:
    """Fire a test event to a specific webhook."""
    hooks = {h["id"]: h for h in list_webhooks()}
    if hook_id not in hooks:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await fire_webhook(
        "scan.complete",
        {
            "job_id": "test-00000000",
            "image_id": "ami-test",
            "provider": "aws",
            "region": "us-east-1",
            "profile": "test-profile",
            "grade": "A",
            "score_pct": 95.0,
            "severity_counts": {"critical": 0, "high": 0, "medium": 2, "low": 5},
            "status": "complete",
            "error": None,
            "_test": True,
        },
    )
    return {"fired": True, "hook_id": hook_id}
