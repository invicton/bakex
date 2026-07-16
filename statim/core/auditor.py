# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Live audit orchestration — scan production systems and produce delta reports."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from statim.core.blueprint import ComplianceProfile
from statim.core.parser import SCAPParser
from statim.openscap import scanner as oscap_scanner
from statim.openscap.container_scanner import run_container_scan
from statim.openscap.content import ensure_datastream, resolve_scan_spec
from statim.openscap.parser import compute_delta, parse_arf
from statim.plugins.registry import registry

logger = logging.getLogger(__name__)

_JOBS_FILE = Path("data/audit_jobs.json")


class AuditStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class AuditJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_host: str = ""
    profile_name: str = ""
    status: AuditStatus = AuditStatus.PENDING
    arf_path: Path | None = None
    results: dict | None = None
    delta: dict | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Image scan fields
    job_type: str = "live_audit"  # "live_audit" | "image_scan"
    image_id: str = ""  # Source image (AMI ID, snapshot ID, etc.)
    provider: str = ""  # Cloud provider name
    region: str = ""  # Cloud region
    grade: str | None = None  # A / B / C / D / F
    score_pct: float | None = None  # Normalised 0–100 compliance score
    severity_counts: dict = field(default_factory=dict)  # {critical/high/medium/low: int}


_audit_jobs: dict[str, AuditJob] = {}


def get_audit(job_id: str) -> AuditJob | None:
    return _audit_jobs.get(job_id)


def list_audits() -> list[AuditJob]:
    return sorted(_audit_jobs.values(), key=lambda j: j.created_at, reverse=True)


def _persist_jobs() -> None:
    """Serialize all audit jobs to data/audit_jobs.json. Called after every mutation."""
    try:
        _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        serialized = {
            jid: {
                "id": j.id,
                "job_type": j.job_type,
                "target_host": j.target_host,
                "profile_name": j.profile_name,
                "status": j.status.value,
                "image_id": j.image_id,
                "provider": j.provider,
                "region": j.region,
                "grade": j.grade,
                "score_pct": j.score_pct,
                "severity_counts": j.severity_counts,
                "results": j.results,
                "error": j.error,
                "created_at": j.created_at.isoformat(),
                "updated_at": j.updated_at.isoformat(),
            }
            for jid, j in _audit_jobs.items()
        }
        _JOBS_FILE.write_text(json.dumps(serialized, indent=2))
    except Exception as exc:
        logger.warning("Could not persist audit jobs: %s", exc)


def load_jobs() -> None:
    """Load persisted audit jobs from disk at startup."""
    if not _JOBS_FILE.exists():
        return
    try:
        data = json.loads(_JOBS_FILE.read_text())
        for jid, d in data.items():
            job = AuditJob(
                id=d["id"],
                job_type=d.get("job_type", "live_audit"),
                target_host=d.get("target_host", ""),
                profile_name=d.get("profile_name", ""),
                status=AuditStatus(d.get("status", "complete")),
                image_id=d.get("image_id", ""),
                provider=d.get("provider", ""),
                region=d.get("region", ""),
                grade=d.get("grade"),
                score_pct=d.get("score_pct"),
                severity_counts=d.get("severity_counts") or {},
                results=d.get("results"),
                error=d.get("error"),
                created_at=datetime.fromisoformat(d["created_at"]),
                updated_at=datetime.fromisoformat(d["updated_at"]),
            )
            _audit_jobs[jid] = job
        logger.info("Loaded %d audit jobs from disk", len(_audit_jobs))
    except Exception as exc:
        logger.warning("Could not load audit jobs from disk: %s", exc)


