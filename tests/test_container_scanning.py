# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Container image scanning — local oscap-podman/oscap-docker scanner + content resolution.

CONT-01  engine selection prefers oscap-podman, falls back to oscap-docker, else errors
CONT-02  the oscap-podman command is assembled correctly
CONT-03  exit codes 0 and 2 are tolerated; anything else raises ScanError
CONT-04  resolve_scan_spec maps os+tier → (benchmark, profile, datastream) from OS_CATALOG
CONT-05  resolve_scan_spec on an unknown OS raises an actionable error listing supported OSes
CONT-06  ensure_datastream returns the host path when present, downloads when absent
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from invicton.openscap import container_scanner as cs
from invicton.openscap import content as content_mod
from invicton.openscap.scanner import ScanError

# ---------------------------------------------------------------------------
# CONT-01 — engine selection
# ---------------------------------------------------------------------------


def test_select_engine_prefers_podman():
    with patch.object(cs.shutil, "which", side_effect=lambda b: "/usr/bin/" + b):
        assert cs.select_engine() == "oscap-podman"


def test_select_engine_falls_back_to_docker():
    def _which(b):
        return "/usr/bin/oscap-docker" if b == "oscap-docker" else None

    with patch.object(cs.shutil, "which", side_effect=_which):
        assert cs.select_engine() == "oscap-docker"


def test_select_engine_missing_both_raises_actionable():
    with patch.object(cs.shutil, "which", return_value=None):
        with pytest.raises(ScanError) as exc:
            cs.select_engine()
    msg = str(exc.value)
    assert "oscap-podman" in msg
    assert "install" in msg.lower()


# ---------------------------------------------------------------------------
# CONT-02 — command assembly
# ---------------------------------------------------------------------------


def test_build_command_shape(tmp_path):
    cmd = cs._build_command(
        engine="oscap-podman",
        image_ref="ubuntu:22.04",
        benchmark_id="xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        profile_id="xccdf_org.ssgproject.content_profile_cis_level1_server",
        arf_path=tmp_path / "arf.xml",
        report_path=tmp_path / "report.html",
        datastream="/host/ssg-ubuntu2204-ds.xml",
    )
    assert cmd[0] == "oscap-podman"
    assert cmd[1] == "ubuntu:22.04"  # image ref before the xccdf subcommand
    assert "xccdf" in cmd and "eval" in cmd
    assert "--profile" in cmd
    assert cmd[-1] == "/host/ssg-ubuntu2204-ds.xml"  # datastream last
    assert "--results-arf" in cmd


# ---------------------------------------------------------------------------
# CONT-03 — exit-code handling
# ---------------------------------------------------------------------------


def _mock_run(returncode):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = ""
    m.stderr = "boom" if returncode not in (0, 2) else ""
    return m


@pytest.mark.parametrize("code", [0, 2])
def test_run_container_scan_tolerates_pass_and_findings(tmp_path, code):
    with (
        patch.object(cs, "select_engine", return_value="oscap-podman"),
        patch.object(cs.subprocess, "run", return_value=_mock_run(code)),
    ):
        arf = cs.run_container_scan(
            image_ref="ubuntu:22.04",
            benchmark_id="b",
            profile_id="p",
            datastream="/host/ds.xml",
            output_dir=tmp_path,
        )
    assert arf == tmp_path / "results-arf.xml"


