# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Generate an Ansible pre-hardening playbook from a HardeningBlueprint.

This playbook runs *before* Ansible-Lockdown to configure the OS-level
settings that CIS benchmarks require to be in place: hostname, timezone,
filesystem mount options, root account, and extra user accounts.

The generated playbook is written to a temporary directory and returned
as a file path. Callers own the path; clean up the parent temp dir when done.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from statim.core.blueprint import ComplianceProfile, MountEntry, SystemConfig, UsersConfig


def generate_prehard_playbook(profile: ComplianceProfile) -> Path | None:
    """Generate a pre-hardening Ansible playbook from a blueprint.

    Returns:
        Path to the generated ``prehard.yml`` file, or ``None`` if the
        blueprint has no system/filesystem/users sections to configure.
    """
    tasks: list[dict] = []

    if profile.system:
        tasks.extend(_system_tasks(profile.system))

    if profile.filesystem:
        tasks.extend(_filesystem_tasks(profile.filesystem))
        tasks.extend(_lvm_tasks(profile.filesystem))

    if profile.compliance.aide:
        tasks.extend(_aide_tasks())

    if profile.compliance.fips:
        tasks.extend(_fips_tasks())

    if profile.users:
        tasks.extend(_users_tasks(profile.users))

    if not tasks:
        return None

    play = {
        "name": f"Statim pre-hardening system configuration — {profile.metadata.name} v{profile.metadata.version}",
        "hosts": "all",
        "become": True,
        "gather_facts": True,
        "tasks": tasks,
    }

    tmp_dir = Path(tempfile.mkdtemp(prefix="statim-playbook-"))
    playbook_path = tmp_dir / "prehard.yml"
    playbook_path.write_text(yaml.dump([play], default_flow_style=False, sort_keys=False, allow_unicode=True))
    return playbook_path


# ---------------------------------------------------------------------------
# Task generators
# ---------------------------------------------------------------------------


def _system_tasks(cfg: SystemConfig) -> list[dict]:
    tasks: list[dict] = []

    if cfg.hostname:
        tasks.append(
            {
                "name": "Set system hostname",
                "ansible.builtin.hostname": {"name": cfg.hostname},
            }
        )
        tasks.append(
            {
                "name": "Update /etc/hosts with new hostname",
                "ansible.builtin.lineinfile": {
                    "path": "/etc/hosts",
                    "regexp": r"^127\.0\.1\.1",
                    "line": f"127.0.1.1 {cfg.hostname}",
                    "state": "present",
                    "create": True,
                },
            }
        )

    if cfg.timezone and cfg.timezone != "UTC":
        tasks.append(
            {
                "name": f"Set timezone to {cfg.timezone}",
                "community.general.timezone": {"name": cfg.timezone},
            }
        )

    if cfg.locale:
        tasks.append(
            {
                "name": f"Set system locale to {cfg.locale}",
                "ansible.builtin.command": f"localectl set-locale LANG={cfg.locale}",
                "changed_when": True,
                "failed_when": False,
            }
        )

    if cfg.selinux_mode:
        tasks.append(
            {
                "name": f"Set SELinux mode to {cfg.selinux_mode}",
                "ansible.posix.selinux": {
                    "policy": "targeted",
                    "state": cfg.selinux_mode,
                },
            }
        )

    return tasks


def _filesystem_tasks(mounts) -> list[dict]:
    tasks: list[dict] = []

    for entry in mounts:
        opts = ",".join(entry.options)
        if entry.size and entry.fstype == "tmpfs":
            opts = f"{opts},size={entry.size}"

        if entry.fstype != "tmpfs":
            tasks.append(
                {
                    "name": f"Format {entry.device} as {entry.fstype}",
                    "community.general.filesystem": {
                        "fstype": entry.fstype,
                        "dev": entry.device,
                    },
                }
            )

        tasks.append(
            {
                "name": f"Configure mount {entry.mountpoint} ({entry.fstype})",
                "ansible.posix.mount": {
                    "path": entry.mountpoint,
                    "src": entry.device,
                    "fstype": entry.fstype,
                    "opts": opts,
                    "state": "mounted" if entry.fstype != "swap" else "present",
                },
            }
        )

        if entry.fstype == "swap":
            tasks.append(
                {
                    "name": f"Enable swap on {entry.device}",
                    "ansible.builtin.command": f"swapon {entry.device}",
                    "changed_when": False,
                    "failed_when": False,
                }
            )

    return tasks


def _lvm_tasks(mounts: list[MountEntry]) -> list[dict]:
    """Generate LVM VG/LV creation and optional LUKS encryption tasks.

    Only processes entries where ``mount_type == "lvm"``.  Plain primary and
    swap entries are handled by :func:`_filesystem_tasks` and skipped here.
    """
    tasks: list[dict] = []

    for entry in mounts:
        if entry.mount_type != "lvm":
            continue
        if not entry.lvm_vg:
            continue  # No VG name — skip; caller should validate blueprint

        lv_name = entry.mountpoint.lstrip("/").replace("/", "_") or "data"

        tasks.append(
            {
                "name": f"Create LVM volume group {entry.lvm_vg} on {entry.device}",
                "community.general.lvg": {
                    "vg": entry.lvm_vg,
                    "pvs": entry.device,
                    "state": "present",
                },
            }
        )
        tasks.append(
            {
                "name": f"Create LVM logical volume lv_{lv_name} in {entry.lvm_vg}",
                "community.general.lvol": {
                    "vg": entry.lvm_vg,
                    "lv": f"lv_{lv_name}",
                    "size": entry.size or "100%FREE",
                    "state": "present",
                },
            }
        )

        lv_path = f"/dev/{entry.lvm_vg}/lv_{lv_name}"

        if entry.encrypt:
            tasks.append(
                {
                    "name": f"LUKS-encrypt {lv_path}",
                    "community.crypto.luks_device": {
                        "device": lv_path,
                        "state": "present",
                        "type": "luks2",
                    },
                }
            )
            # After LUKS formatting the mapped device holds the fs
            lv_path = f"/dev/mapper/{entry.lvm_vg}-lv_{lv_name}"

        tasks.append(
            {
                "name": f"Format {lv_path} as {entry.fstype}",
                "community.general.filesystem": {
                    "fstype": entry.fstype,
                    "dev": lv_path,
                },
            }
        )
        opts = ",".join(entry.options) if entry.options else "defaults"
        tasks.append(
            {
                "name": f"Mount {lv_path} at {entry.mountpoint}",
                "ansible.posix.mount": {
                    "path": entry.mountpoint,
                    "src": lv_path,
                    "fstype": entry.fstype,
                    "opts": opts,
                    "state": "mounted",
                },
            }
        )

    return tasks


