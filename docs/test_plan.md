# Stratum Test Plan

**Version:** 0.3.0  
**Date:** 2026-04-09  
**Scope:** All testable layers of the Stratum platform

---

## 1. Current Coverage Baseline

| Test File | Tests | What It Covers |
|---|---|---|
| `test_blueprint.py` | 7 | ComplianceProfile schema, YAML loading, kind validation, metadata defaults |
| `test_scap_parser.py` | 13 | SCAPParser pass/fail counts, exception engine, rule ID mapping, invalid XML |
| `test_openscap_parser.py` | 6 | ARF/XCCDF XML parsing, counts, delta computation (new failures, fixed, unchanged) |
| `test_plugin_loader.py` | 18 | Provider loading, registry singleton, strict mode, name collisions, abstract method enforcement |
| `test_subprocess_provider.py` | 30 | SubprocessProvider lifecycle, `_call_rpc`, `_build_params`, JSON-RPC error handling |
| **Total** | **74** | |

**Coverage gaps:** API layer (zero tests), API key store, webhook dispatcher, pipeline pass/fail logic, SARIF export, playbook generation, OS catalog, auditor grading, and report builder are entirely untested.

---

## 2. Test Layers

### Layer 1 — Unit Tests (extend `tests/`)

These test individual modules in isolation, with no running server and no external calls.

#### 1.1 Blueprint (`test_blueprint.py` — extend)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| BP-01 | Missing required field `stratum_version` | Profile dict without `stratum_version` | `ValidationError` raised |
| BP-02 | Missing required `compliance.datastream` | Profile without `datastream` | `ValidationError` raised |
| BP-03 | `controls` with mixed bool and override object | `{"rule_a": True, "rule_b": {"enabled": False, "justification": "x"}}` | Both parsed correctly |
| BP-04 | `load_profile` on non-YAML file | `.txt` file path | `ValueError` or `ValidationError` |
| BP-05 | All supported OS keys parse | `ubuntu22.04`, `rhel9`, `rocky9`, `debian12` in `target.os` | No validation error |
| BP-06 | All supported providers parse | `aws`, `gcp`, `azure`, `local`, `digitalocean`, `linode` in `target.provider` | No validation error |
| BP-07 | `fail_on_findings` defaults to `False` | Minimal profile without `fail_on_findings` | `profile.compliance.fail_on_findings is False` |
| BP-08 | CIS L1 vs L2 profile IDs are distinct | Two profiles with different `compliance.profile` values | Different `profile` field values |

#### 1.2 SCAP Parser (`test_scap_parser.py` — extend)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| SP-01 | `notchecked` result status | Rule result `notchecked` | Not counted in pass or fail |
| SP-02 | All supported severity levels | Rules with `critical`, `high`, `medium`, `low` | Severity map populated correctly |
| SP-03 | Empty rule list | No `rule-result` elements in XML | `total_rules == 0`, no exception |
| SP-04 | Duplicate rule IDs | Two results for same `idref` | Both processed; counts reflect both |
| SP-05 | `justification` in override is optional | Override `{"enabled": False}` without justification | Parses without error |
| SP-06 | Very long rule ID | 300-character `idref` | Parsed and mapped without truncation |

#### 1.3 OpenSCAP ARF Parser (`test_openscap_parser.py` — extend)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| OP-01 | Malformed XML (truncated) | Incomplete XML string | `Exception` raised, not silent failure |
| OP-02 | Missing `<arf:reports>` element | ARF shell with no reports | Graceful error or empty result |
| OP-03 | Score element missing from ARF | ARF without `<xccdf:score>` | `score` key is `None` or `0.0` |
| OP-04 | Delta with completely different rule sets | Baseline and current have no overlapping rules | `new_failures` and `fixed` populated; `unchanged_failures` empty |
| OP-05 | `score_delta` precision | Scores 85.12345 and 71.98765 | `score_delta` is accurate to 2 decimal places |