def test_run_container_scan_raises_on_other_exit(tmp_path):
    with (
        patch.object(cs, "select_engine", return_value="oscap-podman"),
        patch.object(cs.subprocess, "run", return_value=_mock_run(1)),
    ):
        with pytest.raises(ScanError):
            cs.run_container_scan(
                image_ref="ubuntu:22.04",
                benchmark_id="b",
                profile_id="p",
                datastream="/host/ds.xml",
                output_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# CONT-04 / CONT-05 — profile/datastream resolution from OS_CATALOG
# ---------------------------------------------------------------------------


def test_resolve_scan_spec_ubuntu22_l1():
    benchmark, profile, datastream = content_mod.resolve_scan_spec("ubuntu22.04", "cis-l1")
    assert benchmark == "xccdf_org.ssgproject.content_benchmark_UBUNTU2204"
    assert profile == "xccdf_org.ssgproject.content_profile_cis_level1_server"
    assert datastream.endswith("ssg-ubuntu2204-ds.xml")


def test_resolve_scan_spec_unknown_os_lists_supported():
    with pytest.raises(ValueError) as exc:
        content_mod.resolve_scan_spec("plan9", "cis-l1")
    msg = str(exc.value)
    assert "plan9" in msg
    assert "ubuntu22.04" in msg  # supported list surfaced


# ---------------------------------------------------------------------------
# CONT-06 — datastream availability on the host
# ---------------------------------------------------------------------------


def test_ensure_datastream_returns_host_path_when_present(tmp_path):
    ds = tmp_path / "ssg-ubuntu2204-ds.xml"
    ds.write_text("<xml/>")
    result = content_mod.ensure_datastream(str(ds), cache_dir=tmp_path / "cache")
    assert result == ds


def test_ensure_datastream_downloads_when_absent(tmp_path):
    cache = tmp_path / "cache"
    downloaded = cache / "ssg-ubuntu2204-ds.xml"

    def _fake_download(datastream_path, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        downloaded.write_text("<xml/>")
        return downloaded

    with patch.object(content_mod, "_download_datastream", side_effect=_fake_download):
        result = content_mod.ensure_datastream("/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml", cache_dir=cache)
    assert result == downloaded


def test_ensure_datastream_unavailable_raises(tmp_path):
    with patch.object(content_mod, "_download_datastream", return_value=None):
        with pytest.raises(content_mod.ScanContentError):
            content_mod.ensure_datastream("/nope/ssg-missing-ds.xml", cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# P2 — orchestration + API (CONT-08..12)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_container_scan_job_produces_graded_complete_job(tmp_path, monkeypatch):
    from invicton.core import auditor

    monkeypatch.setattr(auditor, "resolve_scan_spec", lambda os_slug, tier: ("bench", "prof", "/ds.xml"))
    monkeypatch.setattr(auditor, "ensure_datastream", lambda ds, cache_dir=None: Path(ds))
    monkeypatch.setattr(auditor, "run_container_scan", lambda **kw: tmp_path / "arf.xml")
    monkeypatch.setattr(
        auditor,
        "parse_arf",
        lambda p: {"score": 88.0, "rules": [{"id": "r", "result": "fail", "severity": "high"}]},
    )
    job = auditor.AuditJob(job_type="container_scan", image_id="ubuntu:22.04")
    auditor._audit_jobs[job.id] = job
    try:
        await auditor.run_container_scan_job(job, "ubuntu:22.04", "ubuntu22.04", "cis-l1", tmp_path)
        assert job.status == auditor.AuditStatus.COMPLETE
        assert job.score_pct == 88.0
        assert job.grade == "B"  # 88 → B
        assert job.severity_counts.get("high") == 1
    finally:
        auditor._audit_jobs.pop(job.id, None)


@pytest.mark.anyio
async def test_run_container_scan_job_scanner_error_fails_job(tmp_path, monkeypatch):
    from invicton.core import auditor
    from invicton.openscap.scanner import ScanError

    monkeypatch.setattr(auditor, "resolve_scan_spec", lambda os_slug, tier: ("b", "p", "/ds.xml"))
    monkeypatch.setattr(auditor, "ensure_datastream", lambda ds, cache_dir=None: Path(ds))

    def _boom(**kw):
        raise ScanError("oscap-podman missing")

    monkeypatch.setattr(auditor, "run_container_scan", _boom)
    job = auditor.AuditJob(job_type="container_scan", image_id="ubuntu:22.04")
    auditor._audit_jobs[job.id] = job
    try:
        await auditor.run_container_scan_job(job, "ubuntu:22.04", "ubuntu22.04", "cis-l1", tmp_path)
        assert job.status == auditor.AuditStatus.FAILED
        assert "oscap-podman" in (job.error or "")
    finally:
        auditor._audit_jobs.pop(job.id, None)


@pytest.mark.anyio
async def test_run_container_scan_job_unknown_os_is_actionable(tmp_path):
    from invicton.core import auditor

    job = auditor.AuditJob(job_type="container_scan", image_id="weird:latest")
    auditor._audit_jobs[job.id] = job
    try:
        await auditor.run_container_scan_job(job, "weird:latest", "plan9", "cis-l1", tmp_path)
        assert job.status == auditor.AuditStatus.FAILED
        assert "plan9" in (job.error or "")  # resolve_scan_spec lists supported OSes
    finally:
        auditor._audit_jobs.pop(job.id, None)
