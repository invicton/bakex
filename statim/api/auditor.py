# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Audit trigger + results API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from statim.config import settings
from statim.core import auditor as audit_service
from statim.core.blueprint import list_profiles, load_profile
from statim.paths import TEMPLATES_DIR

_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/api/auditor", tags=["auditor"])

_RESULTS_DIR = Path("data/audits")


class AuditRequest(BaseModel):
    profile_name: str
    target_host: str  # SSH host (local) OR EC2 instance ID (cloud)
    ssh_user: str = "root"
    baseline_arf: str | None = None
    provider_override: str | None = None  # force a specific provider


class ImageScanRequest(BaseModel):
    provider: str
    region: str
    image_id: str  # AMI ID, GCP image name, DigitalOcean snapshot ID, etc.
    os: str  # OS key matching a profile target.os (e.g. "rocky9")
    compliance_profile: str  # Profile metadata.name to resolve benchmark/datastream
    instance_type: str = "t3.medium"


class ContainerScanRequest(BaseModel):
    image: str  # local container image name:tag or image ID (on podman/docker)
    os: str  # OS slug in OS_CATALOG (e.g. "ubuntu22.04", "debian12")
    tier: str = "cis-l1"  # cis-l1 | cis-l2


@router.post("/start")
async def start_audit(req: AuditRequest, background_tasks: BackgroundTasks) -> dict:
    """Trigger a live audit scan. Returns the job ID immediately."""
    profile = _resolve_profile(req.profile_name)
    baseline = Path(req.baseline_arf) if req.baseline_arf else None

    job = audit_service.AuditJob(
        target_host=req.target_host,
        profile_name=profile.metadata.name,
    )
    audit_service._audit_jobs[job.id] = job

    background_tasks.add_task(
        audit_service.run_audit,
        profile,
        req.target_host,
        req.ssh_user,
        _RESULTS_DIR,
        baseline,
    )
    return {"job_id": job.id, "status": job.status.value}


@router.post("/scan-image")
async def start_image_scan(req: ImageScanRequest, background_tasks: BackgroundTasks) -> HTMLResponse:
    """Provision a temporary VM from an existing image, scan it, then tear it down.

    Returns an HTMX-compatible redirect snippet to the results page.
    The finished job includes ``grade`` (A–F), ``score_pct``, and ``severity_counts``.
    """
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

    background_tasks.add_task(
        audit_service.run_image_scan,
        req.image_id,
        req.provider,
        req.region,
        profile,
        req.instance_type,
        _RESULTS_DIR,
    )
    # HTMX redirect: push the browser to the results page
    return HTMLResponse(
        content=f'<div hx-redirect="/auditor/scan-image/{job.id}"></div>',
        headers={"HX-Redirect": f"/auditor/scan-image/{job.id}"},
    )


@router.post("/scan-container")
async def start_container_scan(req: ContainerScanRequest, background_tasks: BackgroundTasks) -> dict:
    """Scan a local container image against its OS CIS datastream via oscap-podman.

    OS-level config compliance of the image contents (not CIS Docker Benchmark, not
    CVEs). Returns the job id immediately; poll ``/jobs/{id}`` or reuse the badge/
    report/compare endpoints, which are target-agnostic.
    """
    job = audit_service.AuditJob(
        job_type="container_scan",
        image_id=req.image,
        target_host=req.image,
        profile_name=f"{req.os}-{req.tier}",
    )
    audit_service._audit_jobs[job.id] = job
    background_tasks.add_task(
        audit_service.run_container_scan_job,
        job,
        req.image,
        req.os,
        req.tier,
        _RESULTS_DIR,
    )
    return {"job_id": job.id, "status": job.status.value}


@router.get("/scan-image/{job_id}/badge.svg")
async def compliance_badge(job_id: str):
    """Return an SVG compliance badge for a scan job.

    Returns 202 while the scan is in progress, 404 if unknown, 200 with SVG when complete.
    Grade colour mapping: A=green, B=teal, C=yellow, D=orange, F=red, pending=grey.
    """
    job = audit_service.get_audit(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    if job.status != audit_service.AuditStatus.COMPLETE:
        # Return a pending SVG with 202 so callers can poll
        svg = _make_badge("compliance", "scanning…", "#6b7280")
        from fastapi.responses import Response as _Resp

        return _Resp(content=svg, status_code=202, media_type="image/svg+xml")

    grade = job.grade or "?"
    score = f"{job.score_pct:.0f}%" if job.score_pct is not None else "N/A"
    _grade_colors = {
        "A": "#22c55e",  # green-500
        "B": "#14b8a6",  # teal-500
        "C": "#eab308",  # yellow-500
        "D": "#f97316",  # orange-500
        "F": "#ef4444",  # red-500
    }
    color = _grade_colors.get(grade, "#6b7280")
    label_text = f"{grade}  {score}"
    svg = _make_badge("compliance", label_text, color)
    from fastapi.responses import Response as _Resp

    return _Resp(content=svg, media_type="image/svg+xml")


def _make_badge(label: str, value: str, color: str) -> str:
    """Generate a Shields.io-style flat SVG badge."""
    lw = len(label) * 7 + 10  # rough pixel width for label
    vw = len(value) * 7 + 10  # rough pixel width for value
    total = lw + vw
    lx = lw // 2
    vx = lw + vw // 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f"</linearGradient>"
        f'<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<rect width="{total}" height="20" fill="url(#s)"/>'
        f"</g>"
        f'<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">'
        f'<text x="{lx}" y="15" fill="#010101" fill-opacity=".3">{label}</text>'
        f'<text x="{lx}" y="14">{label}</text>'
        f'<text x="{vx}" y="15" fill="#010101" fill-opacity=".3">{value}</text>'
        f'<text x="{vx}" y="14">{value}</text>'
        f"</g>"
        f"</svg>"
    )


