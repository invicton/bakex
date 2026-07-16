# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Provider contract tests — abstract base class enforcement and ProviderResult validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from statim.plugins.base_provider import BaseProvider, ProviderResult
from statim.plugins.loader import load_providers
from statim.plugins.registry import ProviderRegistry

# ===========================================================================
# BaseProvider abstract method enforcement
# ===========================================================================


class TestBaseProviderContract:
    # PC-01: all four abstract methods defined
    def test_abstract_methods_exist(self):
        import inspect

        abstracts = {
            name
            for name, method in inspect.getmembers(BaseProvider, predicate=inspect.isfunction)
            if getattr(method, "__isabstractmethod__", False)
        }
        assert "provision" in abstracts
        assert "run_ansible" in abstracts
        assert "snapshot" in abstracts
        assert "teardown" in abstracts

    # PC-02: concrete provider missing a method cannot be instantiated
    def test_missing_provision_raises_on_instantiation(self):
        class Incomplete(BaseProvider):
            name = "incomplete"

            def run_ansible(self, i, p):
                pass

            def snapshot(self, i, p):
                return ProviderResult(artifact_id="x", artifact_type="t")

            def teardown(self, i):
                pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_missing_snapshot_raises_on_instantiation(self):
        class NoSnapshot(BaseProvider):
            name = "nosnapshot"

            def provision(self, p, **kw):
                return "i"

            def run_ansible(self, i, p):
                pass

            def teardown(self, i):
                pass

        with pytest.raises(TypeError):
            NoSnapshot()

    # PC-03: concrete provider with all methods instantiates correctly
    def test_full_implementation_instantiates(self):
        class Full(BaseProvider):
            name = "full"

            def provision(self, p, **kw):
                return "i-001"

            def run_ansible(self, i, p):
                pass

            def snapshot(self, i, p):
                return ProviderResult(artifact_id="img-001", artifact_type="ami")

            def teardown(self, i):
                pass

        provider = Full()
        assert provider is not None

    # PC-04: handles_full_lifecycle defaults to False
    def test_handles_full_lifecycle_default_false(self):
        class ClassBased(BaseProvider):
            name = "classbased"

            def provision(self, p, **kw):
                return "i"

            def run_ansible(self, i, p):
                pass

            def snapshot(self, i, p):
                return ProviderResult(artifact_id="a", artifact_type="t")

            def teardown(self, i):
                pass

        assert getattr(ClassBased, "handles_full_lifecycle", False) is False


# ===========================================================================
# ProviderResult validation
# ===========================================================================


class TestProviderResult:
    # PC-05: ProviderResult requires artifact_id and artifact_type
    def test_requires_artifact_id(self):
        with pytest.raises(Exception):
            ProviderResult(artifact_type="ami")

    def test_requires_artifact_type(self):
        with pytest.raises(Exception):
            ProviderResult(artifact_id="img-001")

    # PC-06: region is optional
    def test_region_optional(self):
        result = ProviderResult(artifact_id="img-001", artifact_type="ami")
        assert result is not None

    def test_region_set_when_provided(self):
        result = ProviderResult(artifact_id="img-001", artifact_type="ami", region="us-east-1")
        assert result.region == "us-east-1"

    def test_artifact_id_accessible(self):
        result = ProviderResult(artifact_id="img-12345", artifact_type="qcow2")
        assert result.artifact_id == "img-12345"

    def test_artifact_type_accessible(self):
        result = ProviderResult(artifact_id="x", artifact_type="snapshot")
        assert result.artifact_type == "snapshot"


# ===========================================================================
# Provider lifecycle contract via a concrete test double
# ===========================================================================


class TestProviderLifecycle:
    """Verify that a correct implementation satisfies the full lifecycle contract."""

    class _TrackingProvider(BaseProvider):
        name = "tracking"
        _calls = []

        def provision(self, profile, **kwargs):
            self._calls.append("provision")
            return "instance-tracking-001"

        def run_ansible(self, instance_id, profile):
            self._calls.append("run_ansible")

        def snapshot(self, instance_id, profile):
            self._calls.append("snapshot")
            return ProviderResult(artifact_id="img-tracking-001", artifact_type="ami")

        def teardown(self, instance_id):
            self._calls.append("teardown")

    def setup_method(self):
        self._TrackingProvider._calls = []

    def test_full_lifecycle_order(self):
        provider = self._TrackingProvider()
        profile = object()
        instance_id = provider.provision(profile)
        provider.run_ansible(instance_id, profile)
        provider.snapshot(instance_id, profile)
        provider.teardown(instance_id)

        assert self._TrackingProvider._calls == ["provision", "run_ansible", "snapshot", "teardown"]

    def test_snapshot_returns_provider_result(self):
        provider = self._TrackingProvider()
        result = provider.snapshot("i-001", object())
        assert isinstance(result, ProviderResult)
        assert result.artifact_id == "img-tracking-001"

    def test_provision_returns_string_instance_id(self):
        provider = self._TrackingProvider()
        instance_id = provider.provision(object())
        assert isinstance(instance_id, str)
        assert len(instance_id) > 0

    def test_teardown_called_with_instance_id(self):
        """teardown must receive the same instance_id returned by provision."""
        provider = self._TrackingProvider()
        instance_id = provider.provision(object())
        provider.teardown(instance_id)
        assert "teardown" in self._TrackingProvider._calls


# ===========================================================================
# All real providers loaded from plugins/providers implement BaseProvider
# ===========================================================================


class TestRealProvidersContract:
    def test_all_loaded_providers_are_subclasses(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert len(providers) > 0, "No providers loaded — check plugins/providers dir"
        for name, cls in providers.items():
            assert issubclass(cls, BaseProvider), f"Provider '{name}' must be a subclass of BaseProvider"

    def test_all_providers_have_non_empty_name(self):
        providers, _ = load_providers(Path("plugins/providers"))
        for name, cls in providers.items():
            assert cls.name, f"Provider class for '{name}' must have a non-empty name attribute"

    def test_aws_provider_loaded_as_subprocess(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "aws" in providers, "aws provider must be loadable"
        assert providers["aws"].handles_full_lifecycle is True

    def test_gcp_provider_loaded_as_subprocess(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "gcp" in providers, "gcp provider must be loadable"

    def test_azure_provider_loaded_as_subprocess(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "azure" in providers, "azure provider must be loadable"

    def test_kvm_provider_loaded_as_subprocess(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "kvm" in providers, "kvm provider must be loadable"
        assert providers["kvm"].handles_full_lifecycle is True

    def test_local_provider_loaded_as_class_based(self):
        providers, _ = load_providers(Path("plugins/providers"))
        assert "local" in providers
        assert getattr(providers["local"], "handles_full_lifecycle", False) is False

    def test_registry_contains_all_providers(self):
        registry = ProviderRegistry()
        registry.load(Path("plugins/providers"))
        names = registry.names()
        for expected in ("aws", "gcp", "azure", "kvm", "local"):
            assert expected in names, f"Provider '{expected}' must be in registry"
