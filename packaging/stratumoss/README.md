# Stratum is now BakeX

**This package has been renamed. Install [`bakex`](https://pypi.org/project/bakex/) instead.**

```bash
pip install bakex
```

`stratumoss` is no longer developed. Everything that was Stratum lives on as BakeX, built by
the same people, in the open, under Apache-2.0.

## What changed

| Was | Now |
|---|---|
| `pip install stratumoss` | `pip install bakex` |
| `import stratum` | `import bakex` |
| `STRATUM_*` environment variables | `BAKEX_*` |
| `stratum_version:` in a blueprint | `bakex_version:` |
| `github.com/StratumOSS/Stratum` | [`github.com/invicton/bakex`](https://github.com/invicton/bakex) |

Installing this package pulls in `bakex` for you, so nothing breaks — but `import stratum`
will raise with a pointer to the new name. Update your imports and depend on `bakex`
directly.

## Why the rename

"Stratum" is a common word and collided with existing projects, including an unrelated
`stratum` package on PyPI. The tool is now **BakeX**: you *bake* a declarative blueprint into
a rigid, ready-to-deploy golden image. It is published under the **Invicton** org.

This happened pre-launch, at v0.6.0. The full rationale is in the
[changelog](https://github.com/invicton/bakex/blob/main/CHANGELOG.md).

## What BakeX does

Describe a hardened OS in one YAML blueprint; BakeX builds the CIS/STIG-benchmarked golden
image on any cloud — or locally on KVM — and hands you the compliance evidence.

```bash
bakex validate blueprints/ubuntu/22.04/cis-l1-aws.yaml
bakex build    blueprints/ubuntu/22.04/cis-l1-aws.yaml
```

Provision → harden with [Ansible-Lockdown](https://github.com/ansible-lockdown) → scan with
OpenSCAP → snapshot → tear down. You get a golden image, an A–F grade, and a SARIF report.

- **Repository:** https://github.com/invicton/bakex
- **Blueprint library:** https://github.com/invicton/bakex/tree/main/blueprints
- **Blueprint JSON Schema:** https://github.com/invicton/bakex/blob/main/docs/schema/hardening-blueprint.schema.json
- **Changelog:** https://github.com/invicton/bakex/blob/main/CHANGELOG.md

Contributions are welcome — the blueprint library is deliberately pure YAML, and there are
[good first issues](https://github.com/invicton/bakex/issues?q=is%3Aissue+is%3Aopen+label%3Ablueprint)
open for new OS/provider combinations.
