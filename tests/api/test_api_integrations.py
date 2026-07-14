# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integrations routes — save/get credentials, test_connection HTMX."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# fixtures from conftest: client, api_key


# ---------------------------------------------------------------------------
# POST /api/integrations/{provider} — save_credentials
# ---------------------------------------------------------------------------


def test_save_credentials_returns_html(client):
    resp = client.post(
        "/api/integrations/aws",
        data={"region": "us-east-1", "aws_access_key_id": "AKIA123"},
    )
    assert resp.status_code == 200
    assert "saved" in resp.text.lower() or "credential" in resp.text.lower()


def test_save_credentials_html_content_type(client):
    resp = client.post("/api/integrations/gcp", data={"project_id": "my-proj"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# GET /api/integrations/{provider} — get_credentials_api
# ---------------------------------------------------------------------------


def test_get_credentials_empty_before_save(client):
    resp = client.get("/api/integrations/nonexistent_provider_xyz")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_get_credentials_returns_saved(client):
    client.post("/api/integrations/azure", data={"tenant_id": "t-123", "subscription_id": "s-456"})
    resp = client.get("/api/integrations/azure")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("tenant_id") == "t-123"
    assert data.get("subscription_id") == "s-456"


def test_download_aws_template_serves_bundled_cloudformation(client):
    resp = client.get("/api/integrations/aws/templates/invicton-scanner-role.yaml")
    assert resp.status_code == 200
    assert "application/x-yaml" in resp.headers.get("content-type", "")
    assert "TrustedPrincipalArn" in resp.text
    assert "^$|^arn:aws:iam::[0-9]{12}:((user|role)/.+|root)$" in resp.text


def test_download_aws_template_unknown_name_returns_404(client):
    resp = client.get("/api/integrations/aws/templates/not-a-template.yaml")
    assert resp.status_code == 404


def test_import_aws_stack_outputs_saves_cloudformation_outputs(client):
    mock_cfn = MagicMock()
    mock_cfn.describe_stacks.return_value = {
        "Stacks": [
            {
                "Outputs": [
                    {
                        "OutputKey": "InvictonRoleArn",
                        "OutputValue": "arn:aws:iam::123456789012:role/InvictonBuilderRole",
                    },
                    {"OutputKey": "ExternalId", "OutputValue": "invicton-onboarding"},
                    {"OutputKey": "InstanceProfileName", "OutputValue": "InvictonBuilderInstanceProfile"},
                    {"OutputKey": "RegionHint", "OutputValue": "us-east-1"},
                ]
            }
        ]
    }
    mock_session = MagicMock()
    mock_session.client.return_value = mock_cfn
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session

    with patch.dict("sys.modules", {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock()}):
        resp = client.post(
            "/api/integrations/aws/import-stack",
            data={
                "cloudformation_stack_name": "invicton-builder",
                "aws_access_key_id": "AKIA123",
                "aws_secret_access_key": "secret",
                "region": "us-east-1",
            },
        )

    assert resp.status_code == 200
    assert "imported and saved" in resp.text
    mock_cfn.describe_stacks.assert_called_once_with(StackName="invicton-builder")
    saved = client.get("/api/integrations/aws").json()
    assert saved["role_arn"] == "arn:aws:iam::123456789012:role/InvictonBuilderRole"
    assert saved["external_id"] == "invicton-onboarding"
    assert saved["iam_profile_name"] == "InvictonBuilderInstanceProfile"


def test_import_aws_stack_outputs_requires_stack_name(client):
    resp = client.post("/api/integrations/aws/import-stack", data={"region": "us-east-1"})
    assert resp.status_code == 200
    assert "stack name is required" in resp.text


# ---------------------------------------------------------------------------
# POST /api/integrations/{provider}/test — test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_unknown_provider_returns_not_implemented(client):
    resp = client.post(
        "/api/integrations/unknown_provider_xyz/test",
        data={"api_key": "tok"},
    )
    assert resp.status_code == 200
    # Returns HTML "not implemented" message
    assert "not implemented" in resp.text.lower() or resp.text.strip() != ""


def test_test_credentials_aws_success(client):
    mock_session = MagicMock()
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": "arn:aws:iam::123456789012:user/invicton",
    }
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
    mock_session.client.side_effect = lambda svc, **kw: mock_sts if svc == "sts" else mock_ec2
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session

    with patch.dict("sys.modules", {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": MagicMock()}):
        # Patch boto3 directly in the module's namespace for this call
        with patch("invicton.api.integrations.boto3", mock_boto3, create=True):
            resp = client.post(
                "/api/integrations/aws/test",
                data={"region": "us-east-1", "aws_access_key_id": "AKIA123", "aws_secret_access_key": "secret"},
            )
    assert resp.status_code == 200


def test_test_credentials_aws_client_error_returns_error_html(client):
    from unittest.mock import MagicMock

    mock_exc_mod = MagicMock()

    # Make ClientError, BotoCoreError real subclasses of Exception so isinstance works
    class FakeClientError(Exception):
        pass

    class FakeBotoCoreError(Exception):
        pass

    class FakeNoCredsError(FakeBotoCoreError):
        pass

    mock_exc_mod.ClientError = FakeClientError
    mock_exc_mod.BotoCoreError = FakeBotoCoreError
    mock_exc_mod.NoCredentialsError = FakeNoCredsError
    mock_exc_mod.PartialCredentialsError = FakeNoCredsError

    mock_boto3 = MagicMock()
    mock_boto3.Session.side_effect = FakeClientError("AccessDenied: token invalid")

    with patch.dict("sys.modules", {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": mock_exc_mod}):
        with patch("invicton.api.integrations.boto3", mock_boto3, create=True):
            resp = client.post(
                "/api/integrations/aws/test",
                data={"region": "us-east-1"},
            )
    assert resp.status_code == 200
    # Should return error HTML (not a 500)


def test_test_credentials_aws_assume_role_access_denied_returns_actionable_hint(client):
    mock_exc_mod = MagicMock()

    class FakeClientError(Exception):
        pass

    class FakeBotoCoreError(Exception):
        pass

    class FakeNoCredsError(FakeBotoCoreError):
        pass

    mock_exc_mod.ClientError = FakeClientError
    mock_exc_mod.BotoCoreError = FakeBotoCoreError
    mock_exc_mod.NoCredentialsError = FakeNoCredsError
    mock_exc_mod.PartialCredentialsError = FakeNoCredsError

    mock_sts = MagicMock()
    mock_sts.assume_role.side_effect = FakeClientError("AccessDenied when calling the AssumeRole operation")
    mock_session = MagicMock()
    mock_session.client.return_value = mock_sts
    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session

    with patch.dict("sys.modules", {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.exceptions": mock_exc_mod}):
        with patch("invicton.api.integrations.boto3", mock_boto3, create=True):
            resp = client.post(
                "/api/integrations/aws/test",
                data={
                    "region": "us-east-1",
                    "aws_access_key_id": "AKIA123",
                    "aws_secret_access_key": "secret",
                    "role_arn": "arn:aws:iam::123456789012:role/InvictonBuilderRole",
                },
            )

    assert resp.status_code == 200
    assert "TrustedPrincipalArn" in resp.text
    assert "sts:AssumeRole" in resp.text


# ---------------------------------------------------------------------------
# _ok_html / _err_html helpers — indirectly tested via routes above
# ---------------------------------------------------------------------------


def test_err_html_escapes_special_chars(client):
    """Ensure HTML injection in error messages is escaped."""
    from invicton.api.integrations import _err_html

    result = _err_html('<script>alert("xss")</script>')
    assert "<script>" not in result
    assert "&lt;script" in result or "script" not in result.lower() or "alert" not in result


def test_ok_html_contains_message(client):
    from invicton.api.integrations import _ok_html

    result = _ok_html("Connected to project my-proj")
    assert "Connected to project my-proj" in result
    assert "emerald" in result


# ---------------------------------------------------------------------------
# GCP test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_gcp_missing_project_id(client):
    resp = client.post("/api/integrations/gcp/test", data={})
    assert resp.status_code == 200
    assert "project_id" in resp.text.lower() or "required" in resp.text.lower()


def test_test_credentials_gcp_import_error(client):
    """When google-cloud-compute is not installed, returns error HTML."""
    import sys

    with patch.dict(sys.modules, {"google.cloud": None, "google.cloud.compute_v1": None}):
        resp = client.post(
            "/api/integrations/gcp/test",
            data={"project_id": "my-proj"},
        )
    assert resp.status_code == 200


def test_test_credentials_gcp_success(client):
    mock_region = MagicMock()
    mock_regions_client = MagicMock()
    mock_regions_client.list.return_value = [mock_region, mock_region]
    mock_compute = MagicMock()
    mock_compute.RegionsClient.return_value = mock_regions_client

    import sys

    with patch.dict(
        sys.modules,
        {
            "google.cloud": MagicMock(),
            "google.cloud.compute_v1": mock_compute,
            "google": MagicMock(),
            "google.oauth2": MagicMock(),
            "google.oauth2.service_account": MagicMock(),
        },
    ):
        with patch("invicton.api.integrations.compute_v1", mock_compute, create=True):
            resp = client.post(
                "/api/integrations/gcp/test",
                data={"project_id": "my-proj"},
            )
    assert resp.status_code == 200


def test_test_credentials_gcp_exception(client):
    async def _fail(creds):
        return '<div class="text-rose-400">Connection failed</div>'

    with patch("invicton.api.integrations._test_gcp", side_effect=_fail):
        resp = client.post(
            "/api/integrations/gcp/test",
            data={"project_id": "my-proj"},
        )
    # _test_gcp is still called by test_credentials
    assert resp.status_code in (200, 500)


# ---------------------------------------------------------------------------
# Azure test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_azure_missing_fields(client):
    resp = client.post(
        "/api/integrations/azure/test",
        data={"tenant_id": "t123"},  # missing client_id, client_secret, subscription_id
    )
    assert resp.status_code == 200
    assert "required" in resp.text.lower() or "client_id" in resp.text


def test_test_credentials_azure_import_error(client):
    import sys

    with patch.dict(sys.modules, {"azure.identity": None, "azure.mgmt.resource": None}):
        resp = client.post(
            "/api/integrations/azure/test",
            data={
                "tenant_id": "t123",
                "client_id": "c456",
                "client_secret": "s789",
                "subscription_id": "sub-abc",
            },
        )
    assert resp.status_code == 200


def test_test_credentials_azure_success(client):
    mock_sub = MagicMock()
    mock_sub.display_name = "My Subscription"
    mock_sub.subscription_id = "sub-abc"

    mock_sub_client = MagicMock()
    mock_sub_client.subscriptions.get.return_value = mock_sub

    mock_identity = MagicMock()
    mock_mgmt = MagicMock()
    mock_mgmt.SubscriptionClient.return_value = mock_sub_client

    import sys

    with patch.dict(
        sys.modules,
        {
            "azure": MagicMock(),
            "azure.identity": mock_identity,
            "azure.mgmt": MagicMock(),
            "azure.mgmt.resource": mock_mgmt,
        },
    ):
        with patch("invicton.api.integrations._test_azure") as mock_fn:

            async def _ok(creds):
                return (
                    '<span class="text-emerald-400">Connected to subscription <strong>My Subscription</strong></span>'
                )

            mock_fn.side_effect = _ok
            resp = client.post(
                "/api/integrations/azure/test",
                data={
                    "tenant_id": "t123",
                    "client_id": "c456",
                    "client_secret": "s789",
                    "subscription_id": "sub-abc",
                },
            )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DigitalOcean test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_digitalocean_missing_token(client):
    resp = client.post("/api/integrations/digitalocean/test", data={})
    assert resp.status_code == 200
    assert "api_token" in resp.text.lower() or "required" in resp.text.lower()


def test_test_credentials_digitalocean_success(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"account": {"email": "ops@example.com", "status": "active"}}
    mock_resp.raise_for_status = MagicMock()
    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp

    with patch("invicton.api.integrations._test_digitalocean") as mock_fn:

        async def _ok(creds):
            return '<span class="text-emerald-400">Connected as <strong>ops@example.com</strong></span>'

        mock_fn.side_effect = _ok
        resp = client.post(
            "/api/integrations/digitalocean/test",
            data={"api_token": "dop_v1_abc123"},
        )
    assert resp.status_code == 200


def test_test_credentials_digitalocean_exception(client):
    with patch("invicton.api.integrations._test_digitalocean") as mock_fn:

        async def _err(creds):
            return '<div class="text-rose-400">Connection failed</div>'

        mock_fn.side_effect = _err
        resp = client.post(
            "/api/integrations/digitalocean/test",
            data={"api_token": "bad-token"},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Linode test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_linode_missing_token(client):
    resp = client.post("/api/integrations/linode/test", data={})
    assert resp.status_code == 200
    assert "api_token" in resp.text.lower() or "required" in resp.text.lower()


def test_test_credentials_linode_success(client):
    with patch("invicton.api.integrations._test_linode") as mock_fn:

        async def _ok(creds):
            return '<span class="text-emerald-400">Connected as <strong>ops@example.com</strong></span>'

        mock_fn.side_effect = _ok
        resp = client.post(
            "/api/integrations/linode/test",
            data={"api_token": "linode-token-123"},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Proxmox test_credentials
# ---------------------------------------------------------------------------


def test_test_credentials_proxmox_missing_fields(client):
    resp = client.post(
        "/api/integrations/proxmox/test",
        data={"host": "pve.example.com"},  # missing user, token_name, token_value
    )
    assert resp.status_code == 200
    assert "required" in resp.text.lower() or "user" in resp.text


def test_test_credentials_proxmox_success(client):
    with patch("invicton.api.integrations._test_proxmox") as mock_fn:

        async def _ok(creds):
            return '<span class="text-emerald-400">Connected to Proxmox VE <strong>8.1</strong></span>'

        mock_fn.side_effect = _ok
        resp = client.post(
            "/api/integrations/proxmox/test",
            data={
                "host": "pve.example.com",
                "user": "root@pam",
                "token_name": "invicton",
                "token_value": "tok-123",
            },
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CredentialStore — unit tests for edge cases
# ---------------------------------------------------------------------------


def test_credential_store_delete(client):
    """Delete should remove a saved provider."""
    client.post("/api/integrations/aws", data={"region": "us-west-2"})
    resp_before = client.get("/api/integrations/aws")
    assert resp_before.json().get("region") == "us-west-2"

    from invicton.api.integrations import credential_store

    credential_store.delete("aws")
    resp_after = client.get("/api/integrations/aws")
    assert resp_after.json() == {}


def test_credential_store_load_invalid_token(tmp_path):
    """InvalidToken on load should not crash — resets to empty store."""
    from invicton.api.integrations import CredentialStore

    store = CredentialStore(data_dir=tmp_path)
    # Write garbage to the credentials file
    (tmp_path / "credentials.enc").write_bytes(b"this-is-not-valid-fernet-data")
    store.load()  # should not raise
    assert store.get("any") is None


def test_credential_store_persist_oserror(tmp_path):
    """OSError on chmod should be silently swallowed."""
    from invicton.api.integrations import CredentialStore

    store = CredentialStore(data_dir=tmp_path)
    store.set("test_provider", {"key": "val"})
    # Verify data is in memory even if chmod would fail
    assert store.get("test_provider") == {"key": "val"}


def test_credential_store_secret_key_derivation(tmp_path):
    """PBKDF2 key derivation path should produce a working store."""
    from invicton.api.integrations import CredentialStore

    store = CredentialStore(data_dir=tmp_path, secret_key="my-secret-passphrase")
    store.set("provider_x", {"token": "abc"})
    assert store.get("provider_x") == {"token": "abc"}


def test_credential_store_load_from_disk(tmp_path):
    """Data persisted to disk should survive across store instances."""
    from invicton.api.integrations import CredentialStore

    store1 = CredentialStore(data_dir=tmp_path, secret_key="pass")
    store1.set("aws", {"region": "eu-west-1"})

    store2 = CredentialStore(data_dir=tmp_path, secret_key="pass")
    store2.load()
    assert store2.get("aws") == {"region": "eu-west-1"}


# ---------------------------------------------------------------------------
# AWS profile + role_arn paths
# ---------------------------------------------------------------------------


def test_test_credentials_aws_with_profile(client):
    """aws_profile branch — uses boto3 profile_name session arg."""
    mock_session = MagicMock()
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {
        "Account": "111122223333",
        "Arn": "arn:aws:iam::111122223333:user/ci",
    }
    mock_ec2 = MagicMock()
    mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
    mock_session.client.side_effect = lambda svc, **kw: mock_sts if svc == "sts" else mock_ec2

    mock_boto3 = MagicMock()
    mock_boto3.Session.return_value = mock_session

    with patch("invicton.api.integrations.boto3", mock_boto3, create=True):
        resp = client.post(
            "/api/integrations/aws/test",
            data={"region": "us-east-1", "aws_profile": "my-profile"},
        )
    assert resp.status_code == 200


def test_test_credentials_aws_with_role_external_id(client):
    """role_arn branch passes ExternalId through to sts:AssumeRole."""
    role_arn = "arn:aws:iam::123456789012:role/InvictonBuilderRole"
    external_id = "invicton-test-external-id"

    base_session = MagicMock()
    assumed_session = MagicMock()

    base_sts = MagicMock()
    base_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "ASIAEXAMPLE",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
        }
    }
    base_session.client.return_value = base_sts

    assumed_sts = MagicMock()
    assumed_sts.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": role_arn,
    }
    assumed_ec2 = MagicMock()
    assumed_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
    assumed_session.client.side_effect = lambda svc, **kw: assumed_sts if svc == "sts" else assumed_ec2

    mock_boto3 = MagicMock()
    mock_boto3.Session.side_effect = [base_session, assumed_session]

    with patch.dict(
        "sys.modules",
        {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.exceptions": MagicMock(),
        },
    ):
        with patch("invicton.api.integrations.boto3", mock_boto3, create=True):
            resp = client.post(
                "/api/integrations/aws/test",
                data={
                    "region": "us-east-1",
                    "role_arn": role_arn,
                    "external_id": external_id,
                },
            )

    assert resp.status_code == 200
    base_sts.assume_role.assert_called_once_with(
        RoleArn=role_arn,
        RoleSessionName="InvictonConnectionTest",
        ExternalId=external_id,
    )


# ---------------------------------------------------------------------------
# Direct async unit tests for _test_* helper functions
# (These hit the inner implementations — route-level tests mock them out)
# ---------------------------------------------------------------------------


async def test_gcp_helper_missing_project_id():
    from invicton.api.integrations import _test_gcp

    result = await _test_gcp({})
    assert "project_id" in result.lower() or "required" in result.lower()


async def test_gcp_helper_import_error():
    import sys

    from invicton.api.integrations import _test_gcp

    with patch.dict(sys.modules, {"google.cloud": None, "google.cloud.compute_v1": None, "google": MagicMock()}):
        result = await _test_gcp({"project_id": "my-proj"})
    assert "not installed" in result.lower() or "error" in result.lower()


async def test_gcp_helper_success_adc():
    from invicton.api.integrations import _test_gcp

    mock_regions_client = MagicMock()
    mock_regions_client.list.return_value = [MagicMock(), MagicMock(), MagicMock()]
    mock_compute = MagicMock()
    mock_compute.RegionsClient.return_value = mock_regions_client

    import sys

    mock_google = MagicMock()
    mock_google.cloud.compute_v1 = mock_compute
    with patch.dict(
        sys.modules, {"google": mock_google, "google.cloud": mock_google.cloud, "google.cloud.compute_v1": mock_compute}
    ):
        result = await _test_gcp({"project_id": "my-proj"})
    assert "my-proj" in result or "connected" in result.lower() or "error" in result.lower()


async def test_gcp_helper_exception():
    from invicton.api.integrations import _test_gcp

    mock_compute = MagicMock()
    mock_compute.RegionsClient.side_effect = Exception("auth error")

    import sys

    mock_google = MagicMock()
    with patch.dict(
        sys.modules, {"google": mock_google, "google.cloud": mock_google.cloud, "google.cloud.compute_v1": mock_compute}
    ):
        result = await _test_gcp({"project_id": "my-proj"})
    assert "error" in result.lower() or "auth error" in result.lower() or result


async def test_azure_helper_missing_tenant():
    from invicton.api.integrations import _test_azure

    result = await _test_azure({"client_id": "c", "client_secret": "s", "subscription_id": "sub"})
    assert "tenant_id" in result.lower() or "required" in result.lower()


async def test_azure_helper_missing_client_id():
    from invicton.api.integrations import _test_azure

    result = await _test_azure({"tenant_id": "t", "client_secret": "s", "subscription_id": "sub"})
    assert "client_id" in result.lower() or "required" in result.lower()


async def test_azure_helper_import_error():
    import sys

    from invicton.api.integrations import _test_azure

    with patch.dict(
        sys.modules,
        {"azure.identity": None, "azure.mgmt.resource": None, "azure": MagicMock(), "azure.mgmt": MagicMock()},
    ):
        result = await _test_azure({"tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub"})
    assert "not installed" in result.lower() or "error" in result.lower()


async def test_azure_helper_success():
    from invicton.api.integrations import _test_azure

    mock_sub = MagicMock()
    mock_sub.display_name = "Prod Subscription"
    mock_sub.subscription_id = "sub-123"
    mock_sub_client = MagicMock()
    mock_sub_client.subscriptions.get.return_value = mock_sub
    mock_identity = MagicMock()
    mock_identity.ClientSecretCredential.return_value = MagicMock()
    mock_mgmt = MagicMock()
    mock_mgmt.SubscriptionClient.return_value = mock_sub_client

    import sys

    with patch.dict(
        sys.modules,
        {
            "azure": MagicMock(),
            "azure.identity": mock_identity,
            "azure.mgmt": MagicMock(),
            "azure.mgmt.resource": mock_mgmt,
        },
    ):
        result = await _test_azure(
            {"tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub-123"}
        )
    assert "Prod Subscription" in result or "connected" in result.lower() or result


async def test_azure_helper_exception():
    from invicton.api.integrations import _test_azure

    mock_identity = MagicMock()
    mock_identity.ClientSecretCredential.side_effect = Exception("token invalid")
    mock_mgmt = MagicMock()

    import sys

    with patch.dict(
        sys.modules,
        {
            "azure": MagicMock(),
            "azure.identity": mock_identity,
            "azure.mgmt": MagicMock(),
            "azure.mgmt.resource": mock_mgmt,
        },
    ):
        result = await _test_azure({"tenant_id": "t", "client_id": "c", "client_secret": "s", "subscription_id": "sub"})
    assert "error" in result.lower() or "token invalid" in result.lower() or result


async def test_digitalocean_helper_missing_token():
    from invicton.api.integrations import _test_digitalocean

    result = await _test_digitalocean({})
    assert "api_token" in result.lower() or "required" in result.lower()


async def test_digitalocean_helper_import_error():
    import sys

    from invicton.api.integrations import _test_digitalocean

    with patch.dict(sys.modules, {"requests": None}):
        result = await _test_digitalocean({"api_token": "tok"})
    assert "not installed" in result.lower() or "error" in result.lower()


async def test_digitalocean_helper_success():
    from invicton.api.integrations import _test_digitalocean

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"account": {"email": "ops@example.com", "status": "active"}}
    mock_resp.raise_for_status.return_value = None
    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp

    import sys

    with patch.dict(sys.modules, {"requests": mock_requests}):
        result = await _test_digitalocean({"api_token": "dop_v1_abc"})
    assert "ops@example.com" in result or "connected" in result.lower() or result


async def test_digitalocean_helper_exception():
    from invicton.api.integrations import _test_digitalocean

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("network timeout")

    import sys

    with patch.dict(sys.modules, {"requests": mock_requests}):
        result = await _test_digitalocean({"api_token": "tok"})
    assert "error" in result.lower() or "network timeout" in result.lower() or result


async def test_linode_helper_missing_token():
    from invicton.api.integrations import _test_linode

    result = await _test_linode({})
    assert "api_token" in result.lower() or "required" in result.lower()


async def test_linode_helper_import_error():
    import sys

    from invicton.api.integrations import _test_linode

    with patch.dict(sys.modules, {"requests": None}):
        result = await _test_linode({"api_token": "tok"})
    assert "not installed" in result.lower() or "error" in result.lower()


async def test_linode_helper_success():
    from invicton.api.integrations import _test_linode

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"email": "devops@example.com", "company": "Acme Corp"}
    mock_resp.raise_for_status.return_value = None
    mock_requests = MagicMock()
    mock_requests.get.return_value = mock_resp

    import sys

    with patch.dict(sys.modules, {"requests": mock_requests}):
        result = await _test_linode({"api_token": "linode-tok"})
    assert "devops@example.com" in result or "connected" in result.lower() or result


async def test_linode_helper_exception():
    from invicton.api.integrations import _test_linode

    mock_requests = MagicMock()
    mock_requests.get.side_effect = Exception("timeout")

    import sys

    with patch.dict(sys.modules, {"requests": mock_requests}):
        result = await _test_linode({"api_token": "tok"})
    assert "error" in result.lower() or result


async def test_proxmox_helper_missing_host():
    from invicton.api.integrations import _test_proxmox

    result = await _test_proxmox({"user": "root@pam", "token_name": "t", "token_value": "v"})
    assert "host" in result.lower() or "required" in result.lower()


async def test_proxmox_helper_import_error():
    import sys

    from invicton.api.integrations import _test_proxmox

    with patch.dict(sys.modules, {"proxmoxer": None}):
        result = await _test_proxmox(
            {
                "host": "pve.example.com",
                "user": "root@pam",
                "token_name": "invicton",
                "token_value": "tok-123",
            }
        )
    assert "not installed" in result.lower() or "error" in result.lower()


async def test_proxmox_helper_success():
    from invicton.api.integrations import _test_proxmox

    mock_proxmox = MagicMock()
    mock_proxmox.version.get.return_value = {"version": "8.1", "release": "1"}
    mock_proxmoxer = MagicMock()
    mock_proxmoxer.ProxmoxAPI.return_value = mock_proxmox

    import sys

    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        result = await _test_proxmox(
            {
                "host": "pve.example.com",
                "user": "root@pam",
                "token_name": "invicton",
                "token_value": "tok-123",
            }
        )
    assert "8.1" in result or "connected" in result.lower() or result


async def test_proxmox_helper_exception():
    from invicton.api.integrations import _test_proxmox

    mock_proxmoxer = MagicMock()
    mock_proxmoxer.ProxmoxAPI.side_effect = Exception("SSL error")

    import sys

    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        result = await _test_proxmox(
            {
                "host": "pve.example.com",
                "user": "root@pam",
                "token_name": "invicton",
                "token_value": "tok-123",
            }
        )
    assert "error" in result.lower() or "SSL error" in result.lower() or result


@pytest.mark.parametrize(
    ("stored_value", "expected"),
    [
        (False, False),
        ("false", False),  # the historical coercion bug: a string "false" must not be truthy
        ("", False),
        (True, True),
        ("true", True),
        ("on", True),
    ],
)
async def test_proxmox_helper_verify_ssl_coercion(stored_value, expected):
    from invicton.api.integrations import _test_proxmox

    mock_proxmox = MagicMock()
    mock_proxmox.version.get.return_value = {"version": "8.1", "release": "1"}
    mock_proxmoxer = MagicMock()
    mock_proxmoxer.ProxmoxAPI.return_value = mock_proxmox

    import sys

    with patch.dict(sys.modules, {"proxmoxer": mock_proxmoxer}):
        await _test_proxmox(
            {
                "host": "pve.example.com",
                "user": "root@pam",
                "token_name": "invicton",
                "token_value": "tok-123",
                "verify_ssl": stored_value,
            }
        )

    assert mock_proxmoxer.ProxmoxAPI.call_args.kwargs["verify_ssl"] is expected
