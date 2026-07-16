# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Pipeline integration API — scan endpoint with API key auth and synchronous wait."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, model_validator

from statim.config import settings
from statim.core import auditor as audit_service
from statim.core import builder as build_service
from statim.core.api_keys import verify_key
from statim.core.blueprint import list_profiles, load_profile

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_RESULTS_DIR = Path("data/audits")
_bearer = HTTPBearer(auto_error=False)


async def _require_api_key(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
    x_api_key: str | None = Header(default=None),
) -> str:
    token = (creds.credentials if creds else None) or x_api_key
    if not token or not verify_key(token):
        raise HTTPException(status_code=401, detail="Invalid or missing API key. Create one at /settings/api-keys.")
    return token


class PipelineScanRequest(BaseModel):
    image_id: str
    provider: str = "aws"
    region: str = "us-east-1"
    os: str = ""
    compliance_profile: str = ""
    instance_type: str = "t3.medium"
    pass_threshold: float = 75.0
    severity_threshold: str = "high"  # critical | high | medium | low
    wait: bool = True
    timeout_seconds: int = 900


def _job_to_response(
    job: audit_service.AuditJob, pass_threshold: float, severity_threshold: str, base_url: str = ""
) -> dict:
    sev_order = ["critical", "high", "medium", "low"]
    threshold_idx = sev_order.index(severity_threshold) if severity_threshold in sev_order else 1
    # Fail if any finding at or above the threshold severity
    threshold_violations = [
        sev for sev in sev_order[: threshold_idx + 1] if (job.severity_counts or {}).get(sev, 0) > 0
    ]
    score_ok = (job.score_pct or 0) >= pass_threshold
    passed = score_ok and not threshold_violations

    report_base = f"{base_url}/api/auditor/scan-image/{job.id}/report"
    return {
        "job_id": job.id,
        "status": job.status.value,
        "passed": passed,
        "grade": job.grade,
        "score_pct": job.score_pct,
        "severity_counts": job.severity_counts or {},
        "threshold_violations": threshold_violations,
        "pass_threshold": pass_threshold,
        "severity_threshold": severity_threshold,
        "image_id": job.image_id,
        "provider": job.provider,
        "region": job.region,
        "profile": job.profile_name,
        "error": job.error,
        "report_url": f"{report_base}?fmt=json",
        "sarif_url": f"{report_base}?fmt=sarif",
        "html_report_url": report_base,
    }


@router.post("/scan")
async def pipeline_scan(
    req: PipelineScanRequest,
    _key: str = Depends(_require_api_key),
):
    """Trigger a compliance image scan. When ``wait=true`` (default), blocks until complete."""
    profile = _resolve_profile(req.compliance_profile)

    job = audit_service.AuditJob(
        job_type="image_scan",
        image_id=req.image_id,
        provider=req.provider,
        region=req.region,
        profile_name=profile.metadata.name,
        target_host=req.image_id,
    )
    audit_service._audit_jobs[job.id] = job

    if req.wait:
        # Run synchronously (blocking) — suitable for CI pipelines
        await audit_service.run_image_scan(
            req.image_id,
            req.provider,
            req.region,
            profile,
            req.instance_type,
            _RESULTS_DIR,
        )
    else:
        import asyncio

        asyncio.create_task(
            audit_service.run_image_scan(
                req.image_id,
                req.provider,
                req.region,
                profile,
                req.instance_type,
                _RESULTS_DIR,
            )
        )

    return _job_to_response(job, req.pass_threshold, req.severity_threshold)


@router.get("/scan/{job_id}")
async def get_pipeline_scan(
    job_id: str,
    pass_threshold: float = 75.0,
    severity_threshold: str = "high",
    _key: str = Depends(_require_api_key),
):
    """Poll a pipeline scan result."""
    job = audit_service.get_audit(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return _job_to_response(job, pass_threshold, severity_threshold)


@router.post("/verify/{job_id}")
async def verify_scan(
    job_id: str,
    pass_threshold: float = 75.0,
    severity_threshold: str = "high",
    _key: str = Depends(_require_api_key),
):
    """Verify an existing completed scan against thresholds. Returns passed=true/false."""
    job = audit_service.get_audit(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    if job.status != audit_service.AuditStatus.COMPLETE:
        raise HTTPException(status_code=400, detail=f"Scan not complete (status: {job.status.value})")
    return _job_to_response(job, pass_threshold, severity_threshold)


@router.get("/scans")
async def list_pipeline_scans(_key: str = Depends(_require_api_key)) -> list[dict]:
    """List recent image scans (newest first, capped at 100)."""
    jobs = [j for j in audit_service.list_audits() if j.job_type == "image_scan"][:100]
    return [_job_to_response(j, 75.0, "high") for j in jobs]


class PipelineBuildRequest(BaseModel):
    profile_name: str = ""
    blueprint_yaml: str | None = None
    provider: str = ""
    region: str = ""
    instance_type: str = ""
    wait: bool = True
    timeout_seconds: int = 1800

    @model_validator(mode="after")
    def _require_profile_or_yaml(self) -> PipelineBuildRequest:
        if not self.profile_name and not self.blueprint_yaml:
            raise ValueError("Either 'profile_name' or 'blueprint_yaml' must be provided")
        return self


def _build_job_to_response(job: build_service.BuildJob) -> dict:
    return {
        "job_id": job.id,
        "status": job.status.value,
        "profile_name": job.profile_name,
        "provider": job.provider_name,
        "artifact_id": job.result.artifact_id if job.result else None,
        "error": job.error,
        "log_tail": job.log[-10:],
    }


@router.post("/build")
async def pipeline_build(
    req: PipelineBuildRequest,
    _key: str = Depends(_require_api_key),
):
    """Trigger a hardened image build. When ``wait=true`` (default), blocks until complete."""
    if req.blueprint_yaml:
        profile = _resolve_inline_yaml(req.blueprint_yaml)
    else:
        profile = _resolve_profile(req.profile_name)
    if req.provider:
        profile.target.provider = req.provider
    # Note: TargetSpec has no `region` field — the region actually used to
    # provision comes from the provider's stored credentials (see e.g.
    # plugins/providers/aws.py's `credentials.get("region", ...)`). `req.region`
    # is recorded on the job for display/audit purposes only, not as an
    # override of where the build actually runs.

    job = build_service.BuildJob(
        profile_name=profile.metadata.name,
        provider_name=profile.target.provider,
        region=req.region,
    )
    build_service._jobs[job.id] = job

    output_dir = Path("data/builds")

    if req.wait:
        await build_service.run_build(profile, output_dir, job)
    else:
        asyncio.create_task(build_service.run_build(profile, output_dir, job))

    return _build_job_to_response(job)


@router.get("/build/{job_id}")
async def get_pipeline_build(
    job_id: str,
    _key: str = Depends(_require_api_key),
):
    """Poll a pipeline build job status."""
    job = build_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Build job not found")
    return _build_job_to_response(job)


def _resolve_profile(name: str):
    for p in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return profile
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")


def _resolve_inline_yaml(blueprint_yaml: str):
    """Parse and validate an inline blueprint YAML string. Raises 422 on failure."""
    try:
        data = yaml.safe_load(blueprint_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"YAML parse error: {exc}")
    try:
        from statim.core.blueprint import ComplianceProfile

        return ComplianceProfile.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
