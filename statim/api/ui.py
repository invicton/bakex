# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Page-rendering routes (Jinja2 full-page responses)."""

from __future__ import annotations

import yaml as _yaml
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from statim.config import settings
from statim.core.auditor import list_audits
from statim.core.blueprint import list_profiles, load_profile
from statim.core.builder import list_jobs
from statim.paths import TEMPLATES_DIR
from statim.plugins.registry import registry

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _toyaml(value) -> str:
    """Jinja2 filter: convert a Pydantic model or dict to a YAML string."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return _yaml.dump(value, default_flow_style=False, sort_keys=False)


templates.env.filters["toyaml"] = _toyaml


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from statim.core.sysdeps import missing_system_deps

    jobs = list_jobs()
    audits = list_audits()
    missing_deps = missing_system_deps()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "providers": registry.names(),
            "recent_jobs": jobs[:5],
            "recent_audits": audits[:5],
            "missing_deps": missing_deps,
        },
    )


@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="integrations/index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "providers": registry.names(),
        },
    )


@router.get("/integrations/{provider_name}/form", response_class=HTMLResponse)
async def integrations_provider_form(request: Request, provider_name: str):
    import json

    from statim.api.integrations import get_credentials
    from statim.config import settings

    creds = get_credentials(provider_name) or {}

    # Check if a specific partial exists
    partial_path = TEMPLATES_DIR / "integrations" / "partials" / f"{provider_name}.html"
    if partial_path.exists():
        template_name = f"integrations/partials/{provider_name}.html"
    else:
        template_name = "integrations/partials/generic.html"

    # Load catalog entry to pass hints/descriptions dynamically
    plugin_meta = {}
    catalog_path = settings.catalog_dir_absolute / "index.json"
    if catalog_path.exists():
        try:
            catalog = json.loads(catalog_path.read_text())
            for p in catalog.get("providers", []):
                if p["id"] == provider_name:
                    plugin_meta = p
                    break
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "request": request,
            "provider_name": provider_name,
            "creds": creds,
            "plugin_meta": plugin_meta,
        },
    )


@router.get("/blueprints", response_class=HTMLResponse)
async def blueprints_page(request: Request):
    paths = list(list_profiles(settings.profiles_dir))
    user_dir = settings.user_profiles_dir
    if user_dir.exists() and user_dir != settings.profiles_dir:
        for p in list_profiles(user_dir):
            if p not in paths:
                paths.append(p)
    profiles = []
    for p in paths:
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass

    from statim.core.registry import get_registry

    try:
        community_profiles = get_registry().list()
    except RuntimeError:
        community_profiles = []

    return templates.TemplateResponse(
        request=request,
        name="blueprints/index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "profiles": profiles,
            "community_profiles": community_profiles,
        },
    )


@router.get("/blueprints/studio/{name}", response_class=HTMLResponse)
async def blueprint_studio_page(request: Request, name: str):
    import yaml
    from fastapi import HTTPException

    profile = None
    search_paths = list(list_profiles(settings.profiles_dir))
    user_dir = settings.user_profiles_dir
    if user_dir.exists() and user_dir != settings.profiles_dir:
        for p in list_profiles(user_dir):
            if p not in search_paths:
                search_paths.append(p)
    for p in search_paths:
        try:
            candidate = load_profile(p)
            if candidate.metadata.name == name:
                profile = candidate
                break
        except Exception:
            pass

    # Also check community registry
    if profile is None:
        from statim.core.registry import get_registry

        try:
            profile = get_registry().get(name)
        except RuntimeError:
            pass

    if profile is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    yaml_content = yaml.dump(profile.model_dump(), default_flow_style=False, sort_keys=False)

    return templates.TemplateResponse(
        request=request,
        name="blueprints/studio.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "profile": profile,
            "controls": profile.controls,
            "yaml_content": yaml_content,
        },
    )


@router.get("/builder", response_class=HTMLResponse)
async def builder_page(request: Request):
    from statim.core.os_catalog import INSTANCE_TYPES, OS_CATALOG, PROVIDER_CATALOG

    return templates.TemplateResponse(
        request=request,
        name="builder/wizard.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "os_catalog": OS_CATALOG,
            "provider_catalog": PROVIDER_CATALOG,
            "instance_types": INSTANCE_TYPES,
        },
    )


@router.get("/builder/wizard/step1", response_class=HTMLResponse)
async def wizard_step1(request: Request):
    from statim.core.os_catalog import INSTANCE_TYPES, OS_CATALOG, PROVIDER_CATALOG

    return templates.TemplateResponse(
        request=request,
        name="builder/steps/step1_os.html",
        context={
            "request": request,
            "os_catalog": OS_CATALOG,
            "provider_catalog": PROVIDER_CATALOG,
            "instance_types": INSTANCE_TYPES,
        },
    )


@router.get("/builder/wizard/step2", response_class=HTMLResponse)
async def wizard_step2(request: Request, os: str = "", provider: str = "", min_root_gb: int = 20):
    from statim.core.os_catalog import INSTANCE_TYPES, OS_CATALOG

    types = INSTANCE_TYPES.get(provider, [])
    actual_min = OS_CATALOG.get(os, {}).get("min_root_gb", min_root_gb)
    return templates.TemplateResponse(
        request=request,
        name="builder/steps/step2_storage.html",
        context={
            "request": request,
            "os": os,
            "provider": provider,
            "instance_types": types,
            "min_root_gb": actual_min,
        },
    )


@router.get("/builder/wizard/step3", response_class=HTMLResponse)
async def wizard_step3(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="builder/steps/step3_users.html",
        context={
            "request": request,
        },
    )


@router.get("/builder/wizard/step4", response_class=HTMLResponse)
async def wizard_step4(request: Request, os: str = "", supported_tiers: str = "cis-l1"):
    tiers = [t.strip() for t in supported_tiers.split(",") if t.strip()]
    return templates.TemplateResponse(
        request=request,
        name="builder/steps/step4_hardening.html",
        context={
            "request": request,
            "os": os,
            "supported_tiers": tiers,
        },
    )


@router.get("/builder/wizard/step5", response_class=HTMLResponse)
async def wizard_step5(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="builder/steps/step5_review.html",
        context={
            "request": request,
        },
    )


@router.get("/builder/run/{job_id}", response_class=HTMLResponse)
async def builder_run_page(request: Request, job_id: str):
    from statim.core.builder import get_job

    job = get_job(job_id)
    return templates.TemplateResponse(
        request=request,
        name="builder/run.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "job": job,
            "job_id": job_id,
        },
    )


@router.get("/auditor", response_class=HTMLResponse)
async def auditor_page(request: Request):
    profile_paths = list_profiles(settings.profiles_dir)
    profiles = []
    for p in profile_paths:
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="auditor/index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "profiles": profiles,
        },
    )


@router.get("/auditor/results/{job_id}", response_class=HTMLResponse)
async def auditor_results_page(request: Request, job_id: str):
    from statim.core.auditor import get_audit

    job = get_audit(job_id)
    return templates.TemplateResponse(
        request=request,
        name="auditor/results.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "job": job,
        },
    )


@router.get("/auditor/scan-image", response_class=HTMLResponse)
async def scan_image_page(request: Request):
    """Image Scanner form — select provider, image ID, and compliance profile."""
    profile_paths = list_profiles(settings.profiles_dir)
    profiles = []
    for p in profile_paths:
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="auditor/scan_image.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "profiles": profiles,
            "providers": registry.names(),
        },
    )


@router.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request):
    """AI Builder page — YAML editor + streaming agent terminal."""
    profile_paths = list_profiles(settings.profiles_dir)
    profiles = []
    for p in profile_paths:
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="agent/index.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "profiles": profiles,
            "providers": registry.names(),
        },
    )


@router.get("/auditor/scanner", response_class=HTMLResponse)
async def scanner_wizard_page(request: Request):
    """Compliance Scanner wizard shell."""
    from statim.core.os_catalog import INSTANCE_TYPES, OS_CATALOG, PROVIDER_CATALOG

    return templates.TemplateResponse(
        request=request,
        name="auditor/scanner/wizard.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "os_catalog": OS_CATALOG,
            "provider_catalog": PROVIDER_CATALOG,
            "instance_types": INSTANCE_TYPES,
        },
    )


@router.get("/auditor/scanner/step1", response_class=HTMLResponse)
async def scanner_step1(request: Request):
    from statim.core.os_catalog import INSTANCE_TYPES, OS_CATALOG, PROVIDER_CATALOG

    return templates.TemplateResponse(
        request=request,
        name="auditor/scanner/steps/step1_target.html",
        context={
            "request": request,
            "os_catalog": OS_CATALOG,
            "provider_catalog": PROVIDER_CATALOG,
            "instance_types": INSTANCE_TYPES,
        },
    )


@router.get("/auditor/scanner/step2", response_class=HTMLResponse)
async def scanner_step2(request: Request, os: str = "", provider: str = ""):
    profile_paths = list_profiles(settings.profiles_dir)
    profiles = []
    for p in profile_paths:
        try:
            profiles.append(load_profile(p))
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="auditor/scanner/steps/step2_benchmark.html",
        context={
            "request": request,
            "os": os,
            "provider": provider,
            "profiles": profiles,
        },
    )


@router.get("/auditor/scanner/step3", response_class=HTMLResponse)
async def scanner_step3(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auditor/scanner/steps/step3_review.html",
        context={
            "request": request,
        },
    )


@router.get("/auditor/history", response_class=HTMLResponse)
async def scan_history_page(request: Request):
    audits = list_audits()
    return templates.TemplateResponse(
        request=request,
        name="auditor/history.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "audits": audits,
        },
    )


@router.get("/auditor/compare/{job_id}/{baseline_id}", response_class=HTMLResponse)
async def compare_scans_page(request: Request, job_id: str, baseline_id: str):
    from statim.core.auditor import get_audit

    job = get_audit(job_id)
    baseline = get_audit(baseline_id)
    return templates.TemplateResponse(
        request=request,
        name="auditor/compare.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "job": job,
            "baseline": baseline,
            "job_id": job_id,
            "baseline_id": baseline_id,
        },
    )


@router.get("/settings/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request):
    from statim.core.api_keys import list_keys

    return templates.TemplateResponse(
        request=request,
        name="settings/api_keys.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "keys": list_keys(),
        },
    )


@router.get("/settings/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    from statim.core.notifications import VALID_EVENTS, list_webhooks

    return templates.TemplateResponse(
        request=request,
        name="settings/webhooks.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "hooks": list_webhooks(),
            "valid_events": sorted(VALID_EVENTS),
        },
    )


@router.get("/auditor/scan-image/{job_id}", response_class=HTMLResponse)
async def scan_image_results_page(request: Request, job_id: str):
    """Image Scanner results page with live HTMX polling."""
    from statim.core.auditor import get_audit

    job = get_audit(job_id)
    if job is None:
        return HTMLResponse(content="<p class='text-red-400'>Scan job not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="auditor/scan_image_results.html",
        context={
            "request": request,
            "app_name": settings.app_name,
            "job": job,
        },
    )
