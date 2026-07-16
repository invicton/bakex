#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Proxmox VE subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core Statim engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Requires the [proxmox] optional extra:
    pip install 'statim[proxmox]'
    # or: pip install proxmoxer requests

Setup requirements:
  - A base VM template on Proxmox (set base_image to its VMID, e.g. "9000")
  - The template must have cloud-init support (or a pre-injected SSH key)
  - The Statim host must be able to SSH to the cloned VM
  - Proxmox API token with VM.Clone, VM.Config.*, VM.PowerMgmt, VM.Audit perms
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time

PROVIDER_NAME = "proxmox"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[proxmox] %(message)s")
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

    tmp = tempfile.mkdtemp(prefix="statim-proxmox-key-")
    key_path = os.path.join(tmp, "statim-build")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "statim-build"],
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


def _run_ansible(playbook_yaml: str, host: str, key_path: str, user: str, tmp_dir: str) -> None:
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
# Proxmox helpers
# ---------------------------------------------------------------------------


def _get_proxmox_client(creds: dict):
    try:
        from proxmoxer import ProxmoxAPI
    except ImportError as exc:
        raise RuntimeError("proxmoxer is not installed. Run: pip install 'statim[proxmox]'") from exc
    # Stored/submitted as a bool, or "true"/"false" strings from a form/JSON
    # body — a bare `.get(..., False)` would treat the string "false" as truthy.
    verify_ssl = str(creds.get("verify_ssl", False)).strip().lower() in ("true", "on", "1", "yes")
    return ProxmoxAPI(
        creds["host"],
        user=creds["user"],
        token_name=creds["token_name"],
        token_value=creds["token_value"],
        verify_ssl=verify_ssl,
    )


def _next_vmid(proxmox) -> int:
    """Get the next available VMID from Proxmox cluster."""
    return int(proxmox.cluster.nextid.get())


def _wait_task(proxmox, node: str, task_id: str, timeout: int = 600) -> None:
    """Poll a Proxmox task until it completes successfully."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = proxmox.nodes(node).tasks(task_id).status.get()
        if status.get("status") == "stopped":
            exit_status = status.get("exitstatus", "")
            if exit_status != "OK":
                raise RuntimeError(f"Proxmox task {task_id} failed: {exit_status}")
            return
        time.sleep(3)
    raise TimeoutError(f"Proxmox task {task_id} did not complete within {timeout}s")


def _wait_vm_status(proxmox, node: str, vmid: int, target_status: str, timeout: int = 300) -> None:
    """Poll until VM reaches the target power status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current = proxmox.nodes(node).qemu(vmid).status.current.get()
            if current.get("status") == target_status:
                return
            logger.info("VM %d status: %s (waiting for %s)", vmid, current.get("status"), target_status)
        except Exception as exc:
            logger.debug("Status poll error (may be transient): %s", exc)
        time.sleep(5)
    raise TimeoutError(f"VM {vmid} did not reach status '{target_status}' within {timeout}s")


