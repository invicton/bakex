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

## CLI Exit Status Codes

The `bakex` command-line interface uses the following exit codes:

| Exit Code | Meaning / Reason |
|---|---|
| `0` | Success (e.g., `bakex version`, or `bakex serve` on graceful termination) |
| `2` | Usage error or invalid arguments |

## More Pipeline Examples

See [`docs/pipeline.md`](pipeline.md) for GitHub Actions, GitLab CI, Jenkins, SARIF upload, and Blueprint-as-Code examples.
