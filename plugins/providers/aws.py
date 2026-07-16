#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""AWS subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [aws] optional extra: pip install bakex[aws]
"""

from __future__ import annotations

import json
import logging
import sys
import time

PROVIDER_NAME = "aws"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[aws] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def _get_boto_session(credentials: dict):
    """Assume the given role via STS and return a boto3 Session."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed. Install with: pip install bakex[aws]") from exc

    role_arn = credentials.get("role_arn", "")
    external_id = credentials.get("external_id", "")
    region = credentials.get("region", "us-east-1")
    profile = credentials.get("aws_profile", "")
    access_key = credentials.get("aws_access_key_id", "")
    secret_key = credentials.get("aws_secret_access_key", "")

    session_args: dict = {"region_name": region}
    if access_key and secret_key:
        session_args["aws_access_key_id"] = access_key
        session_args["aws_secret_access_key"] = secret_key
    elif profile:
        session_args["profile_name"] = profile

    session = boto3.Session(**session_args)
    if not role_arn:
        logger.info(
            "No Role ARN provided, using base %s session in %s",
            f"profile '{profile}'" if profile else "default",
            region,
        )
        return session

    sts = session.client("sts")
    assume_kwargs = {
        "RoleArn": role_arn,
        "RoleSessionName": "BakeXSession",
        "DurationSeconds": 3600,
    }
    if external_id:
        assume_kwargs["ExternalId"] = external_id

    assumed = sts.assume_role(
        **assume_kwargs,
    )
    creds = assumed["Credentials"]
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
    logger.info("Assumed role %s in %s", role_arn, region)
    return session


def _resolve_ami(ec2_client, os_slug: str, fallback: str) -> str:
    """Query describe_images for the latest AMI matching the OS slug's search criteria.

    Falls back to *fallback* if the catalog has no query for *os_slug* or the
    query returns no results.  Always uses the target region of *ec2_client*.
    """
    try:
        # Import lazily — this file runs as a subprocess; avoid top-level imports
        import os as _os

        _catalog_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "bakex", "core", "os_catalog.py")
        # Try to import os_catalog; tolerate missing (e.g. packaged builds)
        import importlib.util as _ilu

        spec = _ilu.spec_from_file_location("os_catalog", _catalog_path)
        if spec is None:
            return fallback
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        query = (mod.OS_CATALOG.get(os_slug) or {}).get("aws_image_query")
        if not query:
            logger.info("No aws_image_query for OS '%s', using fallback AMI", os_slug)
            return fallback
    except Exception as exc:
        logger.warning("Could not load os_catalog for AMI resolution: %s", exc)
        return fallback

    owner = query["owner"]
    name_pattern = query["name_pattern"]
    logger.info("Resolving latest AMI for '%s' (owner=%s, pattern=%s)…", os_slug, owner, name_pattern)
    try:
        resp = ec2_client.describe_images(
            Owners=[owner],
            Filters=[
                {"Name": "name", "Values": [name_pattern]},
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "virtualization-type", "Values": ["hvm"]},
            ],
        )
        images = sorted(
            resp.get("Images", []),
            key=lambda img: img.get("CreationDate", ""),
            reverse=True,
        )
        if not images:
            logger.warning("describe_images returned 0 results for '%s'; using fallback %s", os_slug, fallback)
            return fallback
        resolved = images[0]["ImageId"]
        logger.info("Resolved latest AMI for '%s' → %s (%s)", os_slug, resolved, images[0].get("Name", ""))
        return resolved
    except Exception as exc:
        logger.warning("describe_images failed for '%s': %s — using fallback %s", os_slug, exc, fallback)
        return fallback


