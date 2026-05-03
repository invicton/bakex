# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""GCP provider unit tests — google-cloud-compute mocked, no live credentials."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_GCP_PATH = Path(__file__).parent.parent.parent / "plugins" / "providers" / "gcp.py"


def _load_gcp():
    mock_compute = MagicMock()
    mock_sa = MagicMock()
    mocks = {
        "google": MagicMock(),
        "google.cloud": MagicMock(),
        "google.cloud.compute_v1": mock_compute,
        "google.oauth2": MagicMock(),
        "google.oauth2.service_account": mock_sa,
    }
    with patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location("gcp_provider", _GCP_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod, mock_compute, mock_sa


@pytest.fixture(scope="module")
def gcp():
    mod, _, _ = _load_gcp()
    return mod


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


def test_provider_name_is_gcp(gcp):
    assert gcp.PROVIDER_NAME == "gcp"


def test_dispatch_contains_required_methods(gcp):
    required = {"test_connection", "execute_build", "execute_audit", "execute_scan_image", "list_images"}
    assert required <= set(gcp._DISPATCH)


def test_all_dispatch_values_callable(gcp):
    for name, fn in gcp._DISPATCH.items():
        assert callable(fn), f"Dispatch '{name}' must be callable"


# ---------------------------------------------------------------------------
# test_connection — missing project_id → ValueError
# ---------------------------------------------------------------------------


def test_test_connection_missing_project_id_raises():
    mod, mock_compute, _ = _load_gcp()
    with patch.dict(sys.modules, {"google.cloud.compute_v1": mock_compute}):
        with pytest.raises(ValueError, match="project_id"):
            mod.test_connection({"credentials": {}})


def test_test_connection_success():
    mod, mock_compute, _ = _load_gcp()
    mock_instances = MagicMock()
    mock_compute.InstancesClient.return_value = mock_instances

    with patch.dict(sys.modules, {"google.cloud.compute_v1": mock_compute}):
        with patch.object(mod, "_get_compute_client", return_value=(mock_instances, "my-project", "us-central1-a")):
            result = mod.test_connection(
                {
                    "project_id": "my-project",
                    "zone": "us-central1-a",
                }
            )
    assert result["status"] == "ok"
    assert result["project_id"] == "my-project"


def test_get_compute_client_accepts_service_account_json():
    mod, mock_compute, mock_sa = _load_gcp()
    mock_credentials = MagicMock()
    mock_sa.Credentials.from_service_account_info.return_value = mock_credentials

    with patch.dict(
        sys.modules,
        {
            "google.cloud.compute_v1": mock_compute,
            "google.oauth2.service_account": mock_sa,
        },
    ):
        clients = mod._get_compute_client(
            {
                "service_account_json": json.dumps(
                    {
                        "type": "service_account",
                        "project_id": "my-project",
                        "client_email": "stratum@my-project.iam.gserviceaccount.com",
                        "private_key": "-----BEGIN PRIVATE KEY-----\\nredacted\\n-----END PRIVATE KEY-----\\n",
                    }
                )
            }
        )

    assert len(clients) == 5
    mock_sa.Credentials.from_service_account_info.assert_called_once()
    mock_compute.InstancesClient.assert_called_once_with(credentials=mock_credentials)


# ---------------------------------------------------------------------------
# execute_build — missing project_id → ValueError
# ---------------------------------------------------------------------------


def test_execute_build_missing_project_id_raises():
    mod, _, _ = _load_gcp()
    with pytest.raises(ValueError, match="project_id"):
        mod.execute_build({"credentials": {}})


# ---------------------------------------------------------------------------
# execute_audit — missing target_ip / ssh_key → ValueError
# ---------------------------------------------------------------------------


def test_execute_audit_missing_target_ip_raises():
    mod, _, _ = _load_gcp()
    with pytest.raises(ValueError, match="target_ip"):
        mod.execute_audit(
            {
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----",
                "credentials": {"project_id": "p"},
            }
        )


def test_execute_audit_missing_ssh_key_raises():
    mod, _, _ = _load_gcp()
    with pytest.raises(ValueError, match="ssh_key"):
        mod.execute_audit(
            {
                "target_ip": "10.0.0.1",
                "credentials": {"project_id": "p"},
            }
        )


# ---------------------------------------------------------------------------
# execute_scan_image — missing project_id / image_id → ValueError
# ---------------------------------------------------------------------------


def test_execute_scan_image_missing_project_id_raises():
    mod, _, _ = _load_gcp()
    with pytest.raises(ValueError, match="project_id"):
        mod.execute_scan_image(
            {
                "image_id": "projects/ubuntu-os-cloud/global/images/ubuntu-2204",
                "credentials": {},
            }
        )


def test_execute_scan_image_missing_image_id_raises():
    mod, _, _ = _load_gcp()
    with pytest.raises(ValueError, match="image_id"):
        mod.execute_scan_image({"credentials": {"project_id": "my-project"}})


# ---------------------------------------------------------------------------
# main() — unknown method / parse error
# ---------------------------------------------------------------------------


def test_main_unknown_method_returns_error(capsys):
    mod, _, _ = _load_gcp()
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "no_such_method", "params": {}})
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = payload
        with pytest.raises(SystemExit) as exc:
            mod.main()
    assert exc.value.code == 1
    response = json.loads(capsys.readouterr().out)
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_main_malformed_json_returns_parse_error(capsys):
    mod, _, _ = _load_gcp()
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "{{broken json"
        with pytest.raises(SystemExit) as exc:
            mod.main()
    assert exc.value.code == 1
    response = json.loads(capsys.readouterr().out)
    assert response["error"]["code"] == -32700


# ---------------------------------------------------------------------------
# _wait_zone_operation — success / failure / timeout
# ---------------------------------------------------------------------------


def test_wait_zone_operation_success(gcp):
    mock_ops = MagicMock()
    mock_types = MagicMock()
    done_sentinel = object()
    mock_types.Operation.Status.DONE = done_sentinel
    done_op = MagicMock()
    done_op.status = done_sentinel  # op.status == Operation.Status.DONE → True
    done_op.error = None
    mock_ops.get.return_value = done_op
    with patch.dict(
        sys.modules,
        {
            "google.cloud.compute_v1": MagicMock(),
            "google.cloud.compute_v1.types": mock_types,
        },
    ):
        with patch("time.time", side_effect=[0, 1]):
            with patch("time.sleep"):
                gcp._wait_zone_operation(mock_ops, "proj", "zone", "op-123")


def test_wait_zone_operation_failure_raises(gcp):
    mock_ops = MagicMock()
    mock_types = MagicMock()
    done_sentinel = object()
    mock_types.Operation.Status.DONE = done_sentinel
    failed_op = MagicMock()
    failed_op.status = done_sentinel  # op.status == Operation.Status.DONE → True
    err_item = MagicMock()
    err_item.message = "disk not found"
    failed_op.error.errors = [err_item]
    mock_ops.get.return_value = failed_op
    with patch.dict(
        sys.modules,
        {
            "google.cloud.compute_v1": MagicMock(),
            "google.cloud.compute_v1.types": mock_types,
        },
    ):
        with patch("time.time", side_effect=[0, 1]):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError, match="GCP zone operation failed"):
                    gcp._wait_zone_operation(mock_ops, "proj", "zone", "op-err")
