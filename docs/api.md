# BakeX API Reference

BakeX exposes a FastAPI application for CI/CD and automation. Interactive Swagger documentation is available at `/docs` when the server is running.

## Authentication

Pipeline endpoints require an API key.

```http
X-API-Key: str_<token>
```

API keys are created in **Settings -> API Keys** or through the API key endpoints.

## Core Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check and registered provider list |
| `POST` | `/api/integrations/{provider}` | Save provider credentials/configuration |
| `GET` | `/api/integrations/{provider}` | Read stored provider configuration |
| `POST` | `/api/integrations/{provider}/test` | Test provider connectivity |
| `POST` | `/api/pipeline/scan` | Start a pipeline image scan |
| `GET` | `/api/pipeline/scan/{id}` | Read scan status |
| `POST` | `/api/pipeline/verify/{id}` | Evaluate scan result against a threshold |
| `GET` | `/api/auditor/scan-image/{id}/report?fmt=json` | Export scan report as JSON |
| `GET` | `/api/auditor/scan-image/{id}/report?fmt=sarif` | Export SARIF evidence |
| `POST` | `/api/api-keys` | Create an API key |
| `GET` | `/api/api-keys` | List API keys |
| `DELETE` | `/api/api-keys/{id}` | Revoke an API key |

## The pipeline gate — read this before wiring CI

The three verdict endpoints (`POST /api/pipeline/scan`, `GET /api/pipeline/scan/{id}`,
`POST /api/pipeline/verify/{id}`) return **HTTP 200 by default even when the gate fails**.
The verdict lives in the `passed` field, not the status code. That means the wiring most
people reach for first silently does nothing:

```bash
# WRONG — never fails. `-f` only reacts to HTTP >= 400, and a failed gate returns 200.
curl -sf -X POST "$BAKEX_URL/api/pipeline/scan" -d '...' || exit 1
```

Two correct options. **Parse `.passed`** — works under every version:

```bash
RESULT=$(curl -s -X POST "$BAKEX_URL/api/pipeline/scan" \
  -H "X-API-Key: $BAKEX_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_id\": \"$AMI\", \"pass_threshold\": 75.0, \"severity_threshold\": \"high\"}")

if [ "$(echo "$RESULT" | jq -r '.passed')" != "true" ]; then
  echo "gate failed: $(echo "$RESULT" | jq -c '.threshold_violations')"
  exit 1
fi
```

**Or set `strict`**, which makes the endpoint answer `422` when the gate fails, so `-f` and
`set -e` behave as written. The 422 body is the same verdict object, so `jq` still works:

```bash
curl -sf -X POST "$BAKEX_URL/api/pipeline/scan" \
  -H "X-API-Key: $BAKEX_TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_id\": \"$AMI\", \"strict\": true}" || exit 1
```

`strict` is a body field on `POST /scan` and a query parameter on the two others
(`?strict=true`). It is **opt-in** because the always-200 contract is what v0.6 shipped and
documented; the default is expected to flip in a future minor with a changelog entry. Code
that reads `.passed` is correct either way — prefer it if you want to write this once.

A gate that reports failure and exits 0 is worse than no gate: it produces a green pipeline
and the belief that something was checked.

## Integration Payloads

### AWS

```json
{
  "region": "us-east-1",
  "role_arn": "arn:aws:iam::123456789012:role/BakeXBuilderRole",
  "external_id": "bakex-test-20260503",
  "iam_profile_name": "BakeXBuilderInstanceProfile"
}
```

### Azure

```json
{
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "client_id": "00000000-0000-0000-0000-000000000000",
  "client_secret": "stored-securely-in-bakex",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "resource_group": "bakex-builds",
  "location": "eastus"
}
```

### GCP

```json
{
  "project_id": "my-gcp-project",
  "zone": "us-central1-a",
  "network": "default",
  "subnetwork": "",
  "service_account_email": "bakex-builder@my-gcp-project.iam.gserviceaccount.com"
}
```

Prefer Application Default Credentials or impersonation for GCP. Use `service_account_json` only when user-managed keys are allowed by policy.

## CLI Commands

| Command | Purpose |
|---|---|
| `bakex serve` | Run the web app + API |
| `bakex version` | Print the build version |
| `bakex validate FILE...` | Validate blueprint YAML against the `HardeningBlueprint` schema. `--json` for machine-readable results. Alias: `proof`. |
| `bakex build FILE\|NAME` | Build a hardened image from a blueprint file, or a bundled profile name. `--output-dir DIR`, `--json`. Alias: `bake`. |
| `bakex blueprints` | List the bundled blueprint names `build` accepts. `--json`. Alias: `pantry`. |

### Command aliases

Pre-configuring an image at build time is *baking* (configuring at boot is *frying*), so the
CLI answers to that vocabulary as well as the plain verbs:

| Canonical | Alias |
|---|---|
| `build` | `bake` |
| `validate` | `proof` |
| `blueprints` | `pantry` |

Nothing is renamed — the canonical names are what the docs use and what generated code
should emit. An alias is exactly equivalent: same arguments, same output, same exit code.

## CLI Exit Status Codes

The `bakex` command-line interface uses the following exit codes. Aliases share the exit
codes of the command they resolve to.

| Exit Code | Meaning / Reason |
|---|---|
| `0` | Success — `bakex version`; `bakex serve` graceful termination; `bakex validate` all files valid; `bakex build` job completed; `bakex blueprints` listing produced |
| `1` | Runtime failure — `bakex validate` one or more files invalid; `bakex build` blueprint not found or job failed |
| `2` | Usage error or invalid arguments |

## More Pipeline Examples

See [`docs/pipeline.md`](pipeline.md) for GitHub Actions, GitLab CI, Jenkins, SARIF upload, and Blueprint-as-Code examples.
