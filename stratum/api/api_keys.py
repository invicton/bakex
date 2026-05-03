# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API key management REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stratum.core.api_keys import create_key, list_keys, revoke_key

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class KeyCreate(BaseModel):
    label: str


@router.post("", status_code=201)
async def create_api_key(body: KeyCreate) -> dict:
    """Generate a new API key. The plaintext token is returned once — store it securely."""
    if not body.label.strip():
        raise HTTPException(status_code=422, detail="label is required")
    token, key_id = create_key(body.label.strip())
    return {"id": key_id, "label": body.label.strip(), "token": token}


@router.get("")
async def get_api_keys() -> list[dict]:
    """List API keys (token not included)."""
    return list_keys()


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(key_id: str) -> None:
    if not revoke_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
