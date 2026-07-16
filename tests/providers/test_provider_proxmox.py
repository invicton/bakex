# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Proxmox provider unit tests — proxmoxer mocked, no live VE required."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROXMOX_PATH = Path(__file__).parent.parent.parent / "plugins" / "providers" / "proxmox.py"


def _load_proxmox():
    mock_proxmoxer = MagicMock()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        spec = importlib.util.spec_from_file_location("proxmox_provider", _PROXMOX_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod, mock_proxmoxer


@pytest.fixture(scope="module")
def proxmox():
    mod, _ = _load_proxmox()
    return mod


_REQUIRED_CREDS = {
    "host": "proxmox.lab.local",
    "user": "root@pam",
    "password": "securepassword",
    "node": "pve",
    "storage": "local-lvm",
}


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


def test_provider_name_is_proxmox(proxmox):
    assert proxmox.PROVIDER_NAME == "proxmox"


def test_dispatch_contains_required_methods(proxmox):
    required = {"test_connection", "execute_build", "execute_audit", "execute_scan_image", "list_images"}
    assert required <= set(proxmox._DISPATCH)


def test_all_dispatch_values_callable(proxmox):
    for _name, fn in proxmox._DISPATCH.items():
        assert callable(fn)


# ---------------------------------------------------------------------------
# _get_proxmox — missing host → ValueError
# ---------------------------------------------------------------------------


def test_get_proxmox_missing_host_raises():
    mod, mock_proxmoxer = _load_proxmox()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        with pytest.raises(ValueError, match="host"):
            mod._get_proxmox({"user": "root@pam", "password": "pass"})


def test_get_proxmox_missing_auth_raises():
    mod, mock_proxmoxer = _load_proxmox()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        with pytest.raises(ValueError, match="password|token"):
            mod._get_proxmox({"host": "proxmox.lab.local", "user": "root@pam"})


def test_get_proxmox_token_auth_accepted():
    mod, mock_proxmoxer = _load_proxmox()
    mock_proxmoxer.ProxmoxAPI.return_value = MagicMock()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        result = mod._get_proxmox(
            {
                "host": "proxmox.lab.local",
                "user": "root@pam",
                "token_name": "statim",
                "token_value": "abc123",
                "verify_ssl": False,
            }
        )
    assert result is not None


@pytest.mark.parametrize(
    ("stored_value", "expected"),
    [
        (False, False),
        ("false", False),  # a stored string "false" must not be truthy
        (True, True),
        ("true", True),
    ],
)
def test_get_proxmox_verify_ssl_coercion(stored_value, expected):
    mod, mock_proxmoxer = _load_proxmox()
    mock_proxmoxer.ProxmoxAPI.return_value = MagicMock()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        mod._get_proxmox(
            {
                "host": "proxmox.lab.local",
                "user": "root@pam",
                "token_name": "statim",
                "token_value": "abc123",
                "verify_ssl": stored_value,
            }
        )
    assert mock_proxmoxer.ProxmoxAPI.call_args.kwargs["verify_ssl"] is expected


# ---------------------------------------------------------------------------
# test_connection — success and failure paths
# ---------------------------------------------------------------------------


def test_test_connection_missing_host_raises():
    mod, mock_proxmoxer = _load_proxmox()
    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        with pytest.raises(ValueError, match="host"):
            mod.test_connection({"credentials": {"user": "root@pam", "password": "pass"}})


def test_test_connection_success():
    mod, mock_proxmoxer = _load_proxmox()
    mock_px = MagicMock()
    mock_version = MagicMock()
    mock_version.get.return_value = {"version": "8.1", "release": "8"}
    mock_px.version = mock_version
    mock_px.nodes.get.return_value = [{"node": "pve", "status": "online"}]

    with patch.object(mod, "_get_proxmox", return_value=mock_px):
        result = mod.test_connection({"credentials": _REQUIRED_CREDS})

    assert result["status"] == "ok"
    assert "nodes" in result or "node_count" in result


# ---------------------------------------------------------------------------
# execute_build — missing base_image (template VMID) → ValueError
# ---------------------------------------------------------------------------


def test_execute_build_missing_base_image_raises():
    mod, _ = _load_proxmox()
    with pytest.raises(ValueError, match="base_image"):
        mod.execute_build(
            {
                "credentials": _REQUIRED_CREDS,
                "profile_name": "test",
            }
        )


# ---------------------------------------------------------------------------
# execute_audit — missing target_ip / ssh_key → ValueError
# ---------------------------------------------------------------------------


def test_execute_audit_missing_target_ip_raises():
    mod, _ = _load_proxmox()
    with pytest.raises(ValueError, match="target_ip"):
        mod.execute_audit(
            {
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----",
                "credentials": _REQUIRED_CREDS,
            }
        )


def test_execute_audit_missing_ssh_key_raises():
    mod, _ = _load_proxmox()
    with pytest.raises(ValueError, match="ssh_key"):
        mod.execute_audit(
            {
                "target_ip": "192.168.1.100",
                "credentials": _REQUIRED_CREDS,
            }
        )


# ---------------------------------------------------------------------------
# execute_scan_image — missing image_id (template VMID) → ValueError
# ---------------------------------------------------------------------------


def test_execute_scan_image_missing_image_id_raises():
    mod, _ = _load_proxmox()
    with pytest.raises(ValueError, match="image_id"):
        mod.execute_scan_image({"credentials": _REQUIRED_CREDS})


# ---------------------------------------------------------------------------
# _next_vmid — returns integer
# ---------------------------------------------------------------------------


def test_next_vmid_returns_integer(proxmox):
    mock_px = MagicMock()
    mock_cluster = MagicMock()
    mock_cluster.nextid.get.return_value = 150
    mock_px.cluster = mock_cluster
    result = proxmox._next_vmid(mock_px)
    assert isinstance(result, int)
    assert result == 150


# ---------------------------------------------------------------------------
# _wait_task — success / failure / timeout
# ---------------------------------------------------------------------------


def test_wait_task_success(proxmox):
    mock_px = MagicMock()
    mock_node_tasks = MagicMock()
    mock_node_tasks.status.get.return_value = {"status": "stopped", "exitstatus": "OK"}
    mock_px.nodes.return_value.tasks.return_value = mock_node_tasks

    with patch("time.time", side_effect=[0, 1]):
        with patch("time.sleep"):
            proxmox._wait_task(mock_px, "pve", "UPID:pve:task123", timeout=60)


def test_wait_task_failure_raises(proxmox):
    mock_px = MagicMock()
    mock_node_tasks = MagicMock()
    mock_node_tasks.status.get.return_value = {"status": "stopped", "exitstatus": "ERROR"}
    mock_px.nodes.return_value.tasks.return_value = mock_node_tasks

    with patch("time.time", side_effect=[0, 1]):
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="failed"):
                proxmox._wait_task(mock_px, "pve", "UPID:pve:task456", timeout=60)


def test_wait_task_timeout_raises(proxmox):
    mock_px = MagicMock()
    mock_node_tasks = MagicMock()
    mock_node_tasks.status.get.return_value = {"status": "running"}
    mock_px.nodes.return_value.tasks.return_value = mock_node_tasks

    with patch("time.time", side_effect=[0, 9999]):
        with patch("time.sleep"):
            with pytest.raises((TimeoutError, RuntimeError)):
                proxmox._wait_task(mock_px, "pve", "UPID:pve:running", timeout=1)


# ---------------------------------------------------------------------------
# main() — unknown method / malformed JSON
# ---------------------------------------------------------------------------


def test_main_unknown_method_returns_error(capsys):
    mod, _ = _load_proxmox()
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
    mod, _ = _load_proxmox()
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "this is not json"
        with pytest.raises(SystemExit) as exc:
            mod.main()
    assert exc.value.code == 1
    response = json.loads(capsys.readouterr().out)
    assert response["error"]["code"] == -32700
