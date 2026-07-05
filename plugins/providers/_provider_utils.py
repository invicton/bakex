#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Shared SSH / Ansible / OpenSCAP utilities for Stratum subprocess providers.

Import from any subprocess provider script with:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _provider_utils as utils

All functions in this module operate synchronously — they are designed for
subprocess provider scripts that run as one-shot CLI processes.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OS defaults
# ---------------------------------------------------------------------------

# Default SSH login user per OS family (used when provisioning new instances)
_OS_SSH_USER: dict[str, str] = {
    "ubuntu": "ubuntu",
    "debian": "admin",
    "rocky": "rocky",
    "alma": "almalinux",
    "rhel": "ec2-user",
    "amazon": "ec2-user",
    "centos": "centos",
    "fedora": "fedora",
    "opensuse": "opensuse",
}

# Ansible-Lockdown Galaxy role per OS identifier.
#
# These MUST be the Galaxy role's `name` field (what `ansible-galaxy install
# ansible-lockdown.<name>` actually needs), which frequently differs from the
# GitHub repo name/casing — e.g. the GitHub repo is "UBUNTU22-CIS" but the
# Galaxy name is "ubuntu22_cis"; the Debian 12 repo is "debian12-cis" but its
# Galaxy name is "deb12_cis" (not "debian12_cis"). Verify against
# https://galaxy.ansible.com/api/v1/roles/?owner__username=ansible-lockdown
# before changing — installing the wrong string fails with "role not found".
_OS_LOCKDOWN_ROLE: dict[str, str] = {
    "ubuntu22": "ubuntu22_cis",
    "ubuntu22.04": "ubuntu22_cis",
    "ubuntu24": "ubuntu24_cis",
    "ubuntu24.04": "ubuntu24_cis",
    "ubuntu20": "ubuntu20_cis",
    "ubuntu20.04": "ubuntu20_cis",
    "debian12": "deb12_cis",
    "debian11": "debian11_cis",
    "rocky9": "rhel9_cis",
    "alma9": "rhel9_cis",
    "rhel9": "rhel9_cis",
    "rocky8": "rhel8_cis",
    "alma8": "rhel8_cis",
    "rhel8": "rhel8_cis",
    "amazon-linux-2023": "amazon2023_cis",
    "amazon2023": "amazon2023_cis",
    "amazon2": "amazon2_cis",
}

# Pinned "latest known-good" version per Galaxy role name.
#
# `ansible-galaxy install ansible-lockdown.<role>` with NO version qualifier
# asks Galaxy to compare all published version tags to find the newest one —
# and several ansible-lockdown repos mix tag formats (e.g. "V1.0.0" alongside
# "1.1.0"), which makes that comparison fail outright with "Unable to compare
# role versions ... due to incompatible version formats", aborting the
# install entirely. Requesting an explicit version sidesteps the comparison.
# Update by checking https://galaxy.ansible.com/api/v1/roles/?owner__username=ansible-lockdown
# (each role's summary_fields.versions, newest first) — do not guess.
_ROLE_PINNED_VERSION: dict[str, str] = {
    "ubuntu22_cis": "3.0.0",
    "ubuntu24_cis": "1.6.0",
    "ubuntu20_cis": "3.0.0",
    "deb12_cis": "2.0.5",
    "debian11_cis": "2.0.1",
    "rhel9_cis": "2.2.0",
    "rhel8_cis": "4.0.0",
    "amazon2023_cis": "1.3.0",
    "amazon2_cis": "3.0.2",
}


# ---------------------------------------------------------------------------
# Ansible-Lockdown profile tier variable mappings
# ---------------------------------------------------------------------------
# Each entry maps profile_tier → extra_vars dict for that Ansible-Lockdown role.
# Variable names follow the ansible-lockdown convention: <role_prefix>_level1 / _level2.
# Roles not listed here fall back to the generic CIS mapping below.

