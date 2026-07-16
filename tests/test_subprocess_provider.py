# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for subprocess provider adapter and loader integration."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from bakex.core.blueprint import ComplianceProfile
from bakex.plugins.base_provider import BaseProvider, ProviderResult
from bakex.plugins.loader import _validate_provider, load_providers
from bakex.plugins.subprocess_provider import (
    _build_params,
    _call_rpc,
    make_subprocess_provider_class,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIMAL_PROFILE_DATA = {
    "bakex_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {"name": "test-profile", "version": "1.0.0"},
    "target": {
        "os": "ubuntu22.04",
        "arch": "x86_64",
        "provider": "aws",
        "base_image": "ami-12345678",
    },
    "compliance": {
        "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
        "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
    },
}


@pytest.fixture
def profile() -> ComplianceProfile:
    return ComplianceProfile.model_validate(MINIMAL_PROFILE_DATA)


@pytest.fixture
def echo_script(tmp_path) -> Path:
    """Script that returns a successful JSON-RPC result."""
    script = tmp_path / "echo_provider.py"
    script.write_text(
        "import json, sys\n"
        "req = json.loads(sys.stdin.read())\n"
        'print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), '
        '"result": {"artifact_id": "art-test-001", "artifact_type": "ami",'
        ' "region": "us-east-1"}}))\n'
    )
    return script


@pytest.fixture
def error_script(tmp_path) -> Path:
    """Script that returns a JSON-RPC error response."""
    script = tmp_path / "error_provider.py"
    script.write_text(
        "import json, sys\n"
        "req = json.loads(sys.stdin.read())\n"
        'print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), '
        '"error": {"code": -32603, "message": "intentional error"}}))\n'
    )
    return script


# ── TestMakeSubprocessProviderClass ──────────────────────────────────────────


class TestMakeSubprocessProviderClass:
    def test_name_binding(self):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        assert cls.name == "aws"

    def test_script_path_binding(self):
        path = Path("/tmp/aws.py")
        cls = make_subprocess_provider_class(path, "aws")
        assert cls._script_path == path

    def test_is_subclass_of_base_provider(self):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        assert issubclass(cls, BaseProvider)

    def test_handles_full_lifecycle_true(self):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        assert cls.handles_full_lifecycle is True

    def test_validate_provider_passes(self):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        _validate_provider(cls)  # should not raise

    def test_distinct_classes_per_name(self):
        cls1 = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        cls2 = make_subprocess_provider_class(Path("/tmp/do.py"), "digitalocean")
        assert cls1 is not cls2
        assert cls1.name != cls2.name


# ── TestSubprocessProviderNoOps ───────────────────────────────────────────────


class TestSubprocessProviderNoOps:
    def test_provision_returns_sentinel(self, profile):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        provider = cls()
        assert provider.provision(profile) == "__subprocess_deferred__"

    def test_run_ansible_returns_none(self, profile):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        provider = cls()
        assert provider.run_ansible("__subprocess_deferred__", profile) is None

    def test_teardown_returns_none(self):
        cls = make_subprocess_provider_class(Path("/tmp/aws.py"), "aws")
        provider = cls()
        assert provider.teardown("__subprocess_deferred__") is None


# ── TestSubprocessProviderSnapshot ───────────────────────────────────────────


class TestSubprocessProviderSnapshot:
    def test_returns_provider_result(self, profile, echo_script):
        cls = make_subprocess_provider_class(echo_script, "aws")
        result = cls().snapshot("__subprocess_deferred__", profile)
        assert isinstance(result, ProviderResult)

    def test_correct_artifact_id(self, profile, echo_script):
        cls = make_subprocess_provider_class(echo_script, "aws")
        result = cls().snapshot("__subprocess_deferred__", profile)
        assert result.artifact_id == "art-test-001"

    def test_correct_artifact_type(self, profile, echo_script):
        cls = make_subprocess_provider_class(echo_script, "aws")
        result = cls().snapshot("__subprocess_deferred__", profile)
        assert result.artifact_type == "ami"

    def test_correct_region(self, profile, echo_script):
        cls = make_subprocess_provider_class(echo_script, "aws")
        result = cls().snapshot("__subprocess_deferred__", profile)
        assert result.region == "us-east-1"

    def test_raises_on_missing_artifact_id(self, profile, tmp_path):
        script = tmp_path / "no_artifact.py"
        script.write_text(
            "import json, sys\n"
            "req = json.loads(sys.stdin.read())\n"
            'print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), '
            '"result": {"status": "success"}}))\n'
        )
        cls = make_subprocess_provider_class(script, "aws")
        with pytest.raises(RuntimeError, match="artifact_id"):
            cls().snapshot("__subprocess_deferred__", profile)


# ── TestCallRpc ───────────────────────────────────────────────────────────────


class TestCallRpc:
    def test_successful_call(self, echo_script):
        result = _call_rpc(echo_script, "execute_build", {})
        assert result["artifact_id"] == "art-test-001"

    def test_rpc_error_raises(self, error_script):
        with pytest.raises(RuntimeError, match="intentional error"):
            _call_rpc(error_script, "execute_build", {})

    def test_non_zero_exit_raises(self, tmp_path):
        script = tmp_path / "exitone.py"
        script.write_text("import sys; sys.stdin.read(); sys.exit(1)\n")
        with pytest.raises(RuntimeError, match="exited with code 1"):
            _call_rpc(script, "execute_build", {})

    def test_empty_stdout_raises(self, tmp_path):
        script = tmp_path / "silent.py"
        script.write_text("import sys; sys.stdin.read()\n")
        with pytest.raises(RuntimeError, match="no output"):
            _call_rpc(script, "execute_build", {})

    def test_malformed_json_raises(self, tmp_path):
        script = tmp_path / "badjson.py"
        script.write_text("import sys; sys.stdin.read(); print('not json')\n")
        with pytest.raises(RuntimeError, match="invalid JSON"):
            _call_rpc(script, "execute_build", {})

    def test_stderr_forwarded_to_logger(self, tmp_path, caplog):
        script = tmp_path / "with_stderr.py"
        script.write_text(
            "import json, sys\n"
            "req = json.loads(sys.stdin.read())\n"
            "print('hello from stderr', file=sys.stderr)\n"
            'print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), '
            '"result": {"artifact_id": "x", "region": ""}}))\n'
        )
        with caplog.at_level(logging.DEBUG, logger="bakex.plugins.subprocess_provider"):
            _call_rpc(script, "execute_build", {})
        assert any("hello from stderr" in r.message for r in caplog.records)

    def test_timeout_raises(self, tmp_path):
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(60)\n")
        with pytest.raises(subprocess.TimeoutExpired):
            _call_rpc(script, "execute_build", {}, timeout_seconds=1)

    def test_unknown_method_raises(self, tmp_path):
        script = tmp_path / "unknown_method.py"
        script.write_text(
            "import json, sys\n"
            "req = json.loads(sys.stdin.read())\n"
            'print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), '
            '"error": {"code": -32601, "message": "Method not found"}}))\n'
        )
        with pytest.raises(RuntimeError, match="Method not found"):
            _call_rpc(script, "unknown_method", {})


# ── TestBuildParams ───────────────────────────────────────────────────────────


class TestBuildParams:
    def test_all_required_keys_present(self, profile):
        params = _build_params(profile)
        for key in (
            "base_image",
            "os",
            "arch",
            "benchmark",
            "profile",
            "datastream",
            "profile_name",
            "profile_version",
        ):
            assert key in params, f"Missing key: {key!r}"

    def test_values_match_profile(self, profile):
        params = _build_params(profile)
        assert params["base_image"] == "ami-12345678"
        assert params["os"] == "ubuntu22.04"
        assert params["arch"] == "x86_64"
        assert params["profile_name"] == "test-profile"
        assert params["profile_version"] == "1.0.0"


# ── TestLoaderSubprocessIntegration ──────────────────────────────────────────


class TestLoaderSubprocessIntegration:
    def test_subprocess_script_detected_by_loader(self, tmp_path):
        (tmp_path / "mycloud.py").write_text('PROVIDER_NAME = "mycloud"\n')
        providers, _ = load_providers(tmp_path)
        assert "mycloud" in providers

    def test_subprocess_class_is_subclass_of_base_provider(self, tmp_path):
        (tmp_path / "mycloud.py").write_text('PROVIDER_NAME = "mycloud"\n')
        providers, _ = load_providers(tmp_path)
        assert issubclass(providers["mycloud"], BaseProvider)

    def test_subprocess_and_class_based_coexist(self, tmp_path):
        (tmp_path / "cloud.py").write_text('PROVIDER_NAME = "cloud"\n')
        (tmp_path / "classic.py").write_text(
            "from bakex.plugins.base_provider import BaseProvider, ProviderResult\n"
            "class ClassicProvider(BaseProvider):\n"
            "    name = 'classic'\n"
            "    def provision(self, p, **kw): return 'i'\n"
            "    def run_ansible(self, i, p): pass\n"
            "    def snapshot(self, i, p):\n"
            "        return ProviderResult(artifact_id='a', artifact_type='t')\n"
            "    def teardown(self, i): pass\n"
        )
        providers, _ = load_providers(tmp_path)
        assert "cloud" in providers
        assert "classic" in providers

    def test_local_provider_still_loads_as_class_based(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "local" in providers
        assert not getattr(providers["local"], "handles_full_lifecycle", False)

    def test_subprocess_provider_handles_full_lifecycle(self, tmp_path):
        (tmp_path / "sp.py").write_text('PROVIDER_NAME = "sp"\n')
        providers, _ = load_providers(tmp_path)
        assert providers["sp"].handles_full_lifecycle is True

    def test_aws_and_digitalocean_loaded_from_plugins_dir(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "aws" in providers
        assert "digitalocean" in providers
        assert providers["aws"].handles_full_lifecycle is True
        assert providers["digitalocean"].handles_full_lifecycle is True
