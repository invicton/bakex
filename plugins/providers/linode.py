#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Linode (Akamai Cloud) subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [linode] optional extra: pip install bakex[linode]

Credential fields (stored via BakeX integrations UI):
    api_token   — Linode personal access token (required)
    region      — Linode region ID, e.g. "us-east" (default: us-east)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_NAME = "linode"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[linode] %(message)s")
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
# Linode client helpers
# ---------------------------------------------------------------------------


def _get_client(token: str):
    try:
        from linode_api4 import LinodeClient
    except ImportError as exc:
        raise RuntimeError("linode-api4 is not installed. Install with: pip install bakex[linode]") from exc
    return LinodeClient(token)


def _wait_linode_status(client, linode_id: int, status: str, timeout: int = 300):
    """Poll until Linode reaches *status* or raise TimeoutError."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # linode_api4 uses client.linode.instances(id)
        instances = client.linode.instances(filters={"id": linode_id})
        if instances and instances[0].status == status:
            return instances[0]
        current = instances[0].status if instances else "unknown"
        logger.info("Linode %s status: %s — waiting for %s…", linode_id, current, status)
        time.sleep(15)
    raise TimeoutError(f"Linode {linode_id} did not reach status '{status}' within {timeout}s")


def _poll_image_status(client, image_id: str, timeout: int = 1800):
    """Poll until the private image is available."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        img = client.images(filters={"id": image_id})
        if img and img[0].status == "available":
            return img[0]
        status = img[0].status if img else "unknown"
        logger.info("Image %s status: %s — waiting…", image_id, status)
        time.sleep(30)
    raise TimeoutError(f"Image {image_id} did not become available within {timeout}s")


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Linode credentials by fetching account info."""
    credentials = params.get("credentials", params)
    token = credentials.get("api_token", "")
    if not token:
        raise ValueError("api_token is required")

    client = _get_client(token)
    account = client.account()
    logger.info("test_connection: Linode account %s", account.email)
    return {
        "status": "ok",
        "email": account.email,
        "company": getattr(account, "company", ""),
    }


def execute_build(params: dict) -> dict:
    """Linode → pre-harden → Ansible-Lockdown → OpenSCAP → image → destroy pipeline.

    Credential / param fields:
        api_token         — Linode personal access token (required)
        region            — Linode region (default: us-east)
        linode_type       — Instance type slug (default: g6-standard-2; overridden by instance_type)
        base_image        — Linode image ID, e.g. "linode/ubuntu22.04" or "linode/rocky9"
        instance_type     — Maps to linode_type if provided
        root_password     — Root password for initial login (auto-generated if absent)
        os                — OS identifier for lockdown role selection
        prehard_playbook_yaml — Generated pre-hardening playbook YAML
        profile / datastream  — SCAP profile and datastream path
    """
    credentials = params.get("credentials", {})
    token = credentials.get("api_token", "")
    if not token:
        raise ValueError("api_token is required")

    region = credentials.get("region") or params.get("region") or "us-east"
    linode_type = params.get("instance_type") or credentials.get("linode_type") or "g6-standard-2"
    base_image = params.get("base_image", "linode/ubuntu22.04")
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")

    ssh_user = "root"  # Linode instances always allow root SSH initially

    client = _get_client(token)
    linode_id: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-linode-") as tmpdir:
        tmp = Path(tmpdir)
        key_path, pub_key = utils.generate_ssh_keypair(tmp)

        try:
            # 1. Create Linode instance
            import secrets

            root_pass = credentials.get("root_password") or (secrets.token_urlsafe(24))
            logger.info("Creating Linode %s / %s in %s", linode_type, base_image, region)
            instance, _ = client.linode.instance_create(
                linode_type=linode_type,
                region=region,
                image=base_image,
                label=f"bakex-build-{profile_name[:20]}",
                root_pass=root_pass,
                authorized_keys=[pub_key],
                tags=["bakex", "hardening-build"],
                booted=True,
            )
            linode_id = instance.id
            logger.info("Linode %s created, waiting for running state…", linode_id)

            # 2. Wait for running
            deadline = time.time() + 300
            while time.time() < deadline:
                instance._api_get()
                if instance.status == "running":
                    break
                logger.info("Linode %s status: %s", linode_id, instance.status)
                time.sleep(15)
            else:
                raise TimeoutError(f"Linode {linode_id} did not reach 'running' within 300s")

            ip = instance.ipv4[0] if instance.ipv4 else None
            if not ip:
                raise RuntimeError(f"Linode {linode_id} has no IPv4 address")
            logger.info("Linode %s running at %s", linode_id, ip)

            # 3. Wait for SSH
            utils.wait_for_ssh(ip, timeout=300)
            utils.wait_for_cloud_init(ip, ssh_user, key_path, timeout=180)

            # 4. Pre-hardening
            if prehard_playbook_yaml:
                logger.info("Applying pre-hardening configuration…")
                utils.install_ansible_on_remote(ip, ssh_user, key_path)
                utils.run_prehard_ansible_remote(ip, ssh_user, key_path, prehard_playbook_yaml)

            # 5. Pluggable Hardening
            logger.info("Running compliance hardening…")
            utils.install_ansible_on_remote(ip, ssh_user, key_path)
            hardening_config = params.get("hardening", {})
            utils.run_hardening_remote(ip, ssh_user, key_path, os_name, hardening_config)

            # 6. OpenSCAP
            logger.info("Running OpenSCAP scan…")
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)

            # 6.5. Cleanup history
            utils.cleanup_instance_history_remote(ip, ssh_user, key_path)

            # 7. Power off before creating image
            logger.info("Shutting down Linode %s for image capture…", linode_id)
            instance.shutdown()
            deadline = time.time() + 180
            while time.time() < deadline:
                instance._api_get()
                if instance.status == "offline":
                    break
                time.sleep(10)

            # 8. Create image from primary disk
            disks = instance.disks
            if not disks:
                raise RuntimeError(f"Linode {linode_id} has no disks")
            primary_disk = disks[0]
            image_label = f"bakex-{profile_name[:30]}-{profile_version}"
            logger.info("Creating Linode image from disk %s: %s", primary_disk.id, image_label)
            image = client.images.create(
                disk=primary_disk,
                label=image_label,
                description=f"BakeX hardened image: {profile_name} v{profile_version}",
            )
            logger.info("Image %s creation in progress…", image.id)

            # 9. Wait for image to be available
            deadline = time.time() + 1800
            while time.time() < deadline:
                image._api_get()
                if image.status == "available":
                    break
                logger.info("Image %s status: %s", image.id, image.status)
                time.sleep(30)
            else:
                raise TimeoutError(f"Image {image.id} did not become available within 1800s")

            logger.info("Linode image %s is available", image.id)
            return {
                "status": "success",
                "artifact_id": image.id,
                "artifact_type": "linode_image",
                "region": region,
                "metadata": {
                    "profile_name": profile_name,
                    "profile_version": profile_version,
                    "image_label": image_label,
                    "linode_id": linode_id,
                },
            }

        finally:
            if linode_id:
                logger.info("Deleting Linode %s…", linode_id)
                try:
                    client.linode.instance_delete(linode_id)
                except Exception as exc:
                    logger.warning("Failed to delete Linode %s: %s", linode_id, exc)


def execute_audit(params: dict) -> dict:
    """Run OpenSCAP audit on a running Linode via SSH.

    Required params:
        target_ip  — Public IP of the target Linode
        ssh_user   — SSH username (default: root)
        ssh_key    — Private key PEM string
        profile    — XCCDF profile ID
        datastream — Path to SCAP datastream on the instance
    """
    os_name = params.get("os", "ubuntu22")
    target_ip = params.get("target_ip", "")
    ssh_user = params.get("ssh_user") or "root"
    ssh_key_pem = params.get("ssh_key", "")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not target_ip:
        raise ValueError("execute_audit requires 'target_ip'")
    if not ssh_key_pem:
        raise ValueError("execute_audit requires 'ssh_key' (private key PEM)")

    with tempfile.TemporaryDirectory(prefix="bakex-linode-audit-") as tmpdir:
        key_path = Path(tmpdir) / "audit_key"
        key_path.write_text(ssh_key_pem)
        key_path.chmod(0o600)
        utils.install_oscap_on_remote(target_ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
        xml = utils.run_oscap_remote(target_ip, ssh_user, key_path, profile_id, datastream)

    return {"status": "success", "raw_xml": xml}


def execute_scan_image(params: dict) -> dict:
    """Provision a temporary Linode from an image, scan with OpenSCAP, then delete it.

    Required params:
        image_id      — Linode image ID (e.g. "linode/ubuntu22.04" or private image ID)
        credentials   — {api_token, region, linode_type, ...}
        os            — OS identifier (e.g. "ubuntu22")
        profile       — XCCDF profile ID
        datastream    — Path to SCAP datastream on the instance
    """
    import secrets

    credentials = params.get("credentials", params)
    token = credentials.get("api_token", "")
    if not token:
        raise ValueError("api_token is required")

    region = params.get("region") or credentials.get("region") or "us-east"
    linode_type = params.get("instance_type") or credentials.get("linode_type") or "g6-standard-2"
    image_id = params.get("image_id", "")
    os_name = params.get("os", "ubuntu22")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not image_id:
        raise ValueError("execute_scan_image requires 'image_id'")

    ssh_user = utils.default_ssh_user(os_name)
    client = _get_client(token)
    linode_id: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-linode-scan-") as tmpdir:
        tmp = Path(tmpdir)
        key_path, pub_key = utils.generate_ssh_keypair(tmp)
        try:
            root_pass = secrets.token_urlsafe(24)
            instance, _ = client.linode.instance_create(
                linode_type=linode_type,
                region=region,
                image=image_id,
                label=f"bakex-scan-{int(time.time())}",
                root_pass=root_pass,
                authorized_keys=[pub_key],
                tags=["bakex", "image-scan"],
                booted=True,
            )
            linode_id = instance.id

            deadline = time.time() + 300
            while time.time() < deadline:
                instance._api_get()
                if instance.status == "running":
                    break
                time.sleep(15)
            else:
                raise TimeoutError(f"Scan Linode {linode_id} did not reach 'running' within 300s")

            ip = instance.ipv4[0] if instance.ipv4 else None
            if not ip:
                raise RuntimeError(f"Scan Linode {linode_id} has no IPv4 address")

            utils.wait_for_ssh(ip, timeout=300)
            time.sleep(15)
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            xml = utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)
            return {"status": "success", "raw_xml": xml}

        finally:
            if linode_id:
                try:
                    client.linode.instance_delete(linode_id)
                except Exception:
                    logger.warning("Failed to delete scan Linode %s", linode_id)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return available Linode public images.

    Params:
        api_token — Linode personal access token
    """
    credentials = params.get("credentials", params)
    token = credentials.get("api_token", "")
    if not token:
        return {"images": []}
    try:
        client = _get_client(token)
        images = [
            {
                "id": img.id,
                "name": img.label,
                "vendor": getattr(img, "vendor", "") or "",
                "deprecated": getattr(img, "deprecated", False),
                "size": getattr(img, "size", 0),
            }
            for img in client.images()
            if not getattr(img, "deprecated", False) and getattr(img, "is_public", True)
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
