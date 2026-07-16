# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for the drop-in provider loader and registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from bakex.plugins.base_provider import BaseProvider, ProviderResult
from bakex.plugins.loader import _is_valid_provider, _validate_provider, load_providers
from bakex.plugins.registry import ProviderRegistry


class _ConcreteProvider(BaseProvider):
    name = "test_concrete"

    def provision(self, profile, **kwargs):
        return "instance-001"

    def run_ansible(self, instance_id, profile):
        pass

    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="img-001", artifact_type="qcow2")

    def teardown(self, instance_id):
        pass


def test_is_valid_provider_accepts_concrete():
    assert _is_valid_provider(_ConcreteProvider) is True


def test_is_valid_provider_rejects_base():
    assert _is_valid_provider(BaseProvider) is False


def test_is_valid_provider_rejects_non_class():
    assert _is_valid_provider("not_a_class") is False


def test_load_providers_from_empty_dir(tmp_path):
    providers, warnings = load_providers(tmp_path)
    assert providers == {}
    assert warnings == []


def test_load_providers_from_nonexistent_dir(tmp_path):
    providers, warnings = load_providers(tmp_path / "does_not_exist")
    assert providers == {}


def test_load_providers_drop_in(tmp_path):
    plugin_src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class DropInProvider(BaseProvider):
    name = "dropin"

    def provision(self, profile, **kwargs):
        return "inst-1"

    def run_ansible(self, instance_id, profile):
        pass

    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="art-1", artifact_type="ami")

    def teardown(self, instance_id):
        pass
"""
    (tmp_path / "dropin_provider.py").write_text(plugin_src)
    providers, warnings = load_providers(tmp_path)
    assert "dropin" in providers
    assert issubclass(providers["dropin"], BaseProvider)
    assert warnings == []


def test_drop_in_underscore_files_ignored(tmp_path):
    (tmp_path / "_private.py").write_text("x = 1")
    providers, warnings = load_providers(tmp_path)
    assert providers == {}


def test_load_example_local_provider():
    providers, _ = load_providers(Path("plugins/providers"))
    assert "local" in providers, "example_local.py should register a 'local' provider"


def test_registry_singleton():
    r1 = ProviderRegistry()
    r2 = ProviderRegistry()
    assert r1 is r2


def test_registry_get_missing_raises():
    registry = ProviderRegistry()
    with pytest.raises(KeyError, match="missing_provider"):
        registry.get("missing_provider")


def test_registry_load_and_get(tmp_path):
    plugin_src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class RegTestProvider(BaseProvider):
    name = "regtest"

    def provision(self, profile, **kwargs): return "i-1"
    def run_ansible(self, instance_id, profile): pass
    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="a-1", artifact_type="ami")
    def teardown(self, instance_id): pass
"""
    (tmp_path / "regtest.py").write_text(plugin_src)

    registry = ProviderRegistry()
    registry.load(tmp_path)
    assert "regtest" in registry.names()
    cls = registry.get("regtest")
    assert cls.name == "regtest"


# ── New hardening tests ───────────────────────────────────────────────────────


def test_strict_mode_raises_on_broken_plugin(tmp_path):
    """A plugin that fails to import should raise RuntimeError in strict mode."""
    (tmp_path / "bad.py").write_text("from nonexistent_module_xyz import something\n")
    with pytest.raises(RuntimeError, match="Plugin loading failed"):
        load_providers(tmp_path, strict=True)


def test_non_strict_mode_skips_broken_plugin(tmp_path):
    """A broken plugin is silently skipped (returns empty dict) in non-strict mode."""
    (tmp_path / "bad.py").write_text("from nonexistent_module_xyz import something\n")
    providers, warnings = load_providers(tmp_path, strict=False)
    assert providers == {}


def test_abstract_method_not_implemented_strict(tmp_path):
    """A drop-in that doesn't implement all abstract methods raises in strict mode."""
    plugin_src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class IncompleteProvider(BaseProvider):
    name = "incomplete"

    def provision(self, profile, **kwargs): return "i-1"
    # missing run_ansible, snapshot, teardown
"""
    (tmp_path / "incomplete.py").write_text(plugin_src)
    with pytest.raises(RuntimeError, match="Plugin loading failed"):
        load_providers(tmp_path, strict=True)


def test_name_collision_emits_warning(tmp_path):
    """When two drop-ins share the same provider name, a warning is returned."""
    good_src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class ProviderA(BaseProvider):
    name = "dupe"
    def provision(self, profile, **kwargs): return "i-a"
    def run_ansible(self, instance_id, profile): pass
    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="a", artifact_type="ami")
    def teardown(self, instance_id): pass
"""
    override_src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class ProviderB(BaseProvider):
    name = "dupe"
    def provision(self, profile, **kwargs): return "i-b"
    def run_ansible(self, instance_id, profile): pass
    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="b", artifact_type="ami")
    def teardown(self, instance_id): pass
"""
    # a_plugin.py sorts before b_plugin.py so B overrides A
    (tmp_path / "a_plugin.py").write_text(good_src)
    (tmp_path / "b_plugin.py").write_text(override_src)
    providers, warnings = load_providers(tmp_path, strict=True)
    assert "dupe" in providers
    assert any("dupe" in w for w in warnings), f"Expected collision warning, got: {warnings}"


def test_validate_provider_rejects_missing_name():
    class NoName(BaseProvider):
        def provision(self, profile, **kwargs):
            return ""

        def run_ansible(self, instance_id, profile):
            pass

        def snapshot(self, instance_id, profile):
            return ProviderResult(artifact_id="", artifact_type="")

        def teardown(self, instance_id):
            pass

    with pytest.raises(TypeError, match="name"):
        _validate_provider(NoName)


def test_registry_load_returns_warnings(tmp_path):
    """registry.load() should pass through collision warnings."""
    src = """\
from bakex.plugins.base_provider import BaseProvider, ProviderResult

class P(BaseProvider):
    name = "coltest"
    def provision(self, profile, **kwargs): return "i"
    def run_ansible(self, instance_id, profile): pass
    def snapshot(self, instance_id, profile):
        return ProviderResult(artifact_id="a", artifact_type="ami")
    def teardown(self, instance_id): pass
"""
    (tmp_path / "a_coltest.py").write_text(src)
    (tmp_path / "b_coltest.py").write_text(src.replace("class P", "class Q"))
    reg = ProviderRegistry()
    warnings = reg.load(tmp_path, strict=True)
    assert any("coltest" in w for w in warnings)