# Keys here are the Galaxy role name from _OS_LOCKDOWN_ROLE, upper-cased (see
# tier_extra_vars below) — NOT the GitHub repo name. The Ansible variable
# prefixes inside each dict (e.g. "ubuntu22cis_level1") are a separate,
# role-internal convention defined by each role's own defaults/main.yml and
# are unaffected by the Galaxy package name fix.
_TIER_VARS_BY_ROLE: dict[str, dict[str, dict]] = {
    "RHEL9_CIS": {
        "cis-l1": {"rhel9cis_level1": True, "rhel9cis_level2": False},
        "cis-l2": {"rhel9cis_level1": True, "rhel9cis_level2": True},
        "stig": {"rhel9cis_level1": True, "rhel9cis_level2": True, "rhel9cis_stig": True},
        "custom": {},
    },
    "RHEL8_CIS": {
        "cis-l1": {"rhel8cis_level1": True, "rhel8cis_level2": False},
        "cis-l2": {"rhel8cis_level1": True, "rhel8cis_level2": True},
        "stig": {"rhel8cis_level1": True, "rhel8cis_level2": True, "rhel8cis_stig": True},
        "custom": {},
    },
    "UBUNTU22_CIS": {
        "cis-l1": {"ubuntu22cis_level1": True, "ubuntu22cis_level2": False},
        "cis-l2": {"ubuntu22cis_level1": True, "ubuntu22cis_level2": True},
        "stig": {"ubuntu22cis_level1": True, "ubuntu22cis_level2": True},
        "custom": {},
    },
    "UBUNTU24_CIS": {
        "cis-l1": {"ubuntu24cis_level1": True, "ubuntu24cis_level2": False},
        "cis-l2": {"ubuntu24cis_level1": True, "ubuntu24cis_level2": True},
        "stig": {"ubuntu24cis_level1": True, "ubuntu24cis_level2": True},
        "custom": {},
    },
    "UBUNTU20_CIS": {
        "cis-l1": {"ubuntu2004cis_level1": True, "ubuntu2004cis_level2": False},
        "cis-l2": {"ubuntu2004cis_level1": True, "ubuntu2004cis_level2": True},
        "stig": {"ubuntu2004cis_level1": True, "ubuntu2004cis_level2": True},
        "custom": {},
    },
    "DEB12_CIS": {
        "cis-l1": {"debian12cis_level1": True, "debian12cis_level2": False},
        "cis-l2": {"debian12cis_level1": True, "debian12cis_level2": True},
        "stig": {"debian12cis_level1": True, "debian12cis_level2": True},
        "custom": {},
    },
    "DEBIAN11_CIS": {
        "cis-l1": {"debian11cis_level1": True, "debian11cis_level2": False},
        "cis-l2": {"debian11cis_level1": True, "debian11cis_level2": True},
        "stig": {"debian11cis_level1": True, "debian11cis_level2": True},
        "custom": {},
    },
    "AMAZON2023_CIS": {
        "cis-l1": {"amazon2023cis_level1": True, "amazon2023cis_level2": False},
        "cis-l2": {"amazon2023cis_level1": True, "amazon2023cis_level2": True},
        "stig": {"amazon2023cis_level1": True, "amazon2023cis_level2": True},
        "custom": {},
    },
    "AMAZON2_CIS": {
        "cis-l1": {"amazon2cis_level1": True, "amazon2cis_level2": False},
        "cis-l2": {"amazon2cis_level1": True, "amazon2cis_level2": True},
        "stig": {"amazon2cis_level1": True, "amazon2cis_level2": True},
        "custom": {},
    },
}

# Generic fallback used when a role is not in _TIER_VARS_BY_ROLE
_TIER_VARS_GENERIC: dict[str, dict] = {
    "cis-l1": {"cis_level1": True, "cis_level2": False},
    "cis-l2": {"cis_level1": True, "cis_level2": True},
    "stig": {"cis_level1": True, "cis_level2": True},
    "custom": {},
}


