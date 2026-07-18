# BakeX Project Governance

BakeX is an open source project committed to open, vendor-neutral governance. This
document describes how the project is run today and how contributors grow into
maintainers. As the community grows, this governance will evolve — changes to this
document are proposed by PR and decided like any other change.

## Values

- **Openness** — design discussions, decisions, and roadmap live in public
  (issues, PRs, Discussions), not in private channels.
- **Vendor neutrality** — no company, cloud, or product controls project direction;
  features are judged on merit to users, not to any vendor. No feature of BakeX is,
  or will be, gated behind a commercial license.
- **Evidence over claims** — hardening that isn't scanned and graded didn't happen.
  The same bar applies to the project itself: changes ship with tests, and releases
  ship with verifiable signatures and SBOMs.
- **Kindness with honesty** — reviews are direct about problems and generous with
  credit. First-time contributors get the same quality bar and more patience.

## Roles

### Contributor

Anyone who engages with the project: issues, PRs, blueprints, docs, reviews,
Discussions. No sign-up needed — the [contributing guide](CONTRIBUTING.md) is the
on-ramp, and [blueprints/CONTRIBUTING.md](blueprints/CONTRIBUTING.md) is the
fastest first contribution (a blueprint is one YAML file).

### Reviewer

Contributors with a track record of quality contributions (typically 3+ merged
non-trivial PRs) may be invited to be reviewers: they are listed as suggested
reviewers and their review approval carries weight in merge decisions, but they
cannot merge. Reviewers are nominated by a maintainer and recorded in
[MAINTAINERS.md](MAINTAINERS.md).

### Maintainer

Maintainers own overall quality and direction: they triage, review, merge, cut
releases, and speak for the project. Maintainers are listed in
[MAINTAINERS.md](MAINTAINERS.md).

**Becoming a maintainer:** sustained, high-quality contribution over months (code,
blueprints, reviews, and community care all count), nominated by an existing
maintainer and approved by all current maintainers. There is no company
requirement — maintainers join as individuals.

**Stepping down / removal:** maintainers may step down at any time (moved to an
emeritus list with thanks). A maintainer inactive for 6+ months, or acting against
the [Code of Conduct](CODE_OF_CONDUCT.md), may be moved to emeritus by consensus of
the other maintainers.

## Decision making

- **Default: lazy consensus.** Most decisions happen in the PR or issue; silence
  after reasonable review time is consent.
- **Significant changes** (architecture, public API, blueprint schema, compliance
  grading, governance) get an issue or Discussion first so the community can
  weigh in.
- **Disagreements** are resolved by discussion; if consensus fails, maintainers
  decide by simple majority. While the project has a single maintainer, that
  maintainer decides — and this clause is the reason growing the maintainer group
  is an explicit project goal.

## Releases

Releases follow [semantic versioning](https://semver.org) and are cut from `main`
by a maintainer via a `v*` tag. Every release ships a changelog entry, SBOMs, and
signed artifacts (see [SECURITY.md](SECURITY.md)).

## Changes to this document

Propose changes by PR. Governance changes require approval from all current
maintainers and stay open at least one week for community comment.
