#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""DigitalOcean subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Connectivity model:
  DigitalOcean has no native agent mechanism (no equivalent to AWS SSM or
  Azure Run Command). All remote execution uses SSH.

  Two options depending on your setup:

  Option A — Public IP (default, works anywhere):
    The build Droplet receives its default public IPv4.
    BakeX connects over the internet (ensure firewall allows port 22
    from the BakeX host only — not 0.0.0.0/0).

  Option B — VPC private networking (recommended for production):
    Set credentials.use_private_ip: true
    The BakeX host must also be a Droplet in the same DigitalOcean
    region/VPC. The build Droplet gets a 10.x.x.x private IP reachable
    within the VPC — no internet exposure needed.

Requires the [digitalocean] optional extra:
    pip install 'bakex[digitalocean]'
    # or: pip install requests
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time

PROVIDER_NAME = "digitalocean"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[digitalocean] %(message)s")
logger = logging.getLogger(__name__)

_DO_API = "https://api.digitalocean.com/v2"


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# DigitalOcean API v2 client (uses requests — no extra SDK needed)
# ---------------------------------------------------------------------------


def _do_api(token: str, method: str, path: str, **kwargs) -> dict | list | None:
    """Make a DigitalOcean API v2 call. Returns parsed JSON or None (204)."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is not installed. Run: pip install 'bakex[digitalocean]'") from exc

    resp = requests.request(
        method,
        f"{_DO_API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
        **kwargs,
    )
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    return resp.json()


def _wait_droplet_status(token: str, droplet_id: int, target: str, timeout: int = 300) -> dict:
    """Poll GET /v2/droplets/{id} until status == target. Returns the droplet dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _do_api(token, "GET", f"/droplets/{droplet_id}")
        droplet = data["droplet"]
        status = droplet["status"]
        logger.info("Droplet %d status: %s (waiting for: %s)", droplet_id, status, target)
        if status == target:
            return droplet
        time.sleep(10)
    raise TimeoutError(f"Droplet {droplet_id} did not reach '{target}' within {timeout}s")


def _wait_action(token: str, droplet_id: int, action_id: int, timeout: int = 300) -> None:
    """Poll a Droplet action until it completes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _do_api(token, "GET", f"/droplets/{droplet_id}/actions/{action_id}")
        action = data["action"]
        status = action["status"]
        logger.info("Action %d status: %s", action_id, status)
        if status == "completed":
            return
        if status == "errored":
            raise RuntimeError(f"DigitalOcean action {action_id} errored")
        time.sleep(10)
    raise TimeoutError(f"Action {action_id} did not complete within {timeout}s")


def _pick_ip(droplet: dict, use_private: bool) -> str:
    """Pick the best IP from a droplet dict."""
    networks = droplet.get("networks", {})
    if use_private:
        for net in networks.get("v4", []):
            if net.get("type") == "private":
                logger.info("Using Droplet private IP: %s", net["ip_address"])
                return net["ip_address"]
        logger.warning("Private IP requested but not found — falling back to public IP")
    for net in networks.get("v4", []):
        if net.get("type") == "public":
            logger.info("Using Droplet public IP: %s", net["ip_address"])
            return net["ip_address"]
    raise RuntimeError("No IPv4 address found on Droplet")


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------


def _generate_ssh_keypair() -> tuple[str, str, str]:
    """Generate an ephemeral ed25519 key pair. Returns (key_path, pub_key, tmp_dir)."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="bakex-do-key-")
    key_path = os.path.join(tmp, "bakex-build")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "bakex-build"],
        check=True,
        capture_output=True,
    )
    with open(f"{key_path}.pub") as fh:
        pub_key = fh.read().strip()
    os.chmod(key_path, 0o600)
    return key_path, pub_key, tmp


def _register_ssh_key(token: str, pub_key: str, label: str) -> int:
    """Register a public key with DigitalOcean. Returns the key ID."""
    data = _do_api(token, "POST", "/account/keys", json={"name": label, "public_key": pub_key})
    return data["ssh_key"]["id"]


def _delete_ssh_key(token: str, key_id: int) -> None:
    """Remove a registered SSH key from DigitalOcean."""
    try:
        _do_api(token, "DELETE", f"/account/keys/{key_id}")
    except Exception as exc:
        logger.warning("Failed to delete SSH key %d from DO account: %s", key_id, exc)


