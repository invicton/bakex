# Stratum Community Blueprints

This folder is the public contribution library for `HardeningBlueprint` YAML files.

Stratum keeps built-in runtime templates in `profiles/templates/`. Community contributions should start here in `blueprints/`, where each file is organized by operating system, OS version, framework, level, and provider.

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

## Contribution Checklist

- Start from an existing blueprint for the closest OS/provider.
- Keep `stratum_version: "0.3.0"` and `kind: HardeningBlueprint`.
- Use a unique `metadata.name` and accurate `metadata.tags`.
- Set the correct provider-specific `target.base_image`, `instance_type`, and region assumptions.
- Point `compliance.datastream` and `compliance.profile` to a valid OpenSCAP/SSG profile for that OS.
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
from stratum.core.blueprint import ComplianceProfile

for path in sorted(Path("blueprints").rglob("*.yaml")):
    raw = yaml.safe_load(path.read_text())
    ComplianceProfile.model_validate(raw)
    print(f"OK {path}")
PY
```

## Good First Contributions

- Add CIS L1 blueprints for more providers for a supported OS.
- Add Ubuntu 24.04 and RHEL 9 variants where the OpenSCAP datastream/profile is known.
- Add metadata tags and documented control overrides for common workload types.
- Improve provider-specific defaults such as instance type, volume size, or image family reference.
