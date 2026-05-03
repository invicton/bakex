# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for stratum.core.playbook_gen — Phase 1 TDD red run."""

from __future__ import annotations

from pathlib import Path

import yaml

from stratum.core.blueprint import ComplianceProfile
from stratum.core.playbook_gen import generate_prehard_playbook

# ---------------------------------------------------------------------------
# Minimal profile factory
# ---------------------------------------------------------------------------

_BASE = {
    "stratum_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {"name": "test-profile", "version": "1.0.0"},
    "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-0"},
    "compliance": {
        "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
        "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
    },
}


def _profile(**kwargs) -> ComplianceProfile:
    data = {**_BASE}
    data.update(kwargs)
    return ComplianceProfile.model_validate(data)


def _profile_with_system(**system_kwargs) -> ComplianceProfile:
    data = {**_BASE, "system": system_kwargs}
    return ComplianceProfile.model_validate(data)


def _profile_with_users(**users_kwargs) -> ComplianceProfile:
    data = {**_BASE, "users": users_kwargs}
    return ComplianceProfile.model_validate(data)


# ---------------------------------------------------------------------------
# PG-01: Profile with no optional sections → returns None
# ---------------------------------------------------------------------------


def test_no_optional_sections_returns_none():
    profile = _profile()
    result = generate_prehard_playbook(profile)
    assert result is None, "Profile with no system/filesystem/users must return None"


# ---------------------------------------------------------------------------
# PG-02: Returns a path pointing to a real file
# ---------------------------------------------------------------------------


def test_returns_path_to_real_file():
    profile = _profile_with_system(hostname="hardened-host")
    path = generate_prehard_playbook(profile)
    assert path is not None
    assert isinstance(path, Path)
    assert path.exists(), f"Generated playbook path does not exist: {path}"


# ---------------------------------------------------------------------------
# PG-03: Generated file is valid YAML
# ---------------------------------------------------------------------------


def test_generated_file_is_valid_yaml():
    profile = _profile_with_system(hostname="hardened-host")
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    parsed = yaml.safe_load(content)  # must not raise
    assert parsed is not None


# ---------------------------------------------------------------------------
# PG-04: Output is a list containing one play
# ---------------------------------------------------------------------------


def test_output_is_single_play_list():
    profile = _profile_with_system(hostname="hardened-host")
    path = generate_prehard_playbook(profile)
    plays = yaml.safe_load(path.read_text())
    assert isinstance(plays, list), "Playbook must be a YAML list"
    assert len(plays) == 1, "Playbook must contain exactly one play"


# ---------------------------------------------------------------------------
# PG-05: Play targets 'all' hosts with become: true
# ---------------------------------------------------------------------------


def test_play_targets_all_with_become():
    profile = _profile_with_system(hostname="hardened-host")
    path = generate_prehard_playbook(profile)
    play = yaml.safe_load(path.read_text())[0]
    assert play["hosts"] == "all"
    assert play["become"] is True


# ---------------------------------------------------------------------------
# PG-06: Hostname task present when hostname is set
# ---------------------------------------------------------------------------


def test_hostname_task_present():
    profile = _profile_with_system(hostname="cis-hardened-001")
    path = generate_prehard_playbook(profile)
    play = yaml.safe_load(path.read_text())[0]
    task_names = [t.get("name", "") for t in play["tasks"]]
    assert any("hostname" in name.lower() for name in task_names), (
        "A hostname task must be present when hostname is set"
    )


# ---------------------------------------------------------------------------
# PG-07: Hostname value appears in the tasks
# ---------------------------------------------------------------------------


def test_hostname_value_in_tasks():
    profile = _profile_with_system(hostname="my-cis-server")
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "my-cis-server" in content, "The configured hostname must appear in the playbook"


# ---------------------------------------------------------------------------
# PG-08: Timezone task present when timezone is non-UTC
# ---------------------------------------------------------------------------


def test_timezone_task_present_for_non_utc():
    profile = _profile_with_system(hostname="h", timezone="Asia/Kolkata")
    path = generate_prehard_playbook(profile)
    play = yaml.safe_load(path.read_text())[0]
    task_names = [t.get("name", "") for t in play["tasks"]]
    assert any("timezone" in name.lower() for name in task_names), "Timezone task must be present for non-UTC timezone"


# ---------------------------------------------------------------------------
# PG-09: No timezone task when timezone is UTC (default)
# ---------------------------------------------------------------------------


def test_no_timezone_task_for_utc():
    profile = _profile_with_system(hostname="h", timezone="UTC")
    path = generate_prehard_playbook(profile)
    play = yaml.safe_load(path.read_text())[0]
    task_names = [t.get("name", "") for t in play["tasks"]]
    assert not any("timezone" in name.lower() for name in task_names), (
        "No timezone task must be generated when timezone is UTC"
    )


# ---------------------------------------------------------------------------
# PG-10: AIDE tasks present when compliance.aide is True
# ---------------------------------------------------------------------------


