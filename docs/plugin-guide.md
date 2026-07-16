# Provider Plugin Guide

Add a new cloud provider or hypervisor without forking BakeX. Providers run
as isolated subprocesses (JSON-RPC over stdin/stdout) — they cannot affect the
core engine.

## Minimal provider

```python
from bakex.plugins.base_provider import BaseProvider, ProviderResult
from bakex.core.blueprint import ComplianceProfile

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
        # Destroy the ephemeral instance
        pass
```

Drop the file into `plugins/providers/`. BakeX picks it up on the next
start. The UI provider dropdown and blueprint validator both update
automatically.

## The provider contract

| Method | Purpose |
|--------|---------|
| `provision(profile)` | Create a temporary instance. Return `instance_id`. |
| `run_ansible(instance_id, profile)` | Apply hardening roles via Ansible-Lockdown. |
| `snapshot(instance_id, profile)` | Snapshot to a golden image. Return `ProviderResult`. |
| `teardown(instance_id)` | Unconditionally destroy the temp instance. |

`teardown` must be safe to call after any failure — BakeX invokes it on
every failed build to avoid leaking cloud resources.

## Pip-installed providers

Distribute a provider as a package by registering it under the
`bakex.providers` entry-point group in your `pyproject.toml`:

```toml
[project.entry-points."bakex.providers"]
myprovider = "mypackage.provider:MyProvider"
```

## Installing from the catalog

BakeX ships a provider catalog (`plugins/catalog/`, also bundled in the PyPI
package). The **Integrations** page lists available providers; installing one
copies its script into `plugins/providers/` and hot-reloads the registry —
equivalent to:

```
POST /api/plugins/install        {"provider_id": "gcp"}
GET  /api/plugins/catalog        # what's available
GET  /api/plugins/available      # available-but-not-installed (HTML partial)
```

## Reference implementations

The installed providers in [`plugins/providers/`](../plugins/providers/) are
the best reference — `kvm.py` (fully local, QEMU/KVM), `aws.py` (SSM-based,
no inbound SSH), and `_provider_utils.py` (shared SSH/Ansible/OpenSCAP
helpers, including the OS → Ansible-Lockdown role map with pinned known-good
versions).
