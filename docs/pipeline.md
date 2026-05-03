# Stratum — Pipeline Integration Guide

Use Stratum as a compliance gate in any CI/CD pipeline. After building a hardened image, scan it automatically and fail the pipeline if it doesn't meet your thresholds.

---

## Prerequisites

1. Stratum is running and reachable from your CI environment (e.g. `http://stratum:8001`)
2. You have at least one compliance profile loaded in `profiles/`
3. You have generated an API key at **Settings → API Keys**

---

## API Key Authentication

All pipeline endpoints require an API key. Pass it as either:

```http
X-API-Key: str_<your-key>
```
```http
Authorization: Bearer str_<your-key>
```

Generate a key from the Stratum UI or via the API:

```bash
curl -s -X POST http://stratum:8001/api/api-keys \
  -H "Content-Type: application/json" \
  -d '{"label": "GitHub Actions — prod"}' \
  | jq '{id, token}'   # token shown once — store in your secrets manager
```

---

## Quick Start

The simplest possible pipeline gate — scan an AMI and fail if it doesn't pass:

```bash
curl -sf -X POST http://stratum:8001/api/pipeline/scan \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "image_id":           "ami-0abc1234",
    "provider":           "aws",
    "region":             "us-east-1",
    "compliance_profile": "ubuntu22-cis-l1-aws",
    "wait":               true
  }' | jq -e '.passed == true'
```

`jq -e` exits non-zero if `.passed` is not `true`, failing the pipeline step.

---

## Request Reference

`POST /api/pipeline/scan`

| Field | Type | Default | Description |
|---|---|---|---|
| `image_id` | string | **required** | AMI ID, GCP image, Azure image URI, etc. |
| `provider` | string | `"aws"` | Provider name: `aws`, `gcp`, `azure`, `digitalocean`, `linode`, `proxmox` |
| `region` | string | `"us-east-1"` | Cloud region |
| `os` | string | `""` | OS slug (e.g. `ubuntu22`). Used for AMI resolution if `image_id` is blank. |
| `compliance_profile` | string | `""` | Profile `metadata.name` from your blueprints directory |
| `instance_type` | string | `"t3.medium"` | Instance type for the temporary scan VM |
| `pass_threshold` | float | `75.0` | Minimum compliance score % to pass |
| `severity_threshold` | string | `"high"` | Minimum severity that causes a failure: `critical`, `high`, `medium`, `low` |
| `wait` | bool | `true` | Block until complete. Set `false` for async (poll with `GET /api/pipeline/scan/{id}`) |
| `timeout_seconds` | int | `900` | Maximum wait time when `wait=true` |

---

## Response Reference

```json
{
  "job_id":               "3f2a1b4c-...",
  "status":               "complete",
  "passed":               true,
  "grade":                "B",
  "score_pct":            82.4,
  "severity_counts": {
    "critical": 0,
    "high":     1,
    "medium":   7,
    "low":      12
  },
  "threshold_violations": [],
  "pass_threshold":       75.0,
  "severity_threshold":   "high",
  "image_id":             "ami-0abc1234",
  "provider":             "aws",
  "region":               "us-east-1",
  "profile":              "ubuntu22-cis-l1-aws",
  "error":                null,
  "report_url":           "http://stratum:8001/api/auditor/scan-image/.../report?fmt=json",
  "sarif_url":            "http://stratum:8001/api/auditor/scan-image/.../report?fmt=sarif",
  "html_report_url":      "http://stratum:8001/api/auditor/scan-image/.../report"
}
```

**`passed`** is `true` when:
- `score_pct >= pass_threshold`, AND
- no findings exist at or above `severity_threshold`

**`threshold_violations`** lists the severity levels that caused a failure (e.g. `["critical", "high"]`).

---

## Triggering Image Builds

Stratum can build the hardened image itself — provision, harden, scan, snapshot — and return the artifact ID directly to your pipeline.

### Quick Build Trigger

```bash
curl -sf -X POST http://stratum:8001/api/pipeline/build \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "profile_name": "ubuntu22-cis-l1-aws",
    "wait":         true
  }' | jq '{status, artifact_id}'
```

When `wait=true`, the call blocks until the image is ready (or fails). Use `wait=false` to get a `job_id` immediately and poll.