async def run_audit(
    profile: ComplianceProfile,
    target_host: str,
    ssh_user: str,
    output_dir: Path,
    baseline_arf: Path | None = None,
) -> AuditJob:
    """Scan a live host and optionally compute a delta against a baseline ARF.

    For cloud providers (handles_full_lifecycle=True) the audit is delegated to
    the subprocess provider via JSON-RPC; the returned XML is parsed by SCAPParser
    with the Exception Engine applied.

    For local providers the existing oscap SSH path is used unchanged.

    Args:
        profile: ComplianceProfile describing the benchmark to apply.
        target_host: Hostname/IP (local) or EC2 instance ID (cloud).
        ssh_user: SSH user on the target (local path only).
        output_dir: Where to write scan artefacts (local path only).
        baseline_arf: Optional path to a previous ARF for delta comparison.

    Returns:
        AuditJob with results and (if baseline provided) delta populated.
    """
    job = AuditJob(
        target_host=target_host,
        profile_name=profile.metadata.name,
    )
    _audit_jobs[job.id] = job

    try:
        job.status = AuditStatus.SCANNING
        job.updated_at = datetime.now(UTC)

        provider_cls = registry.get(profile.target.provider)
        use_cloud = provider_cls is not None and getattr(provider_cls, "handles_full_lifecycle", False)

        if use_cloud:
            # Cloud path: delegate to subprocess provider via JSON-RPC
            logger.info("Audit %s: dispatching remote audit via %s", job.id, profile.target.provider)
            provider = provider_cls()
            result = provider.audit(target_host, profile)
            raw_xml = result.get("raw_xml", "")
            job.results = SCAPParser.parse_report(raw_xml, profile.model_dump())
        else:
            # Local path: SSH + oscap (unchanged)
            scan_dir = output_dir / job.id
            job.arf_path = oscap_scanner.run_scan(
                profile,
                target_host=target_host,
                ssh_user=ssh_user,
                output_dir=scan_dir,
            )
            job.results = parse_arf(job.arf_path)

            if baseline_arf is not None and baseline_arf.exists():
                baseline = parse_arf(baseline_arf)
                job.delta = compute_delta(baseline, job.results)

        job.status = AuditStatus.COMPLETE
        job.updated_at = datetime.now(UTC)
        logger.info("Audit %s complete for %s", job.id, target_host)

    except Exception as exc:
        job.error = str(exc)
        job.status = AuditStatus.FAILED
        job.updated_at = datetime.now(UTC)
        logger.exception("Audit job %s failed", job.id)

    _persist_jobs()

    # Fire webhook notifications (best-effort, never raises)
    try:
        from statim.core.notifications import fire_webhook

        event = "scan.complete" if job.status == AuditStatus.COMPLETE else "scan.failed"
        import asyncio

        asyncio.create_task(
            fire_webhook(
                event,
                {
                    "job_id": job.id,
                    "image_id": job.image_id,
                    "provider": job.provider,
                    "region": job.region,
                    "profile": job.profile_name,
                    "grade": job.grade,
                    "score_pct": job.score_pct,
                    "severity_counts": job.severity_counts or {},
                    "status": job.status.value,
                    "error": job.error,
                },
            )
        )
    except Exception:
        pass

    return job


# ---------------------------------------------------------------------------
# Image scan helpers
# ---------------------------------------------------------------------------


