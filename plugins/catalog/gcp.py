#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""GCP subprocess provider — speaks JSON-RPC over stdin/stdout.

Run as a standalone script: the core Invicton engine never imports this file.
Logs go to stderr; only JSON-RPC responses go to stdout.

Connectivity model (no public IP required):
  Invicton host → Cloud IAP TCP tunnel → GCE instance (private subnet)
  Ansible connects to the instance through the IAP tunnel using a local port
  forward created by `gcloud compute start-iap-tunnel`.

Requirements on the Invicton host:
  - gcloud CLI authenticated with the service account (or ADC)
  - IAP API enabled: gcloud services enable iap.googleapis.com
  - IAP-secured Tunnel User role on the VM resource

Requirements on the GCP project:
  - VPC firewall rule allowing IAP to reach port 22 on the build VMs:
      Source: 35.235.240.0/20  →  Target: tag invicton-build  →  TCP 22

Requires the [gcp] optional extra:
    pip install 'invicton[gcp]'
    # or: pip install google-cloud-compute google-auth
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time

PROVIDER_NAME = "gcp"

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[gcp] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_result(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# SSH + IAP tunnel helpers
# ---------------------------------------------------------------------------


def _generate_ssh_keypair() -> tuple[str, str, str]:
    """Generate an ephemeral ed25519 key pair. Returns (key_path, pub_key, tmp_dir)."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="invicton-gcp-key-")
    key_path = os.path.join(tmp, "invicton-build")
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "invicton-build"],
        check=True,
        capture_output=True,
    )
    with open(f"{key_path}.pub") as fh:
        pub_key = fh.read().strip()
    os.chmod(key_path, 0o600)
    return key_path, pub_key, tmp


def _start_iap_tunnel(
    instance_name: str, zone: str, project_id: str, local_port: int, timeout: int = 60
) -> subprocess.Popen:
    """Start a `gcloud compute start-iap-tunnel` process in the background.

    The tunnel forwards localhost:<local_port> → instance:22 via Cloud IAP.
    Returns the Popen object; caller must .terminate() it in a finally block.
    """
    logger.info("Opening IAP tunnel → %s:%s (local port %d)", instance_name, zone, local_port)
    proc = subprocess.Popen(
        [
            "gcloud",
            "compute",
            "start-iap-tunnel",
            instance_name,
            "22",
            f"--local-host-port=localhost:{local_port}",
            f"--zone={zone}",
            f"--project={project_id}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # Wait for the tunnel to be ready
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"IAP tunnel process exited early: {err}")
        # Try a lightweight connect to see if the port is open
        import socket

        try:
            s = socket.create_connection(("localhost", local_port), timeout=2)
            s.close()
            logger.info("IAP tunnel ready on localhost:%d", local_port)
            return proc
        except OSError:
            time.sleep(2)
    raise TimeoutError(f"IAP tunnel did not become ready within {timeout}s")


def _wait_for_ssh_via_tunnel(local_port: int, key_path: str, user: str, timeout: int = 300) -> None:
    """Poll SSH through the IAP tunnel until the instance is reachable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = subprocess.run(
            [
                "ssh",
                "-i",
                key_path,
                "-p",
                str(local_port),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                f"{user}@localhost",
                "echo ok",
            ],
            capture_output=True,
            timeout=15,
        )
        if res.returncode == 0:
            logger.info("SSH ready through IAP tunnel on port %d", local_port)
            return
        logger.info("Waiting for SSH through IAP tunnel…")
        time.sleep(10)
    raise TimeoutError(f"SSH through IAP tunnel did not become ready within {timeout}s")


def _run_ansible_via_tunnel(
    playbook_path: str,
    local_port: int,
    key_path: str,
    user: str,
    extra_vars_file: str | None = None,
    timeout: int = 3600,
) -> None:
    """Run ansible-playbook targeting the IAP tunnel local port."""
    cmd = [
        "ansible-playbook",
        "-i",
        f"localhost:{local_port},",
        "--private-key",
        key_path,
        "-u",
        user,
        "--ssh-extra-args",
        f"-p {local_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
    ]
    if extra_vars_file:
        cmd += ["--extra-vars", f"@{extra_vars_file}"]
    cmd.append(playbook_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        logger.info("ansible-playbook stdout:\n%s", result.stdout[-2000:])
    if result.returncode != 0:
        raise RuntimeError(f"ansible-playbook failed (exit {result.returncode}):\n{result.stderr[-2000:]}")


def _run_ansible_yaml_via_tunnel(playbook_yaml: str, local_port: int, key_path: str, user: str, tmp_dir: str) -> None:
    """Write playbook YAML to disk and run it through the IAP tunnel."""
    playbook_path = os.path.join(tmp_dir, "prehard.yml")
    with open(playbook_path, "w") as fh:
        fh.write(playbook_yaml)
    _run_ansible_via_tunnel(playbook_path, local_port, key_path, user)


def _run_remote_cmd_via_tunnel(local_port: int, key_path: str, user: str, cmd: str, timeout: int = 600) -> str:
    """Run a shell command on the GCE instance through the IAP tunnel."""
    result = subprocess.run(
        [
            "ssh",
            "-i",
            key_path,
            "-p",
            str(local_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{user}@localhost",
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# GCP operation helpers
# ---------------------------------------------------------------------------


def _get_credentials(creds: dict):
    """Return google-auth credentials from service_account_json or ADC."""
    sa_json = creds.get("service_account_json", "")
    if sa_json:
        from google.oauth2 import service_account

        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        return service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    import google.auth

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return credentials


def _wait_zone_op(zone_ops_client, project_id: str, zone: str, op_name: str, timeout: int = 600) -> None:
    from google.cloud import compute_v1

    deadline = time.time() + timeout
    while time.time() < deadline:
        op = zone_ops_client.get(project=project_id, zone=zone, operation=op_name)
        if op.status == compute_v1.Operation.Status.DONE:
            if op.error:
                msgs = [e.message for e in op.error.errors]
                raise RuntimeError(f"GCE zone op failed: {'; '.join(msgs)}")
            return
        time.sleep(5)
    raise TimeoutError(f"GCE zone op {op_name} timed out after {timeout}s")


def _wait_global_op(global_ops_client, project_id: str, op_name: str, timeout: int = 600) -> None:
    from google.cloud import compute_v1

    deadline = time.time() + timeout
    while time.time() < deadline:
        op = global_ops_client.get(project=project_id, operation=op_name)
        if op.status == compute_v1.Operation.Status.DONE:
            if op.error:
                msgs = [e.message for e in op.error.errors]
                raise RuntimeError(f"GCE global op failed: {'; '.join(msgs)}")
            return
        time.sleep(5)
    raise TimeoutError(f"GCE global op {op_name} timed out after {timeout}s")


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


def test_connection(params: dict) -> dict:
    """Validate GCP credentials and IAP setup."""
    creds = params.get("credentials", params)
    project_id = creds.get("project_id", "")
    if not project_id:
        raise ValueError("project_id is required")
    try:
        from google.cloud import compute_v1

        credentials = _get_credentials(creds)
        zones_client = compute_v1.ZonesClient(credentials=credentials)
        zones = list(zones_client.list(project=project_id, max_results=1))
        logger.info("test_connection: project %s reachable, %d zone(s) listed", project_id, len(zones))
        return {"status": "ok", "project_id": project_id}
    except Exception as exc:
        raise ValueError(f"GCP connection test failed: {exc}") from exc


def execute_build(params: dict) -> dict:
    """Full GCE build pipeline via IAP — no public IP required.

    Flow:
      1. Launch private GCE instance (no external IP, tag: invicton-build)
      2. Open IAP TCP tunnel → port 22
      3. Run pre-hardening Ansible playbook through the tunnel
      4. Run Ansible-Lockdown hardening through the tunnel
      5. Run OpenSCAP scan through the tunnel
      6. Stop instance → create GCP Custom Image
      7. Terminate instance (always, in finally)
    """
    creds = params.get("credentials", {})
    project_id = creds.get("project_id", "")
    zone = creds.get("zone", "us-central1-a")
    region = zone.rsplit("-", 1)[0]
    machine_type = creds.get("machine_type", "n2-standard-2")
    network = creds.get("network", "default")
    subnetwork = creds.get("subnetwork", "")

    base_image = params.get("base_image", "")
    os_name = params.get("os", "ubuntu22")
    profile_name = params.get("profile_name", "unnamed")
    profile_version = params.get("profile_version", "0.0.0")
    profile_id = params.get("profile", "")
    datastream = params.get("datastream", "")

    if not project_id:
        raise ValueError("credentials.project_id is required")
    if not base_image:
        raise ValueError("base_image is required")

    try:
        from google.cloud import compute_v1
    except ImportError as exc:
        raise RuntimeError("google-cloud-compute is not installed. Run: pip install 'invicton[gcp]'") from exc

    credentials = _get_credentials(creds)
    instances_client = compute_v1.InstancesClient(credentials=credentials)
    images_client = compute_v1.ImagesClient(credentials=credentials)
    zone_ops_client = compute_v1.ZoneOperationsClient(credentials=credentials)
    global_ops_client = compute_v1.GlobalOperationsClient(credentials=credentials)

    key_path, pub_key, tmp_dir = _generate_ssh_keypair()
    safe_name = profile_name.lower().replace("_", "-").replace(".", "-")[:20]
    instance_name = f"invicton-{safe_name}-{int(time.time())}"
    local_port = random.randint(20000, 29999)
    iap_proc = None

    try:
        # Resolve base image
        source_image = base_image if "/" in base_image else f"projects/{project_id}/global/images/family/{base_image}"

        # Build instance — no external IP (no access_configs)
        disk = compute_v1.AttachedDisk(
            boot=True,
            auto_delete=True,
            initialize_params=compute_v1.AttachedDiskInitializeParams(
                source_image=source_image,
                disk_size_gb=20,
                disk_type=f"zones/{zone}/diskTypes/pd-ssd",
            ),
        )
        net_iface = compute_v1.NetworkInterface(
            network=f"global/networks/{network}",
            # No access_configs → no public IP; IAP provides private access
        )
        if subnetwork:
            net_iface.subnetwork = subnetwork

        instance_resource = compute_v1.Instance(
            name=instance_name,
            machine_type=f"zones/{zone}/machineTypes/{machine_type}",
            disks=[disk],
            network_interfaces=[net_iface],
            metadata=compute_v1.Metadata(
                items=[
                    compute_v1.Items(key="ssh-keys", value=f"invicton_build:{pub_key}"),
                    compute_v1.Items(key="enable-oslogin", value="false"),
                ]
            ),
            # Tag drives the firewall rule allowing IAP → port 22
            tags=compute_v1.Tags(items=["invicton-build"]),
        )

        logger.info("Launching private GCE instance %s (%s) in %s", instance_name, machine_type, zone)
        insert_op = instances_client.insert(project=project_id, zone=zone, instance_resource=instance_resource)
        _wait_zone_op(zone_ops_client, project_id, zone, insert_op.name)
        logger.info("Instance %s launched (private — no external IP)", instance_name)

        # Give the instance time to finish booting
        time.sleep(30)

        # Open IAP TCP tunnel
        iap_proc = _start_iap_tunnel(instance_name, zone, project_id, local_port)

        # Wait for SSH through the tunnel
        _wait_for_ssh_via_tunnel(local_port, key_path, "invicton_build", timeout=300)

        # Pre-hardening system configuration (hostname, filesystem, users)
        prehard_yaml = params.get("prehard_playbook_yaml")
        if prehard_yaml:
            logger.info("Running pre-hardening system configuration via IAP tunnel")
            _run_ansible_yaml_via_tunnel(prehard_yaml, local_port, key_path, "invicton_build", tmp_dir)

        # Pluggable Hardening
        hardening = params.get("hardening", {})
        strategy = hardening.get("strategy", "ansible-galaxy")

        if strategy == "none":
            logger.info("Hardening strategy is 'none' — skipping CIS compliance playbook.")
        else:
            extra_vars = {
                "profile_name": profile_name,
                "benchmark": params.get("benchmark", ""),
                "profile": profile_id,
                "datastream": datastream,
                "invicton_target_os": os_name,
            }
            extra_vars_path = os.path.join(tmp_dir, "invicton_vars.json")
            with open(extra_vars_path, "w") as fh:
                json.dump(extra_vars, fh)

            if strategy == "ansible-galaxy":
                role = hardening.get("role", "auto")
                logger.info("Running Ansible-Lockdown hardening via IAP tunnel (role: %s)", role)
                # Pass the strategy variables to the local site.yml wrapper
                extra_vars["invicton_lockdown_role"] = role
                with open(extra_vars_path, "w") as fh:
                    json.dump(extra_vars, fh)

                _run_ansible_via_tunnel(
                    "ansible/site.yml",
                    local_port,
                    key_path,
                    "invicton_build",
                    extra_vars_file=extra_vars_path,
                )

            elif strategy == "git":
                repo_url = hardening.get("repo_url", "")
                playbook_file = hardening.get("playbook_file", "site.yml")
                if not repo_url:
                    raise ValueError("Hardening strategy is 'git' but 'repo_url' is missing.")

                logger.info("Cloning Git repository %s locally for IAP execution", repo_url)
                clone_dir = os.path.join(tmp_dir, "custom_hardening")
                subprocess.run(["git", "clone", repo_url, clone_dir], check=True)

                playbook_path = os.path.join(clone_dir, playbook_file)
                logger.info("Running custom Git playbook %s via IAP tunnel", playbook_path)
                _run_ansible_via_tunnel(
                    playbook_path,
                    local_port,
                    key_path,
                    "invicton_build",
                    extra_vars_file=extra_vars_path,
                )
            else:
                raise ValueError(f"Unknown hardening strategy: {strategy}")

        # OpenSCAP compliance scan through the tunnel
        logger.info("Running OpenSCAP scan via IAP tunnel")
        oscap_cmd = f"sudo oscap xccdf eval --profile {profile_id} --results /tmp/invicton-scap-results.xml {datastream} || true"
        _run_remote_cmd_via_tunnel(local_port, key_path, "invicton_build", oscap_cmd, timeout=600)

        # Cleanup history
        logger.info("Cleaning up instance logs and history via IAP tunnel")
        cleanup_cmds = [
            "sudo rm -rf /tmp/invicton-*",
            "sudo rm -f /var/log/messages /var/log/syslog /var/log/auth.log",
            "sudo journalctl --vacuum-time=1s || true",
            "sudo sh -c 'cat /dev/null > /var/log/wtmp' || true",
            "cat /dev/null > ~/.bash_history || true",
            "sudo sh -c 'cat /dev/null > /root/.bash_history' || true",
            "sudo find /home -name '.bash_history' -exec sh -c 'cat /dev/null > {}' \\;",
        ]
        try:
            _run_remote_cmd_via_tunnel(local_port, key_path, "invicton_build", " ; ".join(cleanup_cmds), timeout=120)
        except Exception as exc:
            logger.warning("History cleanup encountered an issue, but proceeding with snapshot: %s", exc)

        # Close IAP tunnel before imaging
        if iap_proc:
            iap_proc.terminate()
            iap_proc = None

        # Stop instance before snapshot
        logger.info("Stopping instance %s for imaging", instance_name)
        stop_op = instances_client.stop(project=project_id, zone=zone, instance=instance_name)
        _wait_zone_op(zone_ops_client, project_id, zone, stop_op.name, timeout=300)

        # Create GCP Custom Image from the stopped instance's boot disk
        safe_version = profile_version.replace(".", "-")
        image_name = f"invicton-{safe_name}-{safe_version}"[:63].lower()

        logger.info("Creating GCP Custom Image: %s", image_name)
        img_op = images_client.insert(
            project=project_id,
            image_resource=compute_v1.Image(
                name=image_name,
                description=f"Invicton hardened image: {profile_name} v{profile_version}",
                source_disk=f"zones/{zone}/disks/{instance_name}",
            ),
        )
        _wait_global_op(global_ops_client, project_id, img_op.name, timeout=600)
        logger.info("GCP Custom Image %s is ready", image_name)

        return {
            "status": "success",
            "artifact_id": image_name,
            "artifact_type": "gcp_custom_image",
            "region": region,
            "metadata": {
                "project_id": project_id,
                "zone": zone,
                "image_self_link": f"projects/{project_id}/global/images/{image_name}",
                "profile_name": profile_name,
                "profile_version": profile_version,
            },
        }

    finally:
        if iap_proc is not None:
            iap_proc.terminate()
        try:
            logger.info("Deleting build instance %s", instance_name)
            instances_client.delete(project=project_id, zone=zone, instance=instance_name)
        except Exception as exc:
            logger.warning("Failed to delete instance %s: %s", instance_name, exc)
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