_OS_LOCKDOWN_ROLE: dict[str, str] = {
    "ubuntu22": "UBUNTU22-CIS",
    "ubuntu22.04": "UBUNTU22-CIS",
    "ubuntu24": "UBUNTU24-CIS",
    "ubuntu20": "UBUNTU20-04-CIS",
    "debian12": "DEBIAN12-CIS",
    "debian11": "DEBIAN11-CIS",
    "rocky9": "RHEL9-CIS",
    "alma9": "RHEL9-CIS",
    "rhel9": "RHEL9-CIS",
    "rocky8": "RHEL8-CIS",
    "alma8": "RHEL8-CIS",
    "rhel8": "RHEL8-CIS",
    "amazon-linux-2023": "AMAZON2023-CIS",
    "amazon2023": "AMAZON2023-CIS",
}


def _lockdown_role_for_os(os_name: str) -> str:
    key = (os_name or "").lower()
    if key in _OS_LOCKDOWN_ROLE:
        return _OS_LOCKDOWN_ROLE[key]
    for prefix, role in _OS_LOCKDOWN_ROLE.items():
        if key.startswith(prefix):
            return role
    logger.warning("No lockdown role mapping for OS '%s'; defaulting to UBUNTU22-CIS", os_name)
    return "UBUNTU22-CIS"