def score_to_grade(score: float) -> str:
    """Convert a 0–100 compliance score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _severity_counts(results: dict) -> dict:
    """Tally failed rules by severity from a parsed scan results dict."""
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for rule in results.get("rules", []):
        if rule.get("result") == "fail":
            sev = rule.get("severity", "low").lower()
            if sev in counts:
                counts[sev] += 1
    return counts


async def run_image_scan(
    image_id: str,
    provider_name: str,
    region: str,
    profile: ComplianceProfile,
    instance_type: str,
    output_dir: Path,
) -> AuditJob:
    """Provision a temporary instance from *image_id*, run an OpenSCAP scan, then tear it down.

    For cloud providers (handles_full_lifecycle=True) the scan is delegated via
    the ``execute_scan_image`` JSON-RPC method.  For SSH-based providers the
    builder's provision/teardown pattern is used directly.

    Returns:
        AuditJob with ``grade``, ``score_pct``, and ``severity_counts`` populated.
    """
    job = AuditJob(
        job_type="image_scan",
        image_id=image_id,
        provider=provider_name,
        region=region,
        profile_name=profile.metadata.name,
        target_host=image_id,
    )
    _audit_jobs[job.id] = job

    instance_id: str | None = None
    provider_cls = registry.get(provider_name)
    if provider_cls is None:
        job.error = f"Provider '{provider_name}' not found or not installed"
        job.status = AuditStatus.FAILED
        return job

    try:
        job.status = AuditStatus.SCANNING
        job.updated_at = datetime.now(UTC)

        use_cloud = getattr(provider_cls, "handles_full_lifecycle", False)

        if use_cloud:
            logger.info("Image scan %s: dispatching execute_scan_image via %s", job.id, provider_name)
            provider = provider_cls()
            params = {
                "image_id": image_id,
                "instance_type": instance_type,
                "region": region,
                "os": profile.target.os,
                "benchmark": profile.compliance.benchmark,
                "profile": profile.compliance.profile,
                "datastream": profile.compliance.datastream,
            }
            result = provider.scan_image(params)
            raw_xml = result.get("raw_xml", "")
            job.results = SCAPParser.parse_report(raw_xml, profile.model_dump())
        else:
            # SSH-based providers: provision → scan → teardown
            provider = provider_cls()
            logger.info("Image scan %s: provisioning temp instance from %s via %s", job.id, image_id, provider_name)
            instance_id = provider.provision(profile)

            scan_dir = output_dir / job.id
            job.arf_path = oscap_scanner.run_scan(
                profile,
                target_host=instance_id,
                output_dir=scan_dir,
            )
            job.results = parse_arf(job.arf_path)

        # Compute grade from score
        score = job.results.get("score") if job.results else None
        if score is not None:
            job.score_pct = float(score)
            job.grade = score_to_grade(job.score_pct)
        job.severity_counts = _severity_counts(job.results or {})

        job.status = AuditStatus.COMPLETE
        job.updated_at = datetime.now(UTC)
        logger.info(
            "Image scan %s complete — image=%s grade=%s score=%.1f",
            job.id,
            image_id,
            job.grade,
            job.score_pct or 0,
        )

    except Exception as exc:
        job.error = str(exc)
        job.status = AuditStatus.FAILED
        job.updated_at = datetime.now(UTC)
        logger.exception("Image scan job %s failed", job.id)

    finally:
        if instance_id is not None:
            try:
                provider_cls().teardown(instance_id)
            except Exception:
                logger.warning("Image scan %s: teardown of %s failed (ignored)", job.id, instance_id)

    _persist_jobs()
    return job


async def run_container_scan_job(
    job: AuditJob,
    image_ref: str,
    os_slug: str,
    tier: str,
    output_dir: Path,
) -> AuditJob:
    """Scan a local container image against its OS SCAP datastream via oscap-podman.

    OS-level configuration compliance of the image *contents* — not the CIS Docker
    Benchmark (daemon/runtime) and not CVEs. The caller creates *job* and registers
    it in ``_audit_jobs`` so the API can return its id immediately; this populates
    grade/score/severity or an actionable error. No VM, no teardown.
    """
    try:
        job.status = AuditStatus.SCANNING
        job.updated_at = datetime.now(UTC)

        benchmark, profile_id, datastream_path = resolve_scan_spec(os_slug, tier)
        datastream = ensure_datastream(datastream_path)

        job.arf_path = run_container_scan(
            image_ref=image_ref,
            benchmark_id=benchmark,
            profile_id=profile_id,
            datastream=str(datastream),
            output_dir=output_dir / job.id,
        )
        job.results = parse_arf(job.arf_path)

        score = job.results.get("score") if job.results else None
        if score is not None:
            job.score_pct = float(score)
            job.grade = score_to_grade(job.score_pct)
        job.severity_counts = _severity_counts(job.results or {})

        job.status = AuditStatus.COMPLETE
        job.updated_at = datetime.now(UTC)
        logger.info("Container scan %s complete — image=%s grade=%s", job.id, image_ref, job.grade)

    except Exception as exc:
        job.error = str(exc)
        job.status = AuditStatus.FAILED
        job.updated_at = datetime.now(UTC)
        logger.exception("Container scan job %s failed", job.id)

    _persist_jobs()
    return job
