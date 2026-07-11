# Changelog

All notable changes to Stratum are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- `ROADMAP.md` — public milestones (v0.6 launch, v0.7 blueprint depth,
  v0.8 AI-agent-friendly surface, v1.0 criteria) and the ecosystem
  integration track.
- Dependabot configuration (pip, GitHub Actions, Docker — weekly) and
  repository security updates enabled.
- GitHub Discussions enabled.

### Changed

- Dropped the "open-core" label from all public copy (README, repo
  description, package metadata, CONTRIBUTING). Stratum is straight
  Apache-2.0; a commercial story, if one ever exists, will be additive
  rather than a carve-out of the core.
- Repo hygiene: SECURITY.md supported-versions table now says 0.5.x,
  CONTRIBUTING line-length matches ruff (120), blueprint
  `stratum_version` pins normalized, stale `docs/stratum-blueprints-repo-readme.md`
  stub removed, 0.1.0 changelog date fixed.

## [0.5.2] — 2026-07-11

First release published to PyPI (`pip install stratumoss`).

### Fixed

**`pip install stratumoss` now works from any directory — previously the app only ran from a repo checkout**

- Jinja2 templates and static assets were loaded from CWD-relative paths
  (`stratum/templates`, `stratum/static`), so every UI page 500'd with
  `TemplateNotFound` and CSS/JS never mounted unless the server was started
  from the repo root. All paths are now anchored to the installed package
  (`stratum/paths.py`).
- Built-in blueprint templates (`profiles/templates/`) and the provider
  catalog (`plugins/catalog/`) now ship inside the wheel; `Settings` falls
  back to the bundled copies when the CWD-relative directories are missing.
  Explicitly configured dirs (env var or kwarg) are never overridden.
- Community registry sync failed to cache blueprints with nested index
  paths (e.g. `rocky/9/cis-l1-aws.yaml`) because parent directories were
  never created.
- Playwright UI tests (`tests/ui/`) errored instead of skipping on any
  machine without browsers installed (e.g. CI), because the opt-in
  guard was a function-scoped autouse fixture but pytest-playwright's
  `browser` fixture is session-scoped and instantiated first. Replaced
  with a collection-time `skipif` marker. This had been failing
  `Tests (pytest)` on `main` silently before branch protection made it
  a hard gate.

### Changed

- Default `registry_url` now points at the real community blueprint
  library (`StratumOSS/Stratum` `blueprints/`) instead of the
  never-created `stratum-community/profiles` repo.
- Releases are published to PyPI via GitHub Actions trusted publishing
  on version tags (`.github/workflows/release.yml`).
- Project moved from `github.com/rrskris/Stratum` to a dedicated org,
  `github.com/StratumOSS/Stratum` (old URL redirects automatically).
- PyPI distribution name is now `stratumoss` (the plain `stratum` name is
  an unrelated, long-abandoned package). The importable module is
  unchanged — it's still `import stratum`.

### Added

- Branch protection on `main`: required CI checks, one required review,
  stale-review dismissal, no force-pushes.
- DCO enforcement (`.github/workflows/dco.yml`) — every PR commit must
  carry a `Signed-off-by` line.
- `CODEOWNERS` and an expanded PR template checklist.
- Seven curated `good first issue`/`help wanted` issues covering CIS L2
  blueprints (Ubuntu 22.04, Rocky/Alma 9, Debian 12), first blueprints
  for Ubuntu 24.04, Blueprint Studio validation feedback, a light theme
  toggle, and a Rocky 9 STIG blueprint.

---

## [0.5.1] — 2026-07-05

### Fixed

**OpenSCAP scans were silently no-ops when SCAP content was missing — affects every provider**

- `run_oscap_remote` previously logged a warning and returned an empty string when `oscap` produced no output (e.g. the binary or SCAP content is missing on the target) instead of raising — a build could report `COMPLETE` despite the compliance scan never actually running. Now raises, so this failure mode is loud rather than silently accepted. This was caught by re-verifying a build that had appeared to succeed in the previous release.
- `install_oscap_on_remote` now checks whether the target's SCAP datastream actually exists after the package-manager install attempt, and if not, downloads the matching content directly from a [ComplianceAsCode/content](https://github.com/ComplianceAsCode/content) GitHub release (checksum-verified, cached locally) and uploads it to the expected path. This is the same workaround a real user independently arrived at for the identical Ubuntu 22.04 gap (documented in a public Launchpad question) — not a guess. `scap-security-guide` (the package that would normally provide this content) turns out to be missing from **both** Ubuntu 22.04 and 24.04's archives, not just 22.04 as first thought, so this fix benefits every OS/provider combination, not only the one originally suspected.
- Ubuntu 22.04 still cannot run OpenSCAP scans end-to-end even with this fix, since `openscap-scanner` itself has no apt package on that release in any channel — only the content-availability half of the problem is fixed there. Tracked in `CONTRIBUTING.md`.

---

## [0.5.0] — 2026-07-05

### Added

**Local / on-prem image building (no cloud account required)**