#### 1.4 API Key Store (new: `test_api_keys.py`)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| AK-01 | `create_key` returns `str_` prefixed token | `create_key("ci-pipeline")` | Token starts with `str_` |
| AK-02 | Token roundtrips through `verify_key` | Create key, then verify the returned token | `verify_key(token) is True` |
| AK-03 | Wrong token rejected | Verify a token that was never created | `verify_key(bad_token) is False` |
| AK-04 | Revoked key no longer verifies | Create, revoke, then verify | `verify_key` returns `False` |
| AK-05 | `revoke_key` on nonexistent ID | `revoke_key("does_not_exist")` | Returns `False`, no exception |
| AK-06 | `list_keys` does not include hash or plaintext token | `list_keys()` after creating a key | `"hash"` and `"token"` not in returned dicts |
| AK-07 | `last_used` updated on successful verify | Create key, call `verify_key`, check `list_keys` | `last_used` is no longer `None` |
| AK-08 | SHA-256 hash is stored, not plaintext | Read `_keys` dict after `create_key` | `entry["hash"]` is 64-char hex; plaintext absent |

#### 1.5 Webhook Notifications (new: `test_notifications.py`)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| WH-01 | `register_webhook` returns entry with `secret` | `register_webhook("https://x.com/hook", ["scan.complete"])` | Entry dict contains `"secret"` key |
| WH-02 | `list_webhooks` omits `secret` | Register, then list | No `"secret"` in any listed entry |
| WH-03 | `remove_webhook` on nonexistent ID | `remove_webhook("bad_id")` | Returns `False` |
| WH-04 | Invalid event is filtered out on register | `events=["scan.complete", "not.real"]` | Stored entry only contains `"scan.complete"` |
| WH-05 | HMAC-SHA256 signature is correct | Mock `httpx.AsyncClient.post`, capture `X-Stratum-Signature` header | Header matches `hmac.new(secret, body, sha256).hexdigest()` |
| WH-06 | `fire_webhook` only fires to subscribed events | Two webhooks: one for `scan.complete`, one for `build.complete`; fire `scan.complete` | Only first hook receives the POST |
| WH-07 | `fire_webhook` on disabled webhook | Register webhook, set `"enabled": False`, fire | No HTTP POST made |
| WH-08 | `fire_webhook` swallows HTTP errors | Mock `httpx` to raise `ConnectError` | No exception propagates; warning logged |
| WH-09 | Payload includes event name and timestamp | Mock httpx, fire any event | `body["event"]` and `body["timestamp"]` present |

#### 1.6 Playbook Generator (new: `test_playbook_gen.py`)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| PG-01 | CIS L1 profile maps to correct Ansible role | Profile with `cis_level1_server` profile string | Generated playbook includes `ansible-lockdown` CIS L1 role |
| PG-02 | CIS L2 profile maps to distinct role | Profile with `cis_level2_server` | Different role name from L1 |
| PG-03 | STIG profile maps to STIG role | Profile with `stig` in profile string | Role name contains `stig` |
| PG-04 | Disabled controls produce `when: false` tasks | Profile with `controls: {rule_a: false}` | Generated YAML contains `when: false` for `rule_a` |
| PG-05 | Generated playbook is valid YAML | Any profile | `yaml.safe_load()` succeeds without error |
| PG-06 | OS-specific variables injected | Ubuntu 22.04 profile | Playbook vars include Ubuntu-specific package names |

#### 1.7 Pipeline Pass/Fail Logic (new: `test_pipeline.py` — unit)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| PL-01 | Score above threshold → passed | `score_pct=80`, `pass_threshold=75` | `passed=True` |
| PL-02 | Score below threshold → failed | `score_pct=60`, `pass_threshold=75` | `passed=False` |
| PL-03 | High severity finding → failed even at 100% score | `score_pct=100`, `severity_counts={"high": 1}`, `severity_threshold="high"` | `passed=False` |
| PL-04 | Medium finding below high threshold → passed | `severity_counts={"medium": 5}`, `severity_threshold="high"` | `passed=True` |
| PL-05 | `threshold_violations` lists exact failing severities | High and critical findings, threshold at high | `["critical", "high"]` in `threshold_violations` |
| PL-06 | Default thresholds produce consistent output | No thresholds specified | Uses `pass_threshold=75.0`, `severity_threshold="high"` |

#### 1.8 SARIF Export (new: `test_sarif.py`)