def _inject_ssh_key_via_cloudinit(proxmox, node: str, vmid: int, pub_key: str, ssh_user: str) -> None:
    """Configure cloud-init SSH key on a Proxmox VM."""
    try:
        proxmox.nodes(node).qemu(vmid).config.post(
            ciuser=ssh_user,
            sshkeys=pub_key.replace("\n", "%0a"),
        )
        logger.info("Injected SSH key via cloud-init for user %s on VM %d", ssh_user, vmid)
    except Exception as exc:
        logger.warning("cloud-init SSH injection failed (template may not have cloud-init): %s", exc)


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate Proxmox credentials by fetching cluster status."""
    creds = params.get("credentials", params)
    try:
        proxmox = _get_proxmox_client(creds)
        cluster_status = proxmox.cluster.status.get()
        node_names = [n["name"] for n in cluster_status if n.get("type") == "node"]
        logger.info("test_connection: nodes = %s", node_names)
        return {"status": "ok", "nodes": node_names}
    except Exception as exc:
        raise ValueError(f"Proxmox connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full Proxmox clone → Ansible hardening → OpenSCAP → template pipeline."""
    creds = params.get("credentials", {})
    node = creds.get("node", "pve")
    storage = creds.get("storage", "local-lvm")
    ssh_host = creds.get("ssh_host", "")  # IP/DNS of the cloned VM for Ansible
    ssh_user = creds.get("ssh_user", "root")

    base_image = params.get("base_image", "")  # VMID of the base template
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not base_image:
        raise ValueError("base_image must be the VMID of the Proxmox template (e.g. '9000')")
    template_vmid = int(base_image)

    proxmox = _get_proxmox_client(creds)
    key_path, pub_key, tmp_dir = _generate_ssh_keypair()

    new_vmid = _next_vmid(proxmox)
    safe_name = profile_name.lower().replace("_", "-").replace(".", "-")[:20]
    vm_name = f"statim-{safe_name}-{new_vmid}"
    logger.info("Cloning template VMID %d → new VMID %d (%s)", template_vmid, new_vmid, vm_name)

    try:
        # Clone the base template
        task_id = (
            proxmox.nodes(node)
            .qemu(template_vmid)
            .clone.post(
                newid=new_vmid,
                name=vm_name,
                storage=storage,
                full=1,  # Full clone (not linked) for snapshot independence
            )
        )
        _wait_task(proxmox, node, task_id, timeout=600)
        logger.info("Clone complete: VMID %d", new_vmid)

        # Inject SSH key via cloud-init (requires cloud-init drive in template)
        _inject_ssh_key_via_cloudinit(proxmox, node, new_vmid, pub_key, ssh_user)

        # Start VM
        logger.info("Starting VM %d", new_vmid)
        start_task = proxmox.nodes(node).qemu(new_vmid).status.start.post()
        _wait_task(proxmox, node, start_task, timeout=120)
        _wait_vm_status(proxmox, node, new_vmid, "running", timeout=180)

        # SSH host must be provided if not using cloud-init IP detection
        if not ssh_host:
            # Try to get IP via QEMU guest agent
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    net_info = proxmox.nodes(node).qemu(new_vmid).agent("network-get-interfaces").get()
                    for iface in net_info.get("result", []):
                        if iface.get("name") not in ("lo", "loopback"):
                            for addr in iface.get("ip-addresses", []):
                                if addr.get("ip-address-type") == "ipv4":
                                    ssh_host = addr["ip-address"]
                                    logger.info("Detected VM IP via guest agent: %s", ssh_host)
                                    break
                        if ssh_host:
                            break
                except Exception:
                    pass
                if ssh_host:
                    break
                time.sleep(10)

        if not ssh_host:
            raise RuntimeError(
                "Could not determine VM IP. Set credentials.ssh_host or ensure "
                "QEMU guest agent is installed in the template."
            )

        # Wait for SSH
        _wait_for_ssh(ssh_host, key_path, ssh_user, timeout=300)

        # Pre-hardening system configuration
        prehard_yaml = params.get("prehard_playbook_yaml")
        if prehard_yaml:
            logger.info("Running pre-hardening system configuration")
            _run_ansible(prehard_yaml, ssh_host, key_path, ssh_user, tmp_dir)

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
                "statim_target_os": params.get("os", "ubuntu22"),
            }
            extra_vars_path = os.path.join(tmp_dir, "statim_vars.json")
            with open(extra_vars_path, "w") as fh:
                json.dump(extra_vars, fh)

            if strategy == "ansible-galaxy":
                role = hardening_config.get("role", "auto")
                logger.info("Running Ansible-Lockdown hardening (role: %s)", role)
                # Pass the strategy variables to the local site.yml wrapper
                extra_vars["statim_lockdown_role"] = role
                with open(extra_vars_path, "w") as fh:
                    json.dump(extra_vars, fh)

                _run_ansible_playbook(
                    "ansible/site.yml",
                    ssh_host,
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
                    ssh_host,
                    key_path,
                    ssh_user,
                    extra_vars_file=extra_vars_path,
                )
            else:
                raise ValueError(f"Unknown hardening strategy: {strategy}")

        # OpenSCAP compliance scan
        logger.info("Running OpenSCAP scan")
        oscap_cmd = (
            f"oscap xccdf eval --profile {profile_id} --results /tmp/statim-scap-results.xml {datastream} || true"
        )
        _run_remote_cmd(ssh_host, key_path, ssh_user, oscap_cmd, timeout=600)

        # Cleanup history
        logger.info("Cleaning up instance logs and history via SSH")
        cleanup_cmds = [
            "rm -rf /tmp/statim-*",
            "rm -f /var/log/messages /var/log/syslog /var/log/auth.log",
            "journalctl --vacuum-time=1s || true",
            "sh -c 'cat /dev/null > /var/log/wtmp' || true",
            "cat /dev/null > ~/.bash_history || true",
            "sh -c 'cat /dev/null > /root/.bash_history' || true",
            "find /home -name '.bash_history' -exec sh -c 'cat /dev/null > {}' \\;",
        ]
        try:
            _run_remote_cmd(ssh_host, key_path, ssh_user, " ; ".join(cleanup_cmds), timeout=120)
        except Exception as exc:
            logger.warning("History cleanup encountered an issue, but proceeding with template conversion: %s", exc)

        # Shut down VM before converting to template
        logger.info("Shutting down VM %d for template conversion", new_vmid)
        stop_task = proxmox.nodes(node).qemu(new_vmid).status.stop.post()
        _wait_task(proxmox, node, stop_task, timeout=120)
        _wait_vm_status(proxmox, node, new_vmid, "stopped", timeout=180)

        # Convert the VM into a reusable Proxmox template
        logger.info("Converting VM %d to Proxmox template", new_vmid)
        proxmox.nodes(node).qemu(new_vmid).template.post()
        logger.info("VM %d is now a Proxmox template", new_vmid)

        # Rename template to reflect the profile
        safe_version = profile_version.replace(".", "-")
        template_name = f"statim-{safe_name}-{safe_version}"
        proxmox.nodes(node).qemu(new_vmid).config.post(name=template_name)

        artifact_id = str(new_vmid)
        return {
            "status": "success",
            "artifact_id": artifact_id,
            "artifact_type": "proxmox_template",
            "region": node,
            "metadata": {
                "vmid": new_vmid,
                "template_name": template_name,
                "node": node,
                "profile_name": profile_name,
                "profile_version": profile_version,
            },
        }

    except Exception:
        # On failure: try to delete the (non-template) VM to avoid orphans
        try:
            proxmox.nodes(node).qemu(new_vmid).status.stop.post()
            time.sleep(5)
            proxmox.nodes(node).qemu(new_vmid).delete()
            logger.info("Cleaned up failed build VM %d", new_vmid)
        except Exception as cleanup_exc:
            logger.warning("Could not clean up VM %d: %s", new_vmid, cleanup_exc)
        raise

    finally:
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
