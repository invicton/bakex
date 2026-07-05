#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Azure subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core Stratum engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [azure] optional extra: pip install stratum[azure]

Credential fields (stored via Stratum integrations UI):
    tenant_id         — Azure AD tenant ID (required)
    client_id         — Service principal app ID (required)
    client_secret     — Service principal secret (required)
    subscription_id   — Azure subscription ID (required)
    resource_group    — Existing resource group for build resources (required)
    location          — Azure region, e.g. "eastus" (default: eastus)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_NAME = "azure"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[azure] %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _provider_utils as utils  # noqa: E402

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _ok(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _err(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Azure client helpers
# ---------------------------------------------------------------------------


def _get_credential(credentials: dict):
    try:
        from azure.identity import ClientSecretCredential
    except ImportError as exc:
        raise RuntimeError("azure-identity not installed. Install with: pip install stratum[azure]") from exc
    return ClientSecretCredential(
        tenant_id=credentials["tenant_id"],
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
    )


def _compute_client(cred, subscription_id: str):
    from azure.mgmt.compute import ComputeManagementClient

    return ComputeManagementClient(cred, subscription_id)


def _network_client(cred, subscription_id: str):
    from azure.mgmt.network import NetworkManagementClient

    return NetworkManagementClient(cred, subscription_id)


def _wait_lro(poller, timeout: int = 600):
    """Poll an Azure LRO poller with a timeout."""
    deadline = time.time() + timeout
    while not poller.done():
        if time.time() > deadline:
            raise TimeoutError("Azure LRO did not complete within timeout")
        time.sleep(15)
    return poller.result()


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Azure credentials by fetching subscription info."""
    credentials = params.get("credentials", params)
    for field in ("tenant_id", "client_id", "client_secret", "subscription_id"):
        if not credentials.get(field):
            raise ValueError(f"'{field}' is required")

    try:
        from azure.mgmt.resource import SubscriptionClient
    except ImportError as exc:
        raise RuntimeError("azure-mgmt-resource not installed") from exc

    cred = _get_credential(credentials)
    sub_client = SubscriptionClient(cred)
    sub = sub_client.subscriptions.get(credentials["subscription_id"])
    logger.info("test_connection: subscription %s (%s)", sub.display_name, sub.subscription_id)
    return {
        "status": "ok",
        "subscription_id": sub.subscription_id,
        "display_name": sub.display_name,
        "state": str(sub.state),
    }


def execute_build(params: dict) -> dict:
    """Azure VM → pre-harden → Ansible-Lockdown → OpenSCAP → capture managed image → cleanup.

    Credential / param fields:
        tenant_id / client_id / client_secret / subscription_id — SP credentials (required)
        resource_group    — Resource group for all build resources (required)
        location          — Azure region (default: eastus)
        base_image        — Image reference as "publisher:offer:sku:version"
                            e.g. "Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest"
        instance_type     — VM size (default: Standard_B2s)
        root_volume_size_gb — OS disk size in GB (default: 30)
        os                — OS identifier for lockdown role selection
        prehard_playbook_yaml — Generated pre-hardening playbook YAML
        profile / datastream  — SCAP profile and datastream path
    """
    credentials = params.get("credentials", {})
    for field in ("tenant_id", "client_id", "client_secret", "subscription_id"):
        if not credentials.get(field):
            raise ValueError(f"credentials.{field} is required")

    rg = credentials.get("resource_group", "")
    if not rg:
        raise ValueError("credentials.resource_group is required")

    location = credentials.get("location") or "eastus"
    subscription_id = credentials["subscription_id"]

    base_image_ref = params.get("base_image", "Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest")
    vm_size = params.get("instance_type") or credentials.get("vm_size") or "Standard_B2s"
    disk_gb = int(params.get("root_volume_size_gb") or 30)
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")

    ssh_user = utils.default_ssh_user(os_name)
    cred = _get_credential(credentials)
    compute = _compute_client(cred, subscription_id)
    network = _network_client(cred, subscription_id)

    # Unique suffix for all build resources
    suffix = f"stratum{int(time.time())}"
    vm_name = f"stratum-bld-{suffix[:18]}"
    nic_name = f"stratum-nic-{suffix[:18]}"
    pip_name = f"stratum-pip-{suffix[:18]}"
    vnet_name = f"stratum-vnet-{suffix[:18]}"
    subnet_name = "stratum-subnet"
    disk_name = f"stratum-disk-{suffix[:18]}"
    captured_image_name = f"stratum-{profile_name.lower()[:30]}-{profile_version.replace('.', '-')}"

    resources_to_delete = []

    with tempfile.TemporaryDirectory(prefix="stratum-azure-") as tmpdir:
        tmp = Path(tmpdir)
        key_path, pub_key = utils.generate_ssh_keypair(tmp)
        ip_address: str | None = None

        try:
            from azure.mgmt.compute.models import (
                CachingTypes,
                DiskCreateOptionTypes,
                HardwareProfile,
                ImageReference,
                LinuxConfiguration,
                ManagedDiskParameters,
                NetworkInterfaceReference,
                NetworkProfile,
                OSDisk,
                OSProfile,
                SshConfiguration,
                SshPublicKey,
                StorageProfile,
                VirtualMachine,
            )
            from azure.mgmt.network.models import (
                AddressSpace,
                IPAllocationMethod,
                NetworkInterface,
                NetworkInterfaceIPConfiguration,
                PublicIPAddress,
                PublicIPAddressSku,
                Subnet,
                VirtualNetwork,
            )

            # 1. Create VNet + Subnet
            logger.info("Creating VNet %s in %s/%s", vnet_name, rg, location)
            vnet_poller = network.virtual_networks.begin_create_or_update(
                rg,
                vnet_name,
                VirtualNetwork(
                    location=location,
                    address_space=AddressSpace(address_prefixes=["10.0.0.0/16"]),
                    subnets=[Subnet(name=subnet_name, address_prefix="10.0.0.0/24")],
                ),
            )
            vnet = _wait_lro(vnet_poller, timeout=120)
            resources_to_delete.append(("vnet", vnet_name))
            subnet_id = vnet.subnets[0].id

            # 2. Create public IP
            logger.info("Creating public IP %s", pip_name)
            pip_poller = network.public_ip_addresses.begin_create_or_update(
                rg,
                pip_name,
                PublicIPAddress(
                    location=location,
                    sku=PublicIPAddressSku(name="Basic"),
                    public_ip_allocation_method=IPAllocationMethod.DYNAMIC,
                ),
            )
            pip = _wait_lro(pip_poller, timeout=120)
            resources_to_delete.append(("pip", pip_name))

            # 3. Create NIC
            logger.info("Creating NIC %s", nic_name)
            nic_poller = network.network_interfaces.begin_create_or_update(
                rg,
                nic_name,
                NetworkInterface(
                    location=location,
                    ip_configurations=[
                        NetworkInterfaceIPConfiguration(
                            name="stratum-ipconfig",
                            subnet={"id": subnet_id},
                            public_ip_address={"id": pip.id},
                        )
                    ],
                ),
            )
            nic = _wait_lro(nic_poller, timeout=120)
            resources_to_delete.append(("nic", nic_name))

            # Resolve IP (may need re-fetch after VM start)
            pip = network.public_ip_addresses.get(rg, pip_name)

            # 4. Parse image reference: "publisher:offer:sku:version"
            img_parts = base_image_ref.split(":")
            if len(img_parts) == 4:
                image_ref = ImageReference(
                    publisher=img_parts[0],
                    offer=img_parts[1],
                    sku=img_parts[2],
                    version=img_parts[3],
                )
            else:
                # Treat as resource ID of a managed image or shared image version
                image_ref = ImageReference(id=base_image_ref)

            # 5. Create VM
            logger.info("Creating VM %s (%s)", vm_name, vm_size)
            vm_params = VirtualMachine(
                location=location,
                hardware_profile=HardwareProfile(vm_size=vm_size),
                storage_profile=StorageProfile(
                    image_reference=image_ref,
                    os_disk=OSDisk(
                        name=disk_name,
                        create_option=DiskCreateOptionTypes.FROM_IMAGE,
                        disk_size_gb=disk_gb,
                        managed_disk=ManagedDiskParameters(storage_account_type="Premium_LRS"),
                        caching=CachingTypes.READ_WRITE,
                        delete_option="Delete",
                    ),
                ),
                os_profile=OSProfile(
                    computer_name="stratum-build",
                    admin_username=ssh_user,
                    linux_configuration=LinuxConfiguration(
                        disable_password_authentication=True,
                        ssh=SshConfiguration(
                            public_keys=[
                                SshPublicKey(
                                    path=f"/home/{ssh_user}/.ssh/authorized_keys",
                                    key_data=pub_key,
                                )
                            ]
                        ),
                    ),
                ),
                network_profile=NetworkProfile(
                    network_interfaces=[NetworkInterfaceReference(id=nic.id, primary=True)],
                ),
                tags={"managed-by": "stratum", "blueprint": profile_name},
            )
            vm_poller = compute.virtual_machines.begin_create_or_update(rg, vm_name, vm_params)
            _wait_lro(vm_poller, timeout=600)
            resources_to_delete.append(("vm", vm_name))
            logger.info("VM %s created", vm_name)

            # 6. Get public IP
            pip = network.public_ip_addresses.get(rg, pip_name)
            ip_address = pip.ip_address
            if not ip_address:
                raise RuntimeError(f"Could not obtain public IP for VM {vm_name}")
            logger.info("VM %s is at %s", vm_name, ip_address)

            # 7. Wait for SSH + cloud-init
            utils.wait_for_ssh(ip_address, timeout=300)
            utils.wait_for_cloud_init(ip_address, ssh_user, key_path, timeout=180)

            # 8. Pre-hardening
            if prehard_playbook_yaml:
                logger.info("Applying pre-hardening configuration…")
                utils.install_ansible_on_remote(ip_address, ssh_user, key_path)
                utils.run_prehard_ansible_remote(ip_address, ssh_user, key_path, prehard_playbook_yaml)

            # 9. Pluggable Hardening
            logger.info("Running compliance hardening…")
            utils.install_ansible_on_remote(ip_address, ssh_user, key_path)
            hardening_config = params.get("hardening", {})
            utils.run_hardening_remote(ip_address, ssh_user, key_path, os_name, hardening_config)

            # 10. OpenSCAP
            logger.info("Running OpenSCAP scan…")
            utils.install_oscap_on_remote(ip_address, ssh_user, key_path, os_name=os_name, datastream=datastream)
            utils.run_oscap_remote(ip_address, ssh_user, key_path, profile_id, datastream)

            # 10.5. Cleanup history
            utils.cleanup_instance_history_remote(ip_address, ssh_user, key_path)

            # 11. Deallocate + generalize VM for image capture
            logger.info("Deallocating VM %s…", vm_name)
            dealloc_poller = compute.virtual_machines.begin_deallocate(rg, vm_name)
            _wait_lro(dealloc_poller, timeout=300)

            logger.info("Generalizing VM %s…", vm_name)
            compute.virtual_machines.generalize(rg, vm_name)

            # 12. Capture managed image
            logger.info("Capturing managed image: %s", captured_image_name)
            from azure.mgmt.compute.models import Image

            img_poller = compute.images.begin_create_or_update(
                rg,
                captured_image_name,
                Image(
                    location=location,
                    source_virtual_machine={"id": compute.virtual_machines.get(rg, vm_name).id},
                    tags={"managed-by": "stratum", "blueprint": profile_name},
                ),
            )
            _wait_lro(img_poller, timeout=600)
            logger.info("Managed image %s created", captured_image_name)

            return {
                "status": "success",
                "artifact_id": captured_image_name,
                "artifact_type": "azure_managed_image",
                "region": location,
                "metadata": {
                    "resource_group": rg,
                    "subscription_id": subscription_id,
                    "profile_name": profile_name,
                    "profile_version": profile_version,
                },
            }

        finally:
            # Cleanup build resources in reverse order
            for res_type, res_name in reversed(resources_to_delete):
                try:
                    if res_type == "vm":
                        compute.virtual_machines.begin_delete(rg, res_name).result()
                    elif res_type == "nic":
                        network.network_interfaces.begin_delete(rg, res_name).result()
                    elif res_type == "pip":
                        network.public_ip_addresses.begin_delete(rg, res_name).result()
                    elif res_type == "vnet":
                        network.virtual_networks.begin_delete(rg, res_name).result()
                    logger.info("Deleted %s %s", res_type, res_name)
                except Exception as exc:
                    logger.warning("Failed to delete %s %s: %s", res_type, res_name, exc)


def execute_audit(params: dict) -> dict:
    """Run OpenSCAP audit on a running Azure VM via SSH.

    Required params:
        target_ip  — Public IP of the target VM
        ssh_user   — SSH username
        ssh_key    — Private key PEM string
        profile    — XCCDF profile ID
        datastream — Path to SCAP datastream on the VM
    """
    os_name = params.get("os", "ubuntu22")
    target_ip = params.get("target_ip", "")
    ssh_user = params.get("ssh_user") or utils.default_ssh_user(os_name)
    ssh_key_pem = params.get("ssh_key", "")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not target_ip:
        raise ValueError("execute_audit requires 'target_ip'")
    if not ssh_key_pem:
        raise ValueError("execute_audit requires 'ssh_key' (private key PEM)")

    with tempfile.TemporaryDirectory(prefix="stratum-az-audit-") as tmpdir:
        key_path = Path(tmpdir) / "audit_key"
        key_path.write_text(ssh_key_pem)
        key_path.chmod(0o600)
        utils.install_oscap_on_remote(target_ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
        xml = utils.run_oscap_remote(target_ip, ssh_user, key_path, profile_id, datastream)

    return {"status": "success", "raw_xml": xml}


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return Azure Marketplace images for a given publisher.

    Params:
        credentials    — SP credentials (tenant_id, client_id, client_secret, subscription_id)
        location       — Azure region (default: eastus)
        publisher      — Publisher name (default: Canonical)
    """
    credentials = params.get("credentials", params)
    location = params.get("location") or credentials.get("location") or "eastus"
    publisher = params.get("publisher", "Canonical")
    try:
        cred = _get_credential(credentials)
        compute = _compute_client(cred, credentials["subscription_id"])
        offers = list(compute.virtual_machine_images.list_offers(location, publisher))
        images = []
        for offer in offers[:5]:  # limit to avoid excessive API calls
            skus = list(compute.virtual_machine_images.list_skus(location, publisher, offer.name))
            for sku in skus[:3]:
                images.append(
                    {
                        "id": f"{publisher}:{offer.name}:{sku.name}:latest",
                        "name": f"{publisher} {offer.name} {sku.name}",
                        "publisher": publisher,
                        "offer": offer.name,
                        "sku": sku.name,
                    }
                )
        return {"images": images}
    except Exception as exc:
        logger.warning("list_images failed: %s", exc)
        return {"images": []}


_DISPATCH = {
    "test_connection": test_connection,
    "execute_build": execute_build,
    "execute_audit": execute_audit,
    "list_images": list_images,
}


def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps(_err(None, -32700, f"Parse error: {exc}")), flush=True)
        sys.exit(1)

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method not in _DISPATCH:
        print(json.dumps(_err(req_id, -32601, f"Method not found: {method!r}")), flush=True)
        sys.exit(1)

    try:
        result = _DISPATCH[method](params)
        print(json.dumps(_ok(req_id, result)), flush=True)
    except Exception as exc:
        logger.error("execute error: %s", exc)
        print(json.dumps(_err(req_id, -32603, str(exc))), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
