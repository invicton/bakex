# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""ComplianceProfile / HardeningBlueprint Pydantic schema + YAML loader."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# Blueprint names become filenames (`user_profiles_dir / f"{name}.yaml"`), so this
# must reject path separators and traversal sequences, not just null bytes.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# ---------------------------------------------------------------------------
# Core metadata
# ---------------------------------------------------------------------------


class ProfileMetadata(BaseModel):
    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    source_badge: str = "Local"  # Official | Community | Private | Local

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not _SAFE_NAME_RE.match(v):
            raise ValueError(
                "metadata.name must be 1-128 characters, start with a letter or digit, "
                "and contain only letters, digits, '.', '_', or '-' "
                "(no path separators or '..' — this becomes a filename)"
            )
        return v


class ExtraVolume(BaseModel):
    device_name: str
    size_gb: int
    volume_type: str = "gp3"


class TargetSpec(BaseModel):
    os: str  # e.g. "ubuntu22.04", "rocky9", "rhel9"
    arch: str = "x86_64"
    provider: str  # e.g. "aws", "gcp", "azure", "linode", "proxmox"
    base_image: str  # AMI ID, GCP image family, Azure offer, VMID, etc.
    instance_type: str = ""  # Provider-specific VM size: "t3.medium", "e2-medium", "Standard_B2s"
    root_volume_size_gb: int = 20  # Root disk size in GB
    extra_volumes: list[ExtraVolume] = Field(default_factory=list)


class ComplianceSpec(BaseModel):
    benchmark: str  # e.g. "xccdf_org.ssgproject.content_benchmark_UBUNTU22"
    profile: str  # e.g. "xccdf_org.ssgproject.content_profile_cis_level1_server"
    datastream: str  # Path to SCAP datastream file on the target
    fail_on_findings: bool = True
    severity_threshold: str = "medium"  # low | medium | high | critical
    aide: bool = False  # Initialise AIDE file-integrity database at build time
    fips: bool = False  # Enable FIPS 140-2 mode (kernel param + crypto-policies)


class ControlOverride(BaseModel):
    enabled: bool
    justification: str


class RuleOverride(BaseModel):
    """Per-rule customisation within a hardening profile tier."""

    rule_id: str
    enabled: bool = True
    value: str | None = None  # Override the rule's default value (e.g. MaxAuthTries)


# ---------------------------------------------------------------------------
# Hardening Strategy
# ---------------------------------------------------------------------------


class HardeningStrategy(str, Enum):
    GALAXY = "ansible-galaxy"
    GIT = "git"
    NONE = "none"


class HardeningConfig(BaseModel):
    strategy: HardeningStrategy = HardeningStrategy.GALAXY
    role: str = "auto"
    repo_url: str = ""
    playbook_file: str = "site.yml"
    profile_tier: Literal["cis-l1", "cis-l2", "stig", "custom"] = "cis-l1"
    overrides: list[RuleOverride] = Field(default_factory=list)
    add_rules: list[str] = Field(default_factory=list)  # cherry-pick rules from higher tiers


# ---------------------------------------------------------------------------
# v0.2 expanded blueprint sections
# ---------------------------------------------------------------------------


class SystemConfig(BaseModel):
    """OS-level settings applied before Ansible-Lockdown hardening."""

    hostname: str | None = None
    timezone: str = "UTC"  # IANA timezone, e.g. "America/New_York"
    locale: str = "en_US.UTF-8"
    selinux_mode: str | None = None  # enforcing | permissive | disabled | None (skip)


class MountEntry(BaseModel):
    """A single filesystem mount point with CIS-compliant options."""

    device: str  # e.g. "tmpfs", "/dev/sdb1", "UUID=..."
    mountpoint: str  # e.g. "/tmp", "/var/tmp", "/home"
    fstype: str = "tmpfs"  # ext4 | xfs | tmpfs | vfat | ...
    options: list[str] = Field(default_factory=lambda: ["defaults"])
    size: str | None = None  # For tmpfs: "2G"; disk-based mounts: ignored
    mount_type: Literal["primary", "lvm", "swap"] = "primary"
    encrypt: bool = False  # LUKS-encrypt this volume (requires mount_type=lvm)
    lvm_vg: str | None = None  # LVM volume group name (e.g. "vg_data")


class RootConfig(BaseModel):
    """Root account configuration."""

    lock: bool = True  # Lock the root account (recommended)
    password_hash: str | None = None  # SHA-512 crypt hash (overrides lock when set)


class UserAccount(BaseModel):
    """A non-root user account to create on the hardened image."""

    name: str
    comment: str = ""
    groups: list[str] = Field(default_factory=list)  # e.g. ["wheel", "sudo", "docker"]
    shell: str = "/bin/bash"
    system: bool = False  # System account (UID < 1000)
    password_hash: str | None = None  # SHA-512 crypt hash
    ssh_authorized_keys: list[str] = Field(default_factory=list)


class UsersConfig(BaseModel):
    """Root and extra user account configuration."""

    root: RootConfig = Field(default_factory=RootConfig)
    accounts: list[UserAccount] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Primary schema — ComplianceProfile / HardeningBlueprint
# ---------------------------------------------------------------------------


class ComplianceProfile(BaseModel):
    """Stratum blueprint: describes exactly how to build a reproducible hardened image.

    kind: ComplianceProfile  — legacy (compliance-only, no system/filesystem/users)
    kind: HardeningBlueprint — full blueprint with system, filesystem, users sections
    """

    stratum_version: str
    kind: Literal["ComplianceProfile", "HardeningBlueprint"]
    metadata: ProfileMetadata
    target: TargetSpec
    compliance: ComplianceSpec
    controls: dict[str, bool | ControlOverride] = Field(default_factory=dict)
    hardening: HardeningConfig = Field(default_factory=HardeningConfig)

    # Extended blueprint sections — all optional; existing YAML files are unaffected
    system: SystemConfig | None = None
    filesystem: list[MountEntry] = Field(default_factory=list)
    users: UsersConfig | None = None


# Alias — preferred name for new YAML files
HardeningBlueprint = ComplianceProfile


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_profile(path: Path) -> ComplianceProfile:
    """Load and validate a ComplianceProfile / HardeningBlueprint from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return ComplianceProfile.model_validate(raw)


def list_profiles(profiles_dir: Path) -> list[Path]:
    """Return all .yaml / .yml files under profiles_dir (recursive)."""
    return sorted(p for ext in ("*.yaml", "*.yml") for p in profiles_dir.rglob(ext))
