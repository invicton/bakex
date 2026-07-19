# Contributing a Blueprint

A field-by-field guide to writing and submitting a `HardeningBlueprint` YAML file for the
`blueprints/` community library. See [README.md](README.md) for the current inventory and
the naming/layout convention.

## Before you start: is the OS ready?

Not every OS BakeX could theoretically support is actually ready for a blueprint yet. A
blueprint needs **both** halves working:

1. A real SCAP/OpenSCAP CIS profile from ComplianceAsCode (for scanning/scoring), and
2. A published Ansible-Lockdown role for that OS (for remediation).

As of this writing, these are **not ready** — don't start a blueprint for them yet:

| OS | Blocked on |
|---|---|
| RHEL 10 | No `ansible-lockdown` role published yet (SCAP content exists) |
| Debian 13 | No `ansible-lockdown` role published yet; upstream CIS SCAP content itself is still being actively built (check [ComplianceAsCode/content](https://github.com/ComplianceAsCode/content) PR activity before assuming it's done) |
| Ubuntu 26.04 | CIS hasn't published an official benchmark for it yet, so there's no SCAP profile to target at all |

If you want to help unblock one of these, the highest-leverage contribution is upstream —
either a ComplianceAsCode/content profile PR or a new `ansible-lockdown` role — not a BakeX
blueprint that can't actually remediate anything yet.

## Step 1 — Fork and clone

```bash
git clone https://github.com/<your-handle>/bakex.git
cd bakex
```

## Step 2 — Install dependencies

```bash
uv sync --extra all-providers --group dev
```

## Step 3 — Create a branch

Use the naming convention `<os>/<os-version>/<framework>-<level>-<provider>`:

```bash
git checkout -b rocky/9/cis-l2-aws
```

## Step 4 — Copy the closest existing blueprint

Start from whichever existing file in `blueprints/` is closest to what you're adding (same OS
if possible, otherwise same OS family) rather than writing from scratch.

```bash
mkdir -p blueprints/rocky/9
cp blueprints/rocky/9/cis-l1-aws.yaml blueprints/rocky/9/cis-l2-aws.yaml
```

## Step 5 — Fill in the blueprint

See [Blueprint Anatomy](#blueprint-anatomy) below for a field-by-field explanation and
[SCAP Profile Reference](#scap-profile-reference) for valid `compliance.benchmark`/`profile` values.

Key things to get right:

- `metadata.name` must be unique across the entire library
- Every `controls` entry that sets `enabled: false` **must** have a non-empty `justification`
- Every `controls` entry that sets `enabled: true` for a rule that is off by default **must**
  have a `justification` stating which framework requirement it satisfies
- `compliance.benchmark` and `compliance.profile` must be valid SCAP Security Guide
  identifiers — see the [SCAP Profile Reference](#scap-profile-reference) table. **Verify
  against a real datastream** (`oscap info <datastream>`), don't guess from a similar OS —
  profile ID conventions are not consistent across OS families (see the table; RHEL-family
  and Ubuntu/Debian-family use genuinely different naming schemes for the same tier).
- `target.base_image` must be the real, current image ID for the provider and region — add a
  comment with the canonical source (AWS SSM parameter path, GCP image family, etc.)

## Step 6 — Validate locally

```bash
uv run python - <<'PY'
import yaml
from bakex.core.blueprint import ComplianceProfile

path = "blueprints/rocky/9/cis-l2-aws.yaml"
with open(path) as f:
    data = yaml.safe_load(f)
ComplianceProfile.model_validate(data)
print(f"OK {path}")
PY
```

## Step 7 — Update index.json

```bash
jq '. += ["rocky/9/cis-l2-aws.yaml"] | sort' blueprints/index.json > /tmp/index.json.tmp \
  && mv /tmp/index.json.tmp blueprints/index.json
```

## Step 8 — Open a pull request

```bash
git add blueprints/rocky/9/cis-l2-aws.yaml blueprints/index.json
git commit -m "feat(rocky/9): add CIS L2 blueprint for AWS"
git push origin rocky/9/cis-l2-aws
```

PR checklist:
- [ ] Blueprint validates against the BakeX schema
- [ ] `index.json` is updated and sorted
- [ ] Every control override has a non-empty justification
- [ ] `target.base_image` has a source comment
- [ ] `metadata.author` is set to your name or GitHub handle

---

## Blueprint Anatomy

A fully commented walk-through of every field.

```yaml
# bakex_version: The BakeX schema version this blueprint targets.
bakex_version: "0.5.1"

# kind: Must be "HardeningBlueprint". ("ComplianceProfile" is a legacy alias.)
kind: HardeningBlueprint

metadata:
  # name: Unique identifier across the library. Use the file path slug.
  name: rocky9-cis-l2-aws

  # version: SemVer of this blueprint. Increment MINOR for new controls,
  # PATCH for corrections, MAJOR for breaking changes (e.g., OS EOL migration).
  version: "1.0.0"

  # description: One-paragraph explanation of scope and any notable decisions.
  description: >
    CIS Rocky Linux 9 Benchmark — Level 2 Server profile for AWS. SELinux enforcing.

  # author: Your name or GitHub handle. Required.
  author: "your-github-handle"

  # tags: Used for filtering. Include OS family, framework, level, provider.
  tags: [rocky, rocky9, cis, level2, server, aws, selinux]

target:
  # os: BakeX OS identifier. Must match a key in bakex/core/os_catalog.py's OS_CATALOG.
  os: rocky9
  arch: x86_64
  # provider: aws | gcp | azure | digitalocean | linode | proxmox | kvm
  provider: aws
  # base_image: always add a comment with the canonical source so maintainers can update it
  base_image: ami-078448b73f6313465  # Rocky 9, us-east-1 — check rockylinux.org/cloud-images
  instance_type: t3.medium
  root_volume_size_gb: 20

system:
  hostname: hardened-node
  timezone: UTC
  locale: en_US.UTF-8
  # selinux_mode: enforcing | permissive | disabled | null
  # RHEL-family: "enforcing". Ubuntu/Debian: null (AppArmor is used instead).
  selinux_mode: enforcing

filesystem:
  # CIS L2 requires separate partitions for /var, /var/log, /home, sometimes /var/log/audit.
  # CIS L1 with tmpfs-only layout can omit disk-backed mounts.
  - device: tmpfs
    mountpoint: /tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 2G

users:
  root:
    lock: true  # Required by CIS. Disables direct root login and SSH as root.
  accounts:
    - name: bakex-admin
      groups: [wheel]  # RHEL-family: wheel. Ubuntu/Debian: sudo.
      shell: /bin/bash
      # Leave ssh_authorized_keys empty; inject at launch time, never bake into the image.
      ssh_authorized_keys: []

compliance:
  # benchmark: full SCAP benchmark ID — see SCAP Profile Reference below
  benchmark: xccdf_org.ssgproject.content_benchmark_RHEL-9
  # profile: full SCAP profile ID — see SCAP Profile Reference below
  profile: xccdf_org.ssgproject.content_profile_cis
  # datastream: path to the SCAP XML datastream on the target instance
  datastream: /usr/share/xml/scap/ssg/content/ssg-rl9-ds.xml
  # fail_on_findings: abort the build if the grade is below threshold
  fail_on_findings: true
  severity_threshold: medium
  # aide: initialise the AIDE file-integrity database after hardening
  aide: true
  fips: false

hardening:
  strategy: ansible-galaxy    # ansible-galaxy | git | none
  # profile_tier: cis-l1 | cis-l2 | stig | custom
  profile_tier: cis-l2

controls:
  # Full format, required when overriding a rule's default:
  xccdf_org.ssgproject.content_rule_package_aide_installed:
    enabled: true
    justification: >
      CIS Rocky Linux 9 Benchmark Section 6.1.2 — file integrity monitoring required at L2.
```

---

## Naming Convention

```
<os-slug>-<os-version>-<framework>[-<level>]-<provider>.yaml
```

| Segment | Examples |
|---|---|
| `os-slug` | `amazon-linux`, `ubuntu`, `rocky`, `rhel`, `alma`, `debian` |
| `os-version` | `2023`, `22.04`, `24.04`, `9`, `12` |
| `framework` | `cis`, `stig` |
| `level` | `l1`, `l2` — omit for STIG |
| `provider` | `aws`, `gcp`, `azure`, `digitalocean`, `linode`, `proxmox` |

**File path:** `blueprints/<os-slug>/<os-version>/<framework>[-<level>]-<provider>.yaml`

---

## Controls Reference

Rule IDs follow the pattern `xccdf_org.ssgproject.content_rule_<rule_name>`.

To list all rules for an OS and profile, on a target with the datastream installed:

```bash
oscap xccdf show --profile xccdf_org.ssgproject.content_profile_cis_server_l1 \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml \
  | grep "xccdf_org.ssgproject.content_rule"
```

Or browse the [SCAP Security Guide HTML guides](https://static.open-scap.org/ssg-guides/).

### SCAP Profile Reference

**This is the single most error-prone part of writing a blueprint** — CIS profile ID
conventions genuinely differ between OS families, and guessing wrong produces a blueprint
that silently fails to scan (wrong `--benchmark-id`) or targets a nonexistent profile.
Verified directly against real ComplianceAsCode product definitions, not inferred:

| OS family | `compliance.benchmark` | CIS L1 profile | CIS L2 profile |
|---|---|---|---|
| RHEL-family (RHEL 9, Rocky 9, AlmaLinux 9, Amazon Linux 2023) | `content_benchmark_RHEL-9` / `content_benchmark_AMAZON_LINUX_2023` | `cis_server_l1` | `cis` (bare — there is no `cis_server_l2`) |
| Ubuntu 22.04 / 24.04 | `content_benchmark_UBUNTU2204` / `..._UBUNTU2404` | `cis_level1_server` | `cis_level2_server` |
| Debian 12 | `content_benchmark_DEBIAN12` | `cis_level1_server` | `cis_level2_server` |

Full profile ID = `xccdf_org.ssgproject.content_profile_<fragment>`.

When in doubt, don't trust this table over a real datastream — confirm with
`oscap info <datastream>` against the actual target, especially for any OS not listed above.

### Framework control justification language

| Framework | Justification pattern |
|---|---|
| CIS | `CIS <OS> Benchmark v<version> Section <x.y.z>` |
| DISA STIG | `STIG <OS> STIG v<version> Rule ID <RHEL-09-xxxxxx>` |

---

## PR Review Criteria

**Schema and structure:**
- Blueprint validates without errors
- `index.json` is updated and sorted
- File is in the correct `blueprints/<os>/<version>/` directory
- Filename follows the naming convention

**Controls quality:**
- Every `enabled: false` override has a non-empty justification
- Every `enabled: true` override for a default-off rule has a justification citing the framework clause
- No rules are disabled without documented reason

**Accuracy:**
- `compliance.benchmark` and `compliance.profile` match the OS's actual SCAP Security Guide
  output (see the readiness note and profile reference table above — this is where most
  first-PR mistakes happen)
- `target.base_image` is a real, current image ID with a source comment
- `hardening.profile_tier` matches the SCAP profile tier

**Metadata completeness:**
- `metadata.author` is set
- `metadata.tags` includes the OS family, framework, provider, and version
