# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API key store — file-backed, stdlib only (hashlib + secrets)."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_KEYS_FILE = Path("data/api_keys.json")
_keys: dict[str, dict] = {}  # key_id → {label, hash, created_at, last_used}


def _persist() -> None:
    try:
        _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_FILE.write_text(json.dumps(_keys, indent=2))
    except Exception as exc:
        logger.warning("Could not persist API keys: %s", exc)


def load_keys() -> None:
    if not _KEYS_FILE.exists():
        return
    try:
        _keys.update(json.loads(_KEYS_FILE.read_text()))
        logger.info("Loaded %d API key(s)", len(_keys))
    except Exception as exc:
        logger.warning("Could not load API keys: %s", exc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_key(label: str) -> str:
    """Generate a new API key. Returns the plaintext token (shown once)."""
    token = f"str_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(8)
    _keys[key_id] = {
        "label": label,
        "hash": _hash(token),
        "created_at": datetime.now(UTC).isoformat(),
        "last_used": None,
    }
    _persist()
    return token, key_id


def verify_key(token: str) -> bool:
    """Return True if *token* matches any stored key; update last_used."""
    h = _hash(token)
    for key_id, entry in _keys.items():
        if entry.get("hash") == h:
            _keys[key_id]["last_used"] = datetime.now(UTC).isoformat()
            _persist()
            return True
    return False


def list_keys() -> list[dict]:
    return [
        {"id": kid, "label": v["label"], "created_at": v["created_at"], "last_used": v["last_used"]}
        for kid, v in _keys.items()
    ]


def revoke_key(key_id: str) -> bool:
    if key_id in _keys:
        del _keys[key_id]
        _persist()
        return True
    return False