| ID | Test Case | Input | Expected |
|---|---|---|---|
| SA-01 | Output is valid SARIF 2.1.0 | Completed `AuditJob` with findings | `result["version"] == "2.1.0"` and `"$schema"` present |
| SA-02 | Only `fail` findings are exported | Mix of pass/fail/approved_exception findings | SARIF results contain only `fail` items |
| SA-03 | `approved_exception` findings excluded | Finding with status `approved_exception` | Not present in SARIF results |
| SA-04 | Severity mapped correctly | Findings with `critical`, `high`, `medium`, `low` | Maps to `error`, `error`, `warning`, `note` |
| SA-05 | Duplicate rule IDs deduplicated in rules list | Two findings with same `rule_id` | Only one entry in `runs[0].tool.driver.rules` |
| SA-06 | ARF format findings (rules list) also exported | Job with `results["rules"]` instead of `results["findings"]` | SARIF still generated correctly |
| SA-07 | Empty findings produces valid SARIF with empty results | Job with no findings | `runs[0].results == []` |

---

### Layer 2 — API Integration Tests (new: `tests/api/`)

Use FastAPI's `TestClient` (via `httpx`) with the full app mounted. Mock out `audit_service.run_image_scan` and `audit_service.run_audit` to avoid actual cloud/Ansible calls.

#### 2.1 API Key Endpoints (`test_api_api_keys.py`)

| ID | Endpoint | Test Case | Expected |
|---|---|---|---|
| AK-API-01 | `POST /api/api-keys` | Valid label | `201`, body contains `id`, `label`, `token` |
| AK-API-02 | `POST /api/api-keys` | Empty label `""` | `422` |
| AK-API-03 | `POST /api/api-keys` | Whitespace-only label | `422` |
| AK-API-04 | `GET /api/api-keys` | After creating two keys | `200`, list length == 2, no `token`/`hash` in items |
| AK-API-05 | `DELETE /api/api-keys/{id}` | Valid existing key ID | `204` |
| AK-API-06 | `DELETE /api/api-keys/{id}` | Nonexistent ID | `404` |

#### 2.2 Webhook Endpoints (`test_api_webhooks.py`)

| ID | Endpoint | Test Case | Expected |
|---|---|---|---|
| WH-API-01 | `POST /api/webhooks` | Valid URL and event | `201`, secret in response |
| WH-API-02 | `POST /api/webhooks` | Invalid event name | `422` with valid events listed |
| WH-API-03 | `POST /api/webhooks` | URL not starting with `http://` or `https://` | `422` |
| WH-API-04 | `GET /api/webhooks` | After creating webhook | `200`, secret absent from items |
| WH-API-05 | `DELETE /api/webhooks/{id}` | Valid ID | `204` |
| WH-API-06 | `DELETE /api/webhooks/{id}` | Nonexistent ID | `404` |
| WH-API-07 | `POST /api/webhooks/{id}/test` | Valid ID | `200`, `{"fired": true, "hook_id": id}` |
| WH-API-08 | `POST /api/webhooks/{id}/test` | Nonexistent ID | `404` |

#### 2.3 Auditor Endpoints (`test_api_auditor.py`)

| ID | Endpoint | Test Case | Expected |
|---|---|---|---|
| AU-API-01 | `POST /api/auditor/start` | Valid profile name and host | `200`, `job_id` in response |
| AU-API-02 | `POST /api/auditor/start` | Unknown profile name | `404` |
| AU-API-03 | `GET /api/auditor/jobs` | After creating two audit jobs | `200`, list with both jobs |
| AU-API-04 | `GET /api/auditor/jobs/{id}` | Valid job ID | `200`, job dict with correct fields |
| AU-API-05 | `GET /api/auditor/jobs/{id}` | Nonexistent job ID | `404` |
| AU-API-06 | `GET /api/auditor/scan-image/{id}/report?fmt=json` | Completed scan job | `200`, JSON report |
| AU-API-07 | `GET /api/auditor/scan-image/{id}/report?fmt=sarif` | Completed scan job | `200`, SARIF file download with correct `Content-Disposition` |
| AU-API-08 | `GET /api/auditor/scan-image/{id}/report` | Incomplete job | `400` |
| AU-API-09 | `GET /api/auditor/jobs/{id}/compare/{baseline_id}` | Both jobs complete | `200`, delta with `score_delta`, `new_failures`, `fixed` |
| AU-API-10 | `GET /api/auditor/jobs/{id}/compare/{baseline_id}` | One job not complete | `400` |

#### 2.4 Pipeline Endpoints (`test_api_pipeline.py`)

