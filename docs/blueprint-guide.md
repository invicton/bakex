# HardeningBlueprint Guide

Blueprints are YAML documents that fully describe a hardened image. Every field
has a safe default — start minimal and add only what you need.

Annotated starter template: [`bakex-blueprints-template.yaml`](bakex-blueprints-template.yaml).
Contributing a blueprint to the community library? See
[`blueprints/CONTRIBUTING.md`](../blueprints/CONTRIBUTING.md) for the
field-by-field anatomy, naming convention, and SCAP profile reference table.

## Minimal example

```yaml
bakex_version: "0.5.0"
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

## Full schema

```yaml
bakex_version: "0.5.0"
kind: HardeningBlueprint

metadata:
  name: string                       # Unique identifier
  version: "1.0.0"
  description: string
  author: string
  tags: [list of strings]

target:
  os: amazon-linux-2023              # See supported OS list in the README
  arch: x86_64
  provider: aws                      # See supported providers in the README
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
    - name: bakex-admin
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

## Pre-built templates

Built-in app templates live in [`profiles/templates/`](../profiles/templates/).
Load any of them in the UI or reference them by name.

| File | OS | Provider | Profile |
|---|---|---|---|
| `amazon-linux-2023-cis-l1-aws.yaml` | Amazon Linux 2023 | AWS | CIS L1 |
| `alma9-cis-l1-aws.yaml` | AlmaLinux 9 | AWS | CIS L1 |
| `debian12-cis-l1-aws.yaml` | Debian 12 | AWS | CIS L1 |
| `debian12-cis-l1-digitalocean.yaml` | Debian 12 | DigitalOcean | CIS L1 |
| `debian12-cis-l1-gcp.yaml` | Debian 12 | GCP | CIS L1 |
| `generic-hardening-blueprint.yaml` | Any | Any | Custom starting point |
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

## Community blueprint library

The top-level [`blueprints/`](../blueprints/) folder is the public library
surface for contributor-submitted blueprints — more OS/provider/framework
combinations without changing the BakeX engine.

The folder is organized by OS family and version:

```text
blueprints/<os-family>/<os-version>/<framework>-<level>-<provider>.yaml
```

Each contribution should:

- validate against the `HardeningBlueprint` schema
- use a supported OpenSCAP datastream/profile for the target OS
- include accurate provider defaults and metadata tags
- add its path to [`blueprints/index.json`](../blueprints/index.json)

See [`blueprints/README.md`](../blueprints/README.md) for the contribution
checklist. Blueprint schema and index consistency are CI-enforced.

## Validating locally

```bash
# Validate one file via the API (server running)
curl -s -X POST http://localhost:8000/api/blueprints/validate \
  -u admin:$BAKEX_ADMIN_TOKEN \
  --data-binary @my-blueprint.yaml

# Validate every template offline
uv run python -c "
from bakex.core.blueprint import HardeningBlueprint
import glob, yaml
for f in glob.glob('profiles/**/*.yaml', recursive=True):
    HardeningBlueprint(**yaml.safe_load(open(f)))
    print(f'OK: {f}')
"
```
