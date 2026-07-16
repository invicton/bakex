# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""FastAPI application assembly."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from statim import __version__
from statim.api import agent as agent_api
from statim.api import api_keys as api_keys_api
from statim.api import auditor, blueprints, builder, integrations, plugins, ui
from statim.api import pipeline as pipeline_api
from statim.api import registry as registry_api
from statim.api import system as system_api
from statim.api import webhooks as webhooks_api
from statim.api.integrations import credential_store
from statim.config import settings
from statim.core.auth import require_admin, require_admin_or_key
from statim.core.registry import RegistrySource, init_registry
from statim.core.sysdeps import check_system_deps
from statim.paths import STATIC_DIR
from statim.plugins.registry import registry

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from statim.core.auth import get_admin_token

    get_admin_token()  # generate + log on first boot, so it's visible before any request

    credential_store.load()
    logger.info("Credential store ready (data dir: %s)", settings.data_dir)

    from statim.core.auditor import load_jobs as _load_audit_jobs

    _load_audit_jobs()
    logger.info("Audit job store ready")

    from statim.core.api_keys import load_keys as _load_api_keys

    _load_api_keys()
    logger.info("API key store ready")

    from statim.core.notifications import load_webhooks as _load_webhooks

    _load_webhooks()
    logger.info("Webhook store ready")

    plugins_dir = settings.plugins_dir_absolute
    logger.info("Loading provider plugins from %s", plugins_dir)
    warnings = registry.load(plugins_dir, strict=settings.strict_plugins)
    for w in warnings:
        logger.warning("Plugin warning: %s", w)
    logger.info("Registered providers: %s", registry.names())

    # Initialise blueprint registry — community GitHub + optional S3 private store + local
    community_cache = Path("profiles/community")
    sources: list[RegistrySource] = [
        RegistrySource("github", settings.registry_url, "Community"),
        RegistrySource("local", str(settings.profiles_dir), "Local"),
    ]
    if settings.blueprint_store_s3_bucket:
        sources.insert(
            1,
            RegistrySource(
                "s3",
                settings.blueprint_store_s3_bucket,
                "Private",
                prefix=settings.blueprint_store_s3_prefix,
            ),
        )
    init_registry(sources=sources, cache_dir=community_cache)
    logger.info(
        "Blueprint registry initialised (%d sources: %s)",
        len(sources),
        [s.kind for s in sources],
    )

    yield
    logger.info("Statim shutdown")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Multi-cloud DevSecOps platform for declarative OS hardening",
    lifespan=lifespan,
)

# Static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers
# `pipeline` enforces its own per-route API-key check (CI/automation surface).
# `integrations` and `api_keys` manage cloud credentials / key issuance, so they
# require the stronger admin-only gate. Everything else accepts either the
# admin token or a valid API key.
_auth = [Depends(require_admin_or_key)]
_admin_only = [Depends(require_admin)]

app.include_router(ui.router, dependencies=_auth)
app.include_router(blueprints.router, dependencies=_auth)
app.include_router(builder.router, dependencies=_auth)
app.include_router(auditor.router, dependencies=_auth)
app.include_router(integrations.router, dependencies=_admin_only)
app.include_router(registry_api.router, dependencies=_auth)
app.include_router(system_api.router, dependencies=_auth)
app.include_router(plugins.router, dependencies=_auth)
app.include_router(agent_api.router, dependencies=_auth)
app.include_router(pipeline_api.router)
app.include_router(webhooks_api.router, dependencies=_auth)
app.include_router(api_keys_api.router, dependencies=_admin_only)


@app.get("/health")
async def health(deep: bool = False) -> dict:
    """Shallow liveness by default; ``?deep=1`` adds the system-dependency report."""
    body: dict = {"status": "ok", "providers": registry.names()}
    if deep:
        body["system_deps"] = check_system_deps()
    return body


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    """Last-resort handler: never leak internals, always leave a correlatable trail.

    The error_id printed to the client appears verbatim in the server log next
    to the full traceback, so a user pasting it into a bug report is enough to
    find the cause.
    """
    import uuid

    from fastapi.responses import HTMLResponse as _HTMLResponse
    from fastapi.responses import JSONResponse as _JSONResponse

    error_id = uuid.uuid4().hex[:8]
    logger.exception("Unhandled error %s on %s %s", error_id, request.method, request.url.path)
    if request.headers.get("hx-request"):
        return _HTMLResponse(
            content=(
                f'<div class="bg-rose-950/40 border border-rose-800/60 rounded-lg px-4 py-3 text-sm text-rose-200">'
                f"Internal error — check the server log for error_id {error_id}</div>"
            ),
            status_code=500,
        )
    return _JSONResponse(
        status_code=500,
        content={"detail": "Internal error — see server log", "error_id": error_id},
    )
