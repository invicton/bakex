#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""GCP subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core Stratum engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [gcp] optional extra: pip install stratum[gcp]

Credential fields (stored via Stratum integrations UI):
    project_id            — GCP project ID (required)
    zone                  — Compute zone, e.g. "us-central1-a" (default: us-central1-a)
    service_account_file  — Path to service account JSON key file (optional; uses ADC if absent)
    network               — VPC network name (default: default)
    subnetwork            — Subnetwork name (optional)
    service_account_email — SA email to attach to the VM (optional)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_NAME = "gcp"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[gcp] %(message)s")
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
# GCP compute helpers
# ---------------------------------------------------------------------------


def _get_compute_client(credentials: dict):
    """Return (google.cloud.compute_v1.InstancesClient, project_id, zone)."""
    try:
        from google.cloud import compute_v1
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("google-cloud-compute is not installed. Install with: pip install stratum[gcp]") from exc

    sa_file = credentials.get("service_account_file", "")
    if sa_file and Path(sa_file).exists():
        creds = service_account.Credentials.from_service_account_file(
            sa_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        instances_client = compute_v1.InstancesClient(credentials=creds)
        images_client = compute_v1.ImagesClient(credentials=creds)
        machine_images_client = compute_v1.MachineImagesClient(credentials=creds)
        operations_client = compute_v1.ZoneOperationsClient(credentials=creds)
        global_ops_client = compute_v1.GlobalOperationsClient(credentials=creds)
    else:
        instances_client = compute_v1.InstancesClient()
        images_client = compute_v1.ImagesClient()
        machine_images_client = compute_v1.MachineImagesClient()
        operations_client = compute_v1.ZoneOperationsClient()
        global_ops_client = compute_v1.GlobalOperationsClient()

    return instances_client, images_client, machine_images_client, operations_client, global_ops_client


def _wait_zone_operation(ops_client, project: str, zone: str, operation_name: str, timeout: int = 600):
    from google.cloud.compute_v1.types import Operation

    deadline = time.time() + timeout
    while time.time() < deadline:
        op = ops_client.get(project=project, zone=zone, operation=operation_name)
        if op.status == Operation.Status.DONE:
            if op.error:
                msgs = [e.message for e in op.error.errors]
                raise RuntimeError(f"GCP zone operation failed: {'; '.join(msgs)}")
            return op
        logger.info("Zone operation %s: %s — waiting…", operation_name, op.status.name)
        time.sleep(15)
    raise TimeoutError(f"GCP zone operation {operation_name} did not complete in {timeout}s")


def _wait_global_operation(global_ops_client, project: str, operation_name: str, timeout: int = 600):
    from google.cloud.compute_v1.types import Operation

    deadline = time.time() + timeout
    while time.time() < deadline:
        op = global_ops_client.get(project=project, operation=operation_name)
        if op.status == Operation.Status.DONE:
            if op.error:
                msgs = [e.message for e in op.error.errors]
                raise RuntimeError(f"GCP global operation failed: {'; '.join(msgs)}")
            return op
        logger.info("Global operation %s: %s — waiting…", operation_name, op.status.name)
        time.sleep(15)
    raise TimeoutError(f"GCP global operation {operation_name} did not complete in {timeout}s")


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate GCP credentials by listing zones in the project."""
    credentials = params.get("credentials", params)
    project_id = credentials.get("project_id", "")
    if not project_id:
        raise ValueError("project_id is required")

    try:
        from google.cloud import compute_v1
    except ImportError as exc:
        raise RuntimeError("google-cloud-compute not installed") from exc

    sa_file = credentials.get("service_account_file", "")
    if sa_file and Path(sa_file).exists():
        from google.oauth2 import service_account as _sa

        creds = _sa.Credentials.from_service_account_file(
            sa_file, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        client = compute_v1.RegionsClient(credentials=creds)
    else:
        client = compute_v1.RegionsClient()

    regions = list(client.list(project=project_id))
    logger.info("test_connection: found %d regions in project %s", len(regions), project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "region_count": len(regions),
    }


def execute_build(params: dict) -> dict:
    """GCE instance → pre-harden → Ansible-Lockdown → OpenSCAP → machine image → delete pipeline.

    Credential / param fields:
        project_id            — GCP project (required)
        zone                  — Compute zone (default: us-central1-a)
        service_account_file  — Path to SA JSON key (optional; uses ADC otherwise)
        network               — VPC network (default: default)
        subnetwork            — Subnetwork (optional)
        service_account_email — SA email to attach to the VM (optional)
        base_image            — Image self-link or family, e.g. "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
        instance_type         — Machine type (default: e2-medium)
        root_volume_size_gb   — Boot disk size in GB (default: 20)
        os                    — OS identifier for lockdown role selection
        prehard_playbook_yaml — Generated pre-hardening playbook YAML
        profile / datastream  — SCAP profile and datastream path
    """
    credentials = params.get("credentials", {})
    project_id = credentials.get("project_id", "")
    if not project_id:
        raise ValueError("project_id is required")

    zone = credentials.get("zone") or params.get("zone") or "us-central1-a"
    region = "-".join(zone.split("-")[:2])
    network = credentials.get("network") or "default"
    subnetwork = credentials.get("subnetwork") or ""
    sa_email = credentials.get("service_account_email") or ""

    base_image = params.get("base_image", "")
    machine_type = params.get("instance_type") or credentials.get("machine_type") or "e2-medium"
    disk_gb = int(params.get("root_volume_size_gb") or 20)
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")

    ssh_user = utils.default_ssh_user(os_name)

    (instances_client, images_client, machine_images_client, ops_client, global_ops_client) = _get_compute_client(
        credentials
    )

    instance_name: str | None = None
    try:
        from google.cloud import compute_v1

        with tempfile.TemporaryDirectory(prefix="stratum-gcp-") as tmpdir:
            tmp = Path(tmpdir)
            key_path, pub_key = utils.generate_ssh_keypair(tmp)
            # GCP SSH key metadata format: "username:ssh-rsa AAAA..."
            ssh_meta_value = f"{ssh_user}:{pub_key}"

            # 1. Resolve image self-link
            if base_image.startswith("projects/"):
                image_self_link = f"https://www.googleapis.com/compute/v1/{base_image}"
            elif base_image.startswith("https://"):
                image_self_link = base_image
            else:
                # Treat as image family under a well-known project
                img = images_client.get_from_family(
                    project=base_image.split("/")[0] if "/" in base_image else "ubuntu-os-cloud",
                    family=base_image.split("/")[-1],
                )
                image_self_link = img.self_link

            # 2. Build instance config
            instance_name = f"stratum-build-{profile_name.lower()[:20]}-{int(time.time())}"
            network_interface = compute_v1.NetworkInterface(
                network=f"projects/{project_id}/global/networks/{network}",
                access_configs=[
                    compute_v1.AccessConfig(
                        name="External NAT",
                        type_="ONE_TO_ONE_NAT",
                        network_tier="PREMIUM",
                    )
                ],
            )
            if subnetwork:
                network_interface.subnetwork = f"projects/{project_id}/regions/{region}/subnetworks/{subnetwork}"

            config = compute_v1.Instance(
                name=instance_name,
                machine_type=f"zones/{zone}/machineTypes/{machine_type}",
                disks=[
                    compute_v1.AttachedDisk(
                        boot=True,
                        auto_delete=True,
                        initialize_params=compute_v1.AttachedDiskInitializeParams(
                            source_image=image_self_link,
                            disk_size_gb=disk_gb,
                            disk_type=f"zones/{zone}/diskTypes/pd-ssd",
                        ),
                    )
                ],
                network_interfaces=[network_interface],
                metadata=compute_v1.Metadata(
                    items=[
                        compute_v1.Items(key="ssh-keys", value=ssh_meta_value),
                        compute_v1.Items(key="enable-oslogin", value="false"),
                    ]
                ),
                labels={"managed-by": "stratum", "blueprint": profile_name.lower()[:60]},
                tags=compute_v1.Tags(items=["stratum-build"]),
            )
            if sa_email:
                config.service_accounts = [
                    compute_v1.ServiceAccount(
                        email=sa_email,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    )
                ]

            # 3. Insert instance
            logger.info("Creating GCE instance %s in %s", instance_name, zone)
            op = instances_client.insert(project=project_id, zone=zone, instance_resource=config)
            _wait_zone_operation(ops_client, project_id, zone, op.name, timeout=300)

            # 4. Get external IP
            inst = instances_client.get(project=project_id, zone=zone, instance=instance_name)
            ip = inst.network_interfaces[0].access_configs[0].nat_i_p
            logger.info("Instance %s running at %s", instance_name, ip)

            # 5. Wait for SSH + cloud-init
            utils.wait_for_ssh(ip, timeout=300)
            utils.wait_for_cloud_init(ip, ssh_user, key_path, timeout=180)

            # 6. Pre-hardening
            if prehard_playbook_yaml:
                logger.info("Applying pre-hardening configuration…")
                utils.install_ansible_on_remote(ip, ssh_user, key_path)
                utils.run_prehard_ansible_remote(ip, ssh_user, key_path, prehard_playbook_yaml)

            # 7. Pluggable Hardening
            logger.info("Running compliance hardening…")
            utils.install_ansible_on_remote(ip, ssh_user, key_path)
            hardening_config = params.get("hardening", {})
            utils.run_hardening_remote(ip, ssh_user, key_path, os_name, hardening_config)

            # 8. OpenSCAP
            logger.info("Running OpenSCAP scan…")
            utils.install_oscap_on_remote(ip, ssh_user, key_path)
            utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)

            # 8.5. Cleanup history
            utils.cleanup_instance_history_remote(ip, ssh_user, key_path)

            # 9. Stop instance before image capture
            logger.info("Stopping instance %s for image capture…", instance_name)
            stop_op = instances_client.stop(project=project_id, zone=zone, instance=instance_name)
            _wait_zone_operation(ops_client, project_id, zone, stop_op.name, timeout=300)

            # 10. Create a custom image from the boot disk
            image_name = f"stratum-{profile_name.lower()[:40]}-{profile_version.replace('.', '-')}"
            disk_source = f"projects/{project_id}/zones/{zone}/disks/{instance_name}"
            logger.info("Creating GCP image: %s", image_name)
            image_op = images_client.insert(
                project=project_id,
                image_resource=compute_v1.Image(
                    name=image_name,
                    source_disk=disk_source,
                    description=f"Stratum hardened image: {profile_name} v{profile_version}",
                    labels={"managed-by": "stratum"},
                ),
            )
            _wait_global_operation(global_ops_client, project_id, image_op.name, timeout=600)
            logger.info("GCP image %s created", image_name)

        return {
            "status": "success",
            "artifact_id": image_name,
            "artifact_type": "gcp_image",
            "region": region,
            "metadata": {
                "project_id": project_id,
                "zone": zone,
                "profile_name": profile_name,
                "profile_version": profile_version,
                "image_self_link": f"projects/{project_id}/global/images/{image_name}",
            },
        }

    finally:
        if instance_name:
            logger.info("Deleting instance %s…", instance_name)
            try:
                instances_client.delete(project=project_id, zone=zone, instance=instance_name)
            except Exception as exc:
                logger.warning("Failed to delete instance %s: %s", instance_name, exc)


def execute_audit(params: dict) -> dict:
    """Run OpenSCAP audit on a running GCE instance via SSH.

    Required params:
        target_ip  — External IP of the target instance
        ssh_user   — SSH username (default derived from 'os')
        ssh_key    — Private key PEM string
        profile    — XCCDF profile ID
        datastream — Path to SCAP datastream on the instance
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

    with tempfile.TemporaryDirectory(prefix="stratum-gcp-audit-") as tmpdir:
        key_path = Path(tmpdir) / "audit_key"
        key_path.write_text(ssh_key_pem)
        key_path.chmod(0o600)
        utils.install_oscap_on_remote(target_ip, ssh_user, key_path)
        xml = utils.run_oscap_remote(target_ip, ssh_user, key_path, profile_id, datastream)

    return {"status": "success", "raw_xml": xml}


def execute_scan_image(params: dict) -> dict:
    """Launch a temporary GCE instance from an image, scan with OpenSCAP, then delete it.

    Required params:
        image_id      — GCE image self-link, family path (projects/.../family/...), or URL
        credentials   — {project_id, zone, service_account_file, ...}
        os            — OS identifier (e.g. "ubuntu22")
        profile       — XCCDF profile ID
        datastream    — Path to SCAP datastream on the instance
    """
    credentials = params.get("credentials", {})
    project_id = credentials.get("project_id", "")
    if not project_id:
        raise ValueError("project_id is required")

    zone = credentials.get("zone") or params.get("zone") or "us-central1-a"
    network = credentials.get("network") or "default"
    image_id = params.get("image_id", "")
    machine_type = params.get("instance_type") or credentials.get("machine_type") or "e2-medium"
    os_name = params.get("os", "ubuntu22")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not image_id:
        raise ValueError("execute_scan_image requires 'image_id'")

    ssh_user = utils.default_ssh_user(os_name)
    (instances_client, images_client, machine_images_client, ops_client, global_ops_client) = _get_compute_client(
        credentials
    )

    instance_name: str | None = None
    with tempfile.TemporaryDirectory(prefix="stratum-gcp-scan-") as tmpdir:
        tmp = Path(tmpdir)
        try:
            from google.cloud import compute_v1

            key_path, pub_key = utils.generate_ssh_keypair(tmp)
            ssh_meta_value = f"{ssh_user}:{pub_key}"

            if image_id.startswith("projects/"):
                image_self_link = f"https://www.googleapis.com/compute/v1/{image_id}"
            elif image_id.startswith("https://"):
                image_self_link = image_id
            else:
                img = images_client.get_from_family(
                    project=image_id.split("/")[0] if "/" in image_id else "ubuntu-os-cloud",
                    family=image_id.split("/")[-1],
                )
                image_self_link = img.self_link

            instance_name = f"stratum-scan-{int(time.time())}"
            config = compute_v1.Instance(
                name=instance_name,
                machine_type=f"zones/{zone}/machineTypes/{machine_type}",
                disks=[
                    compute_v1.AttachedDisk(
                        boot=True,
                        auto_delete=True,
                        initialize_params=compute_v1.AttachedDiskInitializeParams(
                            source_image=image_self_link,
                            disk_type=f"zones/{zone}/diskTypes/pd-ssd",
                        ),
                    )
                ],
                network_interfaces=[
                    compute_v1.NetworkInterface(
                        network=f"projects/{project_id}/global/networks/{network}",
                        access_configs=[
                            compute_v1.AccessConfig(
                                name="External NAT",
                                type_="ONE_TO_ONE_NAT",
                                network_tier="PREMIUM",
                            )
                        ],
                    )
                ],
                metadata=compute_v1.Metadata(
                    items=[
                        compute_v1.Items(key="ssh-keys", value=ssh_meta_value),
                        compute_v1.Items(key="enable-oslogin", value="false"),
                    ]
                ),
                tags=compute_v1.Tags(items=["stratum-scan"]),
            )
            op = instances_client.insert(project=project_id, zone=zone, instance_resource=config)
            _wait_zone_operation(ops_client, project_id, zone, op.name)
            inst = instances_client.get(project=project_id, zone=zone, instance=instance_name)
            ip = inst.network_interfaces[0].access_configs[0].nat_i_p
            if not ip:
                raise RuntimeError(f"Scan instance {instance_name} has no external IP")

            utils.wait_for_ssh(ip, timeout=300)
            time.sleep(15)
            utils.install_oscap_on_remote(ip, ssh_user, key_path)
            xml = utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)
            return {"status": "success", "raw_xml": xml}

        finally:
            if instance_name:
                try:
                    instances_client.delete(project=project_id, zone=zone, instance=instance_name)
                except Exception:
                    logger.warning("Failed to delete scan instance %s", instance_name)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return public GCP images for a given project (image family).

    Params:
        project_id      — GCP project for credentials
        image_project   — GCP project to list images from (default: ubuntu-os-cloud)
        service_account_file — path to SA key JSON
    """
    credentials = params.get("credentials", params)
    image_project = params.get("image_project", "ubuntu-os-cloud")
    try:
        from google.cloud import compute_v1

        sa_file = credentials.get("service_account_file", "")
        if sa_file and Path(sa_file).exists():
            from google.oauth2 import service_account as _sa

            creds = _sa.Credentials.from_service_account_file(
                sa_file, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            client = compute_v1.ImagesClient(credentials=creds)
        else:
            client = compute_v1.ImagesClient()
        images = [
            {
                "id": img.self_link,
                "name": img.name,
                "family": img.family or "",
                "disk_size_gb": img.disk_size_gb,
                "status": img.status.name if img.status else "",
            }
            for img in client.list(project=image_project)
            if not img.deprecated
        ]
        return {"images": sorted(images, key=lambda x: x["name"])}
    except Exception as exc:
        logger.warning("list_images failed: %s", exc)
        return {"images": []}


_DISPATCH = {
    "test_connection": test_connection,
    "execute_build": execute_build,
    "execute_audit": execute_audit,
    "execute_scan_image": execute_scan_image,
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
