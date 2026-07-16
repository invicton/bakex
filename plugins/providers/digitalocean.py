#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""DigitalOcean subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [digitalocean] optional extra: pip install bakex[digitalocean]
  pip install requests

Credential fields (stored via BakeX integrations UI):
    api_token      — DigitalOcean personal access token (required)
    region         — DO region slug, e.g. "nyc3" (default: nyc3)
    ssh_key_ids    — comma-separated DO SSH key IDs to add to Droplet (optional)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

PROVIDER_NAME = "digitalocean"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[digitalocean] %(message)s")
logger = logging.getLogger(__name__)

# Import shared SSH utilities from the same directory
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
# DigitalOcean API client (thin wrapper around requests)
# ---------------------------------------------------------------------------


class DOClient:
    BASE = "https://api.digitalocean.com/v2"

    def __init__(self, token: str) -> None:
        try:
            import requests as _requests
        except ImportError as exc:
            raise RuntimeError("requests is not installed. Install with: pip install bakex[digitalocean]") from exc
        self._s = _requests.Session()
        self._s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def get(self, path: str, **kwargs):
        r = self._s.get(f"{self.BASE}{path}", **kwargs)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict, **kwargs):
        r = self._s.post(f"{self.BASE}{path}", json=body, **kwargs)
        r.raise_for_status()
        return r.json()

    def delete(self, path: str, **kwargs):
        r = self._s.delete(f"{self.BASE}{path}", **kwargs)
        if r.status_code not in (204, 200):
            r.raise_for_status()

    # ---- higher-level helpers ----

    def wait_droplet_status(self, droplet_id: int, status: str = "active", timeout: int = 300) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.get(f"/droplets/{droplet_id}")["droplet"]
            if d["status"] == status:
                return d
            logger.info("Droplet %s status: %s — waiting…", droplet_id, d["status"])
            time.sleep(15)
        raise TimeoutError(f"Droplet {droplet_id} did not reach status '{status}' within {timeout}s")

    def wait_action(self, action_id: int, timeout: int = 1800) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            a = self.get(f"/actions/{action_id}")["action"]
            if a["status"] == "completed":
                return a
            if a["status"] == "errored":
                raise RuntimeError(f"DigitalOcean action {action_id} errored")
            logger.info("Action %s: %s — waiting…", action_id, a["status"])
            time.sleep(15)
        raise TimeoutError(f"Action {action_id} did not complete within {timeout}s")

    def add_ssh_key(self, name: str, public_key: str) -> int:
        """Upload a public key and return its DO key ID."""
        body = self.post("/account/keys", {"name": name, "public_key": public_key})
        return body["ssh_key"]["id"]

    def delete_ssh_key(self, key_id: int) -> None:
        try:
            self.delete(f"/account/keys/{key_id}")
        except Exception as exc:
            logger.warning("Failed to delete SSH key %s: %s", key_id, exc)


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate DO credentials by fetching account info."""
    token = params.get("api_token") or params.get("credentials", {}).get("api_token", "")
    if not token:
        raise ValueError("api_token must not be empty")
    client = DOClient(token)
    account = client.get("/account")["account"]
    logger.info("test_connection: account %s", account.get("email"))
    return {
        "status": "ok",
        "email": account.get("email"),
        "uuid": account.get("uuid"),
        "droplet_limit": account.get("droplet_limit"),
    }


def execute_build(params: dict) -> dict:
    """Droplet → pre-harden → Ansible-Lockdown → OpenSCAP → Snapshot → Destroy pipeline.

    Credential / param fields:
        api_token        — DO personal access token
        region           — DO region slug (default: nyc3)
        size_slug        — Droplet size (default: s-2vcpu-4gb; overridden by instance_type)
        base_image       — DO image slug or ID (e.g. "ubuntu-22-04-x64")
        os               — OS identifier for ansible-lockdown role selection
        instance_type    — Maps to size_slug if provided
        root_volume_size_gb — ignored for DO (all-in-one disk; use size_slug for sizing)
        prehard_playbook_yaml — Pre-hardening playbook YAML (from BakeX engine)
        profile_name / profile_version — for snapshot naming
        profile / datastream — SCAP profile ID and datastream path for oscap
    """
    credentials = params.get("credentials", params)
    api_token = credentials.get("api_token", "")
    if not api_token:
        raise ValueError("api_token is required")

    region = credentials.get("region") or params.get("region") or "nyc3"
    size_slug = params.get("instance_type") or credentials.get("size_slug") or "s-2vcpu-4gb"
    base_image = params.get("base_image", "ubuntu-22-04-x64")
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")
    prehard_playbook_yaml: str = params.get("prehard_playbook_yaml", "")

    ssh_user = utils.default_ssh_user(os_name)
    client = DOClient(api_token)
    droplet_id: int | None = None
    temp_key_id: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-do-") as tmpdir:
        tmp = Path(tmpdir)
        try:
            # 1. Generate ephemeral SSH key pair
            key_path, pub_key = utils.generate_ssh_keypair(tmp)
            key_name = f"bakex-build-{profile_name}-{int(time.time())}"
            temp_key_id = client.add_ssh_key(key_name, pub_key)
            logger.info("Uploaded ephemeral SSH key: id=%s", temp_key_id)

            # 2. Create Droplet
            logger.info("Creating Droplet: %s / %s / %s", base_image, size_slug, region)
            droplet_body = {
                "name": f"bakex-build-{profile_name}",
                "region": region,
                "size": size_slug,
                "image": base_image,
                "ssh_keys": [temp_key_id],
                "backups": False,
                "ipv6": False,
                "monitoring": False,
                "tags": ["bakex", "hardening-build"],
            }
            resp = client.post("/droplets", droplet_body)
            droplet_id = resp["droplet"]["id"]
            logger.info("Droplet %s created — waiting for active…", droplet_id)

            # 3. Wait for active
            droplet = client.wait_droplet_status(droplet_id, "active", timeout=300)
            networks = droplet.get("networks", {}).get("v4", [])
            public_ips = [n["ip_address"] for n in networks if n.get("type") == "public"]
            if not public_ips:
                raise RuntimeError(f"Droplet {droplet_id} has no public IPv4 address")
            ip = public_ips[0]
            logger.info("Droplet %s is active at %s", droplet_id, ip)

            # 4. Wait for SSH
            utils.wait_for_ssh(ip, timeout=300)
            # Extra grace period for cloud-init to finish
            time.sleep(20)

            # 5. Pre-hardening system configuration
            if prehard_playbook_yaml:
                logger.info("Applying pre-hardening configuration…")
                utils.install_ansible_on_remote(ip, ssh_user, key_path)
                utils.run_prehard_ansible_remote(ip, ssh_user, key_path, prehard_playbook_yaml)

            # 6. Pluggable Hardening
            logger.info("Running compliance hardening…")
            utils.install_ansible_on_remote(ip, ssh_user, key_path)
            hardening_config = params.get("hardening", {})
            utils.run_hardening_remote(ip, ssh_user, key_path, os_name, hardening_config)

            # 7. OpenSCAP compliance scan
            logger.info("Running OpenSCAP compliance scan…")
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)

            # 7.5. Cleanup history
            utils.cleanup_instance_history_remote(ip, ssh_user, key_path)

            # 8. Power off Droplet before snapshot
            logger.info("Powering off Droplet %s for snapshot…", droplet_id)
            action_resp = client.post(f"/droplets/{droplet_id}/actions", {"type": "power_off"})
            client.wait_action(action_resp["action"]["id"], timeout=120)

            # 9. Create snapshot
            snap_name = f"bakex-{profile_name}-{profile_version}"
            logger.info("Creating snapshot: %s", snap_name)
            snap_resp = client.post(f"/droplets/{droplet_id}/actions", {"type": "snapshot", "name": snap_name})
            action = client.wait_action(snap_resp["action"]["id"], timeout=1800)

            # Retrieve snapshot ID from the resource_id on the action
            snapshot_id = str(action.get("resource_id", ""))
            if not snapshot_id or snapshot_id == "0":
                # Fall back: list snapshots and find by name
                snaps = client.get(f"/droplets/{droplet_id}/snapshots")
                for s in snaps.get("snapshots", []):
                    if s.get("name") == snap_name:
                        snapshot_id = str(s["id"])
                        break
            logger.info("Snapshot created: %s", snapshot_id)

            return {
                "status": "success",
                "artifact_id": snapshot_id,
                "artifact_type": "digitalocean_snapshot",
                "region": region,
                "metadata": {
                    "profile_name": profile_name,
                    "profile_version": profile_version,
                    "snapshot_name": snap_name,
                    "droplet_id": droplet_id,
                },
            }

        finally:
            # Cleanup: destroy Droplet and ephemeral SSH key
            if droplet_id:
                logger.info("Destroying Droplet %s…", droplet_id)
                try:
                    client.delete(f"/droplets/{droplet_id}")
                except Exception as exc:
                    logger.warning("Failed to destroy Droplet %s: %s", droplet_id, exc)
            if temp_key_id:
                client.delete_ssh_key(temp_key_id)


def execute_audit(params: dict) -> dict:
    """Run an OpenSCAP audit on a running DigitalOcean Droplet via SSH.

    Required params:
        target_ip    — Public IP of the Droplet to audit
        ssh_user     — SSH user (default derived from 'os' field)
        ssh_key      — Private key PEM string for SSH access
        profile      — XCCDF profile ID
        datastream   — Path to SCAP datastream on the instance
    """
    target_ip = params.get("target_ip", "")
    os_name = params.get("os", "ubuntu22")
    ssh_user = params.get("ssh_user") or utils.default_ssh_user(os_name)
    ssh_key_pem = params.get("ssh_key", "")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not target_ip:
        raise ValueError("execute_audit requires 'target_ip'")
    if not ssh_key_pem:
        raise ValueError("execute_audit requires 'ssh_key' (private key PEM)")

    with tempfile.TemporaryDirectory(prefix="bakex-do-audit-") as tmpdir:
        key_path = Path(tmpdir) / "audit_key"
        key_path.write_text(ssh_key_pem)
        key_path.chmod(0o600)

        utils.install_oscap_on_remote(target_ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
        xml = utils.run_oscap_remote(target_ip, ssh_user, key_path, profile_id, datastream)

    return {"status": "success", "raw_xml": xml}


def execute_scan_image(params: dict) -> dict:
    """Provision a temporary Droplet from a snapshot/image, scan it with OpenSCAP, then destroy it.

    Required params:
        image_id      — DO image slug or numeric ID (snapshot, distribution image, etc.)
        credentials   — {api_token, region, size_slug, ...}
        os            — OS identifier (e.g. "ubuntu22")
        profile       — XCCDF profile ID
        datastream    — Path to SCAP datastream on the instance
    """
    credentials = params.get("credentials", params)
    api_token = credentials.get("api_token", "")
    if not api_token:
        raise ValueError("api_token is required")

    region = params.get("region") or credentials.get("region") or "nyc3"
    size_slug = params.get("instance_type") or credentials.get("size_slug") or "s-2vcpu-4gb"
    image_id = params.get("image_id", "")
    os_name = params.get("os", "ubuntu22")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not image_id:
        raise ValueError("execute_scan_image requires 'image_id'")

    ssh_user = utils.default_ssh_user(os_name)
    client = DOClient(api_token)
    droplet_id: int | None = None
    temp_key_id: int | None = None

    with tempfile.TemporaryDirectory(prefix="bakex-do-scan-") as tmpdir:
        tmp = Path(tmpdir)
        try:
            key_path, pub_key = utils.generate_ssh_keypair(tmp)
            key_name = f"bakex-scan-{int(time.time())}"
            temp_key_id = client.add_ssh_key(key_name, pub_key)

            droplet_body = {
                "name": f"bakex-scan-{int(time.time())}",
                "region": region,
                "size": size_slug,
                "image": image_id,
                "ssh_keys": [temp_key_id],
                "backups": False,
                "tags": ["bakex", "image-scan"],
            }
            resp = client.post("/droplets", droplet_body)
            droplet_id = resp["droplet"]["id"]
            droplet = client.wait_droplet_status(droplet_id, "active", timeout=300)
            networks = droplet.get("networks", {}).get("v4", [])
            public_ips = [n["ip_address"] for n in networks if n.get("type") == "public"]
            if not public_ips:
                raise RuntimeError(f"Scan droplet {droplet_id} has no public IPv4 address")
            ip = public_ips[0]

            utils.wait_for_ssh(ip, timeout=300)
            time.sleep(15)
            utils.install_oscap_on_remote(ip, ssh_user, key_path, os_name=os_name, datastream=datastream)
            xml = utils.run_oscap_remote(ip, ssh_user, key_path, profile_id, datastream)
            return {"status": "success", "raw_xml": xml}

        finally:
            if droplet_id:
                try:
                    client.delete(f"/droplets/{droplet_id}")
                except Exception:
                    logger.warning("Failed to destroy scan droplet %s", droplet_id)
            if temp_key_id:
                try:
                    client.delete(f"/account/keys/{temp_key_id}")
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------


def list_images(params: dict) -> dict:
    """Return available DigitalOcean base images filtered by OS type.

    Params:
        api_token  — DO personal access token
        type       — "distribution" | "application" | "backup" | "snapshot" (default: distribution)
    """
    credentials = params.get("credentials", params)
    api_token = credentials.get("api_token", "")
    if not api_token:
        return {"images": []}
    img_type = params.get("type", "distribution")
    client = DOClient(api_token)
    try:
        resp = client.get(f"/images?type={img_type}&per_page=100")
        images = [
            {
                "id": str(img["slug"] or img["id"]),
                "name": img["name"],
                "distribution": img.get("distribution", ""),
                "size_gigabytes": img.get("size_gigabytes", 0),
                "regions": img.get("regions", []),
            }
            for img in resp.get("images", [])
            if img.get("public")
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
