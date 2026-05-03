# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Shared fixtures for AWS integration tests.

These tests make REAL AWS API calls. They require:

  STRATUM_RUN_INTEGRATION=1          — explicit opt-in gate
  AWS_ACCESS_KEY_ID                  — IAM access key
  AWS_SECRET_ACCESS_KEY              — IAM secret key
  AWS_DEFAULT_REGION                 — target region (default: ap-south-1)
  STRATUM_SUBNET_ID                  — subnet-xxx or vpc-xxx for EC2 launch
  STRATUM_SECURITY_GROUP_ID          — security group for the build instance
  STRATUM_IAM_PROFILE                — EC2 IAM instance profile with SSM + EC2 permissions
  STRATUM_EXPECTED_ACCOUNT           — (optional) expected AWS account ID for validation

Run with:
    STRATUM_RUN_INTEGRATION=1 \
    AWS_ACCESS_KEY_ID=... \
    AWS_SECRET_ACCESS_KEY=... \
    AWS_DEFAULT_REGION=ap-south-1 \
    STRATUM_SUBNET_ID=subnet-... \
    STRATUM_SECURITY_GROUP_ID=sg-... \
    STRATUM_IAM_PROFILE=StratumBuilderRole \
    pytest tests/integration/ -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Gate: skip entire module if opt-in env var is absent
# ---------------------------------------------------------------------------

_INTEGRATION_ENABLED = os.environ.get("STRATUM_RUN_INTEGRATION", "").strip() == "1"

collect_ignore_glob: list[str] = []

if not _INTEGRATION_ENABLED:
    # pytest will still collect the module but every test will be skipped
    pass


def pytest_collection_modifyitems(items, config):
    """Skip all integration tests unless STRATUM_RUN_INTEGRATION=1."""
    if _INTEGRATION_ENABLED:
        return
    skip_marker = pytest.mark.skip(reason="Set STRATUM_RUN_INTEGRATION=1 to run live AWS integration tests")
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# AWS provider script path
# ---------------------------------------------------------------------------

_AWS_SCRIPT = Path(__file__).parent.parent.parent / "plugins" / "providers" / "aws.py"


# ---------------------------------------------------------------------------
# Low-level JSON-RPC caller (real subprocess — no mocks)
# ---------------------------------------------------------------------------


def call_aws_rpc(method: str, params: dict, timeout: int = 900) -> dict:
    """Invoke aws.py via JSON-RPC subprocess and return the result dict.

    Raises RuntimeError on non-zero exit, empty stdout, JSON decode error,
    or a JSON-RPC error response.
    """
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    proc = subprocess.run(
        [sys.executable, str(_AWS_SCRIPT)],
        input=request,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    # Always surface stderr (provider logs) so pytest -s shows them
    if proc.stderr:
        print("\n--- [aws.py stderr] ---")
        print(proc.stderr.rstrip())
        print("--- [end stderr] ---")

    if proc.returncode != 0:
        raise RuntimeError(f"aws.py exited {proc.returncode}:\n{proc.stderr.strip()}")
    if not proc.stdout.strip():
        raise RuntimeError("aws.py produced no stdout")

    response = json.loads(proc.stdout)
    if "error" in response:
        err = response["error"]
        raise RuntimeError(f"JSON-RPC error [{err.get('code')}]: {err.get('message')}")
    return response["result"]


# ---------------------------------------------------------------------------
# Credentials fixture — collected from env, fail fast if missing
# ---------------------------------------------------------------------------


def _require_env(name: str, default: str = "") -> str:
    val = os.environ.get(name, default).strip()
    if not val:
        pytest.fail(
            f"Missing required env var: {name}\nSee tests/integration/conftest.py for the full list of required vars."
        )
    return val


@pytest.fixture(scope="session")
def aws_credentials() -> dict:
    """Return the AWS credential dict read from environment variables."""
    return {
        "aws_access_key_id": _require_env("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": _require_env("AWS_SECRET_ACCESS_KEY"),
        "region": os.environ.get("AWS_DEFAULT_REGION", "ap-south-1").strip(),
        "subnet_id": _require_env("STRATUM_SUBNET_ID"),
        "security_group_id": _require_env("STRATUM_SECURITY_GROUP_ID"),
        "iam_profile_name": _require_env("STRATUM_IAM_PROFILE"),
    }


@pytest.fixture(scope="session")
def aws_region(aws_credentials) -> str:
    return aws_credentials["region"]


@pytest.fixture(scope="session")
def expected_account() -> str:
    """Optional: expected AWS account ID for cross-checking test_connection."""
    return os.environ.get("STRATUM_EXPECTED_ACCOUNT", "").strip()