@router.get("/scan-image/{job_id}/report")
async def export_scan_report(job_id: str, request: Request, fmt: str = "html"):
    """Export a compliance scan report.

    ?fmt=html  (default) — rich printable HTML, print-to-PDF via browser
    ?fmt=json            — machine-readable job dict
    ?fmt=sarif           — SARIF 2.1.0 (GitHub Advanced Security, Azure DevOps)
    """
    job = audit_service.get_audit(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    if job.status != audit_service.AuditStatus.COMPLETE:
        raise HTTPException(status_code=400, detail=f"Scan not complete (status: {job.status.value})")

    if fmt == "json":
        return JSONResponse(content=_audit_to_dict(job))

    if fmt == "sarif":
        sarif = _to_sarif(job)
        fname = f"scan-{job_id[:8]}.sarif.json"
        return JSONResponse(
            content=sarif,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # Default: rich HTML report
    return _templates.TemplateResponse(
        request=request,
        name="auditor/report.html",
        context={"job": job, "job_dict": _audit_to_dict(job)},
    )


@router.get("/jobs/{job_id}/compare/{baseline_id}")
async def compare_scans(job_id: str, baseline_id: str) -> dict:
    """Compare two completed scan jobs and return a drift delta."""
    from statim.openscap.parser import compute_delta

    current = audit_service.get_audit(job_id)
    baseline = audit_service.get_audit(baseline_id)
    if not current or not baseline:
        raise HTTPException(status_code=404, detail="One or both jobs not found")
    if current.status != audit_service.AuditStatus.COMPLETE or baseline.status != audit_service.AuditStatus.COMPLETE:
        raise HTTPException(status_code=400, detail="Both jobs must be complete")

    # Normalise results to the format compute_delta expects (rules list)
    def _to_rules(job):
        r = job.results or {}
        if "rules" in r:
            return r  # local ARF parse format
        # SCAPParser format: convert findings → rules
        return {
            "score": r.get("score"),
            "rules": [
                {
                    "id": f["rule_id"],
                    "result": f["status"].replace("approved_exception", "notchecked"),
                    "severity": f.get("severity", "low"),
                }
                for f in r.get("findings", [])
            ],
        }

    delta = compute_delta(_to_rules(baseline), _to_rules(current))
    return {
        "job_id": job_id,
        "baseline_id": baseline_id,
        "score_delta": delta.get("score_delta"),
        "new_failures": delta.get("new_failures", []),
        "fixed": delta.get("fixed", []),
        "unchanged_failures": delta.get("unchanged_failures", []),
        "current_grade": current.grade,
        "baseline_grade": baseline.grade,
    }


@router.get("/jobs")
async def list_audit_jobs() -> list[dict]:
    return [_audit_to_dict(j) for j in audit_service.list_audits()]


@router.get("/jobs/{job_id}")
async def get_audit_job(job_id: str) -> dict:
    job = audit_service.get_audit(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Audit job not found")
    return _audit_to_dict(job)


def _resolve_profile(name: str):
    for p in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return profile
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")


def _to_sarif(job: audit_service.AuditJob) -> dict:
    """Convert a completed AuditJob to SARIF 2.1.0 format (pure JSON, no deps)."""
    _sev_map = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}
    rules = []
    results = []
    seen_rules: set[str] = set()
    findings = (job.results or {}).get("findings", [])
    # Also handle local ARF format (rules list)
    if not findings:
        for r in (job.results or {}).get("rules", []):
            if r.get("result") == "fail":
                findings.append(
                    {
                        "rule_id": r["id"],
                        "status": "fail",
                        "severity": r.get("severity", "low"),
                        "title": r.get("title", ""),
                    }
                )
    for finding in findings:
        if finding.get("status") != "fail":
            continue
        rule_id = finding.get("rule_id", "unknown")
        if rule_id not in seen_rules:
            seen_rules.add(rule_id)
            rules.append(
                {
                    "id": rule_id,
                    "name": rule_id,
                    "shortDescription": {"text": finding.get("title") or rule_id},
                    "properties": {"tags": ["compliance", "openscap"], "severity": finding.get("severity", "low")},
                }
            )
        results.append(
            {
                "ruleId": rule_id,
                "level": _sev_map.get((finding.get("severity") or "low").lower(), "warning"),
                "message": {"text": f"Compliance rule failed: {rule_id}"},
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": job.image_id or job.target_host or "unknown"}}}
                ],
            }
        )
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Statim Compliance Scanner",
                        "version": "0.1.1",
                        "informationUri": "https://github.com/invicton/statim",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "image_id": job.image_id,
                    "provider": job.provider,
                    "region": job.region,
                    "grade": job.grade,
                    "score_pct": job.score_pct,
                    "scan_date": job.updated_at.isoformat(),
                },
            }
        ],
    }


def _audit_to_dict(job: audit_service.AuditJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "target_host": job.target_host,
        "profile_name": job.profile_name,
        "status": job.status.value,
        "results": job.results,
        "delta": job.delta,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        # Image scan fields
        "image_id": job.image_id,
        "provider": job.provider,
        "region": job.region,
        "grade": job.grade,
        "score_pct": job.score_pct,
        "severity_counts": job.severity_counts,
    }
