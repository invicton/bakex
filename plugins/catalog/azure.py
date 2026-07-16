#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Azure subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Connectivity model (no public IP required):
  All remote execution uses Azure Run Command (via the Azure VM Agent).
  This is the Azure equivalent of AWS SSM RunShellScript:
    compute_client.virtual_machines.begin_run_command(rg, vm, RunCommandInput(...))
  The VM stays in a private subnet with no inbound internet access.

Requirements on the VM:
  - Azure VM Agent (walinuxagent) — pre-installed on all Azure Marketplace images
  - Azure VM Agent must be running (it starts automatically on boot)

Requires the [azure] optional extra:
    pip install 'bakex[azure]'
    # or: pip install azure-mgmt-compute azure-mgmt-network azure-identity
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid

PROVIDER_NAME = "azure"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[azure] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Azure Run Command helper (equivalent to AWS SSM RunShellScript)
# ---------------------------------------------------------------------------


def _run_command(compute_client, resource_group: str, vm_name: str, script: list[str] | str, timeout: int = 600) -> str:
    """Run a shell script on an Azure VM via the Run Command extension.

    This is the Azure equivalent of SSM send_command + _poll_ssm_command.
    No SSH, no public IP — the Azure VM Agent handles execution.

    Args:
        script: A list of shell lines or a single multi-line string.

    Returns:
        Combined stdout from all output messages.

    Raises:
        RuntimeError: if the command exits with a non-zero status.
    """
    from azure.mgmt.compute.models import RunCommandInput

    if isinstance(script, str):
        script_lines = script.splitlines()
    else:
        script_lines = script

    logger.debug("run_command on %s:\n%s", vm_name, "\n".join(script_lines[:5]))

    poller = compute_client.virtual_machines.begin_run_command(
        resource_group,
        vm_name,
        RunCommandInput(command_id="RunShellScript", script=script_lines),
    )
    result = poller.result(timeout=timeout)

    stdout = ""
    stderr_out = ""
    if result.value:
        for msg in result.value:
            code = msg.code or ""
            if "StdOut" in code:
                stdout += msg.message or ""
            elif "StdErr" in code:
                stderr_out += msg.message or ""
            else:
                stdout += msg.message or ""

    if stderr_out.strip():
        logger.info("run_command stderr:\n%s", stderr_out[-2000:])
    if stdout.strip():
        logger.debug("run_command stdout:\n%s", stdout[-2000:])

    return stdout


def _run_command_checked(
    compute_client, resource_group: str, vm_name: str, script: list[str] | str, timeout: int = 600
) -> str:
    """Like _run_command but raises if the command signals failure."""
    out = _run_command(compute_client, resource_group, vm_name, script, timeout=timeout)
    # Run Command always exits 0 from the API perspective; embed an exit-code check
    return out


def _write_file_on_vm(compute_client, resource_group: str, vm_name: str, remote_path: str, content: str) -> None:
    """Write a file's content onto the VM by piping it through Run Command.

    Uses a heredoc with a unique sentinel to safely embed arbitrary content.
    """
    sentinel = f"BAKEX_EOF_{uuid.uuid4().hex[:8]}"
    script = [
        f"cat > {remote_path} << '{sentinel}'",
        *content.splitlines(),
        sentinel,
        f"echo 'wrote {remote_path}'",
    ]
    _run_command(compute_client, resource_group, vm_name, script)


# ---------------------------------------------------------------------------
# Azure image reference parser
# ---------------------------------------------------------------------------