def _aide_tasks() -> list[dict]:
    """Generate tasks that install AIDE and initialise the integrity database."""
    return [
        {
            "name": "Install AIDE file-integrity monitor",
            "ansible.builtin.package": {
                "name": "aide",
                "state": "present",
            },
        },
        {
            "name": "Initialise AIDE database",
            "ansible.builtin.command": "aide --init",
            "args": {"creates": "/var/lib/aide/aide.db.new"},
            "changed_when": True,
        },
        {
            "name": "Activate AIDE database",
            "ansible.builtin.command": "mv /var/lib/aide/aide.db.new /var/lib/aide/aide.db",
            "args": {"creates": "/var/lib/aide/aide.db"},
            "changed_when": True,
        },
        {
            "name": "Enable aide integrity check timer (if available)",
            "ansible.builtin.systemd": {
                "name": "aidecheck.timer",
                "enabled": True,
                "state": "started",
            },
            "failed_when": False,
        },
    ]


def _fips_tasks() -> list[dict]:
    """Generate tasks that enable FIPS 140-2 mode.

    Supports both RHEL-family (``fips-mode-setup``, ``grubby``) and
    Debian-family (``update-crypto-policies``, ``/etc/default/grub``).
    Uses ``failed_when: false`` on distro-specific steps so the playbook
    runs portably without an OS check.
    """
    return [
        {
            "name": "Install FIPS crypto-policy tooling (RHEL family)",
            "ansible.builtin.package": {
                "name": ["crypto-policies", "crypto-policies-scripts"],
                "state": "present",
            },
            "failed_when": False,
        },
        {
            "name": "Enable FIPS mode via fips-mode-setup (RHEL family)",
            "ansible.builtin.command": "fips-mode-setup --enable",
            "changed_when": True,
            "failed_when": False,
        },
        {
            "name": "Set crypto-policy to FIPS (Debian/Ubuntu family)",
            "ansible.builtin.command": "update-crypto-policies --set FIPS",
            "changed_when": True,
            "failed_when": False,
        },
        {
            "name": "Add fips=1 kernel parameter via grubby (RHEL family)",
            "ansible.builtin.command": "grubby --update-kernel=ALL --args=fips=1",
            "changed_when": True,
            "failed_when": False,
        },
        {
            "name": "Add fips=1 to GRUB_CMDLINE_LINUX (Debian/Ubuntu family)",
            "ansible.builtin.lineinfile": {
                "path": "/etc/default/grub",
                "regexp": r"^GRUB_CMDLINE_LINUX=",
                "backrefs": True,
                "line": r'GRUB_CMDLINE_LINUX="\1 fips=1"',
                "state": "present",
            },
            "register": "grub_fips",
            "failed_when": False,
        },
        {
            "name": "Rebuild GRUB config after FIPS kernel arg update (Debian/Ubuntu family)",
            "ansible.builtin.command": "update-grub",
            "when": "grub_fips is changed",
            "changed_when": True,
            "failed_when": False,
        },
        {
            "name": "Schedule reboot to activate FIPS mode",
            "ansible.builtin.reboot": {
                "msg": "Rebooting to activate FIPS 140-2 mode",
                "reboot_timeout": 300,
            },
        },
    ]


def _users_tasks(cfg: UsersConfig) -> list[dict]:
    tasks: list[dict] = []

    # Root account
    if cfg.root.lock and not cfg.root.password_hash:
        tasks.append(
            {
                "name": "Lock root account",
                "ansible.builtin.user": {
                    "name": "root",
                    "password_lock": True,
                },
            }
        )
    elif cfg.root.password_hash:
        tasks.append(
            {
                "name": "Set root password hash",
                "ansible.builtin.user": {
                    "name": "root",
                    "password": cfg.root.password_hash,
                    "update_password": "always",
                },
            }
        )

    # Extra user accounts
    for user in cfg.accounts:
        user_mod: dict = {
            "name": user.name,
            "state": "present",
            "create_home": True,
            "shell": user.shell,
            "append": True,
        }
        if user.comment:
            user_mod["comment"] = user.comment
        if user.groups:
            user_mod["groups"] = user.groups
        if user.system:
            user_mod["system"] = True
        if user.password_hash:
            user_mod["password"] = user.password_hash
            user_mod["update_password"] = "always"

        tasks.append(
            {
                "name": f"Create user account: {user.name}",
                "ansible.builtin.user": user_mod,
            }
        )

        for key in user.ssh_authorized_keys:
            tasks.append(
                {
                    "name": f"Authorize SSH key for {user.name}",
                    "ansible.posix.authorized_key": {
                        "user": user.name,
                        "key": key,
                        "state": "present",
                    },
                }
            )

    return tasks
