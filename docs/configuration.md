# Configuration

All configuration is via environment variables (or a `.env` file, read
automatically on startup). Copy [`.env.example`](../.env.example) to `.env`
and set what you need — every value is optional with a safe default.

## Core

| Variable | Default | Purpose |
|---|---|---|
| `BAKEX_ADMIN_TOKEN` | auto-generated | Login for the UI and API (HTTP Basic — any username, this as the password). If unset, a random token is generated on first startup and saved to `data/.admin_token`; check there (or the container logs) to log in. Set it explicitly for a stable login. |
| `BAKEX_SECRET_KEY` | auto-generated | Passphrase for the credential-encryption key (Fernet). If unset, a random key is stored in `data/.bakex_key`. Set it so onboarded cloud credentials survive container rebuilds. |
| `BAKEX_AGENT_REQUIRE_CONFIRMATION` | `true` | Require a human click before the AI Builder provisions real cloud infrastructure. |
| `DATA_DIR` | `data/` | Credential store, scan results, API keys. |
| `PLUGINS_DIR` | `plugins/providers` | Installed provider plugins. |
| `PROFILES_DIR` | `profiles/` | Blueprint YAML search path. Pip installs fall back to the templates bundled in the package when this directory doesn't exist. |
| `DEBUG` | `false` | Verbose logging. |

## AI Builder — LLM backends

The AI Builder is LLM-agnostic; all backends implement the same interface.
Pick one via `BAKEX_LLM_PROVIDER`:

| Provider | `BAKEX_LLM_PROVIDER` | Auth | Notes |
|---|---|---|---|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Default; extended thinking on by default |
| OpenAI / compatible | `openai` | `BAKEX_LLM_API_KEY` | Groq, Together, vLLM, LiteLLM, Fireworks |
| Ollama | `ollama` | none | Air-gapped local inference |
| AWS Bedrock | `bedrock` | EC2 role / IRSA / STS | No separate key; needs `bedrock:InvokeModelWithResponseStream` |

Common settings:

```bash
BAKEX_LLM_PROVIDER=anthropic   # anthropic | openai | ollama | bedrock
BAKEX_LLM_MODEL=               # override the backend's default model
BAKEX_LLM_API_KEY=             # for openai-compatible backends
BAKEX_LLM_BASE_URL=            # any OpenAI-compatible endpoint (Ollama: http://localhost:11434/v1)
BAKEX_LLM_THINKING=1           # extended thinking (Anthropic/Bedrock), 1=on 0=off
```

The `openai` and `ollama` backends need the `openai` package
(`uv sync --extra llm-openai`); `bedrock` needs `boto3`
(`uv sync --extra llm-bedrock` — already present with the `aws` extra).

## Blueprint registry

BakeX aggregates blueprints from the community GitHub library, an optional
private S3 store, and the local `profiles/` directory:

```bash
# Private S3 blueprint store (optional; needs boto3)
BLUEPRINT_STORE_S3_BUCKET=my-company-blueprints
BLUEPRINT_STORE_S3_PREFIX=bakex/
BLUEPRINT_STORE_S3_REGION=us-east-1
```

## System dependencies for real builds

BakeX itself is pure Python, but hardening and scanning shell out to
system tools on the host (or in the container, where they're preinstalled):

Debian/Ubuntu:

```bash
apt install ansible openssh-client sshpass openscap-scanner
```

RHEL/Rocky/Amazon Linux:

```bash
dnf install ansible openssh-clients sshpass openscap-scanner scap-security-guide
```

Notes:

- Ubuntu 22.04 has no `openscap-scanner` apt package in any channel (it first
  appears in 24.04) — scanning targets running 22.04 relies on BakeX's
  ComplianceAsCode datastream fallback, and the scanner itself must come from
  elsewhere (e.g. build from source). Tracked in
  [CONTRIBUTING.md](../CONTRIBUTING.md).
- Local `kvm` builds additionally need `qemu-system-x86`, `qemu-utils`, and
  either `cloud-image-utils` (`cloud-localds`) or `genisoimage`.
