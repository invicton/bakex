# BakeX Documentation

| Guide | Purpose |
|---|---|
| [Getting Started](getting-started.md) | Zero → hardened golden image with compliance evidence |
| [Blueprint Guide](blueprint-guide.md) | `HardeningBlueprint` schema, examples, templates, community library |
| [Configuration](configuration.md) | Environment variables, LLM backends, system dependencies |
| [Cloud Onboarding](cloud-onboarding.md) | AWS, Azure, and GCP admin permission model and outputs |
| [Pipeline Guide](pipeline.md) | CI/CD integration, SARIF export, Blueprint-as-Code examples |
| [API Reference](api.md) | Core REST endpoints and integration payloads |
| [Plugin Guide](plugin-guide.md) | Writing and distributing provider plugins |
| [Architecture](architecture.md) | Pipeline state machine, source tree, design decisions |

Related, outside `docs/`:

- [`../ROADMAP.md`](../ROADMAP.md) — milestones and how to influence them
- [`../blueprints/CONTRIBUTING.md`](../blueprints/CONTRIBUTING.md) — contributing community blueprints
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — dev workflow, code style, PR gates
- [`../CHANGELOG.md`](../CHANGELOG.md) — release history

Deep-dive references kept alongside: the
[AL2023 CIS L2 worked example](ux-flow-cis-l2-amazon-linux-2023.md) and the
annotated [blueprint template](bakex-blueprints-template.yaml).
Internal engineering docs live in [`dev/`](dev/).