### Build Request Reference

`POST /api/pipeline/build`

| Field | Type | Default | Description |
|---|---|---|---|
| `profile_name` | string | **required** | Profile `metadata.name` from your blueprints directory |
| `provider` | string | `""` | Override the profile's provider (`aws`, `gcp`, `azure`, etc.) |
| `region` | string | `""` | Override the profile's region |
| `instance_type` | string | `""` | Override the build instance type |
| `wait` | bool | `true` | Block until complete. Set `false` to get a `job_id` and poll. |
| `timeout_seconds` | int | `1800` | Maximum wait time when `wait=true` |

### Build Response Reference

```json
{
  "job_id":       "a1b2c3d4-...",
  "status":       "complete",
  "profile_name": "ubuntu22-cis-l1-aws",
  "provider":     "aws",
  "artifact_id":  "ami-0abc1234def56789",
  "error":        null,
  "log_tail": [
    "[2026-04-12T10:01:00+00:00] Provisioning via aws",
    "[2026-04-12T10:08:30+00:00] Applying Ansible-Lockdown hardening roles",
    "[2026-04-12T10:22:10+00:00] Snapshotting golden image",
    "[2026-04-12T10:23:05+00:00] Image ready: ami-0abc1234def56789"
  ]
}
```

### Build + Scan in One Pipeline

Build the image, then immediately gate on its compliance score:

```bash
#!/usr/bin/env bash
set -euo pipefail

STRATUM_URL="${STRATUM_URL:-http://stratum:8001}"
STRATUM_API_KEY="${STRATUM_API_KEY:?Set STRATUM_API_KEY}"
PROFILE="${1:-ubuntu22-cis-l1-aws}"

echo "Building $PROFILE ..."
BUILD=$(curl -sf -X POST "$STRATUM_URL/api/pipeline/build" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"profile_name\":\"$PROFILE\",\"wait\":true}")

STATUS=$(echo "$BUILD" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
if [ "$STATUS" != "complete" ]; then
  echo "Build failed: $(echo "$BUILD" | python3 -c "import sys,json; print(json.load(sys.stdin)['error'])")"
  exit 1
fi

ARTIFACT=$(echo "$BUILD" | python3 -c "import sys,json; print(json.load(sys.stdin)['artifact_id'])")
echo "Built: $ARTIFACT"

echo "Scanning $ARTIFACT ..."
curl -sf -X POST "$STRATUM_URL/api/pipeline/scan" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"image_id\":           \"$ARTIFACT\",
    \"provider\":           \"aws\",
    \"compliance_profile\": \"$PROFILE\",
    \"pass_threshold\":     75,
    \"severity_threshold\": \"high\",
    \"wait\":               true
  }" | jq -e '.passed == true'
```

### GitHub Actions — Full Build + Gate

```yaml
name: Hardened Image Build

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 3 * * 1'   # Weekly Monday rebuild

jobs:
  build-and-gate:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Stratum build
        id: build
        env:
          STRATUM_API_KEY: ${{ secrets.STRATUM_API_KEY }}
        run: |
          BUILD=$(curl -sf -X POST ${{ vars.STRATUM_URL }}/api/pipeline/build \
            -H "X-API-Key: $STRATUM_API_KEY" \
            -H "Content-Type: application/json" \
            -d '{"profile_name":"ubuntu22-cis-l1-aws","wait":true}')

          echo "$BUILD" | jq .
          STATUS=$(echo "$BUILD" | jq -r '.status')
          [ "$STATUS" = "complete" ] || (echo "Build failed" && exit 1)

          ARTIFACT=$(echo "$BUILD" | jq -r '.artifact_id')
          echo "artifact_id=$ARTIFACT" >> $GITHUB_OUTPUT

      - name: Compliance gate
        env:
          STRATUM_API_KEY: ${{ secrets.STRATUM_API_KEY }}
          ARTIFACT_ID: ${{ steps.build.outputs.artifact_id }}
        run: |
          curl -sf -X POST ${{ vars.STRATUM_URL }}/api/pipeline/scan \
            -H "X-API-Key: $STRATUM_API_KEY" \
            -H "Content-Type: application/json" \
            -d "{
              \"image_id\":           \"$ARTIFACT_ID\",
              \"provider\":           \"aws\",
              \"compliance_profile\": \"ubuntu22-cis-l1-aws\",
              \"pass_threshold\":     75,
              \"wait\":               true
            }" | jq -e '.passed == true'
```

