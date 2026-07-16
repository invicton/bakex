# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""System diagnostics API — what the host can and cannot run."""

from __future__ import annotations

from fastapi import APIRouter

from bakex.core.sysdeps import check_system_deps

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/deps")
async def system_deps() -> list[dict]:
    """Per-dependency host report: present/path/needed_for/install_hint."""
    return check_system_deps()