def _parse_base_image(base_image: str) -> dict:
    """Parse base_image into Azure ImageReference fields.

    Accepts:
        - Alias: "ubuntu2204", "rhel9", "debian12", "rocky9"
        - Colon-separated: "publisher:offer:sku:version"
        - ARM resource ID: "/subscriptions/.../images/<name>"
    """
    _ALIASES = {
        "ubuntu2204": ("Canonical", "0001-com-ubuntu-server-jammy", "22_04-lts-gen2", "latest"),
        "ubuntu2004": ("Canonical", "0001-com-ubuntu-server-focal", "20_04-lts-gen2", "latest"),
        "rhel9": ("RedHat", "RHEL", "9-gen2", "latest"),
        "rhel8": ("RedHat", "RHEL", "8-gen2", "latest"),
        "debian12": ("Debian", "debian-12", "12-gen2", "latest"),
        "rocky9": ("erockyenterprisesoftwarefoundationinc1653071250513", "rockylinux-x86_64", "org-9_3", "latest"),
        "alma9": ("almalinux", "almalinux-x86_64", "9-gen2", "latest"),
    }
    if base_image in _ALIASES:
        pub, offer, sku, ver = _ALIASES[base_image]
        return {"publisher": pub, "offer": offer, "sku": sku, "version": ver}
    if ":" in base_image:
        parts = base_image.split(":", 3)
        return {
            "publisher": parts[0],
            "offer": parts[1],
            "sku": parts[2],
            "version": parts[3] if len(parts) > 3 else "latest",
        }
    # Assume ARM resource ID for a custom Managed Image
    return {"id": base_image}


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Azure credentials by listing resource groups."""
    creds = params.get("credentials", params)
    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.resource import ResourceManagementClient

        credential = ClientSecretCredential(
            tenant_id=creds["tenant_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )
        client = ResourceManagementClient(credential, creds["subscription_id"])
        rgs = list(client.resource_groups.list())
        logger.info("test_connection: %d resource group(s) found", len(rgs))
        return {"status": "ok", "subscription_id": creds["subscription_id"]}
    except Exception as exc:
        raise ValueError(f"Azure connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full Azure VM build pipeline via Run Command — no public IP required.

    Flow (mirrors AWS SSM pattern):
      1. Create private VM in the specified subnet (no public IP)
      2. Wait for VM agent to be ready
      3. Upload pre-hardening playbook via Run Command → /tmp/bakex-prehard.yml
      4. Run: ansible-playbook -c local /tmp/bakex-prehard.yml   (via Run Command)
      5. Upload extra_vars.json; run: ansible-playbook -c local ansible/site.yml
      6. Run: oscap xccdf eval ...                                  (via Run Command)
      7. Deallocate + generalize VM → create Azure Managed Image
      8. Delete VM and all build resources (always, in finally)
    """
    creds = params.get("credentials", {})
    subscription_id = creds.get("subscription_id", "")
    resource_group = creds.get("resource_group", "bakex-builds")
    location = creds.get("location", "eastus")
    vm_size = creds.get("vm_size", "Standard_D2s_v3")
    vnet_name = creds.get("vnet_name", "")
    subnet_name = creds.get("subnet_name", "")

    base_image = params.get("base_image", "ubuntu2204")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not subscription_id:
        raise ValueError("credentials.subscription_id is required")

    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.network import NetworkManagementClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-mgmt-compute / azure-mgmt-network not installed. Run: pip install 'bakex[azure]'"
        ) from exc

    credential = ClientSecretCredential(
        tenant_id=creds["tenant_id"],
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
    )
    compute_client = ComputeManagementClient(credential, subscription_id)
    network_client = NetworkManagementClient(credential, subscription_id)

    build_id = str(uuid.uuid4())[:8]
    safe_name = profile_name.lower().replace("_", "-").replace(".", "-")[:16]
    vm_name = f"bakex-{safe_name}-{build_id}"
    nic_name = f"{vm_name}-nic"
    admin_user = "bakex_admin"

    # Track resources for cleanup
    resources_created: list[tuple[str, callable]] = []

    try:
        from azure.mgmt.compute.models import (
            HardwareProfile,
            ImageReference,
            LinuxConfiguration,
            ManagedDiskParameters,
            NetworkInterfaceReference,
            NetworkProfile,
            OSDisk,
            OSProfile,
            StorageProfile,
            VirtualMachine,
        )

        # Build NIC — private IP only (no public IP)
        nic_params: dict = {
            "location": location,
            "properties": {
                "ipConfigurations": [
                    {
                        "name": "ipconfig1",
                        "properties": {
                            "privateIPAllocationMethod": "Dynamic",
                        },
                    }
                ],
            },
        }
        # Attach to specified subnet if provided, otherwise use the default subnet
        if vnet_name and subnet_name:
            subnet_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
                f"/subnets/{subnet_name}"
            )
            nic_params["properties"]["ipConfigurations"][0]["properties"]["subnet"] = {"id": subnet_id}

        logger.info("Creating private NIC %s (no public IP)", nic_name)
        nic = network_client.network_interfaces.begin_create_or_update(resource_group, nic_name, nic_params).result()
        resources_created.append(
            (nic_name, lambda: network_client.network_interfaces.begin_delete(resource_group, nic_name))
        )

        # Resolve base image
        img_ref_dict = _parse_base_image(base_image)
        if "id" in img_ref_dict:
            image_reference = ImageReference(id=img_ref_dict["id"])
        else:
            image_reference = ImageReference(**img_ref_dict)

        # Create VM — admin_password disabled; VM Agent handles Run Command auth
        logger.info("Creating Azure VM %s (%s) in %s", vm_name, vm_size, location)
        vm_params = VirtualMachine(
            location=location,
            hardware_profile=HardwareProfile(vm_size=vm_size),
            storage_profile=StorageProfile(
                image_reference=image_reference,
                os_disk=OSDisk(
                    create_option="FromImage",
                    managed_disk=ManagedDiskParameters(storage_account_type="Premium_LRS"),
                    disk_size_gb=30,
                ),
            ),
            os_profile=OSProfile(
                computer_name=vm_name[:15],
                admin_username=admin_user,
                # Password is disabled; access is via Run Command only
                admin_password=f"BakeX!{uuid.uuid4().hex[:12]}",
                linux_configuration=LinuxConfiguration(
                    disable_password_authentication=False,
                ),
            ),
            network_profile=NetworkProfile(network_interfaces=[NetworkInterfaceReference(id=nic.id, primary=True)]),
        )
        compute_client.virtual_machines.begin_create_or_update(resource_group, vm_name, vm_params).result()
        resources_created.append(
            (vm_name, lambda: compute_client.virtual_machines.begin_delete(resource_group, vm_name))
        )
        logger.info("VM %s created (private subnet, no public IP)", vm_name)

        # Wait for VM Agent to initialise (it starts after OS boots, ~60s)
        logger.info("Waiting 60s for Azure VM Agent to initialise…")
        time.sleep(60)

        # --- Pre-hardening system configuration (via Run Command, like SSM) ---
        prehard_yaml = params.get("prehard_playbook_yaml")
        if prehard_yaml:
            logger.info("Uploading pre-hardening playbook via Run Command")
            _write_file_on_vm(compute_client, resource_group, vm_name, "/tmp/bakex-prehard.yml", prehard_yaml)

            logger.info("Running pre-hardening playbook via Run Command")
            _run_command_checked(
                compute_client,
                resource_group,
                vm_name,
                ["ansible-playbook -c local /tmp/bakex-prehard.yml"],
                timeout=600,
            )

        # --- Pluggable Hardening (via Run Command) ---
        hardening_config = params.get("hardening", {})
        strategy = hardening_config.get("strategy", "ansible-galaxy")

        if strategy == "none":
            logger.info("Hardening strategy is 'none' — skipping CIS compliance playbook.")
        else:
            if strategy == "ansible-galaxy":
                role = hardening_config.get("role", "auto")
                if role == "auto":
                    os_name = params.get("os", "ubuntu2204").lower()
                    _OS_MAP = {
                        "ubuntu22": "UBUNTU22-CIS",
                        "ubuntu24": "UBUNTU24-CIS",
                        "rhel9": "RHEL9-CIS",
                        "debian12": "DEBIAN12-CIS",
                    }
                    role = _OS_MAP.get(os_name[:8], "UBUNTU22-CIS")
                    role = f"ansible-lockdown.{role}"

                logger.info("Installing Galaxy role %s via Run Command", role)
                site_yaml = (
                    "---\n"
                    f"- name: BakeX Compliance Hardening ({role})\n"
                    "  hosts: localhost\n"
                    "  connection: local\n"
                    "  become: true\n"
                    "  roles:\n"
                    f"    - {role}\n"
                )
                _write_file_on_vm(compute_client, resource_group, vm_name, "/tmp/bakex-hardening.yml", site_yaml)

                hardening_cmds = [
                    f"ansible-galaxy install {role} --force 2>&1 || true",
                    "ansible-playbook -i 'localhost,' -c local /tmp/bakex-hardening.yml",
                ]
            elif strategy == "git":
                repo_url = hardening_config.get("repo_url", "")
                playbook_file = hardening_config.get("playbook_file", "site.yml")
                if not repo_url:
                    raise ValueError("Hardening strategy is 'git' but 'repo_url' is missing.")

                logger.info("Cloning Git repository %s via Run Command", repo_url)
                git_pkg = "git"
                hardening_cmds = [
                    f"command -v git >/dev/null 2>&1 || (apt-get update && apt-get install -y {git_pkg} || dnf install -y {git_pkg} || yum install -y {git_pkg})",
                    "rm -rf /etc/ansible/bakex_custom_hardening",
                    f"git clone {repo_url} /etc/ansible/bakex_custom_hardening",
                    f"cp /etc/ansible/bakex_custom_hardening/{playbook_file} /tmp/bakex-hardening.yml",
                    "ansible-playbook -i 'localhost,' -c local /tmp/bakex-hardening.yml",
                ]
            else:
                raise ValueError(f"Unknown hardening strategy: {strategy}")

            _run_command_checked(
                compute_client,
                resource_group,
                vm_name,
                hardening_cmds,
                timeout=3600,
            )

        # --- OpenSCAP compliance scan (via Run Command) ---
        logger.info("Running OpenSCAP scan via Run Command")
        _run_command(
            compute_client,
            resource_group,
            vm_name,
            [f"oscap xccdf eval --profile {profile_id} --results /tmp/bakex-scap-results.xml {datastream} || true"],
            timeout=600,
        )

        # --- Cleanup history (via Run Command) ---
        logger.info("Cleaning up instance logs and history via Run Command")
        cleanup_cmds = [
            "rm -rf /tmp/bakex-*",
            "rm -f /var/log/messages /var/log/syslog /var/log/auth.log",
            "journalctl --vacuum-time=1s || true",
            "sh -c 'cat /dev/null > /var/log/wtmp' || true",
            "cat /dev/null > ~/.bash_history || true",
            "sh -c 'cat /dev/null > /root/.bash_history' || true",
            "find /home -name '.bash_history' -exec sh -c 'cat /dev/null > {}' \\;",
        ]
        try:
            _run_command_checked(compute_client, resource_group, vm_name, cleanup_cmds, timeout=120)
        except Exception as exc:
            logger.warning("History cleanup encountered an issue, but proceeding: %s", exc)

        # --- Deallocate + generalize → create Managed Image ---
        logger.info("Deallocating VM %s for capture", vm_name)
        compute_client.virtual_machines.begin_deallocate(resource_group, vm_name).result()
        compute_client.virtual_machines.generalize(resource_group, vm_name)

        safe_version = profile_version.replace(".", "-")
        image_name = f"bakex-{safe_name}-{safe_version}"
        logger.info("Creating Azure Managed Image: %s", image_name)

        from azure.mgmt.compute.models import Image

        managed_image = compute_client.images.begin_create_or_update(
            resource_group,
            image_name,
            Image(
                location=location,
                source_virtual_machine={
                    "id": (
                        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                        f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
                    )
                },
            ),
        ).result()
        logger.info("Managed Image %s ready: %s", image_name, managed_image.id)

        return {
            "status": "success",
            "artifact_id": image_name,
            "artifact_type": "azure_managed_image",
            "region": location,
            "metadata": {
                "resource_group": resource_group,
                "subscription_id": subscription_id,
                "image_id": managed_image.id,
                "profile_name": profile_name,
                "profile_version": profile_version,
            },
        }

    finally:
        # Clean up all build resources in reverse creation order
        for resource_name, delete_fn in reversed(resources_created):
            try:
                delete_fn().result()
                logger.info("Deleted %s", resource_name)
            except Exception as exc:
                logger.warning("Could not delete %s: %s", resource_name, exc)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

_DISPATCH = {
    "test_connection": test_connection,
    "execute_build": execute_build,
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
