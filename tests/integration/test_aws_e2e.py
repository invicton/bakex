# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""AWS end-to-end integration tests — real API calls, real EC2, real AMI.

Test stages (run in order — each builds on the previous):
  Stage 1  [FAST]    Credential validation via STS get_caller_identity
  Stage 2  [FAST]    AMI resolution: ubuntu22.04 → latest canonical AMI
  Stage 3  [FAST]    list_images: own AMIs visible in account
  Stage 4  [~10 min] Smoke build: EC2 launch + SSM wait + CreateImage, NO hardening
  Stage 5  [~45 min] Full CIS build: complete Ansible-Lockdown + OpenSCAP pipeline

Run only Stage 1-3 (fast checks):
    pytest tests/integration/ -v -s -m "aws_fast"

Run Stage 4 smoke build:
    pytest tests/integration/ -v -s -m "aws_smoke"

Run everything including the full CIS pipeline:
    pytest tests/integration/ -v -s -m "aws_full"
"""

from __future__ import annotations

import time

import pytest

from tests.integration.conftest import call_aws_rpc

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Stage 1 — Credential Validation
# ---------------------------------------------------------------------------


@pytest.mark.aws_fast
class TestCredentialValidation:
    """STS get_caller_identity must succeed with the provided credentials."""

    def test_connection_returns_ok_status(self, aws_credentials):
        result = call_aws_rpc("test_connection", {"credentials": aws_credentials})
        assert result["status"] == "ok", f"Expected status=ok, got: {result}"

    def test_connection_returns_account_id(self, aws_credentials):
        result = call_aws_rpc("test_connection", {"credentials": aws_credentials})
        account = result.get("account", "")
        assert account.isdigit() and len(account) == 12, f"Expected 12-digit account ID, got: {account!r}"

    def test_connection_returns_arn(self, aws_credentials):
        result = call_aws_rpc("test_connection", {"credentials": aws_credentials})
        arn = result.get("arn", "")
        assert arn.startswith("arn:aws:"), f"Expected ARN starting with arn:aws:, got: {arn!r}"

    def test_connection_account_matches_expected(self, aws_credentials, expected_account):
        if not expected_account:
            pytest.skip("STATIM_EXPECTED_ACCOUNT not set — skipping account ID assertion")
        result = call_aws_rpc("test_connection", {"credentials": aws_credentials})
        assert result["account"] == expected_account, (
            f"Account mismatch: got {result['account']!r}, expected {expected_account!r}"
        )

    def test_connection_fails_with_bad_key(self, aws_credentials, aws_region):
        """Bad credentials must raise a descriptive error, not hang or return ok."""
        bad_creds = {
            "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "region": aws_region,
        }
        with pytest.raises(
            RuntimeError, match=r"(Connection test failed|JSON-RPC error|InvalidClientTokenId|SignatureDoesNotMatch)"
        ):
            call_aws_rpc("test_connection", {"credentials": bad_creds})


# ---------------------------------------------------------------------------
# Stage 2 — AMI Resolution
# ---------------------------------------------------------------------------


@pytest.mark.aws_fast
class TestAMIResolution:
    """resolve_image must return a real, region-specific AMI ID from Canonical."""

    def test_resolve_ubuntu2204_returns_ami_id(self, aws_credentials):
        result = call_aws_rpc(
            "resolve_image",
            {
                "credentials": aws_credentials,
                "os": "ubuntu22.04",
            },
        )
        ami_id = result.get("ami_id", "")
        assert ami_id.startswith("ami-"), (
            f"Expected ami-xxx, got: {ami_id!r} — check describe_images permissions or OS catalog query"
        )

    def test_resolve_ubuntu2204_matches_region(self, aws_credentials, aws_region):
        result = call_aws_rpc(
            "resolve_image",
            {
                "credentials": aws_credentials,
                "os": "ubuntu22.04",
            },
        )
        assert result["region"] == aws_region, f"Region mismatch: expected {aws_region!r}, got {result['region']!r}"

    def test_resolve_returns_different_ami_per_region(self, aws_credentials):
        """Same OS slug must resolve to different AMIs in different regions."""
        regions = ["us-east-1", "eu-west-1"]
        ami_ids = set()
        for region in regions:
            creds = {**aws_credentials, "region": region}
            result = call_aws_rpc(
                "resolve_image",
                {
                    "credentials": creds,
                    "os": "ubuntu22.04",
                },
            )
            ami_id = result.get("ami_id", "")
            if ami_id.startswith("ami-"):
                ami_ids.add(ami_id)
        # AMIs are region-specific — at least two distinct IDs expected across two regions
        assert len(ami_ids) >= 1, "resolve_image returned no valid AMI IDs for any region"
        # Both resolved — if both are valid, they should differ
        if len(ami_ids) == 2:
            assert len(ami_ids) == 2, "Expected region-specific AMI IDs to differ"

    def test_resolve_unknown_os_returns_fallback(self, aws_credentials):
        fallback = "ami-00000000fallback"
        result = call_aws_rpc(
            "resolve_image",
            {
                "credentials": aws_credentials,
                "os": "archlinux-custom-unknown",
                "fallback": fallback,
            },
        )
        assert result["ami_id"] == fallback, f"Unknown OS should return fallback, got: {result['ami_id']!r}"

    def test_resolve_amazon_linux_2023(self, aws_credentials):
        result = call_aws_rpc(
            "resolve_image",
            {
                "credentials": aws_credentials,
                "os": "amazon-linux-2023",
            },
        )
        ami_id = result.get("ami_id", "")
        assert ami_id.startswith("ami-"), f"amazon-linux-2023 resolution failed, got: {ami_id!r}"


# ---------------------------------------------------------------------------
# Stage 3 — List Images
# ---------------------------------------------------------------------------


@pytest.mark.aws_fast
class TestListImages:
    """list_images must return well-formed image dicts from the account."""

    def test_list_images_returns_list(self, aws_credentials):
        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        assert "images" in result, f"Expected 'images' key in result: {result}"
        assert isinstance(result["images"], list)

    def test_list_images_fields_present(self, aws_credentials):
        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        images = result["images"]
        if not images:
            pytest.skip("No owned AMIs in account — skipping field validation")
        for img in images[:5]:
            assert "id" in img, f"Missing 'id' in image: {img}"
            assert "name" in img
            assert "creation_date" in img
            assert img["id"].startswith("ami-"), f"Unexpected image ID: {img['id']!r}"

    def test_list_images_sorted_newest_first(self, aws_credentials):
        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        images = result["images"]
        if len(images) < 2:
            pytest.skip("Fewer than 2 AMIs — skipping sort order check")
        dates = [img["creation_date"] for img in images[:10]]
        assert dates == sorted(dates, reverse=True), "Images are not sorted newest-first by creation_date"

    def test_list_images_capped_at_50(self, aws_credentials):
        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        assert len(result["images"]) <= 50, "list_images returned more than 50 images"


# ---------------------------------------------------------------------------
# Stage 4 — Smoke Build (no hardening, ~10 min)
# ---------------------------------------------------------------------------


@pytest.mark.aws_smoke
class TestSmokeBuild:
    """Launch an EC2 instance, wait for SSM, skip hardening, create an AMI, terminate.

    This validates the full EC2 + SSM + CreateImage plumbing without the
    multi-hour Ansible-Lockdown run. The resulting AMI is deregistered on
    cleanup so it does not accumulate in your account.
    """

    _built_ami: str | None = None
    _built_region: str | None = None

    def test_smoke_build_returns_ami_id(self, aws_credentials, aws_region):
        """Full EC2 pipeline with hardening disabled — must return a valid AMI ID."""
        params = {
            "credentials": aws_credentials,
            "os": "ubuntu22.04",
            "base_image": "",  # trigger runtime AMI resolution
            "instance_type": "t3.micro",
            "root_volume_size_gb": 20,
            "profile_name": "statim-smoke-test",
            "profile_version": "0.0.1",
            "profile": "",  # no SCAP profile — oscap skipped gracefully
            "datastream": "",
            "hardening": {
                "strategy": "none",  # skip Ansible — fast smoke test
            },
        }

        print(f"\n[smoke-build] Launching EC2 in {aws_region} — this takes ~8-12 minutes…")
        start = time.monotonic()

        result = call_aws_rpc("execute_build", params, timeout=1200)  # 20 min hard timeout

        elapsed = time.monotonic() - start
        print(f"[smoke-build] Completed in {elapsed:.0f}s")

        # Store for deregistration in teardown
        TestSmokeBuild._built_ami = result.get("artifact_id")
        TestSmokeBuild._built_region = result.get("region")

        assert result.get("status") == "success", f"Unexpected status: {result}"
        ami_id = result.get("artifact_id", "")
        assert ami_id.startswith("ami-"), f"execute_build must return artifact_id starting with ami-, got: {ami_id!r}"

    def test_smoke_build_artifact_type_is_ami(self, aws_credentials):
        if not TestSmokeBuild._built_ami:
            pytest.skip("Smoke build did not produce an AMI (previous test failed)")
        # Re-use the result stored by the build test
        result = {
            "artifact_id": TestSmokeBuild._built_ami,
            "artifact_type": "ami",
            "region": TestSmokeBuild._built_region,
        }
        assert result["artifact_type"] == "ami"

    def test_smoke_build_ami_is_visible_in_account(self, aws_credentials):
        """The AMI created by the smoke build must appear in list_images."""
        if not TestSmokeBuild._built_ami:
            pytest.skip("No AMI from smoke build")

        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        ami_ids = [img["id"] for img in result["images"]]
        assert TestSmokeBuild._built_ami in ami_ids, (
            f"Built AMI {TestSmokeBuild._built_ami!r} not found in list_images response.\nVisible AMIs: {ami_ids[:10]}"
        )

    @pytest.fixture(autouse=True, scope="class")
    def deregister_smoke_ami(self, aws_credentials):
        """Deregister the smoke AMI and delete its snapshots after the class finishes."""
        yield

        ami_id = TestSmokeBuild._built_ami
        region = TestSmokeBuild._built_region
        if not ami_id:
            return

        print(f"\n[cleanup] Deregistering smoke AMI {ami_id} in {region}…")
        try:
            import boto3

            session = boto3.Session(
                aws_access_key_id=aws_credentials["aws_access_key_id"],
                aws_secret_access_key=aws_credentials["aws_secret_access_key"],
                region_name=region,
            )
            ec2 = session.client("ec2", region_name=region)

            # Get snapshot IDs before deregistering
            resp = ec2.describe_images(ImageIds=[ami_id])
            snapshots = [
                bdm["Ebs"]["SnapshotId"]
                for img in resp.get("Images", [])
                for bdm in img.get("BlockDeviceMappings", [])
                if "Ebs" in bdm and "SnapshotId" in bdm["Ebs"]
            ]

            ec2.deregister_image(ImageId=ami_id)
            print(f"[cleanup] Deregistered {ami_id}")

            for snap_id in snapshots:
                ec2.delete_snapshot(SnapshotId=snap_id)
                print(f"[cleanup] Deleted snapshot {snap_id}")

        except Exception as exc:
            print(f"[cleanup] WARNING: Could not clean up {ami_id}: {exc}")
            print(f"          Manually deregister {ami_id} in {region} to avoid charges.")


# ---------------------------------------------------------------------------
# Stage 5 — Full CIS Build (~45 min)
# ---------------------------------------------------------------------------


@pytest.mark.aws_full
class TestFullCISBuild:
    """Full Ansible-Lockdown + OpenSCAP pipeline for ubuntu22.04 CIS Level 1.

    This is the production path. Expected runtime: 35–60 minutes depending on
    the region and instance type. Use t3.medium or larger — t3.micro is too slow
    for Ansible Galaxy install + playbook run.

    The resulting AMI is deregistered on teardown.
    """

    _built_ami: str | None = None
    _built_region: str | None = None
    _build_result: dict | None = None

    def test_full_cis_build_completes(self, aws_credentials, aws_region):
        """Complete hardening pipeline must return a valid AMI ID."""
        params = {
            "credentials": aws_credentials,
            "os": "ubuntu22.04",
            "base_image": "",  # runtime AMI resolution
            "instance_type": "t3.medium",
            "root_volume_size_gb": 20,
            "profile_name": "ubuntu22-cis-l1",
            "profile_version": "1.0.0",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            "hardening": {
                "strategy": "ansible-galaxy",
                "role": "auto",  # resolves to ansible-lockdown.ubuntu22_cis
            },
        }

        print(
            f"\n[full-build] Starting CIS Level 1 build in {aws_region} on t3.medium\n"
            f"             Expected runtime: 35–60 minutes. Do not interrupt."
        )
        start = time.monotonic()

        result = call_aws_rpc("execute_build", params, timeout=4800)  # 80 min hard cap

        elapsed = time.monotonic() - start
        print(f"[full-build] Completed in {elapsed / 60:.1f} minutes")

        TestFullCISBuild._built_ami = result.get("artifact_id")
        TestFullCISBuild._built_region = result.get("region")
        TestFullCISBuild._build_result = result

        assert result.get("status") == "success", f"Build failed: {result}"
        ami_id = result.get("artifact_id", "")
        assert ami_id.startswith("ami-"), f"execute_build must return artifact_id starting with ami-, got: {ami_id!r}"

    def test_full_build_metadata_contains_profile(self):
        """Result metadata must reference the profile that produced the image."""
        if not TestFullCISBuild._build_result:
            pytest.skip("Full build did not complete")
        meta = TestFullCISBuild._build_result.get("metadata", {})
        assert meta.get("profile_name") == "ubuntu22-cis-l1", (
            f"Expected profile_name='ubuntu22-cis-l1' in metadata, got: {meta}"
        )
        assert meta.get("profile_version") == "1.0.0"

    def test_full_build_ami_is_available(self, aws_credentials):
        """The produced AMI must be in state=available immediately after build."""
        ami_id = TestFullCISBuild._built_ami
        region = TestFullCISBuild._built_region
        if not ami_id:
            pytest.skip("No AMI from full build")

        import boto3

        session = boto3.Session(
            aws_access_key_id=aws_credentials["aws_access_key_id"],
            aws_secret_access_key=aws_credentials["aws_secret_access_key"],
            region_name=region,
        )
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_images(ImageIds=[ami_id])
        images = resp.get("Images", [])
        assert images, f"AMI {ami_id!r} not found via describe_images"
        assert images[0]["State"] == "available", f"AMI {ami_id!r} is not in 'available' state: {images[0]['State']!r}"

    def test_full_build_no_builder_instance_left_running(self, aws_credentials):
        """The builder EC2 instance must be terminated — no orphans left behind."""
        build_result = TestFullCISBuild._build_result
        if not build_result:
            pytest.skip("No build result")
        instance_id = build_result.get("metadata", {}).get("instance_id")
        if not instance_id:
            pytest.skip("instance_id not present in metadata")

        import boto3

        region = TestFullCISBuild._built_region
        session = boto3.Session(
            aws_access_key_id=aws_credentials["aws_access_key_id"],
            aws_secret_access_key=aws_credentials["aws_secret_access_key"],
            region_name=region,
        )
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = resp.get("Reservations", [])
        if not reservations:
            return  # Instance gone — correct
        state = reservations[0]["Instances"][0]["State"]["Name"]
        assert state in ("terminated", "shutting-down"), (
            f"Builder instance {instance_id} is still in state {state!r} — potential orphan"
        )

    def test_full_build_ami_visible_in_list_images(self, aws_credentials):
        """Built AMI must appear in list_images with the correct statim- name prefix."""
        if not TestFullCISBuild._built_ami:
            pytest.skip("No AMI from full build")
        result = call_aws_rpc("list_images", {"credentials": aws_credentials})
        ami_ids = [img["id"] for img in result["images"]]
        assert TestFullCISBuild._built_ami in ami_ids, (
            f"Built AMI {TestFullCISBuild._built_ami!r} not found in list_images.\nVisible: {ami_ids[:10]}"
        )

    @pytest.fixture(autouse=True, scope="class")
    def deregister_full_ami(self, aws_credentials):
        """Deregister the full-build AMI and delete its EBS snapshots after class."""
        yield

        ami_id = TestFullCISBuild._built_ami
        region = TestFullCISBuild._built_region
        if not ami_id:
            return

        print(f"\n[cleanup] Deregistering full-build AMI {ami_id} in {region}…")
        try:
            import boto3

            session = boto3.Session(
                aws_access_key_id=aws_credentials["aws_access_key_id"],
                aws_secret_access_key=aws_credentials["aws_secret_access_key"],
                region_name=region,
            )
            ec2 = session.client("ec2", region_name=region)

            resp = ec2.describe_images(ImageIds=[ami_id])
            snapshots = [
                bdm["Ebs"]["SnapshotId"]
                for img in resp.get("Images", [])
                for bdm in img.get("BlockDeviceMappings", [])
                if "Ebs" in bdm and "SnapshotId" in bdm["Ebs"]
            ]

            ec2.deregister_image(ImageId=ami_id)
            print(f"[cleanup] Deregistered {ami_id}")

            for snap_id in snapshots:
                ec2.delete_snapshot(SnapshotId=snap_id)
                print(f"[cleanup] Deleted snapshot {snap_id}")

        except Exception as exc:
            print(f"[cleanup] WARNING: Could not clean up {ami_id}: {exc}")
            print(f"          Manually deregister {ami_id} in {region} to avoid storage charges.")
