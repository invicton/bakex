# Architecture

How BakeX is put together, and what happens during a build.

## The pipeline

```
HardeningBlueprint (YAML)  ──or──  5-Step Guided Wizard
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  BakeX Engine                                      │
  │                                                      │
  │  1. Provision  →  Spin up a temporary VM             │
  │  2. Harden     →  Apply Ansible-Lockdown CIS/STIG    │
  │  3. Scan       →  Run OpenSCAP, assert compliance    │
  │  4. Snapshot   →  Capture as reusable golden image   │
  │  5. Teardown   →  Remove the ephemeral build VM      │
  └─────────────────────────────────────────────────────┘
        │
        ▼
  Golden Image  (AMI · GCP Custom Image · Azure Managed Image · Snapshot · qcow2)
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │  Compliance Scanner                                  │
  │                                                      │
  │  Scan any image or running VM at any time            │
  │  A–F grade  ·  SARIF export  ·  Drift analysis       │
  │  CI/CD pipeline gate  ·  Webhook notifications       │
  └─────────────────────────────────────────────────────┘
```

## Build pipeline state machine

```
PENDING → PROVISIONING → HARDENING → SCANNING → SNAPSHOTTING → COMPLETE
                                                              ↘ FAILED
```

Each transition emits live log events. The UI polls every 2 seconds via HTMX.
A failed stage always attempts provider teardown so ephemeral build VMs are
not leaked.

## Source tree

```
bakex/
├── api/            11 FastAPI routers (blueprints, builder, auditor, agent, pipeline, …)
├── core/
│   ├── blueprint.py      Pydantic schema: HardeningBlueprint + ComplianceProfile
│   ├── builder.py        5-stage build pipeline state machine
│   ├── auditor.py        Scan orchestration, job persistence, webhook dispatch
│   ├── agent.py          AI Builder: 7 tools, streaming SSE, auto-retry
│   ├── llm/              Pluggable LLM backends (Anthropic, OpenAI, Ollama, Bedrock)
│   ├── parser.py         SCAP rule exception engine
│   ├── openscap/         oscap wrapper + ARF/XCCDF parser
│   ├── playbook_gen.py   Ansible playbook generator (LVM, AIDE, FIPS)
│   ├── registry.py       Multi-source blueprint registry (GitHub + S3 + local)
│   ├── report.py         HTML + SARIF 2.1.0 export
│   └── notifications.py  HMAC-SHA256 signed webhook dispatcher
├── plugins/
│   ├── base_provider.py  Abstract provider contract (4 methods)
│   └── registry.py       Dynamic plugin loader
├── paths.py        Package-anchored template/static/bundled-data paths
├── templates/      Jinja2 + HTMX UI templates
└── config.py       Pydantic settings (reads from .env)

plugins/
├── providers/      Drop-in provider implementations (aws, gcp, azure, kvm, …)
└── catalog/        Installable provider catalog (index.json + scripts)

profiles/
├── templates/      18 ready-to-use HardeningBlueprint YAML files
├── examples/       Minimal reference blueprints
└── user/           User-uploaded blueprints (persisted)

blueprints/         Community blueprint library (contributor surface)
```

## Key design decisions

- **Providers are isolated subprocesses** speaking JSON-RPC over stdin/stdout —
  a misbehaving provider cannot take down the engine, and adding one requires
  no fork of BakeX. See the [Plugin Guide](plugin-guide.md).
- **Blueprints are the single source of truth** — one version-controlled YAML
  file captures OS, provider, compliance tier, per-rule overrides with
  justifications, and system/filesystem/user config. See the
  [Blueprint Guide](blueprint-guide.md).
- **OpenSCAP runs natively** (`oscap xccdf eval`) — no wrappers or
  interpretation layers between you and the scanner output.
- **Credentials are encrypted at rest** (Fernet) and never leave the host;
  see [Configuration](configuration.md).
