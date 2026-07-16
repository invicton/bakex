#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Proxmox VE subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [proxmox] optional extra: pip install bakex[proxmox]

Credential fields (stored via BakeX integrations UI):
    host            — Proxmox VE hostname or IP (required)
    user            — Proxmox user, e.g. "root@pam" (default: root@pam)
    password        — Password for user (required unless token_name+token_value provided)
    token_name      — API token name, e.g. "bakex" (alternative to password)
    token_value     — API token secret (alternative to password)
    node            — Proxmox node name (default: pve)
    storage         — Storage ID for new disks (default: local-lvm)
    verify_ssl      — Whether to verify TLS certificate (default: false for self-signed)
    template_vmid   — VMID of the base VM template to clone (maps to base_image in blueprint)
    bridge          — Network bridge (default: vmbr0)
    ciuser          — cloud-init user for SSH access (default: ubuntu / rocky / etc.)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_NAME = "proxmox"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[proxmox] %(message)s")
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
# Proxmox client helpers
# ---------------------------------------------------------------------------


def _get_proxmox(credentials: dict):
    """Return a proxmoxer ProxmoxAPI instance."""
    try:
        from proxmoxer import ProxmoxAPI
    except ImportError as exc:
        raise RuntimeError("proxmoxer is not installed. Install with: pip install bakex[proxmox]") from exc

    host = credentials.get("host", "")
    if not host:
        raise ValueError("credentials.host is required for Proxmox")

    user = credentials.get("user", "root@pam")
    # Stored/submitted as a bool, or "true"/"false" strings from a form/JSON
    # body — a bare `.get(..., False)` would treat the string "false" as truthy.
    verify_ssl = str(credentials.get("verify_ssl", False)).strip().lower() in ("true", "on", "1", "yes")

    token_name = credentials.get("token_name", "")
    token_value = credentials.get("token_value", "")

    if token_name and token_value:
        return ProxmoxAPI(
            host,
            user=user,
            token_name=token_name,
            token_value=token_value,
            verify_ssl=verify_ssl,
        )
    else:
        password = credentials.get("password", "")
        if not password:
            raise ValueError("credentials.password or token_name+token_value required")
        return ProxmoxAPI(host, user=user, password=password, verify_ssl=verify_ssl)


def _next_vmid(proxmox) -> int:
    """Return the next available VMID from the cluster."""
    return int(proxmox.cluster.nextid.get())


