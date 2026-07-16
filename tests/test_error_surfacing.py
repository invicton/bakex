# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Error-surfacing tests — errors must be loud, specific, and actionable.

ERR-01  /health?deep=1 reports missing system binaries
ERR-02  /api/system/deps returns per-dependency status with install hints
ERR-03  missing ansible-playbook fails fast with an actionable message
ERR-04  kvm execute_build preflights binaries before any real work
ERR-05  builder UI partial renders job.error in a dedicated panel on FAILED
ERR-06  unhandled route exceptions return structured 500 with an error id
ERR-07  unexpected internal errors in blueprint upload are not mislabelled 422
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_TEST_ADMIN_TOKEN = "test-admin-token"
_AUTH_HEADER = {"Authorization": "Basic " + base64.b64encode(f"admin:{_TEST_ADMIN_TOKEN}".encode()).decode()}

_KVM_PATH = Path(__file__).parent.parent / "plugins" / "providers" / "kvm.py"


@pytest.fixture
def raw_client(monkeypatch):
    """TestClient that surfaces 500 responses instead of re-raising, with admin auth."""
    from statim.config import settings
    from statim.main import app

    monkeypatch.setattr(settings, "statim_admin_token", _TEST_ADMIN_TOKEN)
    with patch("statim.main.init_registry"):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.headers.update(_AUTH_HEADER)
            yield c


# ---------------------------------------------------------------------------
# ERR-01 / ERR-02 — system dependency diagnostics
# ---------------------------------------------------------------------------


def test_sysdeps_check_reports_missing_binary(monkeypatch):
    from statim.core import sysdeps

    monkeypatch.setattr(sysdeps.shutil, "which", lambda name: None)
    report = sysdeps.check_system_deps()
    assert report, "expected a non-empty dependency report"
    for dep in report:
        assert dep["present"] is False
        assert dep["install_hint"], f"{dep['name']} has no install hint"


def test_health_deep_reports_missing_binaries(raw_client, monkeypatch):
    from statim.core import sysdeps

    monkeypatch.setattr(sysdeps.shutil, "which", lambda name: None)
    resp = raw_client.get("/health", params={"deep": "1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "system_deps" in data
    missing = [d["name"] for d in data["system_deps"] if not d["present"]]
    assert "ansible-playbook" in missing
    assert "qemu-system-x86_64" in missing


def test_health_shallow_unchanged(raw_client):
    resp = raw_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "system_deps" not in data


def test_system_deps_endpoint_schema(raw_client):
    resp = raw_client.get("/api/system/deps")
    assert resp.status_code == 200
    deps = resp.json()
    names = {d["name"] for d in deps}
    assert {"ansible-playbook", "qemu-system-x86_64", "oscap"} <= names
    for d in deps:
        assert set(d) >= {"name", "present", "needed_for", "install_hint"}


# ---------------------------------------------------------------------------
# ERR-03 — ansible-playbook preflight
# ---------------------------------------------------------------------------


def test_prehard_ansible_missing_binary_is_actionable(monkeypatch):
    from statim.core import builder

    monkeypatch.setattr(builder.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as exc_info:
        builder._run_prehard_ansible(Path("/tmp/playbook.yml"), "10.0.0.1")
    msg = str(exc_info.value)
    assert "ansible-playbook" in msg
    assert "install" in msg.lower()
    assert "FileNotFoundError" not in msg


# ---------------------------------------------------------------------------
# ERR-04 — kvm build preflights binaries
# ---------------------------------------------------------------------------


def test_kvm_execute_build_preflights_binaries():
    spec = importlib.util.spec_from_file_location("kvm_provider_err", _KVM_PATH)
    kvm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kvm)

    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            kvm.execute_build({"base_image": "ubuntu22.04", "os": "ubuntu22.04"})
    assert "qemu" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# ERR-05 — builder failure panel in the UI partial
# ---------------------------------------------------------------------------


def test_job_status_partial_renders_error_panel(raw_client):
    from statim.core import builder

    job = builder.BuildJob(profile_name="p", provider_name="kvm")
    job.status = builder.BuildStatus.FAILED
    job.error = "qemu-system-x86_64 not found on PATH — install qemu-system-x86"
    builder._jobs[job.id] = job
    try:
        resp = raw_client.get(f"/api/builder/jobs/{job.id}/status")
        assert resp.status_code == 200
        assert "qemu-system-x86_64 not found on PATH" in resp.text
        assert 'data-testid="job-error"' in resp.text
    finally:
        builder._jobs.pop(job.id, None)


# ---------------------------------------------------------------------------
# ERR-06 — global exception handler
# ---------------------------------------------------------------------------


def test_unhandled_exception_returns_structured_500(raw_client, monkeypatch):
    import statim.api.ui as ui_mod

    def _boom():
        raise RuntimeError("synthetic unhandled failure")

    monkeypatch.setattr(ui_mod, "list_jobs", _boom)
    resp = raw_client.get("/")
    assert resp.status_code == 500
    body = resp.text
    assert "error_id" in body
    assert "synthetic unhandled failure" not in body  # internals must not leak


# ---------------------------------------------------------------------------
# ERR-07 — unexpected internal errors are not mislabelled as 422
# ---------------------------------------------------------------------------


def test_upload_internal_error_is_not_422(raw_client, monkeypatch, tmp_path):
    from statim.config import settings
    from statim.core.blueprint import ComplianceProfile

    monkeypatch.setattr(settings, "user_profiles_dir", tmp_path)

    def _internal_boom(cls, data):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(ComplianceProfile, "model_validate", classmethod(_internal_boom))
    resp = raw_client.post(
        "/api/blueprints/upload",
        files={"file": ("bp.yaml", b"statim_version: '0.1.0'\nkind: ComplianceProfile\n", "text/yaml")},
    )
    assert resp.status_code == 500, f"expected 500, got {resp.status_code}: {resp.text[:200]}"
    assert "database exploded" not in resp.text
