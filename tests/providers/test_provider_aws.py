# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""AWS provider unit tests — functions tested with mocked boto3.

No live AWS credentials required. boto3 is injected via sys.modules before import
so the provider module never calls real AWS endpoints.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load aws.py as a module with boto3 mocked before import
# ---------------------------------------------------------------------------

_AWS_PATH = Path(__file__).parent.parent.parent / "plugins" / "providers" / "aws.py"


def _load_aws_module():
    """Import aws.py with a mocked boto3 in sys.modules."""
    mock_boto3 = MagicMock()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        spec = importlib.util.spec_from_file_location("aws_provider", _AWS_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod, mock_boto3


@pytest.fixture(scope="module")
def aws():
    """Return (aws_module, mock_boto3). Module-scoped to avoid re-importing."""
    mod, _ = _load_aws_module()
    return mod


# ===========================================================================
# Module structure
# ===========================================================================


def test_provider_name_is_aws(aws):
    assert aws.PROVIDER_NAME == "aws"


def test_dispatch_contains_required_methods(aws):
    required = {
        "test_connection",
        "execute_build",
        "execute_audit",
        "execute_scan_image",
        "list_images",
        "resolve_image",
    }
    assert required <= set(aws._DISPATCH), f"Missing dispatch methods: {required - set(aws._DISPATCH)}"


def test_all_dispatch_values_are_callable(aws):
    for name, fn in aws._DISPATCH.items():
        assert callable(fn), f"Dispatch entry '{name}' must be callable"


# ===========================================================================
# _lockdown_role_for_os — pure lookup inside aws.py
# ===========================================================================


def test_aws_lockdown_role_ubuntu22(aws):
    role = aws._lockdown_role_for_os("ubuntu22.04")
    assert "UBUNTU22" in role.upper()


def test_aws_lockdown_role_rocky9(aws):
    role = aws._lockdown_role_for_os("rocky9")
    assert "RHEL9" in role.upper()


def test_aws_lockdown_role_unknown_defaults_to_ubuntu22(aws):
    """Unknown OS should not raise — it logs a warning and falls back."""
    role = aws._lockdown_role_for_os("unknownos")
    assert role == "UBUNTU22-CIS"


# ===========================================================================
# test_connection — mocked STS
# ===========================================================================


def test_test_connection_success():
    mod, mock_boto3 = _load_aws_module()

    mock_session = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_sts = MagicMock()
    mock_session.client.return_value = mock_sts
    mock_sts.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": "arn:aws:iam::123456789012:user/bakex",
    }

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        result = mod.test_connection(
            {
                "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
                "aws_secret_access_key": "secret",
                "region": "us-east-1",
            }
        )

    assert result["status"] == "ok"
    assert result["account"] == "123456789012"


def test_test_connection_raises_on_sts_failure():
    mod, mock_boto3 = _load_aws_module()

    mock_session = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_sts = MagicMock()
    mock_session.client.return_value = mock_sts
    mock_sts.get_caller_identity.side_effect = Exception("InvalidClientTokenId")

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        with pytest.raises(ValueError, match="Connection test failed"):
            mod.test_connection({"region": "us-east-1"})


def test_assume_role_uses_external_id():
    mod, mock_boto3 = _load_aws_module()

    base_session = MagicMock()
    assumed_session = MagicMock()
    mock_boto3.Session.side_effect = [base_session, assumed_session]
    mock_sts = MagicMock()
    base_session.client.return_value = mock_sts
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "ASIAEXAMPLE",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
        }
    }

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        session = mod._get_boto_session(
            {
                "role_arn": "arn:aws:iam::123456789012:role/BakeXBuilderRole",
                "external_id": "bakex-test-external-id",
                "region": "us-east-1",
            }
        )

    assert session is assumed_session
    mock_sts.assume_role.assert_called_once_with(
        RoleArn="arn:aws:iam::123456789012:role/BakeXBuilderRole",
        RoleSessionName="BakeXSession",
        DurationSeconds=3600,
        ExternalId="bakex-test-external-id",
    )


# ===========================================================================
# _resolve_ami — mocked ec2.describe_images
# ===========================================================================