| ID | Endpoint | Test Case | Expected |
|---|---|---|---|
| PL-API-01 | `POST /api/pipeline/scan` | No API key | `401` |
| PL-API-02 | `POST /api/pipeline/scan` | Invalid API key | `401` |
| PL-API-03 | `POST /api/pipeline/scan` | Valid key, `wait=false` | `200`, job created |
| PL-API-04 | `POST /api/pipeline/scan` | Valid key, unknown profile | `404` |
| PL-API-05 | `POST /api/pipeline/scan` | Key via `Authorization: Bearer` header | `200` (accepted) |
| PL-API-06 | `POST /api/pipeline/scan` | Key via `X-Api-Key` header | `200` (accepted) |
| PL-API-07 | `GET /api/pipeline/scan/{id}` | Valid job ID with API key | `200`, job response |
| PL-API-08 | `GET /api/pipeline/scan/{id}` | No API key | `401` |
| PL-API-09 | `GET /api/pipeline/scans` | Valid API key | `200`, list capped at 100 |
| PL-API-10 | `POST /api/pipeline/verify/{id}` | Completed scan, score 80%, threshold 75% | `200`, `"passed": true` |
| PL-API-11 | `POST /api/pipeline/verify/{id}` | In-progress scan | `400` |

---

### Layer 3 — Provider Contract Tests (new: `tests/providers/`)

Each test uses `unittest.mock.patch` to mock the cloud SDK call. No live cloud credentials required.

#### 3.1 BaseProvider Contract (`test_provider_contract.py`)

| ID | Test Case | Expected |
|---|---|---|
| PC-01 | All four abstract methods exist on `BaseProvider` | `provision`, `run_ansible`, `snapshot`, `teardown` are `abstractmethod` |
| PC-02 | Concrete provider missing one method cannot be instantiated | `TypeError` on instantiation |
| PC-03 | `ProviderResult` requires `artifact_id` and `artifact_type` | `ValidationError` if either missing |
| PC-04 | `ProviderResult.region` is optional | No error when omitted |
| PC-05 | `handles_full_lifecycle` defaults to `False` on class-based providers | `LocalProvider.handles_full_lifecycle is False` |

#### 3.2 Subprocess Provider — Error Paths (extend `test_subprocess_provider.py`)

| ID | Test Case | Expected |
|---|---|---|
| SP-SUB-01 | Script outputs valid JSON but missing `jsonrpc` field | `RuntimeError` raised |
| SP-SUB-02 | Script returns HTTP 200 but empty `result` dict | `RuntimeError` with `artifact_id` message |
| SP-SUB-03 | `artifact_type` missing from result | `RuntimeError` raised |
| SP-SUB-04 | Very large JSON payload (1 MB response) | Parsed correctly without truncation |

---

### Layer 4 — Security Tests (new: `tests/security/`)

#### 4.1 HMAC Signature Verification (`test_webhook_security.py`)

| ID | Test Case | Expected |
|---|---|---|
| SEC-01 | Tampered payload body changes signature | Computed signature does not match original |
| SEC-02 | Wrong secret produces different signature | `hmac.compare_digest` returns `False` |
| SEC-03 | Signature prefix is `sha256=` | `X-Stratum-Signature` header starts with `sha256=` |

#### 4.2 API Key Security (`test_api_key_security.py`)

| ID | Test Case | Expected |
|---|---|---|
| SEC-04 | Plaintext token never stored in `_keys` dict | After `create_key`, no value in `_keys` equals the raw token |
| SEC-05 | `list_keys()` response contains no `hash` field | `"hash"` key absent from all items |
| SEC-06 | Token with `str_` prefix stripped before hash (negative test) | Verify `"str_" + token[4:]` fails — only exact token is valid |
| SEC-07 | Brute-forced short token rejected | 8-char random string does not verify |

#### 4.3 Blueprint Input Sanitization (`test_blueprint_security.py`)

| ID | Test Case | Expected |
|---|---|---|
| SEC-08 | Shell metacharacters in `base_image` | `; rm -rf /` in `base_image` — Pydantic accepts it as string (sanitization is provider responsibility) |
| SEC-09 | Path traversal in `datastream` | `../../etc/passwd` — accepted as string; provider/scanner must validate |
| SEC-10 | Null bytes in `metadata.name` | `ValidationError` or stripped silently; never passed to subprocess |

---

### Layer 5 — Regression / Smoke Tests

These run on every CI commit against a locally running instance (no cloud).