def tier_extra_vars(tier: str, role_name: str) -> dict:
    """Return the Ansible-Lockdown extra vars for a given profile tier and role.

    Strips the ``ansible-lockdown.`` namespace prefix if present, then looks up
    the role-specific mapping, falling back to the generic CIS vars.

    Args:
        tier:      Blueprint ``profile_tier`` value, e.g. "cis-l1", "stig".
        role_name: Galaxy role name, e.g. "ansible-lockdown.rhel9_cis".

    Returns:
        Dict of Ansible extra vars to merge into the playbook run.
    """
    # Normalise to just the role identifier without namespace prefix
    bare_role = role_name.rsplit(".", maxsplit=1)[-1].upper() if "." in role_name else role_name.upper()
    role_map = _TIER_VARS_BY_ROLE.get(bare_role, _TIER_VARS_GENERIC)
    return role_map.get(tier, {})


def default_ssh_user(os_name: str) -> str:
    """Return the default SSH username for a given OS identifier."""
    key = os_name.lower()
    if key in _OS_SSH_USER:
        return _OS_SSH_USER[key]
    for prefix, user in _OS_SSH_USER.items():
        if key.startswith(prefix):
            return user
    return "root"


def lockdown_role_for_os(os_name: str) -> str:
    """Return the ansible-lockdown Galaxy role name for the given OS identifier.

    Raises:
        ValueError: if no mapping is found.
    """
    key = os_name.lower()
    if key in _OS_LOCKDOWN_ROLE:
        return _OS_LOCKDOWN_ROLE[key]
    for prefix, role in _OS_LOCKDOWN_ROLE.items():
        if key.startswith(prefix):
            return role
    raise ValueError(f"No ansible-lockdown role mapping for OS '{os_name}'. Known: {sorted(_OS_LOCKDOWN_ROLE)}")


# ---------------------------------------------------------------------------
# SSH key management
# ---------------------------------------------------------------------------


def generate_ssh_keypair(tmpdir: Path) -> tuple[Path, str]:
    """Generate a temporary RSA-4096 key pair inside *tmpdir*.

    Returns:
        (private_key_path, public_key_openssh)
    """
    key_path = tmpdir / "stratum_id_rsa"
    subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "rsa",
            "-b",
            "4096",
            "-f",
            str(key_path),
            "-N",
            "",
            "-C",
            "stratum-ephemeral-build",
        ],
        check=True,
        capture_output=True,
    )
    pub = (tmpdir / "stratum_id_rsa.pub").read_text().strip()
    key_path.chmod(0o600)
    return key_path, pub


# ---------------------------------------------------------------------------
# SSH connectivity
# ---------------------------------------------------------------------------

_SSH_OPTS: list[str] = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=30",
    "-o",
    "BatchMode=yes",
    "-o",
    "ServerAliveInterval=30",
    "-o",
    "ServerAliveCountMax=5",
    "-o",
    "LogLevel=ERROR",
]


