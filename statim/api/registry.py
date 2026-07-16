# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Community profile registry API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from statim.core.registry import get_registry

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.get("/")
async def list_registry_profiles() -> list[dict]:
    registry = get_registry()
    return [
        {
            "name": p.metadata.name,
            "version": p.metadata.version,
            "os": p.target.os,
            "provider": p.target.provider,
            "benchmark": p.compliance.benchmark,
        }
        for p in registry.list()
    ]


@router.post("/sync", response_class=HTMLResponse)
async def sync_registry() -> str:
    registry = get_registry()
    synced = await registry.sync()
    count = len(synced)
    if count:
        return f'<span class="text-green-400">✓ Synced {count} profile{"s" if count != 1 else ""}</span>'
    return '<span class="text-yellow-400">⚠ No profiles synced (registry may be unavailable)</span>'