def _wait_task(proxmox, node: str, upid: str, timeout: int = 600) -> None:
    """Poll a Proxmox task (UPID) until it completes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = proxmox.nodes(node).tasks(upid).status.get()
        if status.get("status") == "stopped":
            exit_status = status.get("exitstatus", "")
            if exit_status != "OK":
                raise RuntimeError(f"Proxmox task {upid} failed: {exit_status}")
            return
        logger.info("Task %s: %s — waiting…", upid[:30], status.get("status", "?"))
        time.sleep(10)
    raise TimeoutError(f"Proxmox task {upid} did not complete within {timeout}s")


def _get_vm_ip(proxmox, node: str, vmid: int, timeout: int = 300) -> str:
    """Retrieve the VM's IP address via the QEMU guest agent."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ifaces = proxmox.nodes(node).qemu(vmid).agent("network-get-interfaces").get()
            for iface in ifaces.get("result", []):
                if iface.get("name") in ("lo",):
                    continue
                for addr in iface.get("ip-addresses", []):
                    if addr.get("ip-address-type") == "ipv4":
                        ip = addr["ip-address"]
                        if not ip.startswith("127."):
                            logger.info("VM %s IP: %s", vmid, ip)
                            return ip
        except Exception as exc:
            logger.debug("Guest agent not ready yet for %s: %s", vmid, exc)
        time.sleep(15)
    raise TimeoutError(f"Could not get IP for VM {vmid} within {timeout}s")


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Proxmox credentials by fetching node list."""
    credentials = params.get("credentials", params)
    proxmox = _get_proxmox(credentials)
    nodes = proxmox.nodes.get()
    logger.info("test_connection: found %d nodes", len(nodes))
    return {
        "status": "ok",
        "node_count": len(nodes),
        "nodes": [n["node"] for n in nodes],
    }


def execute_build(params: dict) -> dict:
    """Clone template VM → cloud-init → boot → pre-harden → Ansible-Lockdown → OpenSCAP → template.

    Credential / param fields:
        host / user / password (or token_name+token_value) — Proxmox auth (required)
        node            — Proxmox node name (default: pve)
        storage         — Storage for cloned disk (default: local-lvm)
        bridge          — Network bridge (default: vmbr0)
        base_image      — VMID of the template to clone (as a string, e.g. "9000")
        instance_type   — CPU/RAM profile: "2c-4g" maps to cores=2, memory=4096 (default: 2c-4g)
        root_volume_size_gb — Resize boot disk after clone (default: 20)
        os              — OS identifier for lockdown role selection
        prehard_playbook_yaml — Generated pre-hardening playbook YAML
        profile / datastream — SCAP profile and datastream path
    """
    credentials = params.get("credentials", {})
    node = credentials.get("node") or "pve"
    storage = credentials.get("storage") or "local-lvm"
    template_vmid = int(params.get("base_image") or credentials.get("template_vmid") or 0)
    if not template_vmid:
        raise ValueError("base_image (template VMID) is required for Proxmox")

    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")
    disk_gb = int(params.get("root_volume_size_gb") or 20)

    # Parse instance_type "Xc-Yg" → cores, memory
    instance_type = params.get("instance_type") or "2c-4g"
    cores, memory_gb = 2, 4
    if "c-" in instance_type and "g" in instance_type:
        try:
            parts = instance_type.lower().replace("g", "").split("c-")
            cores = int(parts[0])
            memory_gb = int(parts[1])
        except (ValueError, IndexError):
            pass
    memory_mb = memory_gb * 1024

    ssh_user = utils.default_ssh_user(os_name)

    proxmox = _get_proxmox(credentials)
    new_vmid: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-proxmox-") as tmpdir:
        tmp = Path(tmpdir)
        key_path, pub_key = utils.generate_ssh_keypair(tmp)

        try:
            # 1. Clone the template VM to a new VMID
            new_vmid = _next_vmid(proxmox)
            vm_name = f"bakex-build-{profile_name[:20]}-{new_vmid}"
            logger.info("Cloning template VMID %s → %s (%s)", template_vmid, new_vmid, vm_name)
            clone_task = (
                proxmox.nodes(node)
                .qemu(template_vmid)
                .clone.post(
                    newid=new_vmid,
                    name=vm_name,
                    storage=storage,
                    full=1,
                )
            )
            _wait_task(proxmox, node, clone_task, timeout=600)
            logger.info("Clone complete: VMID %s", new_vmid)

            # 2. Configure cloud-init: SSH key, user, resize disk
            qemu = proxmox.nodes(node).qemu(new_vmid)
            config_kwargs: dict = {
                "cores": cores,
                "memory": memory_mb,
                "ciuser": ssh_user,
                "sshkeys": pub_key.replace(" ", "%20").replace("+", "%2B"),
                "ipconfig0": "ip=dhcp",
                "agent": "enabled=1",
            }
            qemu.config.put(**config_kwargs)

            # Resize boot disk
            qemu.resize.put(disk="scsi0", size=f"{disk_gb}G")
            logger.info("Disk resized to %dG", disk_gb)

            # 3. Boot the VM
            logger.info("Starting VM %s…", new_vmid)
            start_task = qemu.status.start.post()
            _wait_task(proxmox, node, start_task, timeout=120)

            # 4. Get IP via guest agent
            ip = _get_vm_ip(proxmox, node, new_vmid, timeout=300)
            utils.wait_for_ssh(ip, timeout=300)
            utils.wait_for_cloud_init(ip, ssh_user, key_path, timeout=180)

            # 5. Pre-hardening
            if prehard_playbook_yaml:
                logger.info("Applying pre-hardening configuration…")
                utils.install_ansible_on_remote(ip, ssh_user, key_path)
                utils.run_prehard_ansible_remote(ip, ssh_user, key_path, prehard_playbook_yaml)

            # 6. Pluggable Hardening
            logger.info("Running compliance hardening…")
            utils.install_ansible_on_remote(ip, ssh_user, key_path)
            hardening_config = params.get("hardening", {})
            utils.run_hardening_remote(ip, ssh_user, key_path, os_name, hardening_config)

            # 7. OpenSCAP
            logger.info("Running OpenSCAP scan…")
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)

            # 7.5. Cleanup history
            utils.cleanup_instance_history_remote(ip, ssh_user, key_path)

            # 8. Shutdown VM cleanly
            logger.info("Shutting down VM %s…", new_vmid)
            stop_task = qemu.status.shutdown.post()
            _wait_task(proxmox, node, stop_task, timeout=120)

            # 9. Convert VM to template
            logger.info("Converting VM %s to template…", new_vmid)
            qemu.template.post()
            logger.info("VM %s is now a Proxmox template", new_vmid)

            return {
                "status": "success",
                "artifact_id": str(new_vmid),
                "artifact_type": "proxmox_template",
                "region": node,
                "metadata": {
                    "node": node,
                    "template_vmid": new_vmid,
                    "vm_name": vm_name,
                    "profile_name": profile_name,
                    "profile_version": profile_version,
                },
            }

        except Exception:
            # On failure, destroy the partially-built VM
            if new_vmid:
                try:
                    logger.info("Destroying failed VM %s…", new_vmid)
                    proxmox.nodes(node).qemu(new_vmid).status.stop.post()
                    time.sleep(10)
                    proxmox.nodes(node).qemu(new_vmid).delete()
                except Exception as exc:
                    logger.warning("Failed to clean up VM %s: %s", new_vmid, exc)
            raise


def execute_audit(params: dict) -> dict:
    """Run OpenSCAP audit on a running Proxmox VM via SSH.

    Required params:
        target_ip  — VM IP address
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

    with tempfile.TemporaryDirectory(prefix="bakex-proxmox-audit-") as tmpdir:
        key_path = Path(tmpdir) / "audit_key"
        key_path.write_text(ssh_key_pem)
        key_path.chmod(0o600)
        utils.install_oscap_on_remote(target_ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
        xml = utils.run_oscap_remote(target_ip, ssh_user, key_path, profile_id, datastream)

    return {"status": "success", "raw_xml": xml}


def execute_scan_image(params: dict) -> dict:
    """Clone a Proxmox template VM, scan it with OpenSCAP, then destroy the clone.

    Required params:
        image_id      — VMID of the source template to clone (string or int)
        credentials   — Proxmox auth dict (host, user, password/token, node, storage)
        os            — OS identifier (e.g. "ubuntu22")
        profile       — XCCDF profile ID
        datastream    — Path to SCAP datastream on the VM
    """
    credentials = params.get("credentials", params)
    node = credentials.get("node", "pve")
    storage = credentials.get("storage", "local-lvm")
    image_id = params.get("image_id", "")
    os_name = params.get("os", "ubuntu22")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not image_id:
        raise ValueError("execute_scan_image requires 'image_id' (template VMID)")

    template_vmid = int(image_id)
    ssh_user = utils.default_ssh_user(os_name)
    proxmox = _get_proxmox(credentials)
    new_vmid: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-proxmox-scan-") as tmpdir:
        tmp = Path(tmpdir)
        key_path, pub_key = utils.generate_ssh_keypair(tmp)
        try:
            new_vmid = _next_vmid(proxmox)
            vm_name = f"bakex-scan-{new_vmid}"
            logger.info("Cloning template VMID %s → %s for scan", template_vmid, new_vmid)
            clone_task = (
                proxmox.nodes(node)
                .qemu(template_vmid)
                .clone.post(
                    newid=new_vmid,
                    name=vm_name,
                    full=1,
                    storage=storage,
                )
            )
            _wait_task(proxmox, node, clone_task, timeout=300)
            proxmox.nodes(node).qemu(new_vmid).status.start.post()
            ip = _get_vm_ip(proxmox, node, new_vmid, timeout=300)
            logger.info("Scan VM %s booted at %s", new_vmid, ip)

            utils.wait_for_ssh(ip, timeout=300)
            time.sleep(15)
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            xml = utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)
            return {"status": "success", "raw_xml": xml}

        finally:
            if new_vmid:
                try:
                    proxmox.nodes(node).qemu(new_vmid).status.stop.post()
                    time.sleep(5)
                    proxmox.nodes(node).qemu(new_vmid).delete()
                except Exception:
                    logger.warning("Failed to destroy scan VM %s", new_vmid)


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return available Proxmox VM templates on the configured node.

    Params:
        credentials — Proxmox auth dict (host, user, password/token, node)
    """
    credentials = params.get("credentials", params)
    node = credentials.get("node", "pve")
    try:
        proxmox = _get_proxmox(credentials)
        vms = proxmox.nodes(node).qemu.get()
        templates = [
            {
                "id": str(vm["vmid"]),
                "name": vm.get("name", f"vm-{vm['vmid']}"),
                "vmid": vm["vmid"],
                "memory": vm.get("maxmem", 0) // 1024 // 1024,
                "cpus": vm.get("cpus", 0),
            }
            for vm in vms
            if vm.get("template") == 1
        ]
        return {"images": sorted(templates, key=lambda x: x["vmid"])}
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