def test_resolve_ami_returns_latest(aws):
    mock_ec2 = MagicMock()
    mock_ec2.describe_images.return_value = {
        "Images": [
            {"ImageId": "ami-newer", "CreationDate": "2026-01-02T00:00:00.000Z", "Name": "ubuntu22-newer"},
            {"ImageId": "ami-older", "CreationDate": "2026-01-01T00:00:00.000Z", "Name": "ubuntu22-older"},
        ]
    }
    result = aws._resolve_ami(mock_ec2, "ubuntu22.04", "ami-fallback")
    assert result == "ami-newer"


def test_resolve_ami_falls_back_on_empty_results(aws):
    mock_ec2 = MagicMock()
    mock_ec2.describe_images.return_value = {"Images": []}
    result = aws._resolve_ami(mock_ec2, "ubuntu22.04", "ami-fallback")
    assert result == "ami-fallback"


def test_resolve_ami_falls_back_on_exception(aws):
    mock_ec2 = MagicMock()
    mock_ec2.describe_images.side_effect = Exception("AuthFailure")
    result = aws._resolve_ami(mock_ec2, "ubuntu22.04", "ami-fallback")
    assert result == "ami-fallback"


def test_resolve_ami_unknown_os_returns_fallback(aws):
    """OS with no catalog entry must return fallback immediately."""
    mock_ec2 = MagicMock()
    result = aws._resolve_ami(mock_ec2, "archlinux-custom", "ami-fallback-00")
    assert result == "ami-fallback-00"
    mock_ec2.describe_images.assert_not_called()


# ===========================================================================
# execute_scan_image — missing image_id raises ValueError
# ===========================================================================


def test_execute_scan_image_missing_image_id_raises():
    mod, mock_boto3 = _load_aws_module()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        with pytest.raises((ValueError, RuntimeError)):
            mod.execute_scan_image({"region": "us-east-1", "credentials": {}})


# ===========================================================================
# execute_audit — missing target_id raises ValueError
# ===========================================================================


def test_execute_audit_missing_target_id_raises():
    mod, mock_boto3 = _load_aws_module()
    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        with pytest.raises(ValueError, match="target_id"):
            mod.execute_audit({"credentials": {}, "profile": "p", "datastream": "ds"})


# ===========================================================================
# main() JSON-RPC dispatch — unknown method returns error, does not raise
# ===========================================================================


def test_main_unknown_method_returns_jsonrpc_error(capsys):
    mod, mock_boto3 = _load_aws_module()

    rpc_input = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "nonexistent_method", "params": {}})

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = rpc_input
            with pytest.raises(SystemExit) as exc_info:
                mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert "error" in response
    assert response["error"]["code"] == -32601  # Method not found


def test_main_malformed_json_returns_parse_error(capsys):
    mod, mock_boto3 = _load_aws_module()

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not valid json {"
            with pytest.raises(SystemExit) as exc_info:
                mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert "error" in response
    assert response["error"]["code"] == -32700  # Parse error


# ===========================================================================
# _poll_ssm_command — timeout and status transitions
# ===========================================================================


def test_poll_ssm_command_success_on_first_poll(aws):
    mock_ssm = MagicMock()
    mock_ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": "<xml/>",
    }
    with patch("time.time", side_effect=[0, 1]):
        result = aws._poll_ssm_command(mock_ssm, "cmd-001", "i-001", timeout=60)
    assert result["Status"] == "Success"


def test_poll_ssm_command_failed_status_raises(aws):
    mock_ssm = MagicMock()
    mock_ssm.get_command_invocation.return_value = {
        "Status": "Failed",
        "StandardErrorContent": "Something went wrong",
    }
    with patch("time.time", side_effect=[0, 1, 999]):
        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Failed"):
                aws._poll_ssm_command(mock_ssm, "cmd-001", "i-001", timeout=300)


def test_poll_ssm_command_timeout_raises(aws):
    mock_ssm = MagicMock()
    mock_ssm.get_command_invocation.return_value = {"Status": "InProgress"}

    # time.time always returns past deadline
    with patch("time.time", side_effect=[0, 9999]):
        with patch("time.sleep"):
            with pytest.raises(TimeoutError, match="did not complete"):
                aws._poll_ssm_command(mock_ssm, "cmd-001", "i-001", timeout=1)
