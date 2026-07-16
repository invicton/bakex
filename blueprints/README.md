# BakeX Community Blueprints

This folder is the public contribution library for `HardeningBlueprint` YAML files.

BakeX keeps built-in runtime templates in `profiles/templates/`. Community contributions
start here in `blueprints/`, where each file is organized by operating system, OS version,
framework, level, and provider.

## Available now

18 blueprints, all CIS Level 1, across 6 OS families:

| OS | Providers | Framework/Level |
|---|---|---|
| AlmaLinux 9 | AWS | CIS L1 |
| Amazon Linux 2023 | AWS | CIS L1 |
| Debian 12 | AWS, DigitalOcean, GCP | CIS L1 |
| Rocky Linux 9 | AWS, Azure, DigitalOcean, GCP, Linode, Proxmox | CIS L1 |
| Ubuntu 22.04 LTS | AWS, Azure, DigitalOcean, GCP, Linode, Proxmox | CIS L1 |
| Generic | — | Unopinionated starting template |

This is an early library, not a complete one — see [Good First Contributions](#good-first-contributions)
below for the concrete gaps we'd like filled in next.

## Layout

```text
blueprints/
  index.json
  amazon-linux/2023/cis-l1-aws.yaml
  ubuntu/22.04/cis-l1-aws.yaml
  rocky/9/cis-l1-proxmox.yaml
  debian/12/cis-l1-gcp.yaml
```

Use this path convention:

```text
blueprints/<os-family>/<os-version>/<framework>-<level>-<provider>.yaml
```

Examples:

- `blueprints/ubuntu/22.04/cis-l1-aws.yaml`
- `blueprints/rocky/9/cis-l1-proxmox.yaml`
- `blueprints/debian/12/cis-l1-gcp.yaml`

See [CONTRIBUTING.md](CONTRIBUTING.md) for a full field-by-field blueprint walkthrough,
naming convention, and SCAP profile reference table.

## Contribution Checklist

- Start from an existing blueprint for the closest OS/provider.
- Keep `bakex_version` and `kind: HardeningBlueprint`.
- Use a unique `metadata.name` and accurate `metadata.tags`.
- Set the correct provider-specific `target.base_image`, `instance_type`, and region assumptions.
- Point `compliance.datastream` and `compliance.profile` to a valid OpenSCAP/SSG profile for that OS
  — verify it's a real profile ID against the actual datastream, not just a plausible-looking one
  (`oscap info <datastream>` on a real target, or check the SCAP profile reference in CONTRIBUTING.md).
- Add documented `controls` overrides only when the exception or enabling rationale is clear.
- Add the new file path to `blueprints/index.json`.
- Run schema validation and tests before opening a PR.

## Validation

From the repository root:

```bash
uv sync --extra all-providers --group dev
uv run python - <<'PY'
from pathlib import Path
import yaml
from bakex.core.blueprint import ComplianceProfile

for path in sorted(Path("blueprints").rglob("*.yaml")):
    raw = yaml.safe_load(path.read_text())
    ComplianceProfile.model_validate(raw)
    print(f"OK {path}")
PY
```

CI runs this automatically on every PR — see the `validate-blueprints` job in `.github/workflows/ci.yml`.

## Good First Contributions

Concrete, scoped gaps — pick one and go:

- **CIS L2 for existing OSes.** Rocky 9, RHEL 9, Amazon Linux 2023, and Debian 12 all have CIS L2
  support in BakeX's `OS_CATALOG` already (SCAP profile + Ansible-Lockdown role variables both
  exist) — there just isn't a blueprint file for it yet in this library.
- **RHEL 9** blueprint (the OS is fully supported by BakeX; no blueprint file exists here yet).
- **More providers per OS** — e.g. AlmaLinux 9 or Amazon Linux 2023 on Azure/GCP, Debian 12 on
  Azure/Linode/Proxmox.
- Add metadata tags and documented control overrides for common workload types.
- Improve provider-specific defaults such as instance type, volume size, or image family reference.

**Not ready yet, don't start these**: RHEL 10, Debian 13, and Ubuntu 26.04 blueprints. All three are
blocked upstream right now — see `CONTRIBUTING.md`'s note on OS readiness before picking a new OS.