def test_aide_tasks_present_when_aide_enabled():
    data = {
        **_BASE,
        "system": {"hostname": "h"},
        "compliance": {
            **_BASE["compliance"],
            "aide": True,
        },
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "aide" in content.lower(), "AIDE install/init tasks must be present when aide=True"


# ---------------------------------------------------------------------------
# PG-11: FIPS tasks present when compliance.fips is True
# ---------------------------------------------------------------------------


def test_fips_tasks_present_when_fips_enabled():
    data = {
        **_BASE,
        "system": {"hostname": "h"},
        "compliance": {
            **_BASE["compliance"],
            "fips": True,
        },
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "fips" in content.lower(), "FIPS tasks must be present when fips=True"


# ---------------------------------------------------------------------------
# PG-12: Root lock task present when users.root.lock is True
# ---------------------------------------------------------------------------


def test_root_lock_task_present():
    data = {**_BASE, "users": {"root": {"lock": True}}}
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "root" in content.lower()
    assert "lock" in content.lower() or "password_lock" in content.lower()


# ---------------------------------------------------------------------------
# PG-13: User account task present for each account in users.accounts
# ---------------------------------------------------------------------------


def test_user_account_tasks_created():
    data = {
        **_BASE,
        "users": {
            "accounts": [
                {"name": "appuser", "shell": "/bin/bash"},
                {"name": "svcaccount", "shell": "/sbin/nologin", "system": True},
            ]
        },
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "appuser" in content, "appuser account task must appear in playbook"
    assert "svcaccount" in content, "svcaccount task must appear in playbook"


# ---------------------------------------------------------------------------
# PG-14: SSH authorized key task present when ssh_authorized_keys set
# ---------------------------------------------------------------------------


def test_ssh_authorized_key_task_present():
    data = {
        **_BASE,
        "users": {
            "accounts": [
                {
                    "name": "appuser",
                    "shell": "/bin/bash",
                    "ssh_authorized_keys": ["ssh-ed25519 AAAAC3Nz testkey"],
                }
            ]
        },
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "authorized_key" in content.lower() or "ssh_authorized_keys" in content.lower()
    assert "testkey" in content


# ---------------------------------------------------------------------------
# PG-15: LVM tasks present for lvm mount entries
# ---------------------------------------------------------------------------


def test_lvm_tasks_present_for_lvm_mounts():
    data = {
        **_BASE,
        "filesystem": [
            {
                "mountpoint": "/var",
                "device": "/dev/sdb",
                "fstype": "ext4",
                "options": ["defaults", "nodev"],
                "mount_type": "lvm",
                "lvm_vg": "vg_data",
                "size": "20G",
            }
        ],
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "vg_data" in content, "LVM volume group name must appear in playbook"
    assert "lvg" in content or "lvol" in content, "LVM task modules must appear in playbook"


# ---------------------------------------------------------------------------
# PG-16: Filesystem mount task present for plain mounts
# ---------------------------------------------------------------------------


def test_plain_mount_task_present():
    data = {
        **_BASE,
        "filesystem": [
            {
                "mountpoint": "/tmp",
                "device": "tmpfs",
                "fstype": "tmpfs",
                "options": ["nodev", "nosuid", "noexec"],
                "size": "1G",
            }
        ],
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "/tmp" in content
    assert "tmpfs" in content


# ---------------------------------------------------------------------------
# PG-17: SELinux task present when selinux_mode is set
# ---------------------------------------------------------------------------


def test_selinux_task_present():
    profile = _profile_with_system(hostname="h", selinux_mode="enforcing")
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "selinux" in content.lower(), "SELinux task must appear when selinux_mode is set"
    assert "enforcing" in content


# ---------------------------------------------------------------------------
# PG-18: Play name includes profile name and version
# ---------------------------------------------------------------------------


def test_play_name_includes_profile_metadata():
    profile = _profile_with_system(hostname="h")
    path = generate_prehard_playbook(profile)
    play = yaml.safe_load(path.read_text())[0]
    assert "test-profile" in play["name"], "Play name must include profile metadata.name"
    assert "1.0.0" in play["name"], "Play name must include profile metadata.version"


# ---------------------------------------------------------------------------
# PG-19: LUKS encrypt task present when encrypt=True on LVM mount
# ---------------------------------------------------------------------------


def test_luks_encrypt_task_present():
    data = {
        **_BASE,
        "filesystem": [
            {
                "mountpoint": "/var/log",
                "device": "/dev/sdb",
                "fstype": "ext4",
                "options": ["defaults"],
                "mount_type": "lvm",
                "lvm_vg": "vg_secure",
                "size": "10G",
                "encrypt": True,
            }
        ],
    }
    profile = ComplianceProfile.model_validate(data)
    path = generate_prehard_playbook(profile)
    content = path.read_text()
    assert "luks" in content.lower() or "luks_device" in content.lower(), (
        "LUKS encryption task must be present when encrypt=True"
    )
