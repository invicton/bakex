# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""DigitalOcean provider unit tests — requests library mocked."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DO_PATH = Path(__file__).parent.parent.parent / "plugins" / "providers" / "digitalocean.py"


def _load_do():
    mock_requests = MagicMock()
    with patch.dict(sys.modules, {"requests": mock_requests}):
        spec = importlib.util.spec_from_file_location("do_provider", _DO_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod, mock_requests


@pytest.fixture(scope="module")
def do():
    mod, _ = _load_do()
    return mod


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


def test_provider_name_is_digitalocean(do):
    assert do.PROVIDER_NAME == "digitalocean"


def test_dispatch_contains_required_methods(do):
    required = {"test_connection", "execute_build", "execute_audit", "execute_scan_image", "list_images"}
    assert required <= set(do._DISPATCH)


def test_all_dispatch_values_callable(do):
    for _name, fn in do._DISPATCH.items():
        assert callable(fn)


# ---------------------------------------------------------------------------
# test_connection — empty/missing api_token → ValueError
# ---------------------------------------------------------------------------


def test_test_connection_empty_token_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="api_token"):
        mod.test_connection({"credentials": {"api_token": ""}})


def test_test_connection_missing_token_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="api_token"):
        mod.test_connection({"credentials": {}})


# ---------------------------------------------------------------------------
# test_connection — success path with mocked DOClient
# ---------------------------------------------------------------------------


def test_test_connection_success():
    mod, _ = _load_do()
    mock_client = MagicMock()
    mock_client.get.return_value = {"account": {"email": "user@example.com", "status": "active", "droplet_limit": 25}}
    with patch.object(mod, "DOClient", return_value=mock_client):
        result = mod.test_connection({"credentials": {"api_token": "do-token-abc"}})
    assert result["status"] == "ok"
    assert "email" in result or "account" in str(result)


# ---------------------------------------------------------------------------
# execute_build — missing api_token → ValueError
# ---------------------------------------------------------------------------


def test_execute_build_missing_token_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="api_token"):
        mod.execute_build({"credentials": {}})


# ---------------------------------------------------------------------------
# execute_audit — missing target_ip / ssh_key → ValueError
# ---------------------------------------------------------------------------


def test_execute_audit_missing_target_ip_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="target_ip"):
        mod.execute_audit(
            {
                "ssh_key": "-----BEGIN RSA PRIVATE KEY-----",
                "credentials": {"api_token": "tok"},
            }
        )


def test_execute_audit_missing_ssh_key_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="ssh_key"):
        mod.execute_audit(
            {
                "target_ip": "10.0.0.1",
                "credentials": {"api_token": "tok"},
            }
        )


# ---------------------------------------------------------------------------
# execute_scan_image — missing api_token / image_id → ValueError
# ---------------------------------------------------------------------------


def test_execute_scan_image_missing_token_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="api_token"):
        mod.execute_scan_image(
            {
                "image_id": "123456",
                "credentials": {},
            }
        )


def test_execute_scan_image_missing_image_id_raises():
    mod, _ = _load_do()
    with pytest.raises(ValueError, match="image_id"):
        mod.execute_scan_image({"credentials": {"api_token": "tok"}})


# ---------------------------------------------------------------------------
# DOClient — initialises with token
# ---------------------------------------------------------------------------


def test_do_client_initialises():
    mod, mock_requests = _load_do()
    with patch.dict(sys.modules, {"requests": mock_requests}):
        client = mod.DOClient("my-token")
    assert client is not None


def test_do_client_get_sets_auth_header():
    mod, mock_requests = _load_do()
    mock_session = mock_requests.Session.return_value
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"droplets": []}
    mock_session.get.return_value = mock_resp

    with patch.dict(sys.modules, {"requests": mock_requests}):
        client = mod.DOClient("my-token")
        client.get("/droplets")

    # DOClient sets auth via session.headers.update — verify that call
    update_call = mock_session.headers.update.call_args
    assert update_call is not None
    headers_arg = update_call[0][0]
    assert "Authorization" in headers_arg
    assert "Bearer" in headers_arg["Authorization"]


# ---------------------------------------------------------------------------
# main() — unknown method / malformed JSON
# ---------------------------------------------------------------------------


def test_main_unknown_method_returns_error(capsys):
    mod, _ = _load_do()
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "bad_method", "params": {}})
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = payload
        with pytest.raises(SystemExit) as exc:
            mod.main()
    assert exc.value.code == 1
    response = json.loads(capsys.readouterr().out)
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_main_malformed_json_returns_parse_error(capsys):
    mod, _ = _load_do()
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read.return_value = "{broken"
        with pytest.raises(SystemExit) as exc:
            mod.main()
    assert exc.value.code == 1
    response = json.loads(capsys.readouterr().out)
    assert response["error"]["code"] == -32700
