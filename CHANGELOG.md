# Changelog

All notable changes to Stratum are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] — 2026-04-16

### Added

**Pluggable LLM backends for the AI Builder**

The AI Builder is no longer tied to Anthropic. A new `stratum/core/llm/` package
provides a `LLMBackend` protocol with four production-ready implementations:

- **Anthropic** (default) — `claude-opus-4-6` with adaptive extended thinking.
  Controlled by `ANTHROPIC_API_KEY`.
- **OpenAI-compatible** — any endpoint that speaks the OpenAI Chat Completions
  protocol: OpenAI, Groq, Together AI, Fireworks, vLLM, LiteLLM. Controlled by
  `STRATUM_LLM_API_KEY` / `OPENAI_API_KEY` + optional `STRATUM_LLM_BASE_URL`.
  Requires `uv add openai` (or `uv sync --extra llm-openai`).
- **Ollama** — local open-weight models (llama3.3:70b, qwen2.5:72b, etc.) via
  Ollama's OpenAI-compatible endpoint. No API key needed. Good for air-gapped /
  on-prem deployments.
- **AWS Bedrock** — Bedrock Converse API using existing AWS credentials (same
  creds Stratum uses for EC2/AMI operations). No separate key required.
  Requires `uv add boto3` (or `uv sync --extra llm-bedrock`).

Backend selection and model override via env vars:

```
STRATUM_LLM_PROVIDER=anthropic | openai | ollama | bedrock
STRATUM_LLM_MODEL=<model-name>
STRATUM_LLM_API_KEY=<key>
STRATUM_LLM_BASE_URL=<url>
STRATUM_LLM_THINKING=0   # disable extended thinking
```

**Other additions**

- `.env.example` — documented reference for all Stratum env vars with per-backend
  LLM examples.
- `pyproject.toml`: new optional dep groups `llm-openai`, `llm-bedrock`, `llm-all`.

### Fixed

- `docker-compose.yml`: `./profiles/templates` volume mount changed to `./profiles`
  so user-uploaded blueprints (`profiles/user/`) survive container restarts.
- `docker-compose.yml`: added commented-out LLM backend env var blocks for each
  supported provider.

### Tests

- 30 new unit tests in `tests/test_llm_backends.py` covering format converters
  (OpenAI + Bedrock tool schemas and message translation), factory routing, and
  `provider_status()`. All offline — no API calls.
- Suite: 755 passed (CI gate: 80%).

---

## [0.2.0] — 2026-04-14

### Added

**Blueprint-as-Code**

- `POST /api/blueprints/upload` — upload a `ComplianceProfile` YAML via API or UI. Schema-validated on receipt; `409` on name collision; saved to a dedicated `profiles/user/` directory separate from built-in templates.
- `POST /api/blueprints/validate` — validate YAML against the `ComplianceProfile` schema without saving. Returns `{"valid": bool, "errors": [...]}`. Use as a pre-commit hook or CI lint step.
- `DELETE /api/blueprints/{name}` — delete a user-uploaded blueprint. Built-in templates return `403`; unknown names return `404`.
- `PipelineBuildRequest.blueprint_yaml` — pass a full blueprint YAML inline in the build request body. Skips the upload step entirely; takes precedence over `profile_name` when both are supplied. Either field is required — `422` if neither is present.
- `settings.user_profiles_dir` — new config key (`STRATUM_USER_PROFILES_DIR`, default `profiles/user/`). All blueprint list, get, download, delete, and preview endpoints now search both `profiles_dir` and `user_profiles_dir`.

**Compliance Badge**

- `GET /api/auditor/scan-image/{job_id}/badge.svg` — Shields.io-style flat SVG badge showing grade and score percentage. Returns `202` with a "scanning…" badge while the job is in progress, `404` for unknown jobs. Colours: A=green, B=teal, C=yellow, D=orange, F=red. Embeddable in READMEs and dashboards.

**Build Pipeline**

- `POST /api/pipeline/build` — new endpoint to trigger a full hardened image build (provision → harden → scan → snapshot). Supports `wait=true` (blocking) and `wait=false` + polling via `GET /api/pipeline/build/{id}`.
- `GET /api/pipeline/build/{id}` — poll a build job; returns `status`, `artifact_id`, and a 10-line `log_tail`.

**UI**

- Blueprint index: "Upload Blueprint" button opens a drag-and-drop modal with client-side YAML validation feedback. Per-card Download YAML and Build buttons visible on hover.
- Blueprint Studio: "Download YAML" button wired to `GET /api/blueprints/{name}/download`. "Build" button sends the current preview YAML as `blueprint_yaml` to the pipeline API and shows a result toast.

**Docs**

- `docs/pipeline.md` — added Build Pipeline, Blueprint-as-Code API, and Compliance Badge sections. Endpoint reference tables updated for all new routes.

**Tests**

- 23 new tests across `test_api_blueprints.py`, `test_api_pipeline.py`, and `test_api_auditor.py`.
- Suite: 688 passed, 22 skipped. Coverage: 82% (CI gate: 80%).

**Config**

- `pytest` markers registered in `pyproject.toml`: `integration`, `aws_fast`, `aws_smoke`, `aws_full`.

---

## [0.1.0] — 2026-03-XX

Initial open-core release.

- Blueprint-driven hardened OS image pipeline (AWS, GCP, Azure, DigitalOcean, Linode, Proxmox).
- Declarative `ComplianceProfile` YAML — OS, provider, CIS benchmark, control overrides.
- Ansible-Lockdown hardening roles + OpenSCAP compliance scanning.
- FastAPI + HTMX UI: Blueprint Studio, Image Builder wizard, Auditor, Integrations.
- Pipeline API with API key auth and webhook notifications.
- Compliance scan reports: HTML, JSON, SARIF 2.1.0.
- Dynamic plugin system: providers installed on-demand from `plugins/catalog/`.
- Runtime AMI resolution — always pulls the latest image for the target region.
- Community blueprint registry sync.
