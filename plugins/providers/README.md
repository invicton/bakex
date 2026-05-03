# Drop-in Provider Guide

Drop any `.py` file in this directory and Stratum will load it automatically on startup — no pip install required.

## Minimal Provider

```python
from stratum.plugins.base_provider import BaseProvider, ProviderResult
from stratum.core.blueprint import ComplianceProfile

class MyProvider(BaseProvider):
    name = "myprovider"        # must be unique

    def provision(self, profile: ComplianceProfile, **kwargs) -> str:
        # Spin up a VM, return an opaque instance_id string
        return "instance-xyz"

    def run_ansible(self, instance_id: str, profile: ComplianceProfile) -> None:
        # Run ansible-playbook against the instance
        pass

    def snapshot(self, instance_id: str, profile: ComplianceProfile) -> ProviderResult:
        return ProviderResult(
            artifact_id="my-golden-image-001",
            artifact_type="qcow2",
        )

    def teardown(self, instance_id: str) -> None:
        # Destroy temp instance
        pass
```

## Pip-Installed Providers

Register your package's provider in `pyproject.toml`:

```toml
[project.entry-points."stratum.providers"]
myprovider = "mypackage.provider:MyProvider"
```

## Provider Contract

| Method | Purpose |
|--------|---------|
| `provision(profile)` | Create a temporary instance. Return `instance_id`. |
| `run_ansible(instance_id, profile)` | Apply hardening roles via Ansible-Lockdown. |
| `snapshot(instance_id, profile)` | Snapshot to a golden image. Return `ProviderResult`. |
| `teardown(instance_id)` | Unconditionally destroy the temp instance. |