def _poll_ssm_command(ssm_client, command_id: str, instance_id: str, timeout: int = 600) -> dict:
    """Poll SSM until command completes or timeout. Returns the invocation dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        inv = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id,
        )
        status = inv["Status"]
        if status == "Success":
            return inv
        if status in ("Failed", "Cancelled", "TimedOut", "Undeliverable", "Terminated"):
            raise RuntimeError(
                f"SSM command {command_id} ended with status {status}: {inv.get('StandardErrorContent', '')}"
            )
        logger.info("SSM command %s status: %s — waiting…", command_id, status)
        time.sleep(10)
    raise TimeoutError(f"SSM command {command_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate AWS credentials by calling STS get_caller_identity."""
    credentials = params.get("credentials", params)  # allow flat or nested
    try:
        session = _get_boto_session(credentials)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        logger.info("test_connection: identity %s", identity.get("Arn"))
        return {
            "status": "ok",
            "account": identity.get("Account"),
            "arn": identity.get("Arn"),
        }
    except Exception as exc:
        raise ValueError(f"Connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full EC2 → SSM → prehard → Ansible-Lockdown → OpenSCAP → CreateImage pipeline.

    Expected params keys (in addition to profile fields):
        credentials:          {role_arn, region, subnet_id, security_group_id, iam_profile_name}
        instance_type:        EC2 instance type (default: t3.medium)
        root_volume_size_gb:  Root EBS volume size in GiB (default: 20)
        prehard_playbook_yaml: YAML content of the pre-hardening playbook (auto-generated
                               from the blueprint by the BakeX engine; optional)
        os:                   OS identifier used to select the ansible-lockdown role
    """
    credentials = params.get("credentials", {})
    region = credentials.get("region", "us-east-1")
    subnet_id = credentials.get("subnet_id", "")
    security_group_id = credentials.get("security_group_id", "")
    iam_profile_name = credentials.get("iam_profile_name", "")
    base_image = params.get("base_image", "")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    instance_type = params.get("instance_type") or "t3.medium"
    root_volume_size_gb = int(params.get("root_volume_size_gb") or 20)
    extra_volumes = params.get("extra_volumes", [])
    os_name = params.get("os", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")

    session = _get_boto_session(credentials)
    ec2 = session.client("ec2", region_name=region)
    ssm = session.client("ssm", region_name=region)

    # Resolve base image: if blank or not a literal ami-xxx, look up the latest
    # AMI in the target region using the OS-specific describe_images query.
    if not base_image or not base_image.startswith("ami-"):
        base_image = _resolve_ami(ec2, os_name, base_image)
    if not base_image:
        raise RuntimeError(
            f"No base image available for OS '{os_name}' in region '{region}'. "
            "Provide an explicit AMI ID or ensure the OS catalog has an aws_image_query entry."
        )

    # Auto-resolve VPC ID → subnet ID (user may have entered vpc-xxx instead of subnet-xxx)
    if subnet_id.startswith("vpc-"):
        logger.info("[aws] Resolving VPC %s to a subnet…", subnet_id)
        subs_resp = ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [subnet_id]},
                {"Name": "state", "Values": ["available"]},
            ]
        )
        subs = sorted(subs_resp["Subnets"], key=lambda s: s["SubnetId"])
        if not subs:
            raise RuntimeError(
                f"No available subnets found in VPC {subnet_id}. Please add a subnet or enter a subnet-xxxx ID directly."
            )
        resolved = subs[0]["SubnetId"]
        logger.info("[aws] Resolved VPC %s → subnet %s", subnet_id, resolved)
        subnet_id = resolved

    instance_id: str | None = None
    try:
        # 1. Launch EC2 instance (private subnet, no public IP, SSM IAM profile)
        logger.info(
            "[aws] Launching %s instance from %s in subnet %s (disk: %dGiB)",
            instance_type,
            base_image,
            subnet_id,
            root_volume_size_gb,
        )
        launch_kwargs: dict = {
            "ImageId": base_image,
            "InstanceType": instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "VolumeSize": root_volume_size_gb,
                        "VolumeType": "gp3",
                        "DeleteOnTermination": True,
                    },
                }
            ],
            "TagSpecifications": [
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": f"bakex-build-{profile_name}"},
                        {"Key": "ManagedBy", "Value": "bakex"},
                    ],
                }
            ],
        }
        for ev in extra_volumes:
            launch_kwargs["BlockDeviceMappings"].append(
                {
                    "DeviceName": ev["device_name"],
                    "Ebs": {
                        "VolumeSize": int(ev["size_gb"]),
                        "VolumeType": ev.get("volume_type", "gp3"),
                        "DeleteOnTermination": True,
                    },
                }
            )
        if subnet_id:
            launch_kwargs["NetworkInterfaces"] = [
                {
                    "DeviceIndex": 0,
                    "SubnetId": subnet_id,
                    "AssociatePublicIpAddress": False,
                    "Groups": [security_group_id] if security_group_id else [],
                }
            ]
        if iam_profile_name:
            launch_kwargs["IamInstanceProfile"] = {"Name": iam_profile_name}

        run_resp = ec2.run_instances(**launch_kwargs)
        instance_id = run_resp["Instances"][0]["InstanceId"]
        logger.info("Instance launched: %s", instance_id)

        # 2. Wait for instance running
        logger.info("Waiting for instance %s to be running…", instance_id)
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])

        # 3. Wait 45s for SSM agent to initialise
        logger.info("Waiting 45s for SSM agent…")
        time.sleep(45)

        # 4a. Run pre-hardening playbook on the instance (system config, mounts, users)
        if prehard_playbook_yaml:
            logger.info("Running pre-hardening system configuration playbook via SSM")
            import base64 as _b64

            pb_b64 = _b64.b64encode(prehard_playbook_yaml.encode()).decode()
            prehard_cmds = [
                # Install ansible if absent
                "command -v ansible-playbook >/dev/null 2>&1 || ("
                "  if command -v apt-get >/dev/null 2>&1; then"
                "    export DEBIAN_FRONTEND=noninteractive &&"
                "    apt-get update -q && apt-get install -y software-properties-common &&"
                "    add-apt-repository --yes --update ppa:ansible/ansible 2>/dev/null || true &&"
                "    apt-get install -y ansible;"
                "  elif command -v dnf >/dev/null 2>&1; then"
                "    dnf install -y ansible;"
                "  fi"
                ")",
                # Decode playbook and run it locally on the instance
                f"echo '{pb_b64}' | base64 -d > /tmp/bakex-prehard.yml",
                "ansible-playbook -i 'localhost,' -c local /tmp/bakex-prehard.yml",
            ]
            ph_resp = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": prehard_cmds},
                TimeoutSeconds=600,
            )
            _poll_ssm_command(ssm, ph_resp["Command"]["CommandId"], instance_id, timeout=600)
            logger.info("Pre-hardening system configuration complete")

        # 4b. Pluggable hardening strategy
        hardening = params.get("hardening", {})
        strategy = hardening.get("strategy", "ansible-galaxy")

        if strategy == "none":
            logger.info("Hardening strategy is 'none' — skipping CIS compliance playbook.")
        else:
            if strategy == "ansible-galaxy":
                role = hardening.get("role", "auto")
                if role == "auto":
                    role = _lockdown_role_for_os(os_name)
                    role = f"ansible-lockdown.{role}"

                logger.info("Installing Galaxy role %s via SSM on %s", role, instance_id)
                site_yaml = (
                    "---\n"
                    f"- name: BakeX Compliance Hardening ({role})\n"
                    "  hosts: localhost\n"
                    "  connection: local\n"
                    "  become: true\n"
                    "  roles:\n"
                    f"    - {role}\n"
                )
                import base64 as _b64

                site_b64 = _b64.b64encode(site_yaml.encode()).decode()
                hardening_cmds = [
                    f"ansible-galaxy install {role} --force 2>&1 || true",
                    f"echo '{site_b64}' | base64 -d > /tmp/bakex-hardening.yml",
                    "ansible-playbook -i 'localhost,' -c local /tmp/bakex-hardening.yml",
                ]
            elif strategy == "git":
                repo_url = hardening.get("repo_url", "")
                playbook_file = hardening.get("playbook_file", "site.yml")
                if not repo_url:
                    raise ValueError("Hardening strategy is 'git' but 'repo_url' is missing.")

                logger.info("Cloning Git repository %s via SSM on %s", repo_url, instance_id)
                git_pkg = "git"
                hardening_cmds = [
                    f"command -v git >/dev/null 2>&1 || (sudo apt-get update && sudo apt-get install -y {git_pkg} || sudo dnf install -y {git_pkg} || sudo yum install -y {git_pkg})",
                    "sudo rm -rf /etc/ansible/bakex_custom_hardening",
                    f"sudo git clone {repo_url} /etc/ansible/bakex_custom_hardening",
                    f"sudo cp /etc/ansible/bakex_custom_hardening/{playbook_file} /tmp/bakex-hardening.yml",
                    "ansible-playbook -i 'localhost,' -c local /tmp/bakex-hardening.yml",
                ]
            else:
                raise ValueError(f"Unknown hardening strategy: {strategy}")

            ansible_resp = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": hardening_cmds},
                TimeoutSeconds=3600,
            )
            _poll_ssm_command(ssm, ansible_resp["Command"]["CommandId"], instance_id, timeout=3600)
            logger.info("Compliance hardening complete")

        # 5. Run OpenSCAP scan via SSM
        oscap_cmd = f"oscap xccdf eval --profile {profile_id} --results /tmp/scap-results.xml {datastream} || true"
        scan_resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [oscap_cmd]},
            TimeoutSeconds=600,
        )
        _poll_ssm_command(ssm, scan_resp["Command"]["CommandId"], instance_id)
        logger.info("OpenSCAP scan complete")

        # 5.5 Cleanup history and logs
        logger.info("Cleaning up instance logs and history before snapshot")
        cleanup_cmds = [
            "sudo rm -rf /tmp/bakex-*",
            "sudo rm -f /var/log/messages /var/log/syslog /var/log/auth.log",
            "sudo journalctl --vacuum-time=1s || true",
            "sudo sh -c 'cat /dev/null > /var/log/wtmp' || true",
            "cat /dev/null > ~/.bash_history || true",
            "sudo sh -c 'cat /dev/null > /root/.bash_history' || true",
            "sudo find /home -name '.bash_history' -exec sh -c 'cat /dev/null > {}' \\;",
        ]
        cleanup_resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [" ; ".join(cleanup_cmds)]},
            TimeoutSeconds=120,
        )
        try:
            _poll_ssm_command(ssm, cleanup_resp["Command"]["CommandId"], instance_id, timeout=120)
        except Exception as exc:
            logger.warning("History cleanup encountered an issue, but proceeding with snapshot: %s", exc)

        # 6. Create AMI + wait for availability
        image_name = f"bakex-{profile_name}-{profile_version}"
        logger.info("Creating AMI: %s", image_name)
        image_resp = ec2.create_image(
            InstanceId=instance_id,
            Name=image_name,
            Description=f"BakeX hardened image: {profile_name} v{profile_version}",
            NoReboot=False,
        )
        ami_id = image_resp["ImageId"]
        ec2.get_waiter("image_available").wait(ImageIds=[ami_id])
        logger.info("AMI %s is available", ami_id)

        return {
            "status": "success",
            "artifact_id": ami_id,
            "artifact_type": "ami",
            "region": region,
            "metadata": {
                "profile_name": profile_name,
                "profile_version": profile_version,
                "instance_id": instance_id,
            },
        }

    finally:
        if instance_id:
            logger.info("Terminating instance %s", instance_id)
            try:
                ec2.terminate_instances(InstanceIds=[instance_id])
            except Exception as exc:
                logger.warning("Failed to terminate %s: %s", instance_id, exc)


def execute_audit(params: dict) -> dict:
    """Run OpenSCAP audit on a target EC2 instance via SSM.

    Expected params keys:
        target_id:   EC2 instance ID to audit
        credentials: {role_arn, region, ...}
        profile:     XCCDF profile ID
        datastream:  Path to SCAP datastream on the instance
    """
    credentials = params.get("credentials", {})
    region = credentials.get("region", "us-east-1")
    target_id = params.get("target_id", "")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not target_id:
        raise ValueError("execute_audit requires 'target_id' (EC2 instance ID)")

    session = _get_boto_session(credentials)
    ssm = session.client("ssm", region_name=region)

    # Run oscap and capture XML output
    oscap_cmd = (
        f"oscap xccdf eval --profile {profile_id} --results /tmp/bakex-audit.xml {datastream}; cat /tmp/bakex-audit.xml"
    )

    logger.info("Sending audit command to instance %s", target_id)
    send_resp = ssm.send_command(
        InstanceIds=[target_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [oscap_cmd]},
        TimeoutSeconds=600,
    )
    command_id = send_resp["Command"]["CommandId"]
    invocation = _poll_ssm_command(ssm, command_id, target_id, timeout=600)

    raw_xml = invocation.get("StandardOutputContent", "")
    logger.info("Audit complete for %s, XML length: %d", target_id, len(raw_xml))

    return {
        "status": "success",
        "raw_xml": raw_xml,
    }


def execute_scan_image(params: dict) -> dict:
    """Launch a temporary EC2 instance from an existing AMI, run OpenSCAP, then terminate it.

    Expected params keys:
        image_id:     Source AMI to scan
        instance_type: EC2 instance type (default: t3.medium)
        region:       AWS region
        os:           OS hint (for logging)
        profile:      XCCDF profile ID
        datastream:   Path to SCAP datastream on the instance
        credentials:  {role_arn, region, aws_access_key_id, aws_secret_access_key, ...}
    """
    credentials = params.get("credentials", {})
    region = params.get("region") or credentials.get("region", "us-east-1")
    image_id = params.get("image_id", "")
    instance_type = params.get("instance_type", "t3.medium")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not image_id:
        raise ValueError("execute_scan_image requires 'image_id'")

    credentials["region"] = region
    session = _get_boto_session(credentials)
    ec2 = session.client("ec2", region_name=region)

    iam_profile_name = credentials.get("iam_profile_name", "")

    launch_args: dict = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": "bakex-scan-image-temp"}],
            }
        ],
    }
    if iam_profile_name:
        launch_args["IamInstanceProfile"] = {"Name": iam_profile_name}

    logger.info("Launching scan instance from AMI %s (%s)", image_id, instance_type)
    run_resp = ec2.run_instances(**launch_args)
    instance_id = run_resp["Instances"][0]["InstanceId"]
    logger.info("Scan instance %s launched; waiting for running state", instance_id)

    try:
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
        # Give SSM agent time to register
        time.sleep(45)

        ssm = session.client("ssm", region_name=region)
        oscap_cmd = (
            f"oscap xccdf eval "
            f"--profile {profile_id} "
            f"--results /tmp/bakex-scan.xml "
            f"{datastream}; "
            f"cat /tmp/bakex-scan.xml"
        )
        logger.info("Sending scan command to %s", instance_id)
        send_resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [oscap_cmd]},
            TimeoutSeconds=900,
        )
        command_id = send_resp["Command"]["CommandId"]
        invocation = _poll_ssm_command(ssm, command_id, instance_id, timeout=900)
        raw_xml = invocation.get("StandardOutputContent", "")
        logger.info("Image scan complete for %s, XML length: %d", image_id, len(raw_xml))
        return {"status": "success", "raw_xml": raw_xml}

    finally:
        logger.info("Terminating scan instance %s", instance_id)
        try:
            ec2.terminate_instances(InstanceIds=[instance_id])
        except Exception as term_exc:
            logger.warning("Failed to terminate scan instance %s: %s", instance_id, term_exc)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return AWS AMIs visible to the account (public official + owned-by-self).

    Params:
        credentials — {role_arn, region, ...}
        os          — OS filter: "ubuntu" | "amazon" | "rocky" | "debian" (optional)
    """
    credentials = params.get("credentials", {})
    region = credentials.get("region", "us-east-1")
    os_filter = params.get("os", "")
    # Map OS hint to well-known owner IDs
    owner_map = {
        "ubuntu": ["099720109477"],  # Canonical
        "amazon": ["137112412989"],  # Amazon
        "debian": ["136693071363"],  # Debian
        "rocky": ["679593333241"],  # Rocky Linux
        "alma": ["764336703387"],  # AlmaLinux
    }
    owners = ["self"]
    for key, ids in owner_map.items():
        if os_filter.lower().startswith(key):
            owners = ids
            break

    try:
        session = _get_boto_session(credentials)
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_images(
            Owners=owners,
            Filters=[
                {"Name": "state", "Values": ["available"]},
                {"Name": "architecture", "Values": ["x86_64"]},
            ],
        )
        images = [
            {
                "id": img["ImageId"],
                "name": img.get("Name", ""),
                "description": img.get("Description", ""),
                "creation_date": img.get("CreationDate", ""),
                "owner_id": img.get("OwnerId", ""),
            }
            for img in resp.get("Images", [])
        ]
        # Sort by creation date descending (newest first)
        images.sort(key=lambda x: x["creation_date"], reverse=True)
        return {"images": images[:50]}  # cap at 50 to avoid overwhelming the UI
    except Exception as exc:
        logger.warning("list_images failed: %s", exc)
        return {"images": []}


def resolve_image(params: dict) -> dict:
    """Return the latest AMI ID for a given OS slug in the target region.

    Params:
        credentials — {region, ...}
        os          — OS slug matching os_catalog (e.g. 'ubuntu22.04')
        fallback    — AMI ID to return if resolution fails (optional)
    """
    credentials = params.get("credentials", {})
    region = credentials.get("region", "us-east-1")
    os_slug = params.get("os", "")
    fallback = params.get("fallback", "")

    session = _get_boto_session(credentials)
    ec2 = session.client("ec2", region_name=region)
    ami_id = _resolve_ami(ec2, os_slug, fallback)
    return {"ami_id": ami_id, "region": region, "os": os_slug}


_DISPATCH = {
    "test_connection": test_connection,
    "execute_build": execute_build,
    "execute_audit": execute_audit,
    "execute_scan_image": execute_scan_image,
    "list_images": list_images,
    "resolve_image": resolve_image,
}


def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps(_jsonrpc_error(None, -32700, f"Parse error: {exc}")), flush=True)
        sys.exit(1)

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method not in _DISPATCH:
        print(
            json.dumps(_jsonrpc_error(req_id, -32601, f"Method not found: {method!r}")),
            flush=True,
        )
        sys.exit(1)

    try:
        result = _DISPATCH[method](params)
        print(json.dumps(_jsonrpc_result(req_id, result)), flush=True)
    except Exception as exc:
        logger.error("execute error: %s", exc)
        print(json.dumps(_jsonrpc_error(req_id, -32603, str(exc))), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