### Polling a Long Build

For builds that exceed your CI step timeout, use `wait=false` and poll `GET /api/pipeline/build/{id}`:

```bash
JOB_ID=$(curl -sf -X POST "$STRATUM_URL/api/pipeline/build" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"profile_name":"ubuntu22-cis-l1-aws","wait":false}' \
  | jq -r '.job_id')

while true; do
  RESP=$(curl -sf "$STRATUM_URL/api/pipeline/build/$JOB_ID" \
    -H "X-API-Key: $STRATUM_API_KEY")
  STATUS=$(echo "$RESP" | jq -r '.status')
  echo "Build status: $STATUS"
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ] && break
  sleep 60
done

echo "$RESP" | jq '{artifact_id, status, error}'
```

---

## CI/CD Examples

### GitHub Actions

```yaml
name: Build and Compliance Gate

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      ami_id: ${{ steps.build.outputs.ami_id }}
    steps:
      - uses: actions/checkout@v4
      - name: Build hardened AMI
        id: build
        run: |
          AMI=$(./scripts/build.sh)   # your existing build step
          echo "ami_id=$AMI" >> $GITHUB_OUTPUT

  compliance-gate:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Compliance Scan
        env:
          STRATUM_API_KEY: ${{ secrets.STRATUM_API_KEY }}
          AMI_ID: ${{ needs.build.outputs.ami_id }}
        run: |
          RESULT=$(curl -sf -X POST ${{ vars.STRATUM_URL }}/api/pipeline/scan \
            -H "X-API-Key: $STRATUM_API_KEY" \
            -H "Content-Type: application/json" \
            -d "{
              \"image_id\":           \"$AMI_ID\",
              \"provider\":           \"aws\",
              \"region\":             \"us-east-1\",
              \"compliance_profile\": \"ubuntu22-cis-l1-aws\",
              \"pass_threshold\":     75,
              \"severity_threshold\": \"high\",
              \"wait\":               true
            }")

          echo "$RESULT" | jq .

          # Upload SARIF to GitHub Security tab
          SARIF_URL=$(echo "$RESULT" | jq -r '.sarif_url')
          curl -sf "$SARIF_URL" -H "X-API-Key: $STRATUM_API_KEY" > stratum.sarif.json

          # Fail the job if not passed
          echo "$RESULT" | jq -e '.passed == true'

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: stratum.sarif.json
          category: stratum-compliance
```

---

### GitLab CI

```yaml
compliance-scan:
  stage: test
  image: curlimages/curl:latest
  needs: [build-ami]
  script:
    - |
      RESULT=$(curl -sf -X POST "$STRATUM_URL/api/pipeline/scan" \
        -H "X-API-Key: $STRATUM_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{
          \"image_id\":           \"$AMI_ID\",
          \"provider\":           \"aws\",
          \"region\":             \"us-east-1\",
          \"compliance_profile\": \"ubuntu22-cis-l1-aws\",
          \"wait\":               true
        }")
    - echo "$RESULT" | grep -q '"passed":true' || (echo "Compliance gate failed" && exit 1)
  artifacts:
    reports:
      # GitLab doesn't natively render SARIF, but you can archive it
      paths: []
    when: always
```

---

### Jenkins (Declarative Pipeline)

```groovy
pipeline {
  agent any
  stages {
    stage('Compliance Gate') {
      steps {
        script {
          def response = sh(
            script: """
              curl -sf -X POST ${env.STRATUM_URL}/api/pipeline/scan \\
                -H "X-API-Key: ${env.STRATUM_API_KEY}" \\
                -H "Content-Type: application/json" \\
                -d '{"image_id":"${env.AMI_ID}","provider":"aws","compliance_profile":"ubuntu22-cis-l1-aws","wait":true}'
            """,
            returnStdout: true
          ).trim()

          def result = readJSON text: response
          echo "Grade: ${result.grade}  Score: ${result.score_pct}%  Passed: ${result.passed}"

          if (!result.passed) {
            error "Compliance gate failed — grade ${result.grade}, score ${result.score_pct}%"
          }
        }
      }
    }
  }
}
```