def wait_for_ssh(host: str, port: int = 22, timeout: int = 300, interval: int = 10) -> None:
    """Poll until TCP port *port* on *host* accepts a connection or *timeout* elapses.

    Raises:
        TimeoutError: if the port does not open within *timeout* seconds.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=5):
                logger.info("SSH is available at %s:%s", host, port)
                return
        except OSError:
            logger.debug("Waiting for SSH on %s:%s…", host, port)
            time.sleep(interval)
    raise TimeoutError(f"SSH on {host}:{port} did not open within {timeout}s")


def run_remote_cmd(
    host: str,
    user: str,
    key_path: Path,
    command: str,
    timeout: int = 300,
    check: bool = True,
    port: int = 22,
) -> tuple[int, str, str]:
    """Execute *command* on *host* via SSH.

    *port* defaults to 22 (every cloud provider's ephemeral instance gets its
    own routable IP on the standard port) — the local KVM provider is the one
    caller that passes a non-default, per-build forwarded port since its guest
    is only reachable via 127.0.0.1:<forwarded-port>.

    Returns:
        (returncode, stdout, stderr)

    Raises:
        RuntimeError: if *check* is True and the exit code is non-zero
                      (exit code 2 is allowed — oscap exits 2 when findings exist).
    """
    proc = subprocess.run(
        ["ssh", "-i", str(key_path), "-p", str(port), *_SSH_OPTS, f"{user}@{host}", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode not in (0, 2):
        # Many callers redirect the remote command's own stderr into stdout
        # (`... 2>&1`), so the real diagnostic often lands in stdout, not
        # proc.stderr (which only captures ssh's own errors) — include both.
        raise RuntimeError(
            f"Remote command failed (exit {proc.returncode}):\n"
            f"CMD: {command[:300]}\n"
            f"STDOUT: {proc.stdout[:800]}\n"
            f"STDERR: {proc.stderr[:800]}"
        )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Ansible helpers
# ---------------------------------------------------------------------------


def install_ansible_on_remote(host: str, user: str, key_path: Path, port: int = 22) -> None:
    """Ensure ``ansible-playbook`` is installed on the remote machine."""
    script = (
        "command -v ansible-playbook >/dev/null 2>&1 && exit 0; "
        "if command -v apt-get >/dev/null 2>&1; then "
        "  export DEBIAN_FRONTEND=noninteractive; "
        "  apt-get update -q && apt-get install -y software-properties-common; "
        "  add-apt-repository --yes --update ppa:ansible/ansible 2>/dev/null || true; "
        "  apt-get install -y ansible; "
        "elif command -v dnf >/dev/null 2>&1; then "
        "  dnf install -y ansible; "
        "elif command -v yum >/dev/null 2>&1; then "
        "  yum install -y ansible; "
        "fi"
    )
    run_remote_cmd(host, user, key_path, f"sudo bash -c '{script}'", timeout=300, port=port)
    logger.info("Ansible ready on %s", host)


def run_prehard_ansible_remote(
    host: str,
    user: str,
    key_path: Path,
    playbook_yaml: str,
    timeout: int = 1800,
    port: int = 22,
) -> None:
    """Upload a pre-hardening playbook to the remote host and run it locally there.

    The playbook is transferred via base64-encoded echo to avoid shell-quoting issues.
    It is run with ``ansible-playbook -i localhost, -c local`` so it affects the instance
    itself without needing an inventory file.
    """
    b64 = base64.b64encode(playbook_yaml.encode()).decode()
    # Write the playbook
    run_remote_cmd(
        host,
        user,
        key_path,
        f"echo '{b64}' | base64 -d | sudo tee /tmp/stratum-prehard.yml > /dev/null",
        port=port,
    )
    # Run it locally on the instance
    run_remote_cmd(
        host,
        user,
        key_path,
        "sudo ansible-playbook -i 'localhost,' -c local /tmp/stratum-prehard.yml",
        timeout=timeout,
        port=port,
    )
    logger.info("Pre-hardening playbook complete on %s", host)


def run_hardening_remote(
    host: str,
    user: str,
    key_path: Path,
    os_name: str,
    hardening_config: dict,
    extra_vars: dict | None = None,
    timeout: int = 3600,
    port: int = 22,
) -> None:
    """Run compliance hardening on the remote host based on the Pluggable Strategy."""
    strategy = hardening_config.get("strategy", "ansible-galaxy")
    if strategy == "none":
        logger.info("Hardening strategy is 'none' — skipping CIS compliance playbook.")
        return

    # Merge profile-tier Ansible-Lockdown vars into extra_vars
    profile_tier = hardening_config.get("profile_tier", "cis-l1")

    if strategy == "ansible-galaxy":
        role = hardening_config.get("role", "auto")
        pinned_version: str | None = None
        if role == "auto":
            bare_name = lockdown_role_for_os(os_name)
            role = f"ansible-lockdown.{bare_name}"
            pinned_version = _ROLE_PINNED_VERSION.get(bare_name)

        # Inject tier variables for this role
        tier_vars = tier_extra_vars(profile_tier, role)
        if tier_vars:
            extra_vars = {**tier_vars, **(extra_vars or {})}
        logger.info(
            "Installing Galaxy role %s%s on %s (tier=%s, tier_vars=%s)",
            role,
            f" (pinned {pinned_version})" if pinned_version else "",
            host,
            profile_tier,
            list(tier_vars.keys()),
        )
        # Install role on the remote instance. A pinned version is required
        # for roles whose published tags mix formats (e.g. "V1.0.0" alongside
        # "1.1.0") — installing with no version qualifier asks Galaxy to
        # compare all tags to find "latest", which then fails outright with
        # "Unable to compare role versions ... due to incompatible version
        # formats" (see _ROLE_PINNED_VERSION).
        install_spec = f"{role},{pinned_version}" if pinned_version else role
        run_remote_cmd(
            host,
            user,
            key_path,
            f"sudo ansible-galaxy install {install_spec} --force 2>&1",
            timeout=300,
            port=port,
        )

        # Build a minimal site playbook
        site_yaml = (
            "---\n"
            f"- name: Stratum Compliance Hardening ({role})\n"
            "  hosts: localhost\n"
            "  connection: local\n"
            "  become: true\n"
            "  roles:\n"
            f"    - {role}\n"
        )
        b64_site = base64.b64encode(site_yaml.encode()).decode()
        run_remote_cmd(
            host,
            user,
            key_path,
            f"echo '{b64_site}' | base64 -d | sudo tee /tmp/stratum-hardening.yml > /dev/null",
            port=port,
        )

    elif strategy == "git":
        repo_url = hardening_config.get("repo_url", "")
        playbook_file = hardening_config.get("playbook_file", "site.yml")
        if not repo_url:
            raise ValueError("Hardening strategy is 'git' but 'repo_url' is missing.")

        logger.info("Cloning Git repository %s on %s", repo_url, host)
        git_pkg = "git"
        run_remote_cmd(
            host,
            user,
            key_path,
            f"command -v git >/dev/null 2>&1 || (sudo apt-get update && sudo apt-get install -y {git_pkg} || sudo dnf install -y {git_pkg} || sudo yum install -y {git_pkg})",
            timeout=300,
            check=False,
            port=port,
        )

        # Clone the repo
        clone_cmd = (
            "sudo rm -rf /etc/ansible/stratum_custom_hardening && "
            f"sudo git clone {repo_url} /etc/ansible/stratum_custom_hardening"
        )
        run_remote_cmd(host, user, key_path, clone_cmd, timeout=300, port=port)

        logger.info("Git playbook selected: %s", playbook_file)
        run_remote_cmd(
            host,
            user,
            key_path,
            f"sudo cp /etc/ansible/stratum_custom_hardening/{playbook_file} /tmp/stratum-hardening.yml",
            port=port,
        )
    else:
        raise ValueError(f"Unknown hardening strategy: {strategy}")

    # Translate blueprint RuleOverride entries into Ansible extra vars.
    # Convention: rule_id maps directly to an Ansible-Lockdown boolean variable.
    # Overrides with enabled=False → set var to False; enabled=True with a value → set value.
    overrides: list[dict] = hardening_config.get("overrides", [])
    for override in overrides:
        rule_id = override.get("rule_id", "")
        if not rule_id:
            continue
        enabled = override.get("enabled", True)
        value = override.get("value")
        if value is not None:
            extra_vars = {**(extra_vars or {}), rule_id: value}
        else:
            extra_vars = {**(extra_vars or {}), rule_id: enabled}

    cmd = "sudo ansible-playbook -i 'localhost,' -c local /tmp/stratum-hardening.yml"
    if extra_vars:
        b64_ev = base64.b64encode(json.dumps(extra_vars).encode()).decode()
        run_remote_cmd(
            host,
            user,
            key_path,
            f"echo '{b64_ev}' | base64 -d | sudo tee /tmp/stratum-extravars.json > /dev/null",
            port=port,
        )
        cmd += " --extra-vars @/tmp/stratum-extravars.json"

    run_remote_cmd(host, user, key_path, cmd, timeout=timeout, port=port)
    logger.info("Compliance hardening complete on %s", host)


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def cleanup_instance_history_remote(host: str, user: str, key_path: Path, port: int = 22) -> None:
    """Clear OS history and logs before snapshot generation."""
    logger.info("Cleaning up instance logs and history before snapshot on %s", host)
    cmds = [
        "sudo rm -rf /tmp/stratum-*",
        "sudo rm -f /var/log/messages /var/log/syslog /var/log/auth.log",
        "sudo journalctl --vacuum-time=1s || true",
        "sudo sh -c 'cat /dev/null > /var/log/wtmp' || true",
        "cat /dev/null > ~/.bash_history || true",
        "sudo sh -c 'cat /dev/null > /root/.bash_history' || true",
        "sudo find /home -name '.bash_history' -exec sh -c 'cat /dev/null > {}' \\;",
    ]
    script = " ; ".join(cmds)
    # Ignore errors during cleanup as different OSs have different paths
    run_remote_cmd(host, user, key_path, script, check=False, port=port)


# ---------------------------------------------------------------------------
# OpenSCAP helpers
# ---------------------------------------------------------------------------


def install_oscap_on_remote(host: str, user: str, key_path: Path, port: int = 22) -> None:
    """Ensure oscap is installed on the remote.

    KNOWN GAP: on Debian-family targets this installs the `oscap` CLI only —
    it does NOT install SCAP content (the XCCDF datastream files under
    /usr/share/xml/scap/ssg/content/). `scap-security-guide` (bundled here
    previously) is the RHEL/Fedora package name and does not exist for
    Debian/Ubuntu under any name; `ssg-debderived` (also bundled previously)
    does not exist either. Bundling either into the same `apt-get install`
    call made the *entire* install fail even where `openscap-scanner` itself
    is available (Debian 12, Ubuntu 24.04+) — fixed by installing it alone.
    Ubuntu 22.04 additionally lacks `openscap-scanner` via apt in any channel
    (first appears in 24.04) — the whole install is a no-op there today.
    Getting real SCAP content onto a Debian-family target requires a separate
    fix (e.g. downloading a ComplianceAsCode/content release), tracked as a
    follow-up rather than solved here.
    """
    script = (
        "if command -v apt-get >/dev/null 2>&1; then "
        "  export DEBIAN_FRONTEND=noninteractive; "
        "  apt-get install -y openscap-scanner 2>&1; "
        "elif command -v dnf >/dev/null 2>&1; then "
        "  dnf install -y openscap openscap-scanner scap-security-guide 2>&1; "
        "elif command -v yum >/dev/null 2>&1; then "
        "  yum install -y openscap openscap-scanner scap-security-guide 2>&1; "
        "fi"
    )
    run_remote_cmd(host, user, key_path, f"sudo bash -c '{script}'", timeout=300, port=port)
    logger.info("OpenSCAP ready on %s", host)


def run_oscap_remote(
    host: str,
    user: str,
    key_path: Path,
    profile_id: str,
    datastream: str,
    results_path: str = "/tmp/stratum-oscap.xml",
    timeout: int = 600,
    port: int = 22,
) -> str:
    """Run ``oscap xccdf eval`` on *host* and return the XCCDF results XML.

    oscap exits with code 2 when findings are present (not an error for our purposes).
    Returns the raw XML content.
    """
    cmd = (
        f"sudo oscap xccdf eval "
        f"--profile {profile_id} "
        f"--results {results_path} "
        f"--report /tmp/stratum-oscap-report.html "
        f"{datastream}; "  # exit code 2 = findings — allowed
        f"cat {results_path}"
    )
    _, stdout, stderr = run_remote_cmd(host, user, key_path, cmd, timeout=timeout, check=False, port=port)
    if not stdout.strip():
        logger.warning("oscap produced no output; stderr: %s", stderr[:500])
    return stdout


# ---------------------------------------------------------------------------
# File transfer helpers
# ---------------------------------------------------------------------------


def copy_file_to_remote(
    local_path: str | Path,
    remote_path: str,
    host: str,
    user: str,
    key_path: Path,
    timeout: int = 120,
    port: int = 22,
) -> None:
    """Copy a local file to *remote_path* on *host* via SCP.

    Prefer this over the base64-echo approach for files larger than ~8 KB,
    as it avoids argument-length limitations and is significantly faster.
    """
    proc = subprocess.run(
        [
            "scp",
            "-i",
            str(key_path),
            "-P",
            str(port),
            *[arg for pair in zip(["-o"] * len(_SSH_OPTS[::2]), _SSH_OPTS[1::2], strict=True) for arg in pair],
            str(local_path),
            f"{user}@{host}:{remote_path}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scp to {host}:{remote_path} failed (exit {proc.returncode}):\n{proc.stderr[:400]}")
    logger.debug("Copied %s → %s:%s", local_path, host, remote_path)


def upload_content_to_remote(
    content: str,
    remote_path: str,
    host: str,
    user: str,
    key_path: Path,
    sudo: bool = True,
    timeout: int = 60,
    port: int = 22,
) -> None:
    """Write *content* to *remote_path* on *host*.

    Uses a temporary local file + SCP for reliable transfer regardless of
    content size or special characters (avoids shell-quoting pitfalls).
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        # SCP to a world-readable temp location, then move with sudo if needed
        staging = f"/tmp/stratum-upload-{os.path.basename(remote_path)}"
        copy_file_to_remote(tmp_path, staging, host, user, key_path, timeout=timeout, port=port)
        if sudo:
            run_remote_cmd(host, user, key_path, f"sudo mv {staging} {remote_path}", timeout=30, port=port)
        else:
            run_remote_cmd(host, user, key_path, f"mv {staging} {remote_path}", timeout=30, port=port)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------


