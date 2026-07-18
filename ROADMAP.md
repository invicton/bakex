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

- [ ] README restructured as a landing page (≤300 lines); full reference
      material moved to `docs/` with an index
- [ ] Canonical getting-started tutorial (promoted from the AL2023 UX walkthrough)
- [ ] Clean-machine quickstart verified honestly: clone → compose up → local
      `kvm` build → compliance grade, no cloud account required
- [ ] Demo GIF + real screenshots
- [ ] Supply-chain layer: OpenSSF Scorecard workflow (target ≥7), SHA-pinned
      actions, `uv sync --locked` in CI, Python 3.11 + 3.12 matrix, coverage gate
- [ ] Release artifacts: SBOM (syft), keyless signatures (cosign), signed
      container image on GHCR alongside the PyPI package

## v0.7 — Blueprint library depth

The community blueprint library (`blueprints/`) is the main contribution
surface. Depth targets:

- [ ] CIS Level 2 coverage for every OS that supports it
      ([#1](https://github.com/invicton/bakex/issues/1),
      [#2](https://github.com/invicton/bakex/issues/2),
      [#3](https://github.com/invicton/bakex/issues/3))
- [ ] Ubuntu 24.04 blueprints ([#4](https://github.com/invicton/bakex/issues/4))
- [ ] First STIG blueprints ([#7](https://github.com/invicton/bakex/issues/7))
- [ ] New OS support as upstream unblocks: RHEL 10 / Debian 13 / Ubuntu 26.04
      are all currently blocked on missing Ansible-Lockdown roles or CIS
      benchmarks — tracked, re-checked periodically, not promised
- [ ] Centralize the per-OS support matrix (today it lives in six places in the
      codebase; adding an OS should be one edit, not a checklist)

## v0.8 — AI-agent-friendly surface

Hardening pipelines are increasingly driven by AI agents, not just humans and
CI. BakeX should be the OS-hardening tool an agent can operate correctly:

- [ ] **MCP server** — validate blueprints, list templates, start builds,
      poll status, fetch compliance reports/grades from any MCP client
- [ ] Published JSON Schema for `HardeningBlueprint` / `ComplianceProfile`
      (generated from the Pydantic models; enables editor + agent validation)
- [ ] Published OpenAPI reference (replaces the hand-written API doc)
- [ ] `llms.txt` — a machine-oriented map of the project
- [ ] `AGENTS.md` — conventions and gotchas for AI coding agents contributing
      to BakeX itself
- [ ] Error-message audit: every API error specific and machine-actionable
      (house style already; make it a checked standard)

## Ecosystem integration (ongoing, parallel)

- [ ] Upstream-first: fixes contributed to ComplianceAsCode, Ansible-Lockdown,
      and OpenSCAP where the bug belongs upstream
- [ ] GitHub Action for blueprint validation / build triggering in CI
- [ ] `pre-commit` hook for blueprint validation
- [ ] Helm chart for cluster deployment
- [ ] Interop guides: BakeX with Packer, BakeX + Ansible-Lockdown,
      complementing scanners (Wazuh, Lynis)

## v1.0 criteria

Cut only when all of these are true:

1. The blueprint schema is stable (breaking changes require a major version)
2. CIS L1 + L2 verified end-to-end on every supported OS/provider combination
3. At least two active maintainers besides the founder
4. OpenSSF Scorecard ≥ 7 sustained; signed releases the norm for ≥ 3 releases
5. The 10-minute quickstart holds on a clean machine, re-verified each release

## How to influence this roadmap

Open a [Discussion](https://github.com/invicton/bakex/discussions) or an
issue. Good first contributions are labeled
[`good first issue`](https://github.com/invicton/bakex/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
— most are pure-YAML blueprint work with acceptance criteria and a local verify
command included.
