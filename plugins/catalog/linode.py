#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Linode/Akamai Cloud subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core BakeX engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Connectivity model:
  Linode has no native agent mechanism (no equivalent to AWS SSM or Azure Run Command).
  Access is via SSH. Two options depending on your setup:

  Option A — Public IP (default, works anywhere):
    The build Linode gets its default public IPv4; BakeX connects over the internet.

  Option B — Private networking (recommended for production):
    Set credentials.use_private_ip: true
    The BakeX host must also be a Linode in the same datacenter (e.g. us-east).
    The build Linode is assigned a 192.168.x.x private IP reachable within the DC.
    No public SSH exposure needed.

Requires the [linode] optional extra:
    pip install 'bakex[linode]'
    # or: pip install linode-api4
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time

PROVIDER_NAME = "linode"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[linode] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------


def _generate_ssh_keypair() -> tuple[str, str, str]:
    """Generate an ephemeral ed25519 key pair. Returns (key_path, pub_key, tmp_dir)."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="bakex-linode-key-")
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
# Linode API helpers
# ---------------------------------------------------------------------------


def _linode_client(api_token: str):
    try:
        from linode_api4 import LinodeClient
    except ImportError as exc:
        raise RuntimeError("linode-api4 is not installed. Run: pip install 'bakex[linode]'") from exc
    return LinodeClient(api_token)


def _reload_instance(client, linode_id: int):
    """Reload a Linode instance object by ID to get fresh status."""
    from linode_api4 import Linode

    return client.load(Linode, linode_id)


def _wait_instance_status(client, linode_id: int, target: str, timeout: int = 300) -> None:
    """Poll until the Linode reaches *target* status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        instance = _reload_instance(client, linode_id)
        status = instance.status
        logger.info("Linode %d status: %s (waiting for: %s)", linode_id, status, target)
        if status == target:
            return
        if status in ("offline", "stopped") and target == "running":
            raise RuntimeError(f"Linode {linode_id} went offline unexpectedly")
        time.sleep(10)
    raise TimeoutError(f"Linode {linode_id} did not reach '{target}' within {timeout}s")


def _pick_ip(instance, use_private: bool) -> str:
    """Pick the best IP to connect to: private (if available + requested) or public."""
    if use_private:
        for ip in instance.ips.ipv4.private:
            if ip.address:
                logger.info("Using Linode private IP: %s", ip.address)
                return ip.address
        logger.warning("Private IP requested but not found — falling back to public IP")
    public_ip = instance.ips.ipv4.public[0].address
    logger.info("Using Linode public IP: %s", public_ip)
    return public_ip


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Linode API token by fetching account info."""
    creds = params.get("credentials", params)
    api_token = creds.get("api_token", "")
    if not api_token:
        raise ValueError("credentials.api_token is required")
    try:
        client = _linode_client(api_token)
        account = client.account()
        logger.info("test_connection: account %s", account.email)
        return {"status": "ok", "email": account.email}
    except Exception as exc:
        raise ValueError(f"Linode connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full Linode → Ansible hardening → OpenSCAP → Private Image pipeline.

    Connectivity: SSH to the Linode's public or private IP.
    Set credentials.use_private_ip: true if the BakeX host is also a Linode
    in the same datacenter — this avoids exposing SSH to the public internet.
    """
    creds = params.get("credentials", {})
    api_token = creds.get("api_token", "")
    region = creds.get("region", "us-east")
    instance_type = creds.get("instance_type", "g6-standard-2")
    use_private_ip = creds.get("use_private_ip", False)

    base_image = params.get("base_image", "linode/ubuntu22.04")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not api_token:
        raise ValueError("credentials.api_token is required")

    client = _linode_client(api_token)
    key_path, pub_key, tmp_dir = _generate_ssh_keypair()

    safe_name = profile_name.lower().replace("_", "-").replace(".", "-")[:20]
    linode_label = f"bakex-{safe_name}-{int(time.time())}"
    # Linode images default to 'root' SSH access
    ssh_user = "root"
    linode_instance = None

    try:
        # Create Linode — inject SSH key so root can be accessed immediately
        create_kwargs: dict = dict(
            ltype=instance_type,
            region=region,
            image=base_image,
            label=linode_label,
            authorized_keys=[pub_key],
            tags=["bakex", "bakex-build"],
            private_ip=use_private_ip,  # Enable private networking if requested
        )
        logger.info(
            "Creating Linode %s (%s) in %s from %s (private_ip=%s)",
            linode_label,
            instance_type,
            region,
            base_image,
            use_private_ip,
        )
        linode_instance, _ = client.linode.instance_create(**create_kwargs)
        linode_id = linode_instance.id
        logger.info("Linode %d created", linode_id)

        # Wait for running
        _wait_instance_status(client, linode_id, "running", timeout=300)
        linode_instance = _reload_instance(client, linode_id)

        # Pick IP
        connect_ip = _pick_ip(linode_instance, use_private_ip)

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
                "bakex_target_os": params.get("os", "ubuntu22"),
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
            logger.warning("History cleanup encountered an issue, but proceeding with imaging: %s", exc)

        # Shut down before imaging (required by Linode image API)
        logger.info("Shutting down Linode %d for imaging", linode_id)
        linode_instance = _reload_instance(client, linode_id)
        linode_instance.shutdown()
        _wait_instance_status(client, linode_id, "offline", timeout=300)

        # Find the primary (non-swap) disk to image
        linode_instance = _reload_instance(client, linode_id)
        all_disks = linode_instance.disks
        boot_disk = next(
            (d for d in all_disks if d.filesystem not in ("swap",)),
            all_disks[0],
        )

        # Create Linode Private Image from the boot disk
        safe_version = profile_version.replace(".", "-")
        image_label = f"bakex-{safe_name}-{safe_version}"
        logger.info("Creating Linode Private Image '%s' from disk %d", image_label, boot_disk.id)
        image = client.images.create(
            disk=boot_disk.id,
            label=image_label,
            description=f"BakeX hardened image: {profile_name} v{profile_version}",
        )
        logger.info("Linode Private Image %s (%s) created", image.label, image.id)

        return {
            "status": "success",
            "artifact_id": image.id,
            "artifact_type": "linode_private_image",
            "region": region,
            "metadata": {
                "image_label": image.label,
                "profile_name": profile_name,
                "profile_version": profile_version,
            },
        }

    finally:
        if linode_instance is not None:
            try:
                logger.info("Deleting Linode %d", linode_instance.id)
                linode_instance.delete()
            except Exception as exc:
                logger.warning("Failed to delete Linode: %s", exc)
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