- New `kvm` provider (`plugins/providers/kvm.py` + `plugins/providers/_qemu_utils.py`) — builds hardened images on the machine running Stratum using `qemu-system-x86_64` (KVM-accelerated when `/dev/kvm` is available, falling back to slower TCG emulation). Reuses the existing Ansible-Lockdown hardening and OpenSCAP scanning flow unchanged.
- Base images: pass a downloadable OS slug (`ubuntu22.04`, `ubuntu24.04`, `debian12`) to auto-download and checksum-verify the official upstream cloud image, or a path to a qcow2 you already have.
- Output format: qcow2 (default) or raw, selectable via `output_format` in the build request. Every artifact ships with a `.sha256` checksum sidecar and a `metadata.json` provenance file.
- Guest access via a per-build ephemeral SSH keypair injected through a cloud-init NoCloud seed ISO — key-only auth, no password ever set.
- `GET /api/builder/jobs/{job_id}/artifact` and `.../artifact.sha256` — download routes for the built image (the first downloadable-file artifact type; every other provider's artifact is a cloud-native reference like an AMI ID).
- Requires system packages (not pip): `qemu-system-x86`, `qemu-utils`, and either `cloud-image-utils` (`cloud-localds`) or `genisoimage`.

### Fixed

**Ansible-Lockdown integration — affects every provider, not just the new `kvm` one:**

- Galaxy role identifiers in `_provider_utils.py`'s OS→role map used the ansible-lockdown GitHub repo name/casing (e.g. `UBUNTU22-CIS`) instead of the actual installable Galaxy package name (`ubuntu22_cis`) — `ansible-galaxy install` was failing with "role not found" for every OS. Debian 12 is a particularly non-obvious case: the Galaxy name is `deb12_cis`, not `debian12_cis`. `os_catalog.py`'s `lockdown_roles` field (used by the Builder wizard UI) had the same bug.
- Several ansible-lockdown roles mix git tag formats (`V1.0.0` alongside `1.1.0`), which made `ansible-galaxy install <role>` with no version qualifier fail outright trying to resolve "latest". Now pins a known-good version for each auto-resolved role.
- `_provider_utils.run_remote_cmd`'s error message only included the command's stderr, but most callers redirect stderr into stdout (`... 2>&1`) — failures were reported with an empty, useless message. Now includes both streams.
- `install_oscap_on_remote` bundled `openscap-scanner` with `scap-security-guide` (the RHEL/Fedora package name — doesn't exist for Debian/Ubuntu) and `ssg-debderived` (doesn't exist at all) into the same `apt-get install` call, failing the entire install even where `openscap-scanner` itself is available (Debian 12, Ubuntu 24.04+). Now installs it alone on Debian-family targets.

All four were found by actually running a full build end-to-end against a local KVM guest rather than relying on mocked tests alone.

**Known gap, not yet fixed:** Ubuntu 22.04 has no `openscap-scanner` package via apt in any channel (it first appears in 24.04), and getting real SCAP content (the XCCDF datastream files) onto any Debian-family target still needs a separate fix (no distro package reliably provides it) — tracked in `CONTRIBUTING.md`. Ansible-Lockdown hardening itself is unaffected on any OS; only the OpenSCAP scan step is.

---

## [0.4.0] — 2026-07-05

### Added

**Cloud Onboarding**

- AWS: `POST /api/integrations/aws/import-stack` imports a CloudFormation
  stack's outputs (role ARN, ExternalId, instance profile) directly into the
  credential store — no manual copy-paste of onboarding template outputs.
  Onboarding CloudFormation templates are served locally at
  `GET /api/integrations/aws/templates/{template_name}` instead of linking out.
- Azure and GCP onboarding flows (role/service-account templates, onboarding
  scripts under `deploy/azure/`, `deploy/gcp/`).
- Default `ExternalId` and trusted-principal handling for AWS onboarding.
- Community blueprint library (`blueprints/`) covering Alma, Rocky, Debian,
  Ubuntu, and Amazon Linux across CIS profiles and providers.

### Fixed

- Public-facing docs, the README, and generated SARIF compliance reports no
  longer reference the private development repository — all point at
  `github.com/StratumOSS/Stratum`.
- `POST /api/pipeline/build` no longer 500s when a `region` override is
  supplied (`TargetSpec` has no `region` field; the value is now recorded on
  the job for display instead of an invalid attribute assignment).
- AI Builder agent: `start_build` now updates the job it already created
  instead of silently starting an unrelated one under a different id.

### Security

- Every API/UI router now requires authentication (an admin token via HTTP
  Basic, or an API key) except `/health` and the already-authenticated
  `/api/pipeline` — previously most routes, including the one returning raw
  stored cloud credentials, had none.
- Fixed a path-traversal bug in blueprint upload that allowed writing
  attacker-controlled file content to an arbitrary path on disk.
- Added SSRF protection for webhook registration and delivery (blocks
  loopback/private/link-local/metadata addresses).
- The credential store's encryption key is now derived with a random,
  per-install salt instead of a fixed constant shared by every deployment;
  existing installs migrate automatically on next load.
- Proxmox TLS certificate verification is now a visible, configurable option
  instead of being silently hardcoded off.
- Added a request size cap on blueprint YAML uploads.
- The AI Builder agent now requires explicit confirmation before provisioning
  real cloud infrastructure by default (`STRATUM_AGENT_REQUIRE_CONFIRMATION`).

### Community

- Added `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue templates, and a PR
  template.
- Added `authors`, `classifiers`, and `[project.urls]` to `pyproject.toml`.

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

## [0.1.0] — 2026-03-15

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
