# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Webhook notification dispatcher — file-backed, uses httpx."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_WEBHOOKS_FILE = Path("data/webhooks.json")
_webhooks: dict[str, dict] = {}

VALID_EVENTS = {"scan.complete", "scan.failed", "scan.grade_change", "build.complete", "build.failed"}


def is_safe_webhook_url(url: str) -> tuple[bool, str]:
    """Reject webhook URLs that resolve to loopback/private/link-local/reserved
    addresses — including the 169.254.169.254 cloud metadata IP — to close an
    SSRF hole via unauthenticated (or attacker-configured) webhook targets.

    Re-resolving at send time (not just at registration time) narrows, but does
    not eliminate, a DNS-rebinding race: a hostname could pass this check then
    have its DNS record repointed before the actual request is made.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, "url must be a valid http:// or https:// URL"

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        return False, f"could not resolve host {parsed.hostname!r}: {exc}"

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, f"webhook host resolves to a disallowed address ({ip}) — private/internal targets are blocked"

    return True, ""


def _persist() -> None:
    try:
        _WEBHOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WEBHOOKS_FILE.write_text(json.dumps(_webhooks, indent=2))
    except Exception as exc:
        logger.warning("Could not persist webhooks: %s", exc)


def load_webhooks() -> None:
    if not _WEBHOOKS_FILE.exists():
        return
    try:
        _webhooks.update(json.loads(_WEBHOOKS_FILE.read_text()))
        logger.info("Loaded %d webhook(s)", len(_webhooks))
    except Exception as exc:
        logger.warning("Could not load webhooks: %s", exc)


def register_webhook(url: str, events: list[str], label: str = "") -> dict:
    hook_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(24)
    entry = {
        "id": hook_id,
        "url": url,
        "label": label,
        "events": [e for e in events if e in VALID_EVENTS],
        "secret": secret,
        "enabled": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _webhooks[hook_id] = entry
    _persist()
    return {**entry}  # return copy including secret (shown once via API)


def list_webhooks() -> list[dict]:
    return [
        {
            "id": v["id"],
            "url": v["url"],
            "label": v["label"],
            "events": v["events"],
            "enabled": v["enabled"],
            "created_at": v["created_at"],
        }
        for v in _webhooks.values()
    ]


def remove_webhook(hook_id: str) -> bool:
    if hook_id in _webhooks:
        del _webhooks[hook_id]
        _persist()
        return True
    return False


async def fire_webhook(event: str, payload: dict) -> None:
    """POST *payload* to all webhooks subscribed to *event*. Best-effort, never raises."""
    matching = [w for w in _webhooks.values() if w.get("enabled") and event in w.get("events", [])]
    if not matching:
        return

    if httpx is None:
        logger.warning("httpx not available — webhooks not fired for event %s", event)
        return

    body = json.dumps({"event": event, "timestamp": datetime.now(UTC).isoformat(), **payload})

    async with httpx.AsyncClient(timeout=10) as client:
        for hook in matching:
            try:
                safe, reason = is_safe_webhook_url(hook["url"])
                if not safe:
                    logger.warning("Webhook %s blocked for event %s: %s", hook["id"], event, reason)
                    continue
                sig = hmac.new(hook["secret"].encode(), body.encode(), hashlib.sha256).hexdigest()
                await client.post(
                    hook["url"],
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-BakeX-Event": event,
                        "X-BakeX-Signature": f"sha256={sig}",
                    },
                )
                logger.info("Webhook %s fired for event %s", hook["id"], event)
            except Exception as exc:
                logger.warning("Webhook %s failed for event %s: %s", hook["id"], event, exc)
