# BakeX Roadmap

BakeX's goal: **the layer that makes Ansible-Lockdown + OpenSCAP + every major
cloud reliable and reviewable as code.** We integrate with the mainstream
hardening ecosystem — we don't compete with it. That means absorbing its rough
edges (Galaxy naming gotchas, SCAP profile-ID surprises, missing distro
packages) so users never discover them, and contributing fixes upstream when
the problem belongs there.

Releases are milestone-based, not calendar-based. Every claim below follows the
house rule: nothing ships as "supported" unless it has been verified end-to-end
against real infrastructure, and every feature lands tests-first.

## v0.6 — Launch release

The "anyone arriving cold succeeds in 10 minutes" release.

- [x] README restructured as a landing page (well under the 300-line target); full
      reference material moved to [`docs/`](docs/)
- [x] Canonical getting-started tutorial ([`docs/getting-started.md`](docs/getting-started.md))
- [x] Release artifacts: SBOM (syft), keyless signatures (cosign), provenance
      attestations, signed container image on GHCR alongside the PyPI package
- [x] Supply-chain CI: OpenSSF Scorecard workflow, SHA-pinned actions,
      `uv sync --locked`, Python 3.11 + 3.12 matrix, coverage gate
- [ ] **Scorecard ≥ 7** — the workflow runs and the badge is live, but the score is
      **5.3**. Remaining gaps are branch protection, least-privilege token permissions,
      and pinned-dependency triage. Tracked separately because the workflow shipping and
      the score passing are two different things.
- [ ] Clean-machine quickstart re-verified each release: clone → compose up → local
      `kvm` build → compliance grade, no cloud account required
- [ ] Demo GIF + real screenshots. The three SVGs in `docs/assets/` are illustrations,
      not captures of a real run — this stays open until they are.

## v0.7 — Blueprint library depth

The community blueprint library (`blueprints/`) is the main contribution
surface. Depth targets:

Where the library actually stands today — 18 blueprints, unevenly distributed:

| OS | In catalog | Blueprints shipped |
|---|---|---|
| Ubuntu 22.04 | yes | 6 (CIS L1, all providers) |
| Rocky 9 | yes | 6 (CIS L1, all providers) |
| Debian 12 | yes | 3 (CIS L1) |
| AlmaLinux 9 | yes | 1 |
| Amazon Linux 2023 | yes | 1 |
| **RHEL 9** | yes | **0** |
| **Ubuntu 24.04** | yes | **0** |

The gap between "the OS is wired" and "a blueprint ships" is the contribution surface —
those two zeroes are pure-YAML work with acceptance criteria already written.

