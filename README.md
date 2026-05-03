# Stratum

**The Terraform of OS Hardening — open-core, multi-cloud, declarative.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.3.0-brightgreen)]()
[![CI](https://github.com/sachinponnapalli/Stratum/actions/workflows/ci.yml/badge.svg)](https://github.com/sachinponnapalli/Stratum/actions/workflows/ci.yml)

Stratum is a self-hosted DevSecOps platform that turns a declarative YAML blueprint into a fully-hardened, CIS/STIG-benchmarked golden image — automatically, on any cloud.

Write your security policy once. Build everywhere. Scan everything.

---

## How It Works

```
HardeningBlueprint (YAML)  ──or──  5-Step Guided Wizard
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  Stratum Engine                                      │
  │                                                      │
  │  1. Provision  →  Spin up a temporary VM             │
  │  2. Harden     →  Apply Ansible-Lockdown CIS/STIG    │
  │  3. Scan       →  Run OpenSCAP, assert compliance    │
  │  4. Snapshot   →  Capture as reusable golden image   │
  │  5. Teardown   →  Remove the ephemeral build VM      │
  └─────────────────────────────────────────────────────┘
        │
        ▼
  Golden Image  (AMI · GCP Custom Image · Azure Managed Image · Snapshot)
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  Compliance Scanner                                  │
  │                                                      │
  │  Scan any image or running VM at any time            │
  │  A–F grade  ·  SARIF export  ·  Drift analysis       │
  │  CI/CD pipeline gate  ·  Webhook notifications       │
  └─────────────────────────────────────────────────────┘
```

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Features](#features)
3. [Supported Platforms](#supported-platforms)
4. [HardeningBlueprint Reference](#hardeningblueprint-reference)
5. [Community Blueprint Library](#community-blueprint-library)
6. [AI Builder](#ai-builder)
7. [Compliance Scanner](#compliance-scanner)
8. [CI/CD Integration](#cicd-integration)
9. [Provider Plugin System](#provider-plugin-system)
10. [LLM Backends](#llm-backends)
11. [Configuration](#configuration)
12. [Development](#development)
13. [Architecture](#architecture)

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/sachinponnapalli/Stratum.git
cd Stratum
docker compose up
```

Open **http://localhost:8001** in your browser.

> Set `STRATUM_SECRET_KEY` in `docker-compose.yml` before first run so credentials survive container rebuilds.

**What gets mounted automatically:**

| Host path | Container path | Purpose |
|---|---|---|
| `~/.aws` | `/root/.aws` | AWS credentials / config |
| `~/.config/gcloud` | `/root/.config/gcloud` | GCP Application Default Credentials |
| `~/.ssh` | `/root/.ssh` | SSH keys for Ansible |
| `./plugins/providers` | `/app/plugins/providers` | Installed provider plugins (persisted) |
| `./profiles` | `/app/profiles` | Blueprint YAML files (persisted) |
| `./data` | `/app/data` | Encrypted credential store + audit results |

### Local Development

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Ansible, OpenSCAP

```bash
git clone https://github.com/sachinponnapalli/Stratum.git
cd Stratum

# Install all provider SDKs + dev tools
uv sync --extra all-providers --group dev

# Copy and edit environment config
cp .env.example .env

# Start the server
uv run uvicorn stratum.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

---

## Features

### Image Builder
- **Declarative blueprints** — YAML-first; version-controllable, diffable, reviewable
- **5-step guided wizard** — UI-first path for teams new to YAML
- **AI Builder** — describe what you need in plain English; the agent writes the blueprint, runs the build, and iterates until the compliance grade passes
- **Live build log** — real-time pipeline tracker with per-stage progress
- **18 ready-to-use templates** — Amazon Linux 2023, Ubuntu 22.04/24.04, Rocky Linux 9, Debian 12, RHEL 9 — across AWS, GCP, Azure, DigitalOcean, Linode, and Proxmox

### Compliance Engine
- **CIS Level 1 and Level 2** — full server benchmarks for each supported OS
- **STIG** — where SCAP Security Guide provides a datastream
- **OpenSCAP native** — runs `oscap xccdf eval` directly; no wrappers, no interpretation layers
- **A–F compliance grade** — computed from weighted findings; configurable pass threshold
- **Per-rule overrides** — disable any rule with a documented justification; exceptions are audit-logged
- **Drift analysis** — compare scan results across time; flag regressions

### Reporting
- **HTML report** — printable, PDF-ready compliance report per build
- **SARIF 2.1.0 export** — import directly into GitHub Advanced Security, Azure DevOps, or any SARIF-aware tool
- **JSON export** — machine-readable findings for downstream pipeline processing
- **Audit log** — all build and scan events persisted and searchable

### Pipeline Integration
- **REST API** — authenticated with API keys; SHA-256 hashed at rest
- **Webhooks** — HMAC-SHA256 signed; configurable per-event (build complete, scan failed, drift detected)
- **SARIF gate** — fail the CI/CD pipeline on grade below threshold or any finding above severity threshold
- **GitHub Actions, GitLab CI, Jenkins** — example integrations in [`docs/pipeline.md`](docs/pipeline.md)

---

## Supported Platforms

### Operating Systems

| OS | CIS L1 | CIS L2 | STIG | Benchmark ID |
|---|---|---|---|---|
| Amazon Linux 2023 | ✓ | ✓ | — | `AMAZON_LINUX_2023` |
| Ubuntu 22.04 LTS | ✓ | ✓ | — | `UBUNTU2204` |
| Ubuntu 24.04 LTS | ✓ | ✓ | — | `UBUNTU2404` |
| Rocky Linux 9 | ✓ | ✓ | ✓ | `RHEL-9` |
| RHEL 9 | ✓ | ✓ | ✓ | `RHEL-9` |
| Debian 12 | ✓ | ✓ | — | `DEBIAN12` |

### Cloud Providers

| Provider | Artifact | Auth |
|---|---|---|
| AWS | AMI | IAM role, `~/.aws/credentials`, or env vars |
| GCP | Custom Image | Application Default Credentials |
| Azure | Managed Image | Service Principal or Managed Identity |
| DigitalOcean | Snapshot | API token |
| Linode | Private Image | API token |
| Proxmox | VM Template | API token or username/password |

---

## HardeningBlueprint Reference

Blueprints are YAML documents that fully describe a hardened image. Every field has a safe default — start minimal and add only what you need.

### Minimal example

```yaml
stratum_version: "0.3.0"
kind: HardeningBlueprint

metadata:
  name: my-baseline
  version: "1.0.0"

target:
  os: amazon-linux-2023
  provider: aws
  base_image: ami-0230bd60aa48260c6
  instance_type: t3.medium

compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_AMAZON_LINUX_2023
  profile: xccdf_org.ssgproject.content_profile_cis_server_l2
  datastream: /usr/share/xml/scap/ssg/content/ssg-al2023-ds.xml
  fail_on_findings: true
  severity_threshold: medium
```

### Full schema

```yaml
stratum_version: "0.3.0"
kind: HardeningBlueprint

metadata:
  name: string                       # Unique identifier
  version: "1.0.0"
  description: string
  author: string
  tags: [list of strings]

target:
  os: amazon-linux-2023              # See supported OS list
  arch: x86_64
  provider: aws                      # See supported providers
  base_image: ami-xxxxxxxx           # Provider-specific image reference
  instance_type: t3.medium
  root_volume_size_gb: 15
  extra_volumes:
    - device_name: /dev/sdf
      size_gb: 2

system:
  hostname: hardened-node
  timezone: UTC
  locale: en_US.UTF-8
  selinux_mode: enforcing            # enforcing | permissive | disabled

filesystem:
  - device: /dev/nvme1n1
    mountpoint: /var
    fstype: xfs
  - device: tmpfs
    mountpoint: /tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 2G

users:
  root:
    lock: true
  accounts:
    - name: stratum-admin
      groups: [wheel]
      shell: /bin/bash
      ssh_authorized_keys: []

compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_AMAZON_LINUX_2023
  profile: xccdf_org.ssgproject.content_profile_cis_server_l2
  datastream: /usr/share/xml/scap/ssg/content/ssg-al2023-ds.xml
  fail_on_findings: true
  severity_threshold: medium         # critical | high | medium | low
  aide: true                         # Enable AIDE file integrity monitoring
  fips: false                        # Enable FIPS 140-2 mode

hardening:
  strategy: ansible-galaxy           # ansible-galaxy | git | none
  profile_tier: cis-l2               # cis-l1 | cis-l2 | stig | custom

controls:
  # Disable a rule with a documented justification
  xccdf_org.ssgproject.content_rule_package_telnet_removed:
    enabled: false
    justification: "Telnet is blocked at the network layer; package removal causes build failures."
  # Enable a rule that is off by default in this profile
  xccdf_org.ssgproject.content_rule_sshd_disable_root_login:
    enabled: true
    justification: "Root SSH login is prohibited by organisational security policy."
```

### Pre-built templates

Built-in app templates are in [`profiles/templates/`](profiles/templates/). Load any of them in the UI or reference them by name.

| File | OS | Provider | Profile |
|---|---|---|---|
| `amazon-linux-2023-cis-l1-aws.yaml` | Amazon Linux 2023 | AWS | CIS L1 |
| `alma9-cis-l1-aws.yaml` | AlmaLinux 9 | AWS | CIS L1 |
| `debian12-cis-l1-aws.yaml` | Debian 12 | AWS | CIS L1 |
| `debian12-cis-l1-digitalocean.yaml` | Debian 12 | DigitalOcean | CIS L1 |
| `debian12-cis-l1-gcp.yaml` | Debian 12 | GCP | CIS L1 |
| `rocky9-cis-l1-aws.yaml` | Rocky Linux 9 | AWS | CIS L1 |
| `rocky9-cis-l1-azure.yaml` | Rocky Linux 9 | Azure | CIS L1 |
| `rocky9-cis-l1-digitalocean.yaml` | Rocky Linux 9 | DigitalOcean | CIS L1 |
| `rocky9-cis-l1-gcp.yaml` | Rocky Linux 9 | GCP | CIS L1 |
| `rocky9-cis-l1-linode.yaml` | Rocky Linux 9 | Linode | CIS L1 |
| `rocky9-cis-l1-proxmox.yaml` | Rocky Linux 9 | Proxmox | CIS L1 |
| `ubuntu22-cis-l1-aws.yaml` | Ubuntu 22.04 | AWS | CIS L1 |
| `ubuntu22-cis-l1-azure.yaml` | Ubuntu 22.04 | Azure | CIS L1 |
| `ubuntu22-cis-l1-digitalocean.yaml` | Ubuntu 22.04 | DigitalOcean | CIS L1 |
| `ubuntu22-cis-l1-gcp.yaml` | Ubuntu 22.04 | GCP | CIS L1 |
| `ubuntu22-cis-l1-linode.yaml` | Ubuntu 22.04 | Linode | CIS L1 |
| `ubuntu22-cis-l1-proxmox.yaml` | Ubuntu 22.04 | Proxmox | CIS L1 |

---

## Community Blueprint Library

Stratum includes a top-level [`blueprints/`](blueprints/) folder for contributor-submitted blueprints. This is the public library surface for adding more OS/provider/framework combinations without changing the Stratum engine.

The folder is organized by OS family and version:

```text
blueprints/<os-family>/<os-version>/<framework>-<level>-<provider>.yaml
```

Each contribution should:

- validate against the `HardeningBlueprint` schema
- use a supported OpenSCAP datastream/profile for the target OS
- include accurate provider defaults and metadata tags
- add its path to [`blueprints/index.json`](blueprints/index.json)

See [`blueprints/README.md`](blueprints/README.md) for the contribution checklist.

---

## AI Builder

The AI Builder takes a plain-English description and produces a compliant hardened image autonomously.

**How to use it:**

1. Open the **AI Builder** tab in the UI
2. Describe your target: `"Amazon Linux 2023 on AWS, CIS Level 2, us-east-1, t3.medium"`
3. The agent:
   - Generates a `HardeningBlueprint` YAML
   - Validates the schema
   - Starts the full build pipeline
   - Monitors each stage
   - Reads the OpenSCAP results
   - If the grade is below B, it revises the blueprint and retries (up to 2×)
   - Streams narration to the UI in real time via SSE
4. At completion: golden image ID + compliance grade appear in the build summary

**LLM backend selection** — set one of these in `.env`:

```bash
STRATUM_LLM_PROVIDER=anthropic   # default — uses claude-sonnet-4-6 or configured model
STRATUM_LLM_PROVIDER=openai      # OpenAI or any OpenAI-compatible endpoint
STRATUM_LLM_PROVIDER=ollama      # Local inference; set STRATUM_LLM_MODEL=llama3.3:70b
STRATUM_LLM_PROVIDER=bedrock     # AWS Bedrock; uses EC2 role / IRSA — no separate key
```

---

## Compliance Scanner

Scan any running VM or existing image at any time — independent of the builder.

**From the UI:**

1. Open **Compliance Scanner**
2. Enter the target host IP or hostname
3. Select the benchmark and profile
4. Click **Run Scan**

**Results include:**
- Compliance score (0–100%) and letter grade (A–F)
- Findings by severity: Critical / High / Medium / Low
- Per-rule pass/fail/not-checked status
- HTML and SARIF exports

**Drift analysis:**

Compare any two scans. Stratum highlights rules that regressed (pass → fail) and rules that improved (fail → pass) between any two points in time.

---

## CI/CD Integration

Stratum exposes an authenticated REST API for pipeline integration. Full reference in [`docs/pipeline.md`](docs/pipeline.md).

### GitHub Actions example

```yaml
- name: Gate on compliance grade
  env:
    STRATUM_API_KEY: ${{ secrets.STRATUM_API_KEY }}
    STRATUM_URL: https://stratum.internal
  run: |
    RESULT=$(curl -sf -H "X-API-Key: $STRATUM_API_KEY" \
      "$STRATUM_URL/api/pipeline/scan" \
      -d '{"target":"${{ env.AMI_ID }}","benchmark":"AMAZON_LINUX_2023","profile":"cis_server_l2"}')
    GRADE=$(echo "$RESULT" | jq -r '.grade')
    echo "Compliance grade: $GRADE"
    [[ "$GRADE" =~ ^[AB]$ ]] || exit 1
```

### Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/pipeline/scan` | Trigger a compliance scan |
| `GET` | `/api/pipeline/scan/{job_id}` | Poll scan status and results |
| `POST` | `/api/builder/build` | Trigger an image build |
| `GET` | `/api/builder/build/{job_id}` | Poll build status |
| `GET` | `/api/auditor/export/{job_id}/sarif` | Download SARIF report |
| `GET` | `/api/auditor/export/{job_id}/html` | Download HTML report |

All endpoints require `X-API-Key: <key>` header. Keys are managed under **Settings → API Keys** in the UI.

---

## Provider Plugin System

Add a new cloud provider or hypervisor without forking Stratum. Providers run as isolated subprocesses — they cannot affect the core engine.

### Minimal provider

```python
from stratum.plugins.base_provider import BaseProvider, ProviderResult

class MyProvider(BaseProvider):
    name = "myprovider"

    def provision(self, profile, **kwargs) -> str:
        # spin up VM, return instance ID
        return "instance-xyz"

    def run_ansible(self, instance_id: str, profile) -> None:
        # run Ansible against the instance
        pass

    def snapshot(self, instance_id: str, profile) -> ProviderResult:
        # create image, return artifact ID and type
        return ProviderResult(artifact_id="img-001", artifact_type="qcow2")

    def teardown(self, instance_id: str) -> None:
        # terminate the ephemeral VM
        pass
```

Drop the file into `plugins/providers/`. Stratum picks it up on the next start. The UI provider dropdown and blueprint validator both update automatically.

See [`plugins/providers/README.md`](plugins/providers/README.md) for the full plugin contract.

---

## LLM Backends

The AI Builder is LLM-agnostic. All backends implement the same interface.

| Provider | `STRATUM_LLM_PROVIDER` | Auth | Notes |
|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Default; extended thinking enabled by default |
| OpenAI / compatible | `openai` | `STRATUM_LLM_API_KEY` | Groq, Together, vLLM, LiteLLM, Fireworks |
| Ollama | `ollama` | None | Air-gapped; set `STRATUM_LLM_MODEL=llama3.3:70b` |
| AWS Bedrock | `bedrock` | EC2 role / IRSA / STS | No separate key; AWS-native |

Set `STRATUM_LLM_BASE_URL` to point at any OpenAI-compatible endpoint.

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and set what you need.

```bash
# Core
STRATUM_SECRET_KEY=changeme          # AES-128 Fernet key for credential encryption
DATA_DIR=data/                       # Credential store, results, API keys
PLUGINS_DIR=plugins/providers        # Provider plugin directory
PROFILES_DIR=profiles/               # Blueprint YAML search path
DEBUG=false

# AI Builder
STRATUM_LLM_PROVIDER=anthropic       # anthropic | openai | ollama | bedrock
STRATUM_LLM_MODEL=                   # Override model name
STRATUM_LLM_API_KEY=                 # For openai-compatible backends
STRATUM_LLM_BASE_URL=                # OpenAI-compatible base URL
STRATUM_LLM_THINKING=1               # Extended thinking (1=on, 0=off)
ANTHROPIC_API_KEY=sk-ant-...

# Blueprint Registry
BLUEPRINT_STORE_S3_BUCKET=           # Private S3 registry (optional)
BLUEPRINT_STORE_S3_PREFIX=blueprints/
BLUEPRINT_STORE_S3_REGION=us-east-1
```

---

## Development

```bash
# Install dev dependencies
uv sync --extra all-providers --group dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=stratum --cov-report=term-missing

# Lint + format
uv run ruff check .
uv run ruff format .

# Validate all blueprint templates
uv run python -c "
from stratum.core.blueprint import HardeningBlueprint
import glob, yaml
for f in glob.glob('profiles/**/*.yaml', recursive=True):
    HardeningBlueprint(**yaml.safe_load(open(f)))
    print(f'OK: {f}')
"
```

**System dependencies for running actual builds:**

On Debian/Ubuntu:
```bash
apt install openscap-scanner ssg-debderived ansible openssh-client sshpass
```

On RHEL/Rocky/Amazon Linux:
```bash
dnf install openscap-scanner scap-security-guide ansible openssh-clients sshpass
```

---

## Architecture

```
stratum/
├── api/            11 FastAPI routers (blueprints, builder, auditor, agent, pipeline, …)
├── core/
│   ├── blueprint.py      Pydantic schema: HardeningBlueprint + ComplianceProfile
│   ├── builder.py        5-stage build pipeline state machine
│   ├── auditor.py        Scan orchestration, job persistence, webhook dispatch
│   ├── agent.py          AI Builder: 7 tools, streaming SSE, auto-retry
│   ├── llm/              Pluggable LLM backends (Anthropic, OpenAI, Ollama, Bedrock)
│   ├── parser.py         SCAP rule exception engine
│   ├── openscap/         oscap wrapper + ARF/XCCDF parser
│   ├── playbook_gen.py   Ansible playbook generator (LVM, AIDE, FIPS)
│   ├── registry.py       Multi-source blueprint registry (GitHub + S3 + local)
│   ├── report.py         HTML + SARIF 2.1.0 export
│   └── notifications.py  HMAC-SHA256 signed webhook dispatcher
├── plugins/
│   ├── base_provider.py  Abstract provider contract (4 methods)
│   └── registry.py       Dynamic plugin loader
├── templates/      Jinja2 + HTMX UI templates
└── config.py       Pydantic settings (reads from .env)

plugins/
└── providers/      Drop-in provider implementations (aws, gcp, azure, …)

profiles/
├── templates/      18 ready-to-use HardeningBlueprint YAML files
├── examples/       Minimal reference blueprints
└── user/           User-uploaded blueprints (persisted)
```

**Build pipeline state machine:**

```
PENDING → PROVISIONING → HARDENING → SCANNING → SNAPSHOTTING → COMPLETE
                                                              ↘ FAILED
```

Each transition emits live log events. The UI polls every 2 seconds via HTMX.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built by [Vamshi Krishna Santhapuri](https://linuxcent.com).
