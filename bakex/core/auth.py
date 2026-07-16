# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Auth gate for UI/management routers — HTTP Basic admin token, or an API key.

BakeX is a single-operator, self-hosted tool with no reverse proxy assumed
(``docker-compose.yml`` exposes the HTTP port directly). Every router except
``/health`` and ``/api/pipeline/*`` (which already enforces its own API-key
check, see ``bakex.api.pipeline``) is gated by one of the two dependencies
below:

- ``require_admin_or_key`` — general gate for the UI and automation surfaces.
  Accepts either the admin token (HTTP Basic, any username) or a valid API key
  (``Authorization: Bearer`` or ``X-Api-Key``).
- ``require_admin`` — stricter gate for credential and API-key management
  (``/api/integrations``, ``/api/api-keys``). An API key must not be usable to
  read raw cloud credentials or mint further API keys, so those surfaces only
  accept the admin token.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer

from bakex.config import settings
from bakex.core.api_keys import verify_key

logger = logging.getLogger(__name__)

_basic = HTTPBasic(auto_error=False)
_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="Authentication required (HTTP Basic admin token, or API key via Bearer/X-Api-Key).",
    headers={"WWW-Authenticate": 'Basic realm="BakeX"'},
)


def get_admin_token() -> str:
    """Return the admin token, generating and persisting one on first use.

    Resolution order mirrors ``CredentialStore._init_fernet``:
    1. ``BAKEX_ADMIN_TOKEN`` env var.
    2. Existing ``data_dir/.admin_token`` file.
    3. Freshly generated random token, persisted to that file (chmod 600).
    """
    if settings.bakex_admin_token:
        return settings.bakex_admin_token

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    token_file = settings.data_dir / ".admin_token"
    if token_file.exists():
        return token_file.read_text().strip()

    token = secrets.token_urlsafe(32)
    token_file.write_text(token)
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    logger.warning(
        "No BAKEX_ADMIN_TOKEN set — generated an admin token and saved it to %s. "
        "Use it as the password for HTTP Basic Auth (any username works): %s",
        token_file,
        token,
    )
    return token


def _admin_ok(credentials: HTTPBasicCredentials | None) -> bool:
    if credentials is None:
        return False
    return secrets.compare_digest(credentials.password, get_admin_token())


async def require_admin(
    basic: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    if not _admin_ok(basic):
        raise _UNAUTHORIZED
    return "admin"


async def require_admin_or_key(
    basic: HTTPBasicCredentials | None = Depends(_basic),
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Header(default=None),
) -> str:
    if _admin_ok(basic):
        return "admin"
    token = (bearer.credentials if bearer else None) or x_api_key
    if token and verify_key(token):
        return token
    raise _UNAUTHORIZED