---

### Plain Bash / Any CI

```bash
#!/usr/bin/env bash
set -euo pipefail

STRATUM_URL="${STRATUM_URL:-http://stratum:8001}"
STRATUM_API_KEY="${STRATUM_API_KEY:?Set STRATUM_API_KEY}"
AMI_ID="${1:?Pass AMI ID as first argument}"
PROFILE="${2:-ubuntu22-cis-l1-aws}"

echo "Scanning $AMI_ID against $PROFILE ..."

RESULT=$(curl -sf -X POST "$STRATUM_URL/api/pipeline/scan" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"image_id\":           \"$AMI_ID\",
    \"provider\":           \"aws\",
    \"compliance_profile\": \"$PROFILE\",
    \"pass_threshold\":     75,
    \"severity_threshold\": \"high\",
    \"wait\":               true
  }")

GRADE=$(echo "$RESULT"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['grade'])")
SCORE=$(echo "$RESULT"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['score_pct'])")
PASSED=$(echo "$RESULT"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['passed'])")
REPORT=$(echo "$RESULT"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['html_report_url'])")

echo "Grade: $GRADE  Score: $SCORE%"
echo "Report: $REPORT"

if [ "$PASSED" != "True" ]; then
  echo "FAILED: Compliance gate did not pass."
  exit 1
fi

echo "PASSED"
```

---

## Async Mode (Long Builds)

For scans that may take longer than your CI timeout, use `wait=false` and poll:

```bash
# Trigger without waiting
JOB_ID=$(curl -sf -X POST "$STRATUM_URL/api/pipeline/scan" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"image_id":"ami-0abc","compliance_profile":"ubuntu22-cis-l1-aws","wait":false}' \
  | jq -r '.job_id')

# Poll until complete
while true; do
  STATUS=$(curl -sf "$STRATUM_URL/api/pipeline/scan/$JOB_ID" \
    -H "X-API-Key: $STRATUM_API_KEY" | jq -r '.status')
  echo "Status: $STATUS"
  [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ] && break
  sleep 30
done

# Get final result
curl -sf "$STRATUM_URL/api/pipeline/scan/$JOB_ID" \
  -H "X-API-Key: $STRATUM_API_KEY" | jq -e '.passed == true'
```

---

## Webhook Notifications

Register a webhook to receive push notifications instead of polling:

```bash
# Register
curl -X POST "$STRATUM_URL/api/webhooks" \
  -H "Content-Type: application/json" \
  -d '{
    "url":    "https://hooks.slack.com/services/...",
    "label":  "Slack #security",
    "events": ["scan.complete", "scan.failed"]
  }'
```

Verify the payload signature (Python):

```python
import hmac, hashlib

def verify(secret: str, body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

---

## SARIF Integration

Every completed scan exposes a SARIF 2.1.0 endpoint. Upload it to your security dashboard:

**GitHub Advanced Security:**

```bash
# Download SARIF
curl -sf "$SARIF_URL" -H "X-API-Key: $STRATUM_API_KEY" > stratum.sarif.json

# Upload via GitHub API
curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Content-Type: application/sarif+json" \
  --data @stratum.sarif.json \
  "https://api.github.com/repos/$OWNER/$REPO/code-scanning/sarifs"
```

**Azure DevOps:**

Use the [PublishBuildArtifacts task](https://learn.microsoft.com/en-us/azure/devops/pipelines/tasks/reference/publish-build-artifacts-v1) to upload `stratum.sarif.json`, then view it in the Security tab.

---

## Verify an Existing Scan

Re-check a previously completed scan against different thresholds without re-running:

```bash
curl -X POST "$STRATUM_URL/api/pipeline/verify/$JOB_ID?pass_threshold=90&severity_threshold=critical" \
  -H "X-API-Key: $STRATUM_API_KEY" \
  | jq '{passed, grade, score_pct}'
```

---

## Blueprint-as-Code API

Manage blueprints programmatically — upload from CI, validate before committing, build from inline YAML.

### Upload a Blueprint

```bash
curl -sf -X POST http://stratum:8001/api/blueprints/upload \
  -F "file=@ubuntu22-cis-l1-aws.yaml" \
  | jq '{name}'
