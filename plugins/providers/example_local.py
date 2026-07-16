# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Local / SSH class-based provider — reference implementation.

Targets any host reachable over SSH (Vagrant VM, LXC container, bare metal, etc.).
This is the simplest possible complete provider and serves as the canonical
reference when writing a new class-based provider plugin.

Drop-in location: plugins/providers/example_local.py
Provider name:    "local"

Blueprint usage:
    target:
      provider: local
      base_image: "192.168.1.100"   # hostname or IP of an already-running host
      instance_type: ""              # ignored for local provider
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bakex.core.blueprint import ComplianceProfile
from bakex.plugins.base_provider import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

# Default SSH options — disable strict host-key checking for ephemeral lab hosts
_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=30",
    "-o",
    "BatchMode=yes",
    "-o",
    "LogLevel=ERROR",
]


def _run(cmd: list[str], label: str, timeout: int = 1800) -> None:
    """Run *cmd*, raise RuntimeError with *label* context on non-zero exit."""
    logger.info("[local] %s: %s", label, " ".join(cmd[:6]))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout.strip():
        for line in result.stdout.splitlines():
            logger.debug("[local] stdout: %s", line)
    if result.returncode != 0:
        raise RuntimeError(f"[local] {label} failed (exit {result.returncode}):\n{result.stderr[:800]}")


class LocalProvider(BaseProvider):
    """Provider that targets any host reachable over SSH.

    ``base_image`` in the blueprint is treated as the host address (IP or hostname).
    The provider expects the host to already be running and SSH-accessible using
    the key / user configured in ``credentials`` (via the BakeX integrations UI)
    or the defaults below.

    Credential fields (BakeX integrations UI):
        ssh_user         SSH login username (default: root)
        private_key_path Path to the SSH private key file (default: ~/.ssh/id_rsa)
    """

    name = "local"

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _credentials(self) -> tuple[str, str]:
        """Return (ssh_user, private_key_path) from the BakeX credential store."""
        try:
            from bakex.api.integrations import get_credentials

            creds = get_credentials("local") or {}
        except Exception:
            creds = {}
        ssh_user = creds.get("ssh_user", "root")
        key_path = creds.get("private_key_path", str(Path.home() / ".ssh" / "id_rsa"))
        return ssh_user, key_path

    def _ansible_playbook(
        self,
        host: str,
        playbook: str,
        ssh_user: str,
        key_path: str,
        extra_vars: dict | None = None,
        timeout: int = 1800,
    ) -> None:
        """Run an Ansible playbook against *host* over SSH."""
        cmd = [
            "ansible-playbook",
            "-i",
            f"{host},",
            "--user",
            ssh_user,
            "--private-key",
            key_path,
            "--ssh-extra-args",
            " ".join(_SSH_OPTS),
            playbook,
        ]
        if extra_vars:
            import json
            import tempfile as _tmp

            with _tmp.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as ef:
                json.dump(extra_vars, ef)
                cmd.extend(["--extra-vars", f"@{ef.name}"])
        _run(cmd, f"ansible-playbook {playbook}", timeout=timeout)

    # ---------------------------------------------------------------------------
    # BaseProvider interface
    # ---------------------------------------------------------------------------

    def provision(self, profile: ComplianceProfile, **kwargs) -> str:
        """Local provider treats the host as already provisioned.

        Returns ``base_image`` (hostname / IP) as the instance ID.
        """
        host = profile.target.base_image
        logger.info("[local] Using existing host: %s", host)
        return host

    def run_ansible(self, instance_id: str, profile: ComplianceProfile) -> None:
        """Apply pre-hardening config and then Ansible-Lockdown to *instance_id*.

        Steps:
            1. Run the pre-hardening playbook (hostname, mounts, users) if present.
            2. Run ``ansible/site.yml`` which auto-detects the OS and applies the
               correct ansible-lockdown CIS role.
        """
        ssh_user, key_path = self._credentials()
        host = instance_id

        # Step 1: pre-hardening (generated from blueprint)
        from bakex.core.playbook_gen import generate_prehard_playbook

        prehard_path = generate_prehard_playbook(profile)
        if prehard_path is not None:
            logger.info("[local] Applying pre-hardening configuration on %s", host)
            self._ansible_playbook(host, str(prehard_path), ssh_user, key_path, timeout=600)

        # Step 2: Ansible-Lockdown CIS hardening
        logger.info("[local] Running Ansible-Lockdown hardening on %s", host)
        self._ansible_playbook(host, "ansible/site.yml", ssh_user, key_path, timeout=3600)
        logger.info("[local] Ansible hardening complete on %s", host)

    def snapshot(self, instance_id: str, profile: ComplianceProfile) -> ProviderResult:
        """Create a compressed tar archive of the remote root filesystem.

        The archive is saved to the current directory on the BakeX server.
        For a real on-premises workflow, replace this with a ``qemu-img convert``
        call, a Packer build, or a hypervisor-specific snapshot API.
        """
        artifact = f"{profile.metadata.name}-{profile.metadata.version}.tar.gz"
        ssh_user, key_path = self._credentials()
        host = instance_id

        logger.info("[local] Creating root filesystem snapshot on %s → %s", host, artifact)
        cmd = [
            "ssh",
            "-i",
            key_path,
            *_SSH_OPTS,
            f"{ssh_user}@{host}",
            "sudo tar --exclude=/proc --exclude=/sys --exclude=/dev --exclude=/tmp --exclude=/run -czf - / 2>/dev/null",
        ]
        with open(artifact, "wb") as out:
            result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, timeout=3600)

        if result.returncode not in (0, 1):  # tar exits 1 on "file changed as we read it" (harmless)
            raise RuntimeError(f"[local] Snapshot failed (exit {result.returncode}):\n{result.stderr.decode()[:400]}")
        logger.info("[local] Snapshot written to %s", artifact)
        return ProviderResult(
            artifact_id=artifact,
            artifact_type="tar.gz",
            metadata={"host": instance_id},
        )

    def teardown(self, instance_id: str) -> None:
        """Local provider leaves the host running.

        Override this if you want to power off a Vagrant VM or an LXC container.
        Example:
            subprocess.run(["vagrant", "halt"], check=True)
        """
        logger.info("[local] Teardown skipped — host %s left running", instance_id)

    def audit(self, target_id: str, profile: ComplianceProfile) -> dict:
        """Run an OpenSCAP scan against *target_id* and return the raw XML.

        ``target_id`` should be the hostname/IP. The scan uses the XCCDF profile
        and datastream specified in the blueprint's ``compliance`` section.
        """
        ssh_user, key_path = self._credentials()

        oscap_cmd = (
            f"sudo oscap xccdf eval "
            f"--profile {profile.compliance.profile} "
            f"--results /tmp/bakex-audit.xml "
            f"{profile.compliance.datastream} || true; "
            f"cat /tmp/bakex-audit.xml"
        )
        result = subprocess.run(
            ["ssh", "-i", key_path, *_SSH_OPTS, f"{ssh_user}@{target_id}", oscap_cmd],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if not result.stdout.strip():
            raise RuntimeError(f"[local] oscap produced no output for {target_id}: {result.stderr[:400]}")
        logger.info("[local] Audit complete for %s (%d bytes)", target_id, len(result.stdout))
        return {"status": "success", "raw_xml": result.stdout}
