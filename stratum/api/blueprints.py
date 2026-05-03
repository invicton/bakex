# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Blueprint (ComplianceProfile) CRUD REST endpoints + Studio preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from stratum.config import settings
from stratum.core.blueprint import ComplianceProfile, list_profiles, load_profile

router = APIRouter(prefix="/api/blueprints", tags=["blueprints"])
templates = Jinja2Templates(directory="stratum/templates")


def _all_profile_paths() -> list[Path]:
    """Return YAML paths from both the main profiles dir and the user profiles dir."""
    paths = list(list_profiles(settings.profiles_dir))
    user_dir = settings.user_profiles_dir
    if user_dir.exists() and user_dir != settings.profiles_dir:
        for p in list_profiles(user_dir):
            if p not in paths:
                paths.append(p)
    return paths


@router.get("/")
async def list_blueprints() -> list[dict]:
    """List all discovered ComplianceProfile YAML files."""
    profiles = []
    for p in _all_profile_paths():
        try:
            profile = load_profile(p)
            profiles.append(
                {
                    "name": profile.metadata.name,
                    "version": profile.metadata.version,
                    "os": profile.target.os,
                    "provider": profile.target.provider,
                    "benchmark": profile.compliance.benchmark,
                    "path": str(p),
                }
            )
        except Exception as exc:
            profiles.append({"path": str(p), "error": str(exc)})
    return profiles


@router.get("/{name}/download")
async def download_blueprint(name: str) -> Response:
    """Download a blueprint YAML file as an attachment.

    Returns the original file bytes for local profiles (preserving comments and
    formatting), or a re-serialized YAML for community registry profiles.
    """
    # Search local profiles first — return original file bytes
    for p in _all_profile_paths():
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return Response(
                    content=p.read_bytes(),
                    media_type="application/yaml",
                    headers={"Content-Disposition": f'attachment; filename="{name}.yaml"'},
                )
        except Exception:
            continue

    # Fall back to community registry (in-memory only — re-serialize)
    try:
        from stratum.core.registry import get_registry

        profile = get_registry().get(name)
        if profile is not None:
            yaml_content = yaml.dump(profile.model_dump(), default_flow_style=False, sort_keys=False)
            return Response(
                content=yaml_content.encode(),
                media_type="application/yaml",
                headers={"Content-Disposition": f'attachment; filename="{name}.yaml"'},
            )
    except RuntimeError:
        pass

    raise HTTPException(status_code=404, detail=f"Blueprint '{name}' not found")


@router.post("/upload", status_code=201)
async def upload_blueprint(file: UploadFile) -> dict:
    """Upload a ComplianceProfile YAML. Validates schema, then saves to the user profiles dir."""
    raw = await file.read()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"YAML parse error: {exc}")

    try:
        profile = ComplianceProfile.model_validate(data)
    except (ValidationError, Exception) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user_dir = settings.user_profiles_dir
    user_dir.mkdir(parents=True, exist_ok=True)

    dest = user_dir / f"{profile.metadata.name}.yaml"
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Blueprint '{profile.metadata.name}' already exists")

    dest.write_bytes(raw)
    return {"name": profile.metadata.name, "path": str(dest)}


@router.post("/validate")
async def validate_blueprint(request: Request) -> dict:
    """Validate a ComplianceProfile YAML body without saving it."""
    raw = await request.body()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [str(exc)]}

    try:
        profile = ComplianceProfile.model_validate(data)
        return {"valid": True, "name": profile.metadata.name}
    except (ValidationError, Exception) as exc:
        return {"valid": False, "errors": [str(exc)]}


@router.delete("/{name}", status_code=204)
async def delete_blueprint(name: str) -> None:
    """Delete a user-uploaded blueprint. Templates (not in user_profiles_dir) cannot be deleted."""
    user_dir = settings.user_profiles_dir

    # Search user dir first
    if user_dir.exists():
        for p in list_profiles(user_dir):
            try:
                profile = load_profile(p)
                if profile.metadata.name == name:
                    p.unlink()
                    return
            except Exception:
                continue

    # Check if it exists in the main profiles dir (template) — reject with 403
    for p in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                raise HTTPException(
                    status_code=403, detail=f"Blueprint '{name}' is a built-in template and cannot be deleted"
                )
        except HTTPException:
            raise
        except Exception:
            continue

    raise HTTPException(status_code=404, detail=f"Blueprint '{name}' not found")


@router.get("/{name}")
async def get_blueprint(name: str) -> dict:
    """Return the raw ComplianceProfile by metadata.name."""
    for p in _all_profile_paths():
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return profile.model_dump()
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Blueprint '{name}' not found")


@router.post("/preview", response_class=HTMLResponse)
async def preview_blueprint(request: Request) -> str:
    """HTMX endpoint: receive control toggles, return updated YAML fragment.

    Form fields:
        profile_name: str
        controls[<rule_id>][enabled]: "true" | absent (unchecked)
        controls[<rule_id>][justification]: str
    """
    form = await request.form()
    profile_name: str = form.get("profile_name", "")

    # Resolve profile
    profile = _find_profile(profile_name)
    if profile is None:
        return '<pre class="text-red-400">Profile not found</pre>'

    # Parse controls from flat form data: controls[rule_id][enabled/justification]
    new_controls: dict[str, Any] = {}
    existing_rule_ids = set(profile.controls.keys())

    # Build mapping from submitted form data
    submitted_enabled: dict[str, bool] = {}
    submitted_justification: dict[str, str] = {}

    for key, value in form.multi_items():
        if key.startswith("controls[") and key.endswith("][enabled]"):
            rule_id = key[len("controls[") : -len("][enabled]")]
            submitted_enabled[rule_id] = str(value).lower() == "true"
        elif key.startswith("controls[") and key.endswith("][justification]"):
            rule_id = key[len("controls[") : -len("][justification]")]
            submitted_justification[rule_id] = str(value)

    yaml_warning: str | None = None

    for rule_id in existing_rule_ids:
        enabled = submitted_enabled.get(rule_id, False)  # unchecked = absent = False
        justification = submitted_justification.get(rule_id, "")

        if not enabled and not justification.strip():
            yaml_warning = (
                f"Control '{rule_id}' is disabled but has no justification — "
                "provide a justification to create an approved exception."
            )
            new_controls[rule_id] = {"enabled": False, "justification": ""}
        elif not enabled:
            new_controls[rule_id] = {"enabled": False, "justification": justification}
        else:
            new_controls[rule_id] = True

    # Also include any rules submitted but not in existing profile
    for rule_id, enabled in submitted_enabled.items():
        if rule_id not in new_controls:
            justification = submitted_justification.get(rule_id, "")
            new_controls[rule_id] = True if enabled else {"enabled": False, "justification": justification}

    # Build updated profile dict for serialisation
    profile_dict = profile.model_dump()
    profile_dict["controls"] = new_controls
    yaml_content = yaml.dump(profile_dict, default_flow_style=False, sort_keys=False)

    return templates.TemplateResponse(
        request=request,
        name="partials/blueprint_yaml.html",
        context={
            "request": request,
            "yaml_content": yaml_content,
            "yaml_warning": yaml_warning,
        },
    )


def _find_profile(name: str) -> ComplianceProfile | None:
    for p in _all_profile_paths():
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return profile
        except Exception:
            continue
    # Check community registry
    try:
        from stratum.core.registry import get_registry

        return get_registry().get(name)
    except RuntimeError:
        return None