```

Returns `201` with `{"name": "...", "path": "..."}`. Returns `409` if a blueprint with that `metadata.name` already exists, `422` if the YAML fails schema validation.

### Validate Without Saving

Run the schema check without persisting anything — useful as a pre-commit hook:

```bash
curl -sf -X POST http://stratum:8001/api/blueprints/validate \
  -H "Content-Type: application/yaml" \
  --data-binary @ubuntu22-cis-l1-aws.yaml \
  | jq '{valid, errors}'
```

Returns `{"valid": true, "name": "..."}` or `{"valid": false, "errors": ["..."]}`.

**Pre-commit hook example (`.pre-commit-hooks.yaml`):**

```yaml
- id: stratum-blueprint-validate
  name: Validate Stratum blueprint
  language: system
  entry: bash -c 'curl -sf -X POST http://stratum:8001/api/blueprints/validate
    -H "Content-Type: application/yaml" --data-binary @"$1" | python3 -c
    "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"valid\"] else 1)"'
  files: '^profiles/.*\.ya?ml$'
```

### Build from Inline YAML

Skip the upload step — pass the blueprint YAML directly in the build request:

```bash
curl -sf -X POST http://stratum:8001/api/pipeline/build \
  -H "X-API-Key: $STRATUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"blueprint_yaml\": $(cat ubuntu22-cis-l1-aws.yaml | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
    \"wait\": true
  }" | jq '{status, artifact_id}'
```

When `blueprint_yaml` is set it takes precedence over `profile_name`. Either field is required — the API returns `422` if neither is provided.

### Delete a User Blueprint

Only blueprints you uploaded (in `profiles/user/`) can be deleted. Built-in templates return `403`.

```bash
curl -sf -X DELETE http://stratum:8001/api/blueprints/ubuntu22-cis-l1-aws
# → 204 No Content
```

### Compliance Badge

Embed a live compliance grade badge in your README or dashboard:

```markdown
![Compliance](http://stratum:8001/api/auditor/scan-image/{job_id}/badge.svg)
```

Returns SVG. While the scan is in progress the endpoint returns `202` with a "scanning…" badge — useful for polling. Colours: `A` green, `B` teal, `C` yellow, `D` orange, `F` red.

---

## All Pipeline Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/pipeline/build` | Trigger a hardened image build. `wait=true` blocks until done. |
| `GET` | `/api/pipeline/build/{id}` | Get build job status and artifact ID. |
| `POST` | `/api/pipeline/scan` | Trigger a compliance scan. `wait=true` blocks until done. |
| `GET` | `/api/pipeline/scan/{id}` | Get scan status and result. |
| `POST` | `/api/pipeline/verify/{id}` | Re-verify a scan against new thresholds. |
| `GET` | `/api/pipeline/scans` | List recent scans (newest first, max 100). |
| `POST` | `/api/api-keys` | Create an API key `{"label": "..."}`. |
| `GET` | `/api/api-keys` | List API keys (no token values). |
| `DELETE` | `/api/api-keys/{id}` | Revoke an API key. |
| `POST` | `/api/webhooks` | Register a webhook. |
| `GET` | `/api/webhooks` | List webhooks. |
| `DELETE` | `/api/webhooks/{id}` | Remove a webhook. |
| `POST` | `/api/webhooks/{id}/test` | Fire a test event. |

## Blueprint Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/blueprints/` | List all blueprints (local + user-uploaded). |
| `GET` | `/api/blueprints/{name}` | Get a blueprint by name. |
| `GET` | `/api/blueprints/{name}/download` | Download the YAML file. |
| `POST` | `/api/blueprints/upload` | Upload a blueprint YAML. Validates schema. Returns `409` on duplicate. |
| `POST` | `/api/blueprints/validate` | Validate YAML without saving. Returns `{valid, errors}`. |
| `DELETE` | `/api/blueprints/{name}` | Delete a user-uploaded blueprint. `403` for built-in templates. |
| `GET` | `/api/auditor/scan-image/{id}/badge.svg` | SVG compliance badge for a scan job. |
