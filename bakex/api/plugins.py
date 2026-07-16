# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API routes for browsing and installing provider plugins from the catalog."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from bakex.config import settings
from bakex.paths import TEMPLATES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------


def _load_catalog() -> list[dict]:
    """Read plugins/catalog/index.json and return the providers list."""
    catalog_index = settings.catalog_dir_absolute / "index.json"
    if not catalog_index.exists():
        logger.warning("Catalog index not found at %s", catalog_index)
        return []
    try:
        data = json.loads(catalog_index.read_text())
        return data.get("providers", [])
    except Exception as exc:
        logger.error("Failed to parse catalog index: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/available", response_class=HTMLResponse)
async def list_available_plugins(request: Request) -> Any:
    """Return the HTML partial listing providers available in the catalog."""
    from bakex.plugins.registry import registry

    installed = set(registry.names())

    catalog = _load_catalog()
    available = [p for p in catalog if p["id"] not in installed]

    return templates.TemplateResponse(
        request=request,
        name="integrations/partials/available_plugins.html",
        context={
            "request": request,
            "plugins": available,
            "installed_count": len(installed),
        },
    )


@router.get("/catalog", response_model=list[dict])
async def get_catalog() -> list[dict]:
    """Return the full provider catalog as JSON (id, name, description, etc.)."""
    from bakex.plugins.registry import registry

    installed = set(registry.names())
    catalog = _load_catalog()
    for entry in catalog:
        entry["installed"] = entry["id"] in installed
    return catalog


@router.get("/catalog/{provider_id}/download")
async def download_provider_script(provider_id: str) -> Response:
    """Download the raw provider script from the catalog.

    This lets users inspect the plugin before installing it, or use it outside
    BakeX (e.g. drop it into another tool).
    """
    catalog = _load_catalog()
    entry = next((p for p in catalog if p["id"] == provider_id), None)
    if entry is None:
        return Response(
            content=json.dumps({"detail": f"Provider '{provider_id}' not in catalog"}),
            status_code=404,
            media_type="application/json",
        )

    script_path = settings.catalog_dir_absolute / entry["script"]
    if not script_path.exists():
        return Response(
            content=json.dumps({"detail": f"Catalog script not found: {entry['script']}"}),
            status_code=404,
            media_type="application/json",
        )

    return Response(
        content=script_path.read_bytes(),
        media_type="text/x-python",
        headers={"Content-Disposition": f'attachment; filename="{entry["script"]}"'},
    )


@router.post("/install", response_class=HTMLResponse)
async def install_plugin(
    request: Request,
    provider_id: str = Form(...),
) -> Any:
    """Install a provider from the catalog by copying its script to plugins/providers/."""
    catalog = _load_catalog()
    entry = next((p for p in catalog if p["id"] == provider_id), None)
    if entry is None:
        return HTMLResponse(
            content=f'<span class="text-rose-400">Unknown provider: {provider_id}</span>',
            status_code=400,
        )

    src = settings.catalog_dir_absolute / entry["script"]
    if not src.exists():
        return HTMLResponse(
            content=f'<span class="text-rose-400">Catalog script missing: {entry["script"]}</span>',
            status_code=500,
        )

    plugins_dir = settings.plugins_dir_absolute
    plugins_dir.mkdir(parents=True, exist_ok=True)
    dst = plugins_dir / entry["script"]

    try:
        dst.write_bytes(src.read_bytes())
        logger.info("Installed provider '%s' from catalog → %s", provider_id, dst)

        # Reload provider registry
        from bakex.plugins.registry import registry

        registry.load(plugins_dir, strict=False)

        return HTMLResponse(
            content=f'<span class="text-emerald-400">Installed {entry["name"]}! Refreshing…</span>',
            headers={"HX-Refresh": "true"},
        )
    except Exception as exc:
        logger.error("Failed to install provider '%s': %s", provider_id, exc)
        return HTMLResponse(
            content=f'<span class="text-rose-400">Error installing {provider_id}: {exc}</span>',
            status_code=500,
        )


@router.post("/{provider_id}/remove", response_class=HTMLResponse)
async def remove_plugin(request: Request, provider_id: str) -> Any:
    """Remove an installed provider plugin."""
    plugins_dir = settings.plugins_dir_absolute

    # Look up the script filename from the catalog
    catalog = _load_catalog()
    entry = next((p for p in catalog if p["id"] == provider_id), None)
    script_filename = entry["script"] if entry else f"{provider_id}.py"

    script_path = plugins_dir / script_filename

    try:
        if script_path.exists():
            script_path.unlink()
            logger.info("Removed provider plugin at %s", script_path)
        else:
            logger.warning("Provider script not found at %s — nothing to remove", script_path)

        from bakex.plugins.registry import registry

        registry.load(plugins_dir, strict=False)

        return HTMLResponse(
            content=f'<span class="text-rose-400">Removed {provider_id}. Refreshing…</span>',
            headers={"HX-Refresh": "true"},
        )
    except Exception as exc:
        logger.error("Failed to remove provider '%s': %s", provider_id, exc)
        return HTMLResponse(
            content=f'<span class="text-rose-400">Error removing {provider_id}: {exc}</span>',
            status_code=500,
        )
