# Contributing to BakeX

Copyright 2026 Vamshi Krishna Santhapuri
Licensed under the [Apache License 2.0](LICENSE)

Thank you for your interest in contributing! BakeX is an Apache-2.0, multi-cloud
DevSecOps platform for reproducible OS hardening. All contributions — code, blueprint
templates, bug reports, documentation — are welcome.

> **Fastest first contribution: a community blueprint.** Blueprints are pure YAML —
> no Python required — and each open
> [`blueprint` issue](https://github.com/invicton/bakex/issues?q=is%3Aissue+is%3Aopen+label%3Ablueprint)
> ships with acceptance criteria and a local verify command. The
> [Blueprint Library Guide](blueprints/CONTRIBUTING.md) walks through every field,
> from fork to merged PR.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in all project spaces.
Found a security vulnerability? See [SECURITY.md](SECURITY.md) instead of
opening a public issue.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Project Structure](#project-structure)
3. [Writing a Provider Plugin](#writing-a-provider-plugin)
4. [Contributing a Blueprint Template](#contributing-a-blueprint-template)
5. [Development Workflow](#development-workflow)
6. [Code Style](#code-style)
7. [Testing](#testing)
8. [Pull Request Process](#pull-request-process)
9. [License](#license)

---

## Getting Started

```bash
git clone https://github.com/invicton/bakex.git
cd bakex

# Install with all provider extras
pip install uv
uv sync --extra all-providers --extra dev

# Run the development server
uv run uvicorn bakex.main:app --reload
```

System dependencies (Debian 12):

```bash
apt install openscap-scanner scap-security-guide ansible openssh-client
```

System dependencies (Ubuntu 24.04+ — `scap-security-guide` isn't a real
Ubuntu package under any name, unlike Debian; see the note below):

```bash
apt install openscap-scanner ansible openssh-client
```

> **OpenSCAP content on Debian-family targets:** `install_oscap_on_remote()`
> installs `openscap-scanner` via the package manager, then checks whether
> the target's SCAP datastream is actually present afterward. If not (true
> for **every** Ubuntu release — `scap-security-guide` doesn't exist there
> at all, not just on 22.04 as first suspected; Debian 12 does ship it), it
> downloads the matching content directly from a
> [ComplianceAsCode/content](https://github.com/ComplianceAsCode/content)
> GitHub release (checksum-verified, cached locally) instead — the same
> workaround a real user independently found for this exact gap. **Ubuntu
> 22.04 still can't run a scan at all**, though, since it additionally lacks
> the `openscap-scanner` binary itself via apt in any channel (first appears
> in 24.04) — building `openscap` from source there is a tracked follow-up.
> Hardening (Ansible-Lockdown) is unaffected either way; only the OpenSCAP
> scan step is.

Building images locally with the `kvm` provider additionally needs:

```bash
apt install qemu-system-x86 qemu-utils cloud-image-utils   # or: genisoimage instead of cloud-image-utils
```

---

## Project Structure

```
bakex/                  Core FastAPI application
  api/                    REST endpoints + Jinja2 HTML pages
    agent.py              AI Builder SSE endpoint
    api_keys.py           API key management (create / list / revoke)
    auditor.py            Live audit + image scan + report export (HTML/JSON/SARIF)
    blueprints.py         Blueprint CRUD + preview
    builder.py            Build job trigger + status + controls
    integrations.py       Credential store + provider forms
    pipeline.py           CI/CD pipeline scan API (authenticated)
    registry.py           Blueprint registry sync
    ui.py                 Page-rendering routes (wizard steps + settings pages)
    webhooks.py           Webhook CRUD + test-fire endpoint
  core/                   Domain logic
    agent.py              Agentic build loop (claude-opus-4-6)
    api_keys.py           API key store (SHA-256 hashed, file-backed)
    auditor.py            Audit orchestration + image scan + webhook dispatch
    blueprint.py          ComplianceProfile / HardeningBlueprint schema
    builder.py            Build pipeline state machine
    notifications.py      Webhook dispatcher (httpx, HMAC-SHA256 signed)
    os_catalog.py         OS catalog, AMI defaults, CIS control definitions
    parser.py             SCAP result parser + exception engine
    playbook_gen.py       Ansible playbook generator (LVM, AIDE, FIPS)
    registry.py           Multi-source blueprint registry
  plugins/                Provider registry, loader, subprocess adapter
  openscap/               Scanner + ARF/XCCDF result parser
  templates/              HTMX + Tailwind HTML templates
    auditor/scanner/      3-step compliance scan wizard
    auditor/              history, compare, report, results templates
    builder/              5-step image builder wizard + run page
    settings/             API keys + webhooks management UI

plugins/
  providers/              Drop-in provider scripts (JSON-RPC subprocess model)
    _provider_utils.py    Shared SSH / Ansible / OpenSCAP helpers
    aws.py                AWS EC2 + SSM provider
    gcp.py                Google Cloud Compute provider
    azure.py              Microsoft Azure provider
    digitalocean.py       DigitalOcean Droplets provider
    linode.py             Linode (Akamai Cloud) provider
    proxmox.py            Proxmox VE provider
    example_local.py      Reference class-based provider
  catalog/                Cloud image catalog generators (for UI dropdowns)

profiles/
  templates/              Ready-to-use HardeningBlueprint YAML files
  examples/               Minimal examples for learning

docs/
  pipeline.md             CI/CD pipeline integration guide

ansible/
  site.yml                OS-detecting Ansible entrypoint (auto-selects lockdown role)
  roles/                  Vendored roles (git-ignored; installed on demand via ansible-galaxy)

tests/                    pytest test suite
```

---

## Writing a Provider Plugin

BakeX supports two provider models. Choose the one that fits your use case.

### Model A — Subprocess Provider (recommended for cloud providers)

A standalone Python script that communicates via JSON-RPC over stdin/stdout. The
BakeX engine never imports it; it runs as an isolated subprocess.

**Minimal skeleton:**

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""MyCloud subprocess provider."""

import json, sys, os

PROVIDER_NAME = "mycloud"   # <-- This sentinel identifies it as a subprocess provider

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _provider_utils as utils  # shared SSH / Ansible / oscap helpers


def test_connection(params: dict) -> dict:
    """Validate credentials. Return {"status": "ok", ...} or raise."""
    ...

def execute_build(params: dict) -> dict:
    """Full build pipeline. Must return {"artifact_id": ..., "artifact_type": ..., ...}."""
    # Key params available:
    #   params["base_image"]           - image ID from blueprint
    #   params["os"]                   - OS identifier, e.g. "ubuntu22"
    #   params["instance_type"]        - VM size from blueprint
    #   params["root_volume_size_gb"]  - disk size from blueprint
    #   params["prehard_playbook_yaml"]- pre-hardening Ansible playbook YAML (auto-generated)
    #   params["profile"]              - XCCDF profile ID
    #   params["datastream"]           - SCAP datastream path on target
    #   params["credentials"]          - dict of provider credentials from BakeX UI
    ...

def execute_audit(params: dict) -> dict:
    """Audit a running instance. Must return {"status": "success", "raw_xml": ...}."""
    # Key params available:
    #   params["instance_id"]   - running instance to audit
    #   params["os"]            - OS identifier
    #   params["benchmark"]     - XCCDF benchmark ID
    #   params["profile"]       - XCCDF profile ID
    #   params["datastream"]    - SCAP datastream path on target
    #   params["credentials"]   - provider credentials
    ...

def execute_scan_image(params: dict) -> dict:
    """Provision a temp instance from params["image_id"], run OpenSCAP, terminate.
    Must return {"status": "success", "raw_xml": ...} where raw_xml is the XCCDF
    result XML string. The engine parses it to extract score, grade, findings."""
    # Key params available:
    #   params["image_id"]      - AMI / image ID to scan
    #   params["instance_type"] - VM size to use for the scan instance
    #   params["region"]        - cloud region
    #   params["os"]            - OS identifier
    #   params["benchmark"]     - XCCDF benchmark ID
    #   params["profile"]       - XCCDF profile ID
    #   params["datastream"]    - SCAP datastream path on target
    #   params["credentials"]   - provider credentials
    ...

def list_images(params: dict) -> dict:
    """Optional: return available base images for the UI catalog."""
    return {"images": []}

def resolve_image(params: dict) -> dict:
    """Optional: resolve the latest image ID for a given OS at runtime.
    Must return {"image_id": ..., "source": "resolved"|"fallback"}."""
    return {"image_id": "", "source": "fallback"}


_DISPATCH = {
    "test_connection": test_connection,
    "execute_build": execute_build,
    "execute_audit": execute_audit,
    "execute_scan_image": execute_scan_image,
    "list_images": list_images,
    "resolve_image": resolve_image,
}


def main():
    req = json.loads(sys.stdin.read())
    method = req.get("method")
    if method not in _DISPATCH:
        print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                          "error": {"code": -32601, "message": f"Method not found: {method}"}}))
        sys.exit(1)
    try:
        result = _DISPATCH[method](req.get("params", {}))
        print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": result}))
    except Exception as exc:
        print(json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                          "error": {"code": -32603, "message": str(exc)}}))
        sys.exit(1)

if __name__ == "__main__":
    main()
```

Drop the file into `plugins/providers/mycloud.py` and BakeX will auto-discover it on
next start. No registration needed.

**Credential fields** are declared as a `CREDENTIAL_FIELDS` list (optional but
recommended for the integrations UI to render the correct form):

```python
CREDENTIAL_FIELDS = [
    {"key": "api_token", "label": "API Token",  "type": "password", "required": True},
    {"key": "region",    "label": "Region",     "type": "text",     "required": False,
     "default": "us-east-1"},
]
```

### Model B — Class-based Provider (for on-premises / non-subprocess use)

Subclass `bakex.plugins.base_provider.BaseProvider` and implement the four abstract
methods: `provision`, `run_ansible`, `snapshot`, `teardown`. See
`plugins/providers/example_local.py` for a reference implementation.

---

## Contributing a Blueprint Template

Blueprint templates are the core BakeX USP — a version-controlled YAML file that
fully describes how to build a reproducible hardened image.

**Rules for contributed templates:**

1. Place under `profiles/templates/<os>-<benchmark>-<level>-<provider>.yaml`
2. Set `kind: HardeningBlueprint`
3. Include **all four sections**: `system`, `filesystem`, `users`, `compliance`
4. Every `controls` override must have a non-empty `justification`
5. The `author` field must be your name or GitHub handle
6. Add a comment at the top linking to the official image list for `base_image`

**Naming convention:**

| Segment | Examples |
|---------|---------|
| OS | `ubuntu22`, `rocky9`, `alma9`, `debian12`, `amzn2023` |
| Benchmark | `cis` |
| Level | `l1`, `l2` |
| Provider | `aws`, `gcp`, `azure`, `digitalocean`, `linode`, `proxmox` |

Example: `ubuntu22-cis-l1-aws.yaml`

**Minimal required sections:**

```yaml
bakex_version: "0.1.0"
kind: HardeningBlueprint

metadata:
  name: <os>-cis-l1-<provider>
  version: "1.0.0"
  description: "..."
  author: "Your Name"
  tags: [os, benchmark, provider]

target:
  os: <os-identifier>
  arch: x86_64
  provider: <provider>
  base_image: <provider-specific-image-id>
  instance_type: <provider-size>
  root_volume_size_gb: 20

system:
  hostname: hardened-node
  timezone: UTC
  locale: en_US.UTF-8
  selinux_mode: null          # or: enforcing (RHEL family)

filesystem:                   # CIS 1.1.x: these three mounts are required
  - { device: tmpfs, mountpoint: /tmp,     fstype: tmpfs, options: [rw,nosuid,nodev,noexec,relatime], size: 2G }
  - { device: tmpfs, mountpoint: /var/tmp, fstype: tmpfs, options: [rw,nosuid,nodev,noexec,relatime], size: 1G }
  - { device: tmpfs, mountpoint: /dev/shm, fstype: tmpfs, options: [rw,nosuid,nodev,noexec,relatime] }

users:
  root:
    lock: true
  accounts:
    - name: bakex-admin
      groups: [sudo]           # or [wheel] for RHEL family
      shell: /bin/bash
      ssh_authorized_keys: []

compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_<BENCHMARK>
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-<os>-ds.xml
  fail_on_findings: true
  severity_threshold: medium

controls:
  xccdf_org.ssgproject.content_rule_sshd_disable_root_login:
    enabled: true
    justification: Root SSH login is prohibited by CIS and organisational policy.
```

---

## Development Workflow

```bash
# Create a feature branch
git checkout -b feat/my-provider

# Make changes, then run tests
uv run pytest

# Run linting
uv run ruff check bakex/ plugins/ tests/
uv run ruff format --check bakex/ plugins/ tests/

# Start the dev server and verify in browser
uv run uvicorn bakex.main:app --reload
```

### Installing a provider's dependencies locally

```bash
# AWS
uv pip install -e ".[aws]"

# All providers
uv pip install -e ".[all-providers]"
```

---

## Code Style

- Python 3.11+, type-annotated where practical
- `from __future__ import annotations` in every module
- `ruff` for formatting and linting (line length 120)
- Every file starts with the SPDX header:
  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Vamshi Krishna Santhapuri
  ```
- Subprocess provider scripts are self-contained — no imports from `bakex.*`
- Use `_provider_utils` for all SSH / Ansible / oscap operations in providers

---

## Testing

```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_blueprint.py -v

# Run with coverage
uv run pytest --cov=bakex --cov-report=term-missing
```

New provider plugins should include at least:
- A `test_connection` smoke test using mocked API responses
- A `execute_build` test validating parameter handling

---

## Pull Request Process

1. Fork the repo and create a feature branch from `main`
2. Follow the code style guidelines above
3. Add or update tests for any changed behaviour
4. Update the relevant template YAML files if you change the blueprint schema
5. Ensure `uv run pytest` passes with no failures
6. Open a pull request with a clear description of what changed and why
7. Address review comments promptly

### How PRs get merged

`main` is protected — there are no direct pushes, and every PR must have:

1. **Green CI** — lint, tests, schema validation, and (for blueprint changes)
   the community-blueprint check. All of these run on fork PRs with no
   secrets required, so you can iterate entirely from your fork.
2. **Signed-off commits** — every commit needs a `Signed-off-by` line
   (`git commit -s`), asserting the
   [Developer Certificate of Origin](https://developercertificate.org/).
   No CLA, no paperwork — the sign-off is the whole agreement.
3. **Maintainer review** — one approval from the maintainer. Pushing new
   commits dismisses stale approvals, so the reviewed code is always the
   merged code.

Issues labelled `good first issue` state their acceptance criteria and the
exact local verification command up front — if that command passes and CI is
green, review is usually quick.

PRs that add new provider plugins must include:
- The plugin script in `plugins/providers/<name>.py`
- All four required RPC methods: `test_connection`, `execute_build`, `execute_audit`, `execute_scan_image`
- At least one blueprint template in `profiles/templates/`
- Updated `pyproject.toml` optional dependencies if new packages are needed
- `aws_image_query` entries in `bakex/core/os_catalog.py` if the provider uses a public image catalog

---

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).

```
Copyright 2026 Vamshi Krishna Santhapuri

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```
