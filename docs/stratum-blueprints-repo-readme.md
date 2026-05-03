# stratum-blueprints

**The community blueprint library for [Stratum](https://github.com/sachinponnapalli/Stratum) — hardening controls from every major framework, ready to build.**

[![Validate Blueprints](https://github.com/stratum-community/stratum-blueprints/actions/workflows/validate.yml/badge.svg)](https://github.com/stratum-community/stratum-blueprints/actions/workflows/validate.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Blueprints](https://img.shields.io/badge/blueprints-community-orange)]()

This repository is the community library of `HardeningBlueprint` YAML files for Stratum.
Each blueprint is a fully declared, validated, machine-executable OS hardening policy.
Pick one, point Stratum at this repo, build your golden image.

No engine forks. No vendor lock-in. No starting from scratch.

---

## Table of Contents

1. [Add to Your Stratum Instance](#add-to-your-stratum-instance)
2. [Blueprint Library](#blueprint-library)
3. [Framework Coverage](#framework-coverage)
4. [How to Contribute](#how-to-contribute)
5. [Blueprint Anatomy](#blueprint-anatomy)
6. [Naming Convention](#naming-convention)
7. [Controls Reference](#controls-reference)
8. [index.json Maintenance](#indexjson-maintenance)
9. [CI Pipeline](#ci-pipeline)
10. [PR Review Criteria](#pr-review-criteria)
11. [Governance](#governance)

---

## Add to Your Stratum Instance

One environment variable. One sync call.

```bash
# In your Stratum .env
REGISTRY_URL=https://raw.githubusercontent.com/stratum-community/stratum-blueprints/main
```

Then trigger a sync from the UI (**Settings → Registry → Sync**) or via API:

```bash
curl -sf -X POST \
  -H "X-API-Key: $STRATUM_API_KEY" \
  http://localhost:8001/api/registry/sync
```

All blueprints in this repo appear immediately in your Stratum instance, badged as **Community**.
They are available in the 5-step wizard, the blueprint browser, and via the REST API.

---

## Blueprint Library

### Amazon Linux

| Blueprint | Framework | Level | Provider | File |
|---|---|---|---|---|
| Amazon Linux 2023 | CIS Benchmark | L1 | AWS | `blueprints/amazon-linux/2023/cis-l1-aws.yaml` |
| Amazon Linux 2023 | CIS Benchmark | L2 | AWS | `blueprints/amazon-linux/2023/cis-l2-aws.yaml` |
| Amazon Linux 2023 | DISA STIG | — | AWS | `blueprints/amazon-linux/2023/stig-aws.yaml` |

### Ubuntu

| Blueprint | Framework | Level | Provider | File |
|---|---|---|---|---|
| Ubuntu 22.04 LTS | CIS Benchmark | L1 | AWS | `blueprints/ubuntu/22.04/cis-l1-aws.yaml` |
| Ubuntu 22.04 LTS | CIS Benchmark | L2 | AWS | `blueprints/ubuntu/22.04/cis-l2-aws.yaml` |
| Ubuntu 22.04 LTS | CIS Benchmark | L1 | GCP | `blueprints/ubuntu/22.04/cis-l1-gcp.yaml` |
| Ubuntu 22.04 LTS | CIS Benchmark | L1 | Azure | `blueprints/ubuntu/22.04/cis-l1-azure.yaml` |
| Ubuntu 22.04 LTS | HIPAA Technical | — | AWS | `blueprints/ubuntu/22.04/hipaa-aws.yaml` |
| Ubuntu 24.04 LTS | CIS Benchmark | L1 | AWS | `blueprints/ubuntu/24.04/cis-l1-aws.yaml` |
| Ubuntu 24.04 LTS | CIS Benchmark | L2 | AWS | `blueprints/ubuntu/24.04/cis-l2-aws.yaml` |

### Rocky Linux

| Blueprint | Framework | Level | Provider | File |
|---|---|---|---|---|
| Rocky Linux 9 | CIS Benchmark | L1 | AWS | `blueprints/rocky/9/cis-l1-aws.yaml` |
| Rocky Linux 9 | CIS Benchmark | L2 | AWS | `blueprints/rocky/9/cis-l2-aws.yaml` |
| Rocky Linux 9 | DISA STIG | — | AWS | `blueprints/rocky/9/stig-aws.yaml` |
| Rocky Linux 9 | CIS Benchmark | L1 | GCP | `blueprints/rocky/9/cis-l1-gcp.yaml` |
| Rocky Linux 9 | CIS Benchmark | L1 | Azure | `blueprints/rocky/9/cis-l1-azure.yaml` |
| Rocky Linux 9 | CIS Benchmark | L1 | Proxmox | `blueprints/rocky/9/cis-l1-proxmox.yaml` |
| Rocky Linux 9 | PCI-DSS v4 | — | AWS | `blueprints/rocky/9/pci-dss-v4-aws.yaml` |
| Rocky Linux 9 | FedRAMP Moderate | — | AWS | `blueprints/rocky/9/fedramp-moderate-aws.yaml` |

### RHEL

| Blueprint | Framework | Level | Provider | File |
|---|---|---|---|---|
| RHEL 9 | CIS Benchmark | L1 | AWS | `blueprints/rhel/9/cis-l1-aws.yaml` |
| RHEL 9 | DISA STIG | — | AWS | `blueprints/rhel/9/stig-aws.yaml` |

### Debian

| Blueprint | Framework | Level | Provider | File |
|---|---|---|---|---|
| Debian 12 | CIS Benchmark | L1 | AWS | `blueprints/debian/12/cis-l1-aws.yaml` |
| Debian 12 | CIS Benchmark | L1 | GCP | `blueprints/debian/12/cis-l1-gcp.yaml` |

---

## Framework Coverage

The library covers every major hardening framework that has machine-executable controls.
Frameworks are implemented in one of two ways:

- **SCAP-native:** The framework has an official SCAP Security Guide datastream. The blueprint's
  `compliance.profile` points directly at the benchmark profile ID. OpenSCAP runs the evaluation
  natively — no interpretation layer.
- **Annotated overlay:** The framework has no SCAP datastream. Controls are implemented via a
  CIS L1 or L2 base profile, with specific rules enabled/disabled in the `controls` block and
  justified against the framework's control language. Compliance intent is documented in control
  justifications and `metadata.tags`.

| Framework | Implementation | Profile tier | Coverage |
|---|---|---|---|
| **CIS Benchmarks L1** | SCAP-native | `cis-l1` | Ubuntu 22/24, Rocky 9, RHEL 9, Debian 12, AL2023 |
| **CIS Benchmarks L2** | SCAP-native | `cis-l2` | Ubuntu 22/24, Rocky 9, RHEL 9, AL2023 |
| **DISA STIG** | SCAP-native | `stig` | Rocky 9, RHEL 9, AL2023 |
| **NIST SP 800-53 (OSPP)** | SCAP-native (`ospp` profile) | `cis-l2` base | RHEL-family via SSG `ospp` profile |
| **NIST SP 800-53 (PCS)** | SCAP-native (`pcs` profile) | `cis-l2` base | RHEL-family via SSG `pcs_hardening` profile |
| **PCI-DSS v4** | Annotated overlay on CIS L2 | `cis-l2` | Rocky 9, RHEL 9 — controls mapped to Req. 1–11 |
| **HIPAA Technical Safeguards** | SCAP-native (`hipaa` profile) | `cis-l1` base | RHEL-family + Ubuntu via SSG `hipaa` profile |
| **FedRAMP Moderate** | Annotated overlay on STIG | `stig` | Rocky 9, RHEL 9 — NIST 800-53 Moderate mappings |
| **ISO 27001 / 27002** | Annotated overlay on CIS L1 | `cis-l1` | All OSes — A.12/A.14 control annotations |

### What "annotated overlay" means in practice

For frameworks without a SCAP datastream (PCI-DSS, ISO 27001), the blueprint:

1. Uses a CIS L1 or L2 SCAP profile as the scan baseline (so OpenSCAP can still produce a score)
2. In the `controls` block, enables specific rules that satisfy the framework's requirements
   and disables rules that conflict with workload constraints — with justifications that
   reference the specific control clause (e.g. `PCI-DSS v4.0 Req 8.3.9`)
3. Uses `metadata.tags` to declare which framework the blueprint targets:
   `[pci-dss, pci-dss-v4, req-8, cardholder-data-environment]`
4. Uses `metadata.description` to explicitly state the framework mapping

This means you get a real OpenSCAP compliance score, plus documented evidence that the
specific framework's requirements are addressed.

---

## How to Contribute

### Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (Astral's Python package manager)
- `git`
- `jq` (for `index.json` updates)
- A working knowledge of the target OS and the hardening framework you're implementing

### Step 1 — Fork and clone

```bash
git clone https://github.com/<your-handle>/stratum-blueprints.git
cd stratum-blueprints
```

### Step 2 — Install the Stratum schema validator

```bash
uv venv && source .venv/bin/activate
uv pip install "stratum[validate] @ git+https://github.com/sachinponnapalli/Stratum.git"
```

Or if you have a local Stratum checkout:

```bash
uv pip install -e /path/to/Stratum
```

### Step 3 — Create a branch

Use the naming convention `<os>/<os-version>/<framework>-<level>-<provider>`:

```bash
git checkout -b rocky/9/pci-dss-v4-aws
```

### Step 4 — Copy the template

```bash
cp templates/BLUEPRINT_TEMPLATE.yaml blueprints/rocky/9/pci-dss-v4-aws.yaml
```

Create the directory if it does not exist:

```bash
mkdir -p blueprints/rocky/9
```

### Step 5 — Fill in the blueprint

Open `blueprints/rocky/9/pci-dss-v4-aws.yaml` in your editor.

See [Blueprint Anatomy](#blueprint-anatomy) for a field-by-field explanation.
See [Controls Reference](#controls-reference) for how to write controls for each framework.

Key things to get right:

- `metadata.name` must be unique across the entire library
- Every `controls` entry that sets `enabled: false` **must** have a non-empty `justification`
- Every `controls` entry that sets `enabled: true` for a rule that is off by default **must** have a `justification` stating which framework requirement it satisfies
- `compliance.benchmark` and `compliance.profile` must be valid SCAP Security Guide identifiers — see the [SCAP Profile Reference](#scap-profile-reference) table below
- `target.base_image` must be the real, current image ID for the provider and region — add a comment with the canonical source (AWS SSM parameter path, GCP image family, etc.)

### Step 6 — Validate locally

```bash
# Validate your blueprint's schema
python - <<'EOF'
import yaml, sys
from stratum.core.blueprint import ComplianceProfile

path = "blueprints/rocky/9/pci-dss-v4-aws.yaml"
with open(path) as f:
    data = yaml.safe_load(f)
try:
    ComplianceProfile.model_validate(data)
    print(f"✓ {path}")
except Exception as e:
    print(f"✗ {path}: {e}")
    sys.exit(1)
EOF
```

Run the full validation suite against all blueprints:

```bash
python scripts/validate_all.py
```

### Step 7 — Update index.json

Add your filename to `index.json`. The registry sync reads this file; if your blueprint is not
listed here, Stratum instances will not pick it up.

```bash
# Add to index.json (flat filename, no path prefix)
jq '. += ["rocky/9/pci-dss-v4-aws.yaml"]' index.json > index.json.tmp && mv index.json.tmp index.json
```

Keep `index.json` sorted alphabetically:

```bash
jq 'sort' index.json > index.json.tmp && mv index.json.tmp index.json
```

### Step 8 — Open a pull request

```bash
git add blueprints/rocky/9/pci-dss-v4-aws.yaml index.json
git commit -m "feat(rocky/9): add PCI-DSS v4 annotated overlay for AWS"
git push origin rocky/9/pci-dss-v4-aws
```

Open a PR against `main`. The PR template asks you to confirm:
- [ ] Blueprint validates against the Stratum schema
- [ ] `index.json` is updated and sorted
- [ ] Every control override has a non-empty `justification`
- [ ] `target.base_image` has a source comment
- [ ] `metadata.author` is set to your name or GitHub handle
- [ ] The blueprint has been tested against a real Stratum instance (optional but encouraged)

---

## Blueprint Anatomy

A fully commented walk-through of every field.

```yaml
# stratum_version: The Stratum schema version this blueprint targets.
# Use the current latest unless you have a specific reason to pin.
stratum_version: "0.3.0"

# kind: Must be "HardeningBlueprint". ("ComplianceProfile" is a legacy alias.)
kind: HardeningBlueprint

# ─────────────────────────────────────────────────────────────────────────────
# metadata — who made this and what it covers
# ─────────────────────────────────────────────────────────────────────────────
metadata:
  # name: Unique identifier across the library. Use the file path slug.
  # Pattern: <os-slug><os-version>-<framework>-<level>-<provider>
  name: rocky9-pci-dss-v4-aws

  # version: SemVer of this blueprint. Increment MINOR for new controls,
  # PATCH for corrections, MAJOR for breaking changes (e.g., OS EOL migration).
  version: "1.0.0"

  # description: One-paragraph explanation. For annotated overlays, state
  # which framework version this targets and what the CIS baseline is.
  description: >
    Rocky Linux 9 hardened to PCI-DSS v4.0 requirements, using CIS RHEL 9
    Level 2 as the SCAP scan baseline. Controls are mapped to PCI-DSS
    Requirements 1–11 (physical and logical security). Suitable for
    cardholder data environment (CDE) workloads on AWS.

  # author: Your name or GitHub handle. Required.
  author: "your-github-handle"

  # tags: Used for filtering in the UI and pipeline API. Include the OS family,
  # framework name, framework version, provider, and any relevant workload tags.
  tags:
    - rocky
    - rocky9
    - rhel9
    - pci-dss
    - pci-dss-v4
    - cde
    - aws
    - cis-l2-base

# ─────────────────────────────────────────────────────────────────────────────
# target — what to build and where
# ─────────────────────────────────────────────────────────────────────────────
target:
  # os: Stratum OS identifier. Must match a key in os_catalog.py.
  # Valid: amazon-linux-2023 | ubuntu22.04 | ubuntu24.04 | rocky9 | rhel9 | debian12
  os: rocky9

  arch: x86_64

  # provider: Cloud/hypervisor provider.
  # Valid: aws | gcp | azure | digitalocean | linode | proxmox
  provider: aws

  # base_image: The provider-specific image reference.
  # Always add a comment with the canonical source so maintainers can update it.
  # AWS: https://aws.amazon.com/marketplace or SSM parameter path
  # GCP: image family name (e.g. "rocky-linux-9")
  # Azure: publisher/offer/sku (e.g. "erockyenterprisesoftwarefoundationinc1653071250513/rockylinux-9/...")
  base_image: ami-067daee80a6d36ac0  # Rocky Linux 9, us-east-1 — check https://rockylinux.org/cloud-images

  # instance_type: Use the smallest instance that reliably completes the build.
  # t3.medium is sufficient for most CIS L1/L2 builds. t3.large for STIG.
  instance_type: t3.medium

  # root_volume_size_gb: Must be large enough for OS + Ansible Galaxy + SCAP tools.
  # Minimum: 15 GB. Recommended: 20 GB for RHEL-family. 25 GB for STIG.
  root_volume_size_gb: 20

  # extra_volumes: Additional EBS/disk volumes. Required for CIS L2 which mandates
  # separate partitions for /var, /var/log, /home, and sometimes /var/log/audit.
  # For CIS L1 with tmpfs-only layout, this section can be omitted.
  extra_volumes:
    - device_name: /dev/sdf
      size_gb: 4    # /var
    - device_name: /dev/sdg
      size_gb: 2    # /var/log
    - device_name: /dev/sdh
      size_gb: 2    # /home

# ─────────────────────────────────────────────────────────────────────────────
# system — OS-level settings applied before hardening
# ─────────────────────────────────────────────────────────────────────────────
system:
  hostname: hardened-node

  # timezone: IANA timezone identifier. Use UTC for most server workloads.
  timezone: UTC
  locale: en_US.UTF-8

  # selinux_mode: enforcing | permissive | disabled | null
  # RHEL-family: set to "enforcing". CIS and STIG require it.
  # Ubuntu/Debian: set to null (AppArmor is used instead; SELinux is not present).
  selinux_mode: enforcing

# ─────────────────────────────────────────────────────────────────────────────
# filesystem — mount points and options
# CIS requires nosuid/nodev/noexec on /tmp, /var/tmp, /dev/shm.
# CIS L2 additionally requires separate partitions for /var, /var/log, /home.
# ─────────────────────────────────────────────────────────────────────────────
filesystem:
  # Disk-backed mounts (require extra_volumes above)
  - device: /dev/nvme1n1    # maps to /dev/sdf after NVMe remapping
    mountpoint: /var
    fstype: xfs
    options: [nosuid]

  - device: /dev/nvme2n1
    mountpoint: /var/log
    fstype: xfs
    options: [nosuid, nodev, noexec]

  - device: /dev/nvme3n1
    mountpoint: /home
    fstype: xfs
    options: [nosuid, nodev]

  # tmpfs mounts — always required; no extra_volumes needed
  - device: tmpfs
    mountpoint: /tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 2G

  - device: tmpfs
    mountpoint: /var/tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 1G

  - device: tmpfs
    mountpoint: /dev/shm
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]

# ─────────────────────────────────────────────────────────────────────────────
# users — accounts created on the hardened image
# ─────────────────────────────────────────────────────────────────────────────
users:
  root:
    # lock: true disables direct root login and SSH as root. Required by CIS.
    lock: true

  accounts:
    - name: stratum-admin
      comment: "Stratum-managed admin account"
      # RHEL-family: wheel grants sudo. Ubuntu/Debian: use sudo instead.
      groups: [wheel]
      shell: /bin/bash
      # ssh_authorized_keys: Leave empty in the blueprint; inject at launch time
      # via EC2 key pair or cloud-init. Embedding keys in the golden image is
      # an anti-pattern — the key becomes baked into every instance.
      ssh_authorized_keys: []

# ─────────────────────────────────────────────────────────────────────────────
# compliance — the SCAP evaluation that runs after hardening
# ─────────────────────────────────────────────────────────────────────────────
compliance:
  # benchmark: Full SCAP benchmark ID from the SCAP Security Guide datastream.
  # See the SCAP Profile Reference table for valid values per OS.
  benchmark: xccdf_org.ssgproject.content_benchmark_RHEL-9

  # profile: Full SCAP profile ID. For annotated overlays use the closest
  # matching SCAP profile (usually CIS L2). The controls block then documents
  # the framework-specific overrides.
  profile: xccdf_org.ssgproject.content_profile_cis_server_l2

  # datastream: Path to the SCAP XML datastream on the target instance.
  # Install on RHEL-family: dnf install scap-security-guide
  # Install on Ubuntu/Debian: apt install ssg-debderived
  datastream: /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml

  # fail_on_findings: Abort the build if the grade is below threshold.
  # Set to true for production blueprints.
  fail_on_findings: true

  # severity_threshold: Fail if any finding at or above this severity exists.
  # Valid: critical | high | medium | low
  severity_threshold: medium

  # aide: Initialise the AIDE file-integrity database after hardening.
  # Required for PCI-DSS Req 11.5, STIG RHEL-09-651010.
  aide: true

  # fips: Enable FIPS 140-2 mode. Required for FedRAMP, DoD workloads.
  # Warning: enabling FIPS on an existing non-FIPS system may break package
  # installations. Test thoroughly. Not required for PCI-DSS.
  fips: false

# ─────────────────────────────────────────────────────────────────────────────
# hardening — which Ansible-Lockdown role to run
# ─────────────────────────────────────────────────────────────────────────────
hardening:
  strategy: ansible-galaxy    # ansible-galaxy | git | none

  # profile_tier: Controls which Ansible role variables are set.
  # cis-l1 | cis-l2 | stig | custom
  profile_tier: cis-l2

# ─────────────────────────────────────────────────────────────────────────────
# controls — per-rule overrides applied on top of the profile
#
# Two formats:
#   Simple: rule_id: true | false
#   Full:   rule_id: { enabled: true|false, justification: "..." }
#
# Justification is REQUIRED when:
#   - enabled: false  (you are disabling a rule the profile enables)
#   - enabled: true   (you are enabling a rule the profile disables by default)
#
# The justification should state WHY, not WHAT. Reference the specific control
# clause that requires or permits this decision.
# ─────────────────────────────────────────────────────────────────────────────
controls:
  # Enabling a rule that is off by default in CIS L2:
  xccdf_org.ssgproject.content_rule_package_aide_installed:
    enabled: true
    justification: >
      PCI-DSS v4.0 Req 11.5.2 requires a change-detection mechanism for
      critical system files. AIDE satisfies this requirement.

  # Enforcing a rule that CIS L2 also enables, with explicit justification
  # linking it to the PCI-DSS control:
  xccdf_org.ssgproject.content_rule_sshd_disable_root_login:
    enabled: true
    justification: >
      PCI-DSS v4.0 Req 8.2.1 prohibits shared or generic accounts for
      administrative access. Root SSH login must be disabled.

  # Disabling a rule with a documented reason:
  xccdf_org.ssgproject.content_rule_smartcard_auth:
    enabled: false
    justification: >
      Smart card authentication is not feasible for EC2 instances. Access is
      controlled via IAM roles and SSH key pairs instead (PCI-DSS Req 8.3.6
      compensating control: MFA enforced at the AWS console and API level).
```

---

## Naming Convention

```
<os-slug>-<os-version>-<framework>[-<level>]-<provider>.yaml
```

| Segment | Examples |
|---|---|
| `os-slug` | `amazon-linux`, `ubuntu`, `rocky`, `rhel`, `debian` |
| `os-version` | `2023`, `22.04`, `24.04`, `9`, `12` |
| `framework` | `cis`, `stig`, `hipaa`, `pci-dss-v4`, `fedramp-moderate`, `iso-27001` |
| `level` | `l1`, `l2` — omit for STIG and non-CIS frameworks |
| `provider` | `aws`, `gcp`, `azure`, `digitalocean`, `linode`, `proxmox` |

**File path:** `blueprints/<os-slug>/<os-version>/<filename>.yaml`

**Examples:**

| File path | Meaning |
|---|---|
| `blueprints/rocky/9/cis-l2-aws.yaml` | Rocky 9 · CIS L2 · AWS |
| `blueprints/ubuntu/22.04/hipaa-aws.yaml` | Ubuntu 22.04 · HIPAA · AWS |
| `blueprints/rhel/9/stig-aws.yaml` | RHEL 9 · DISA STIG · AWS |
| `blueprints/rocky/9/pci-dss-v4-aws.yaml` | Rocky 9 · PCI-DSS v4 annotated overlay · AWS |
| `blueprints/amazon-linux/2023/fedramp-moderate-aws.yaml` | AL2023 · FedRAMP Moderate · AWS |

---

## Controls Reference

### How to find SCAP rule IDs

Rule IDs follow the pattern:

```
xccdf_org.ssgproject.content_rule_<rule_name>
```

To list all rules for an OS and profile:

```bash
# Install scap-security-guide on a target instance, then:
oscap info /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml

# List all rules in a profile:
oscap xccdf show \
  --profile xccdf_org.ssgproject.content_profile_cis_server_l2 \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml \
  | grep "xccdf_org.ssgproject.content_rule"
```

Or browse them online via the [SCAP Security Guide HTML guides](https://static.open-scap.org/ssg-guides/).

### SCAP Profile Reference

| OS | `compliance.benchmark` | Profile ID fragment | Profile |
|---|---|---|---|
| Amazon Linux 2023 | `content_benchmark_AMAZON_LINUX_2023` | `cis_server_l1` | CIS L1 |
| Amazon Linux 2023 | `content_benchmark_AMAZON_LINUX_2023` | `cis_server_l2` | CIS L2 |
| Ubuntu 22.04 | `content_benchmark_UBUNTU2204` | `cis_level1_server` | CIS L1 |
| Ubuntu 22.04 | `content_benchmark_UBUNTU2204` | `cis_level2_server` | CIS L2 |
| Ubuntu 22.04 | `content_benchmark_UBUNTU2204` | `hipaa` | HIPAA |
| Ubuntu 24.04 | `content_benchmark_UBUNTU2404` | `cis_level1_server` | CIS L1 |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `cis_server_l1` | CIS L1 |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `cis_server_l2` | CIS L2 |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `stig` | DISA STIG |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `ospp` | NIST OSPP |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `hipaa` | HIPAA |
| Rocky Linux 9 | `content_benchmark_RHEL-9` | `pcs_hardening` | NIST PCS |
| RHEL 9 | `content_benchmark_RHEL-9` | (same as Rocky 9) | — |
| Debian 12 | `content_benchmark_DEBIAN12` | `cis_level1_server` | CIS L1 |

Full profile ID = `xccdf_org.ssgproject.content_profile_<fragment>`

### Framework control justification language

Use this language pattern in justifications to make it easy for auditors to trace:

| Framework | Justification pattern |
|---|---|
| CIS | `CIS <OS> Benchmark v<version> Section <x.y.z>` |
| DISA STIG | `STIG <OS> STIG v<version> Rule ID <RHEL-09-xxxxxx>` |
| PCI-DSS v4 | `PCI-DSS v4.0 Req <x.y.z> — <brief description>` |
| HIPAA | `HIPAA §164.312(a)(2)(i) — Unique User Identification` |
| NIST SP 800-53 | `NIST SP 800-53 Rev5 Control <AC-2> — <brief description>` |
| FedRAMP | `FedRAMP Moderate Baseline Control <IA-5> — <brief description>` |
| ISO 27001 | `ISO/IEC 27001:2022 Annex A <8.9> — <brief description>` |

---

## index.json Maintenance

`index.json` at the repo root is a flat JSON array of all blueprint file paths.
Stratum's registry sync fetches this file first, then downloads each listed blueprint.

**Format:**

```json
[
  "blueprints/amazon-linux/2023/cis-l1-aws.yaml",
  "blueprints/amazon-linux/2023/cis-l2-aws.yaml",
  "blueprints/rocky/9/cis-l1-aws.yaml",
  "blueprints/rocky/9/pci-dss-v4-aws.yaml"
]
```

**Rules:**
- Paths are relative to the repo root (not the raw GitHub URL)
- File must be valid JSON — no trailing commas
- Keep entries sorted alphabetically
- Every blueprint file in `blueprints/` must have an entry; orphaned files are not synced

**Update script:**

```bash
# Regenerate index.json from all YAML files in blueprints/
find blueprints/ -name "*.yaml" | sort | jq -R . | jq -s . > index.json
```

---

## CI Pipeline

Every pull request runs the following checks automatically.

### Schema validation

Validates every YAML file in `blueprints/` against the Stratum `ComplianceProfile` Pydantic schema.

```yaml
# .github/workflows/validate.yml
- name: Validate blueprint schemas
  run: |
    python - <<'EOF'
    import glob, yaml, sys
    from stratum.core.blueprint import ComplianceProfile

    errors = []
    for path in sorted(glob.glob("blueprints/**/*.yaml", recursive=True)):
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            ComplianceProfile.model_validate(data)
            print(f"✓ {path}")
        except Exception as e:
            errors.append(f"✗ {path}: {e}")

    if errors:
        for e in errors:
            print(e)
        sys.exit(1)
    EOF
```

### index.json consistency check

Verifies that every file in `blueprints/` is listed in `index.json`, and every entry
in `index.json` exists as a file on disk.

```bash
# Unlisted files (exist on disk, missing from index.json)
find blueprints/ -name "*.yaml" | sort > /tmp/disk.txt
jq -r '.[]' index.json | sort > /tmp/index.txt
diff /tmp/disk.txt /tmp/index.txt
```

### YAML lint

```bash
yamllint blueprints/
```

### Justification completeness

All `enabled: false` controls must have a non-empty `justification` field.

```bash
python scripts/check_justifications.py
```

---

## PR Review Criteria

Maintainers check the following before merging. Reviewers from the relevant OS family
are assigned via CODEOWNERS.

**Schema and structure:**
- Blueprint validates without errors
- `index.json` is updated and sorted
- File is in the correct `blueprints/<os>/<version>/` directory
- Filename follows the naming convention

**Controls quality:**
- Every `enabled: false` override has a non-empty justification
- Every `enabled: true` override for a default-off rule has a justification citing the framework clause
- Justifications are written in the framework's control language (see Controls Reference)
- No rules are disabled without documented reason

**Accuracy:**
- `compliance.benchmark` and `compliance.profile` match the OS's actual SCAP Security Guide output
- `target.base_image` is a real, current image ID with a source comment
- `hardening.profile_tier` matches the SCAP profile (e.g. `cis-l2` profile → `cis-l2` tier)
- Filesystem mount options match CIS/STIG requirements for the declared level

**Metadata completeness:**
- `metadata.author` is set
- `metadata.tags` includes the OS family, framework, provider, and version
- `metadata.description` clearly states the framework, framework version, and any notable design decisions

---

## Governance

### CODEOWNERS

```
# CODEOWNERS
blueprints/amazon-linux/   @vamshikrish-sec
blueprints/ubuntu/         @vamshikrish-sec
blueprints/rocky/          @vamshikrish-sec
blueprints/rhel/           @vamshikrish-sec
blueprints/debian/         @vamshikrish-sec
templates/                 @vamshikrish-sec
schemas/                   @vamshikrish-sec
```

Community maintainers can be added per OS family as the contributor base grows.
Open an issue titled `Maintainer request: <os-slug>` to request CODEOWNERS rights for an OS family.

### Versioning

Each blueprint carries its own `metadata.version` in SemVer:

- **PATCH** (`1.0.1`): Correct a control ID, fix a justification wording, update a base image ID
- **MINOR** (`1.1.0`): Add new controls, extend framework coverage, add AIDE or FIPS support
- **MAJOR** (`2.0.0`): Target OS reaches EOL and blueprint is migrated (e.g. Ubuntu 22.04 → 24.04), or framework version changes in a breaking way

### Deprecation

When an OS reaches end-of-life or a framework version is superseded:

1. The blueprint file is moved to `blueprints/<os>/<version>/deprecated/`
2. A notice is added to the file's `metadata.description`
3. The entry in `index.json` is updated to point to the `deprecated/` path
4. A deprecation issue is opened with a migration guide to the replacement blueprint

### Security reports

Do not open a public issue for security vulnerabilities in a blueprint (e.g. a control that
weakens security rather than strengthening it). Email `security@linuxcent.com` instead.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

Built and maintained by [Vamshi Krishna Santhapuri](https://linuxcent.com) and the Stratum community.