- [ ] CIS Level 2 coverage for every OS that supports it
      ([#1](https://github.com/invicton/bakex/issues/1),
      [#2](https://github.com/invicton/bakex/issues/2),
      [#3](https://github.com/invicton/bakex/issues/3))
- [ ] RHEL 9 blueprints ([#54](https://github.com/invicton/bakex/issues/54),
      [#56](https://github.com/invicton/bakex/issues/56))
- [ ] Ubuntu 24.04 blueprints ([#4](https://github.com/invicton/bakex/issues/4))
- [ ] First STIG blueprints ([#7](https://github.com/invicton/bakex/issues/7))
- [ ] New OS support as upstream unblocks: RHEL 10 / Debian 13 / Ubuntu 26.04 /
      Azure Linux (Mariner) are all currently blocked on missing Ansible-Lockdown roles
      or CIS benchmarks — tracked, re-checked periodically, **not promised**. Adding an
      OS is not a blueprint task; it needs a hardening role and SCAP content to exist
      first.
- [ ] Centralize the per-OS support matrix (today it lives in six places in the
      codebase; adding an OS should be one edit, not a checklist)

## v0.8 — AI-agent-friendly surface

Hardening pipelines are increasingly driven by AI agents, not just humans and
CI. BakeX should be the OS-hardening tool an agent can operate correctly:

- [ ] **MCP server** — validate blueprints, list templates, start builds,
      poll status, fetch compliance reports/grades from any MCP client
- [x] Published JSON Schema for `HardeningBlueprint` / `ComplianceProfile`
      ([`docs/schema/`](docs/schema/), generated from the Pydantic models)
- [x] Published OpenAPI reference — served at `/openapi.json`, `/docs`, `/redoc`
- [x] [`llms.txt`](llms.txt) — a machine-oriented map of the project
- [x] [`AGENTS.md`](AGENTS.md) — conventions and gotchas for AI coding agents
- [ ] Error-message audit: every API error specific and machine-actionable
      (house style already; make it a checked standard)

## v0.9 — Evidence you can hand to an auditor

Grading an image is half the job; the other half is producing evidence that survives leaving
this tool. This is the line between "we ran a scanner" and "here is a signed artifact".

- [ ] **Policy artifact export** — a signed, portable statement of what a blueprint
      asserts, consumable by cluster-side scanners so a running image can be graded
      against the blueprint that built it
      ([#34](https://github.com/invicton/bakex/issues/34))
- [ ] Decide the policy-artifact schema **before** the exporter: align with in-toto
      attestation / SLSA predicate formats rather than inventing one. Cheap to decide
      now, expensive to change later
- [ ] OCI artifact transport — attach the policy artifact alongside the image so
      `cosign verify` covers it
- [ ] Drift detection v2 — continuous re-scan of running instances against the
      artifact, classifying conformant / drifted / never-baked
- [ ] SLSA Build L3 provenance on releases, plus a documented key-rotation runbook

## Platform breadth (as demand appears, not before)

Each of these is real work with a real maintenance cost. They are listed so the direction is
public, and deliberately ungated by date — they follow demand rather than leading it.

- [ ] Multi-arch container images (amd64 + arm64) and a verified arm64 image build
- [ ] Per-blueprint build-time and cost benchmarks, published and refreshed by CI
- [ ] Terraform / Pulumi provider so BakeX can be invoked from existing IaC
- [ ] Plugin SDK stabilization — documented provider interface, versioning policy,
      and a path for community providers to live outside this repo
- [ ] Reusable CI templates beyond GitHub Actions (GitLab CI, Jenkins)
- [ ] Public evidence dashboard: per-blueprint grade plus SARIF/HTML, refreshed weekly

## Ecosystem integration (ongoing, parallel)

- [ ] Upstream-first: fixes contributed to ComplianceAsCode, Ansible-Lockdown,
      and OpenSCAP where the bug belongs upstream
- [x] GitHub Action for blueprint validation — `action.yml` at the repo root, so
      `uses: invicton/bakex@v0.6.0`. Offline, annotates failures on the file, self-tested
      by `.github/workflows/test-action.yml`. Build-triggering deliberately not included:
      it needs a reachable server and credentials, which is a different trust model from
      a validation step and belongs in its own action if anyone asks for it.
- [ ] `pre-commit` hook for blueprint validation
- [ ] Interop guides: BakeX with Packer, BakeX + Ansible-Lockdown,
      complementing scanners (Wazuh, Lynis)

> **Dropped 2026-07-27 — Helm chart for cluster deployment.** BakeX is a build tool that talks
> to cloud APIs; it does not need to run as a cluster workload to harden images *for* one.
> Nothing Helm-shaped ever existed in the repo, and the v0.5 blog series shipped install
> instructions for a chart that was never written. Removed rather than left as implied debt.
> If Kubernetes-native deployment is ever asked for by a real user, reopen it then.

## v1.0 criteria

Cut only when all of these are true:

1. The blueprint schema is stable (breaking changes require a major version)
2. **Public API v1 frozen** — a backward-compatibility contract and a written
   deprecation policy in [`docs/api.md`](docs/api.md)
3. CIS L1 + L2 verified end-to-end on every supported OS/provider combination
4. At least two active maintainers besides the founder
5. OpenSSF Scorecard ≥ 7 sustained; signed releases the norm for ≥ 3 releases
6. An independent security review has been completed and its findings addressed
7. The 10-minute quickstart holds on a clean machine, re-verified each release

Criteria 4 and 6 are the ones that cannot be met by writing more code. If BakeX is useful
to you, the most valuable contribution is not a pull request — it is
[telling us you use it](ADOPTERS.md), or reviewing someone else's blueprint.

## How to influence this roadmap

Open a [Discussion](https://github.com/invicton/bakex/discussions) or an
issue. Good first contributions are labeled
[`good first issue`](https://github.com/invicton/bakex/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
— most are pure-YAML blueprint work with acceptance criteria and a local verify
command included.