| ID | Test Case | Tool | Expected |
|---|---|---|---|
| REG-01 | App starts without error | `uvicorn stratum.main:app` | Process exits 0 within 5 seconds of startup check |
| REG-02 | `GET /` returns 200 | `httpx` | Status 200, HTML body |
| REG-03 | `GET /api/auditor/jobs` returns empty list on fresh start | `httpx` | `[]` |
| REG-04 | `GET /api/api-keys` returns empty list on fresh start | `httpx` | `[]` |
| REG-05 | Example profile loads without error | `load_profile("profiles/examples/ubuntu22_cis_l1.yaml")` | No exception |
| REG-06 | `local` provider loads from `plugins/providers` | `load_providers(Path("plugins/providers"))` | `"local"` in result |
| REG-07 | `aws` and `digitalocean` subprocess providers load | Same call as above | Both present with `handles_full_lifecycle=True` |

---

## 3. Test Infrastructure

### Framework & Libraries

```
pytest >= 8.2
pytest-anyio          # async test support
httpx                 # FastAPI TestClient
pytest-mock           # unittest.mock integration
respx                 # mock httpx calls (for webhook fire tests)
```

Install additions:
```
pip install pytest-mock respx
```

### Directory Structure

```
tests/
├── __init__.py
├── test_blueprint.py          # existing — extend
├── test_scap_parser.py        # existing — extend
├── test_openscap_parser.py    # existing — extend
├── test_plugin_loader.py      # existing — extend
├── test_subprocess_provider.py # existing — extend
├── test_api_keys.py           # new
├── test_notifications.py      # new
├── test_playbook_gen.py       # new
├── test_pipeline_logic.py     # new (unit — no server)
├── test_sarif.py              # new
├── security/
│   ├── __init__.py
│   ├── test_webhook_security.py
│   ├── test_api_key_security.py
│   └── test_blueprint_security.py
├── api/
│   ├── __init__.py
│   ├── conftest.py            # TestClient fixture, mock audit_service
│   ├── test_api_api_keys.py
│   ├── test_api_webhooks.py
│   ├── test_api_auditor.py
│   └── test_api_pipeline.py
└── providers/
    ├── __init__.py
    └── test_provider_contract.py
```

### Shared Fixtures (`tests/api/conftest.py`)

```python
import pytest
from fastapi.testclient import TestClient
from stratum.main import app
from stratum.core import api_keys

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def api_key(client):
    """Create a real API key and return the token."""
    resp = client.post("/api/api-keys", json={"label": "test"})
    return resp.json()["token"]
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only (fast, no server)
pytest tests/ --ignore=tests/api --ignore=tests/security

# API integration tests
pytest tests/api/

# Security tests
pytest tests/security/

# With coverage
pytest --cov=stratum --cov=plugins --cov-report=term-missing
```

---

## 4. Coverage Targets

| Layer | Current | Target |
|---|---|---|
| `stratum/core/blueprint.py` | ~90% | 95% |
| `stratum/core/parser.py` | ~85% | 95% |
| `stratum/openscap/parser.py` | ~80% | 90% |
| `stratum/plugins/` | ~75% | 90% |
| `stratum/core/api_keys.py` | 0% | 90% |
| `stratum/core/notifications.py` | 0% | 85% |
| `stratum/core/playbook_gen.py` | 0% | 80% |
| `stratum/api/auditor.py` | 0% | 80% |
| `stratum/api/pipeline.py` | 0% | 85% |
| `stratum/api/api_keys.py` | 0% | 90% |
| `stratum/api/webhooks.py` | 0% | 85% |
| **Overall** | **~35%** | **80%** |

---

## 5. What Is Out of Scope

- **Live cloud provider calls** — AWS, GCP, Azure, Linode, DigitalOcean, Proxmox require real credentials and billable resources. These belong in a separate manual/staging test suite, not CI.
- **Live Ansible-Lockdown execution** — Requires a real target VM. Test via subprocess provider mock instead.
- **Live OpenSCAP binary** — Use pre-generated ARF XML fixtures rather than invoking `oscap`.
- **UI / browser tests** — The Jinja2 templates render HTML; full Playwright/Selenium E2E tests are deferred until the UI stabilizes.
- **AI Agent** (`stratum/core/agent.py`) — Requires a live Anthropic API key and produces non-deterministic output. Test prompt construction and context building only; mock the `anthropic` client.