def run_remote_cmd_with_retry(
    host: str,
    user: str,
    key_path: Path,
    command: str,
    retries: int = 3,
    retry_delay: float = 15.0,
    timeout: int = 300,
    check: bool = True,
    port: int = 22,
) -> tuple[int, str, str]:
    """Run *command* on *host* via SSH, retrying on transient connection errors.

    Retries on ``subprocess.TimeoutExpired`` and connection-refused / broken-pipe
    SSH errors. Does **not** retry on non-zero command exit codes.

    Args:
        retries:     Number of additional attempts after the first failure.
        retry_delay: Seconds to wait between attempts (linear backoff).
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            return run_remote_cmd(host, user, key_path, command, timeout=timeout, check=check, port=port)
        except subprocess.TimeoutExpired as exc:
            last_exc = exc
            logger.warning("SSH command timed out (attempt %d/%d)", attempt, retries + 1)
        except RuntimeError as exc:
            # Only retry on connection-level errors, not command failures.
            # "connection reset"/"kex_exchange_identification" covers a common
            # early-boot race: sshd's TCP listener is up (passing wait_for_ssh)
            # but sshd itself resets the connection until it's fully ready.
            msg = str(exc).lower()
            if any(
                kw in msg
                for kw in (
                    "connection refused",
                    "connection reset",
                    "kex_exchange_identification",
                    "broken pipe",
                    "no route",
                    "network",
                )
            ):
                last_exc = exc
                logger.warning("SSH connection error (attempt %d/%d): %s", attempt, retries + 1, exc)
            else:
                raise
        if attempt <= retries:
            time.sleep(retry_delay)
    raise RuntimeError(f"Command failed after {retries + 1} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Cloud-init readiness
# ---------------------------------------------------------------------------


def wait_for_cloud_init(
    host: str,
    user: str,
    key_path: Path,
    timeout: int = 300,
    port: int = 22,
) -> None:
    """Block until cloud-init finishes on *host*.

    Runs ``cloud-init status --wait`` on the remote; if cloud-init is not
    installed (bare metal or pre-baked images) the call is silently skipped.
    """
    rc, _, _ = run_remote_cmd(
        host,
        user,
        key_path,
        "command -v cloud-init >/dev/null 2>&1 && sudo cloud-init status --wait || true",
        timeout=timeout,
        check=False,
        port=port,
    )
    logger.info("cloud-init ready on %s (exit %s)", host, rc)