def _wait_for_ssh(host: str, key_path: str, user: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = subprocess.run(
            [
                "ssh",
                "-i",
                key_path,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                f"{user}@{host}",
                "echo ok",
            ],
            capture_output=True,
            timeout=15,
        )
        if res.returncode == 0:
            logger.info("SSH ready on %s", host)
            return
        logger.info("Waiting for SSH on %s…", host)
        time.sleep(10)
    raise TimeoutError(f"SSH on {host} did not become available within {timeout}s")


def _run_ansible_from_yaml(playbook_yaml: str, host: str, key_path: str, user: str, tmp_dir: str) -> None:
    playbook_path = os.path.join(tmp_dir, "prehard.yml")
    with open(playbook_path, "w") as fh:
        fh.write(playbook_yaml)
    _run_ansible_playbook(playbook_path, host, key_path, user)


def _run_ansible_playbook(
    playbook_path: str, host: str, key_path: str, user: str, extra_vars_file: str | None = None, timeout: int = 3600
) -> None:
    cmd = [
        "ansible-playbook",
        "-i",
        f"{host},",
        "--private-key",
        key_path,
        "-u",
        user,
        "--ssh-extra-args",
        "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
    ]
    if extra_vars_file:
        cmd += ["--extra-vars", f"@{extra_vars_file}"]
    cmd.append(playbook_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        logger.info("ansible-playbook stdout:\n%s", result.stdout[-2000:])
    if result.returncode != 0:
        raise RuntimeError(f"ansible-playbook failed (exit {result.returncode}):\n{result.stderr[-2000:]}")


def _run_remote_cmd(host: str, key_path: str, user: str, cmd: str, timeout: int = 600) -> str:
    result = subprocess.run(
        [
            "ssh",
            "-i",
            key_path,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{user}@{host}",
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate the DigitalOcean API token by fetching account info."""
    creds = params.get("credentials", params)
    token = creds.get("api_token", "")
    if not token:
        raise ValueError("credentials.api_token is required")
    try:
        data = _do_api(token, "GET", "/account")
        email = data["account"]["email"]
        logger.info("test_connection: account %s", email)
        return {"status": "ok", "email": email}
    except Exception as exc:
        raise ValueError(f"DigitalOcean connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full Droplet → Ansible hardening → OpenSCAP → Snapshot pipeline.

    Connectivity: SSH to the Droplet's public or VPC private IP.
    Set credentials.use_private_ip: true if the BakeX host is a Droplet
    in the same region/VPC to avoid internet SSH exposure.
    """
    creds = params.get("credentials", {})
    token = creds.get("api_token", "")
    region = creds.get("region", "nyc3")
    size = creds.get("size", "s-2vcpu-4gb")
    use_private_ip = creds.get("use_private_ip", False)

    base_image = params.get("base_image", "ubuntu-22-04-x64")
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not token:
        raise ValueError("credentials.api_token is required")

    key_path, pub_key, tmp_dir = _generate_ssh_keypair()
    safe_name = profile_name.lower().replace("_", "-").replace(".", "-")[:20]
    droplet_name = f"bakex-{safe_name}-{int(time.time())}"
    # DigitalOcean images use 'root' by default
    ssh_user = "root"

    do_ssh_key_id: int | None = None
    droplet_id: int | None = None

    try:
        # Register ephemeral SSH key with DigitalOcean so it can be injected at
        # Droplet creation time (DO does not allow key injection after creation)
        key_label = f"bakex-build-{int(time.time())}"
        logger.info("Registering ephemeral SSH key with DigitalOcean")
        do_ssh_key_id = _register_ssh_key(token, pub_key, key_label)

        # Create Droplet
        droplet_payload: dict = {
            "name": droplet_name,
            "region": region,
            "size": size,
            "image": base_image,
            "ssh_keys": [do_ssh_key_id],
            "tags": ["bakex", "bakex-build"],
            "private_networking": use_private_ip,
        }
        logger.info(
            "Creating Droplet %s (%s) in %s from %s (private_networking=%s)",
            droplet_name,
            size,
            region,
            base_image,
            use_private_ip,
        )
        resp = _do_api(token, "POST", "/droplets", json=droplet_payload)
        droplet_id = resp["droplet"]["id"]
        logger.info("Droplet %d created", droplet_id)

        # Wait for Droplet to become active (fully booted)
        droplet = _wait_droplet_status(token, droplet_id, "active", timeout=300)

        # Pick IP
        connect_ip = _pick_ip(droplet, use_private_ip)

        # Wait for SSH
        _wait_for_ssh(connect_ip, key_path, ssh_user, timeout=300)

        # Pre-hardening system configuration
        prehard_yaml = params.get("prehard_playbook_yaml")
        if prehard_yaml:
            logger.info("Running pre-hardening system configuration")
            _run_ansible_from_yaml(prehard_yaml, connect_ip, key_path, ssh_user, tmp_dir)

        # Pluggable Hardening
        hardening_config = params.get("hardening", {})
        strategy = hardening_config.get("strategy", "ansible-galaxy")

        if strategy == "none":
            logger.info("Hardening strategy is 'none' — skipping CIS compliance playbook.")
        else:
            extra_vars = {
                "profile_name": profile_name,
                "benchmark": params.get("benchmark", ""),
                "profile": profile_id,
                "datastream": datastream,
                "bakex_target_os": os_name,
            }
            extra_vars_path = os.path.join(tmp_dir, "bakex_vars.json")
            with open(extra_vars_path, "w") as fh:
                json.dump(extra_vars, fh)

            if strategy == "ansible-galaxy":
                role = hardening_config.get("role", "auto")
                logger.info("Running Ansible-Lockdown hardening (role: %s)", role)
                # Pass the strategy variables to the local site.yml wrapper
                extra_vars["bakex_lockdown_role"] = role
                with open(extra_vars_path, "w") as fh:
                    json.dump(extra_vars, fh)

                _run_ansible_playbook(
                    "ansible/site.yml",
                    connect_ip,
                    key_path,
                    ssh_user,
                    extra_vars_file=extra_vars_path,
                )

            elif strategy == "git":
                repo_url = hardening_config.get("repo_url", "")
                playbook_file = hardening_config.get("playbook_file", "site.yml")
                if not repo_url:
                    raise ValueError("Hardening strategy is 'git' but 'repo_url' is missing.")

                logger.info("Cloning Git repository %s locally", repo_url)
                clone_dir = os.path.join(tmp_dir, "custom_hardening")
                subprocess.run(["git", "clone", repo_url, clone_dir], check=True)

                playbook_path = os.path.join(clone_dir, playbook_file)
                logger.info("Running custom Git playbook %s", playbook_path)
                _run_ansible_playbook(
                    playbook_path,
                    connect_ip,
                    key_path,
                    ssh_user,
                    extra_vars_file=extra_vars_path,
                )
            else:
                raise ValueError(f"Unknown hardening strategy: {strategy}")

        # OpenSCAP compliance scan
        logger.info("Running OpenSCAP scan")
        _run_remote_cmd(
            connect_ip,
            key_path,
            ssh_user,
            f"oscap xccdf eval --profile {profile_id} --results /tmp/bakex-scap-results.xml {datastream} || true",
            timeout=600,
        )

        # Cleanup history
        logger.info("Cleaning up instance logs and history via SSH")
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
            _run_remote_cmd(connect_ip, key_path, ssh_user, " ; ".join(cleanup_cmds), timeout=120)
        except Exception as exc:
            logger.warning("History cleanup encountered an issue, but proceeding with snapshot: %s", exc)

        # Power off the Droplet before snapshotting (DO requires this)
        logger.info("Powering off Droplet %d for snapshot", droplet_id)
        action_resp = _do_api(
            token,
            "POST",
            f"/droplets/{droplet_id}/actions",
            json={"type": "power_off"},
        )
        _wait_action(token, droplet_id, action_resp["action"]["id"], timeout=300)

        # Create Snapshot
        safe_version = profile_version.replace(".", "-")
        snapshot_name = f"bakex-{safe_name}-{safe_version}"
        logger.info("Creating Droplet snapshot: %s", snapshot_name)
        snap_resp = _do_api(
            token,
            "POST",
            f"/droplets/{droplet_id}/actions",
            json={"type": "snapshot", "name": snapshot_name},
        )
        _wait_action(token, droplet_id, snap_resp["action"]["id"], timeout=600)

        # Retrieve snapshot ID from the Droplet's snapshot list
        snap_data = _do_api(token, "GET", f"/droplets/{droplet_id}/snapshots")
        snapshots = snap_data.get("snapshots", [])
        snapshot = next((s for s in snapshots if s["name"] == snapshot_name), None)
        snapshot_id = str(snapshot["id"]) if snapshot else snapshot_name
        logger.info("Snapshot ready: %s (id: %s)", snapshot_name, snapshot_id)

        return {
            "status": "success",
            "artifact_id": snapshot_id,
            "artifact_type": "digitalocean_snapshot",
            "region": region,
            "metadata": {
                "snapshot_name": snapshot_name,
                "profile_name": profile_name,
                "profile_version": profile_version,
            },
        }

    finally:
        # Delete the build Droplet
        if droplet_id is not None:
            try:
                _do_api(token, "DELETE", f"/droplets/{droplet_id}")
                logger.info("Deleted Droplet %d", droplet_id)
            except Exception as exc:
                logger.warning("Failed to delete Droplet %d: %s", droplet_id, exc)
        # Remove the ephemeral SSH key from the DO account
        if do_ssh_key_id is not None:
            _delete_ssh_key(token, do_ssh_key_id)
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
