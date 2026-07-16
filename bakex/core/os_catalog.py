# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Static OS/provider compatibility catalog and CIS reference data."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# OS catalog — slug → metadata + provider compatibility
# ---------------------------------------------------------------------------

OS_CATALOG: dict[str, dict] = {
    "amazon-linux-2023": {
        "display": "Amazon Linux 2023",
        "icon": "🟠",
        "providers": ["aws"],
        "min_root_gb": 15,
        "default_base_image": {
            "aws": "ami-0190ba1cb5ab4e9e8",  # fallback us-east-1; resolved at build time
        },
        "aws_image_query": {
            "owner": "137112412989",  # Amazon
            "name_pattern": "al2023-ami-2023.*-kernel-*-x86_64",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_AMAZON_LINUX_2023",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_server_l1", "l2": "cis"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-al2023-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2"],
        "selinux": True,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.amazon2023_cis",
            "cis-l2": "ansible-lockdown.amazon2023_cis",
        },
    },
    "ubuntu22.04": {
        "display": "Ubuntu 22.04 LTS",
        "icon": "🟣",
        "providers": ["aws", "gcp", "azure", "digitalocean", "linode", "kvm"],
        "min_root_gb": 20,
        "default_base_image": {
            "aws": "ami-00de3875b03809ec5",  # fallback us-east-1; resolved at build time
            "gcp": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts",
            "azure": "ubuntu2204",
            "kvm": "ubuntu22.04",  # downloadable OS slug — auto-fetched + checksum-verified
            "digitalocean": "ubuntu-22-04-x64",
            "linode": "linode/ubuntu22.04",
        },
        "aws_image_query": {
            "owner": "099720109477",  # Canonical
            "name_pattern": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_level1_server", "l2": "cis_level2_server"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2"],
        "selinux": False,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.ubuntu22_cis",
            "cis-l2": "ansible-lockdown.ubuntu22_cis",
        },
    },
    "ubuntu24.04": {
        "display": "Ubuntu 24.04 LTS",
        "icon": "🟣",
        "providers": ["aws", "gcp", "azure", "digitalocean", "linode", "kvm"],
        "min_root_gb": 20,
        "default_base_image": {
            "aws": "ami-04eaa218f1349d88b",  # fallback us-east-1; resolved at build time
            "gcp": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts",
            "azure": "ubuntu2404",
            "digitalocean": "ubuntu-24-04-x64",
            "linode": "linode/ubuntu24.04",
            "kvm": "ubuntu24.04",  # downloadable OS slug — auto-fetched + checksum-verified
        },
        "aws_image_query": {
            "owner": "099720109477",  # Canonical
            "name_pattern": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2404",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_level1_server", "l2": "cis_level2_server"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2"],
        "selinux": False,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.ubuntu24_cis",
            "cis-l2": "ansible-lockdown.ubuntu24_cis",
        },
    },
    "rocky9": {
        "display": "Rocky Linux 9",
        "icon": "🪨",
        "providers": ["aws", "gcp", "azure", "digitalocean", "linode", "proxmox"],
        "min_root_gb": 20,
        "default_base_image": {
            "aws": "ami-078448b73f6313465",  # fallback us-east-1; resolved at build time
            "gcp": "projects/rocky-linux-cloud/global/images/family/rocky-linux-9",
            "azure": "rocky9",
            "digitalocean": "rockylinux-9-x64",
            "linode": "linode/rocky9",
            "proxmox": "",
        },
        "aws_image_query": {
            "owner": "679593333241",  # Rocky Linux Foundation
            "name_pattern": "Rocky-9-EC2-Base-9.*-*.x86_64-*",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_RHEL-9",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_server_l1", "l2": "cis"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-rl9-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2", "stig"],
        "selinux": True,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.rhel9_cis",
            "cis-l2": "ansible-lockdown.rhel9_cis",
            "stig": "ansible-lockdown.rhel9_stig",
        },
    },
    "rhel9": {
        "display": "RHEL 9",
        "icon": "🔴",
        "providers": ["aws", "azure", "gcp"],
        "min_root_gb": 20,
        "default_base_image": {
            "aws": "ami-09216e44daeab9582",  # fallback us-east-1; resolved at build time
            "azure": "rhel9",
            "gcp": "projects/rhel-cloud/global/images/family/rhel-9",
        },
        "aws_image_query": {
            "owner": "309956199498",  # Red Hat
            "name_pattern": "RHEL-9.*_HVM-*-x86_64-*-Hourly2-GP3",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_RHEL-9",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_server_l1", "l2": "cis"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2", "stig"],
        "selinux": True,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.rhel9_cis",
            "cis-l2": "ansible-lockdown.rhel9_cis",
            "stig": "ansible-lockdown.rhel9_stig",
        },
    },
    "alma9": {
        "display": "AlmaLinux 9",
        "icon": "🅰️",
        "providers": ["aws", "azure"],
        "min_root_gb": 20,
        "default_base_image": {
            "aws": "ami-0f673487d7e5f89ca",  # fallback us-east-1; resolved at build time
            "azure": "alma9",
        },
        "aws_image_query": {
            "owner": "764336703387",  # AlmaLinux OS Foundation
            "name_pattern": "AlmaLinux OS 9*x86_64*",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_RHEL-9",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_server_l1", "l2": "cis"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2"],
        "selinux": True,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.rhel9_cis",
            "cis-l2": "ansible-lockdown.rhel9_cis",
        },
    },
    "debian12": {
        "display": "Debian 12 (Bookworm)",
        "icon": "🌀",
        "providers": ["aws", "gcp", "azure", "digitalocean", "linode", "kvm"],
        "min_root_gb": 15,
        "default_base_image": {
            "aws": "ami-09f28a87e74de5c5a",  # fallback us-east-1; resolved at build time
            "gcp": "projects/debian-cloud/global/images/family/debian-12",
            "azure": "debian12",
            "digitalocean": "debian-12-x64",
            "linode": "linode/debian12",
            "kvm": "debian12",  # downloadable OS slug — auto-fetched + checksum-verified
        },
        "aws_image_query": {
            "owner": "136693071363",  # Debian
            "name_pattern": "debian-12-amd64-*",
        },
        "scap_benchmark": "xccdf_org.ssgproject.content_benchmark_DEBIAN12",
        "scap_profile_prefix": "xccdf_org.ssgproject.content_profile_",
        "cis_profile_suffixes": {"l1": "cis_level1_server", "l2": "cis_level2_server"},
        "scap_datastream": "/usr/share/xml/scap/ssg/content/ssg-debian12-ds.xml",
        "supported_tiers": ["cis-l1", "cis-l2"],
        "selinux": False,
        "lockdown_roles": {
            "cis-l1": "ansible-lockdown.deb12_cis",
            "cis-l2": "ansible-lockdown.deb12_cis",
        },
    },
}

# ---------------------------------------------------------------------------
# Provider catalog — slug → display metadata
# ---------------------------------------------------------------------------

PROVIDER_CATALOG: dict[str, dict] = {
    "aws": {
        "display": "AWS",
        "label": "Amazon Web Services",
        "icon": "☁️",
        "color": "amber",
    },
    "gcp": {
        "display": "GCP",
        "label": "Google Cloud",
        "icon": "🔵",
        "color": "blue",
    },
    "azure": {
        "display": "Azure",
        "label": "Microsoft Azure",
        "icon": "🔷",
        "color": "blue",
    },
    "digitalocean": {
        "display": "DigitalOcean",
        "label": "DigitalOcean",
        "icon": "🌊",
        "color": "cyan",
    },
    "linode": {
        "display": "Linode",
        "label": "Akamai Linode",
        "icon": "🟢",
        "color": "green",
    },
    "proxmox": {
        "display": "Proxmox",
        "label": "Proxmox VE",
        "icon": "🖥️",
        "color": "orange",
    },
}

# ---------------------------------------------------------------------------
# Instance type suggestions per provider
# ---------------------------------------------------------------------------

INSTANCE_TYPES: dict[str, list[dict]] = {
    "aws": [
        {"value": "t3.medium", "label": "t3.medium   — 2 vCPU / 4 GB RAM  (General Purpose)"},
        {"value": "t3.large", "label": "t3.large    — 2 vCPU / 8 GB RAM  (General Purpose)"},
        {"value": "m5.large", "label": "m5.large    — 2 vCPU / 8 GB RAM  (Memory Balanced)"},
        {"value": "m5.xlarge", "label": "m5.xlarge   — 4 vCPU / 16 GB RAM (Memory Balanced)"},
        {"value": "c5.large", "label": "c5.large    — 2 vCPU / 4 GB RAM  (Compute Optimised)"},
        {"value": "c5.xlarge", "label": "c5.xlarge   — 4 vCPU / 8 GB RAM  (Compute Optimised)"},
    ],
    "gcp": [
        {"value": "e2-medium", "label": "e2-medium      — 2 vCPU / 4 GB RAM"},
        {"value": "e2-standard-2", "label": "e2-standard-2  — 2 vCPU / 8 GB RAM"},
        {"value": "n2-standard-2", "label": "n2-standard-2  — 2 vCPU / 8 GB RAM"},
        {"value": "n2-standard-4", "label": "n2-standard-4  — 4 vCPU / 16 GB RAM"},
    ],
    "azure": [
        {"value": "Standard_B2s", "label": "Standard_B2s    — 2 vCPU / 4 GB RAM"},
        {"value": "Standard_B2ms", "label": "Standard_B2ms   — 2 vCPU / 8 GB RAM"},
        {"value": "Standard_D2s_v3", "label": "Standard_D2s_v3 — 2 vCPU / 8 GB RAM"},
        {"value": "Standard_D4s_v3", "label": "Standard_D4s_v3 — 4 vCPU / 16 GB RAM"},
    ],
    "digitalocean": [
        {"value": "s-2vcpu-4gb", "label": "s-2vcpu-4gb  — 2 vCPU / 4 GB RAM"},
        {"value": "s-4vcpu-8gb", "label": "s-4vcpu-8gb  — 4 vCPU / 8 GB RAM"},
        {"value": "g-2vcpu-8gb", "label": "g-2vcpu-8gb  — 2 vCPU / 8 GB RAM (General)"},
    ],
    "linode": [
        {"value": "g6-nanode-1", "label": "g6-nanode-1   — 1 vCPU / 1 GB RAM"},
        {"value": "g6-standard-2", "label": "g6-standard-2 — 1 vCPU / 2 GB RAM"},
        {"value": "g6-standard-4", "label": "g6-standard-4 — 2 vCPU / 4 GB RAM"},
        {"value": "g6-standard-6", "label": "g6-standard-6 — 4 vCPU / 8 GB RAM"},
    ],
    "proxmox": [],
}

# ---------------------------------------------------------------------------
# CIS standard filesystem layout recommendation
# ---------------------------------------------------------------------------

CIS_STANDARD_LAYOUT: list[dict] = [
    {
        "mountpoint": "/var",
        "fstype": "xfs",
        "size_gb": 8,
        "options": ["defaults", "nodev"],
        "description": "CIS 1.1.3 — Separate partition for /var",
    },
    {
        "mountpoint": "/var/log",
        "fstype": "xfs",
        "size_gb": 4,
        "options": ["defaults", "nodev", "nosuid", "noexec"],
        "description": "CIS 1.1.4 — Separate partition for /var/log",
    },
    {
        "mountpoint": "/var/log/audit",
        "fstype": "xfs",
        "size_gb": 2,
        "options": ["defaults", "nodev", "nosuid", "noexec"],
        "description": "CIS 1.1.5 — Separate partition for /var/log/audit",
    },
    {
        "mountpoint": "/home",
        "fstype": "xfs",
        "size_gb": 4,
        "options": ["defaults", "nodev", "nosuid"],
        "description": "CIS 1.1.6 — Separate partition for /home",
    },
    {
        "mountpoint": "/tmp",
        "fstype": "tmpfs",
        "size_gb": 2,
        "options": ["rw", "nosuid", "nodev", "noexec", "relatime"],
        "description": "CIS 1.1.1 — Separate /tmp with noexec,nosuid,nodev",
    },
]

# ---------------------------------------------------------------------------
# CIS control stubs per OS/tier
# These are representative samples. Production use should parse SCAP datastreams.
# ---------------------------------------------------------------------------

# CIS Ubuntu 22.04/24.04 Level 1 — comprehensive rule set
# Sections: 1=Initial Setup, 2=Services, 3=Network, 4=Logging/Audit, 5=Access/Auth, 6=Maintenance
_UBUNTU22_CIS_L1 = [
    # --- Section 1: Initial Setup — Filesystem ---
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_tmp",
        "title": "1.1.1 Ensure /tmp is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_nodev",
        "title": "1.1.2 Ensure /tmp is mounted with nodev",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_nosuid",
        "title": "1.1.3 Ensure /tmp is mounted with nosuid",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_noexec",
        "title": "1.1.4 Ensure /tmp is mounted with noexec",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_var",
        "title": "1.1.5 Ensure /var is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_var_tmp",
        "title": "1.1.6 Ensure /var/tmp is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_tmp_nodev",
        "title": "1.1.7 Ensure /var/tmp is mounted with nodev",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_tmp_nosuid",
        "title": "1.1.8 Ensure /var/tmp is mounted with nosuid",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_tmp_noexec",
        "title": "1.1.9 Ensure /var/tmp is mounted with noexec",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_var_log",
        "title": "1.1.10 Ensure /var/log is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_var_log_audit",
        "title": "1.1.11 Ensure /var/log/audit is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_home",
        "title": "1.1.12 Ensure /home is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_home_nodev",
        "title": "1.1.13 Ensure /home is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_home_nosuid",
        "title": "1.1.14 Ensure /home is mounted with nosuid",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_dev_shm_nodev",
        "title": "1.1.15 Ensure /dev/shm is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_dev_shm_nosuid",
        "title": "1.1.16 Ensure /dev/shm is mounted with nosuid",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_dev_shm_noexec",
        "title": "1.1.17 Ensure /dev/shm is mounted with noexec",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_cramfs_disabled",
        "title": "1.1.18 Ensure cramfs kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_freevxfs_disabled",
        "title": "1.1.19 Ensure freevxfs kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_jffs2_disabled",
        "title": "1.1.20 Ensure jffs2 kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_hfs_disabled",
        "title": "1.1.21 Ensure hfs kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_hfsplus_disabled",
        "title": "1.1.22 Ensure hfsplus kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_udf_disabled",
        "title": "1.1.23 Ensure udf kernel module is disabled",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_usb_storage_disabled",
        "title": "1.1.24 Ensure USB storage is disabled",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 1: Initial Setup — Software Updates ---
    {
        "id": "xccdf_org.ssgproject.content_rule_ensure_gpgcheck_globally_activated",
        "title": "1.2.1 Ensure GPG keys are configured",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ensure_gpgcheck_never_disabled",
        "title": "1.2.2 Ensure package manager repositories are configured",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 1: Initial Setup — AppArmor ---
    {
        "id": "xccdf_org.ssgproject.content_rule_package_apparmor_installed",
        "title": "1.3.1 Ensure AppArmor is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_enable_apparmor",
        "title": "1.3.2 Ensure AppArmor is enabled in GRUB2",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_apparmor_profiles_in_enforce_mode",
        "title": "1.3.3 Ensure all AppArmor profiles are in enforce or complain mode",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 1: Initial Setup — Boot Settings ---
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_password",
        "title": "1.4.1 Ensure bootloader password is set",
        "severity": "high",
        "enabled": False,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_owner_grub2_cfg",
        "title": "1.4.2 Ensure bootloader config is owned by root",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_grub2_cfg",
        "title": "1.4.3 Ensure bootloader config permissions are 400 or 600",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 1: Initial Setup — Process Hardening ---
    {
        "id": "xccdf_org.ssgproject.content_rule_coredump_disable_storage",
        "title": "1.5.1 Ensure core dump storage is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_coredump_disable_backtraces",
        "title": "1.5.2 Ensure core dump backtraces are disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_randomize_va_space",
        "title": "1.5.3 Ensure ASLR is enabled (kernel.randomize_va_space=2)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_dmesg_restrict",
        "title": "1.5.4 Ensure dmesg access is restricted",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_perf_event_paranoid",
        "title": "1.5.5 Ensure ptrace scope is restricted",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 2: Services ---
    {
        "id": "xccdf_org.ssgproject.content_rule_service_xinetd_disabled",
        "title": "2.1.1 Ensure xinetd is not installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_openbsd_inetd_removed",
        "title": "2.1.2 Ensure openbsd-inetd is not installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_timesyncd_enabled",
        "title": "2.2.1 Ensure time synchronization is in use",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_xorg_x11_disabled",
        "title": "2.2.2 Ensure X Window System is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_avahi_daemon_disabled",
        "title": "2.2.3 Ensure Avahi Server is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_cups_removed",
        "title": "2.2.4 Ensure CUPS is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_dhcp_removed",
        "title": "2.2.5 Ensure DHCP Server is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_openldap_clients_removed",
        "title": "2.2.6 Ensure LDAP client is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_nfs_utils_removed",
        "title": "2.2.7 Ensure NFS is not installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_nis_removed",
        "title": "2.2.8 Ensure NIS is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_telnet_removed",
        "title": "2.2.9 Ensure telnet is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_rsh_removed",
        "title": "2.2.10 Ensure rsh client is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_talk_removed",
        "title": "2.2.11 Ensure talk is not installed",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 3: Network ---
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_ip_forward",
        "title": "3.1.1 Ensure IP forwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_send_redirects",
        "title": "3.1.2 Ensure packet redirect sending is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_accept_source_route",
        "title": "3.2.1 Ensure source routed packets are not accepted (IPv4)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv6_conf_all_accept_source_route",
        "title": "3.2.2 Ensure source routed packets are not accepted (IPv6)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_accept_redirects",
        "title": "3.2.3 Ensure ICMP redirects are not accepted (IPv4)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_secure_redirects",
        "title": "3.2.4 Ensure secure ICMP redirects are not accepted",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_log_martians",
        "title": "3.2.5 Ensure suspicious packets are logged",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_icmp_echo_ignore_broadcasts",
        "title": "3.2.6 Ensure broadcast ICMP requests are ignored",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_icmp_ignore_bogus_error_responses",
        "title": "3.2.7 Ensure bogus ICMP responses are ignored",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_rp_filter",
        "title": "3.2.8 Ensure Reverse Path Filtering is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_tcp_syncookies",
        "title": "3.2.9 Ensure TCP SYN Cookies is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv6_conf_all_accept_ra",
        "title": "3.2.10 Ensure IPv6 router advertisements are not accepted",
        "severity": "medium",
        "enabled": True,
    },
    # Firewall
    {
        "id": "xccdf_org.ssgproject.content_rule_package_ufw_installed",
        "title": "3.4.1 Ensure ufw is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_ufw_enabled",
        "title": "3.4.2 Ensure ufw is enabled and active",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ufw_default_deny_forward",
        "title": "3.4.3 Ensure ufw default deny forward policy",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ufw_default_deny_input",
        "title": "3.4.4 Ensure ufw default deny inbound policy",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ufw_default_deny_output",
        "title": "3.4.5 Ensure ufw default deny outbound policy",
        "severity": "low",
        "enabled": False,
    },
    # --- Section 4: Logging & Auditing ---
    {
        "id": "xccdf_org.ssgproject.content_rule_package_audit_installed",
        "title": "4.1.1 Ensure auditd is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_auditd_enabled",
        "title": "4.1.2 Ensure auditd service is enabled and active",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_audit_argument",
        "title": "4.1.3 Ensure auditing for processes before auditd starts",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_login_events",
        "title": "4.1.4 Ensure login and logout events are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_session_events",
        "title": "4.1.5 Ensure session initiation information is collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_mac_modification",
        "title": "4.1.6 Ensure events that modify the system's MAC are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_usergroup_modification",
        "title": "4.1.7 Ensure events modifying user/group information are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_networkconfig_modification",
        "title": "4.1.8 Ensure events modifying the network environment are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_sysadmin_actions",
        "title": "4.1.9 Ensure system administrator actions (sudolog) are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_kernel_module_loading",
        "title": "4.1.10 Ensure kernel module loading and unloading is collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_privileged_commands",
        "title": "4.1.11 Ensure use of privileged commands is collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_unsuccessful_file_modification",
        "title": "4.1.12 Ensure unsuccessful unauthorised file access attempts are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_file_deletion_events",
        "title": "4.1.13 Ensure file deletion events by users are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_time_adjtimex",
        "title": "4.1.14 Ensure events that modify date/time information are collected",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_auditd_data_retention_space_left_action",
        "title": "4.1.15 Ensure audit log storage size is configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_auditd_data_retention_action_mail_acct",
        "title": "4.1.16 Ensure audit logs are not automatically deleted",
        "severity": "medium",
        "enabled": True,
    },
    # Syslog
    {
        "id": "xccdf_org.ssgproject.content_rule_package_rsyslog_installed",
        "title": "4.2.1 Ensure rsyslog is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_rsyslog_enabled",
        "title": "4.2.2 Ensure rsyslog service is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_rsyslog_files_permissions",
        "title": "4.2.3 Ensure rsyslog log files have correct permissions",
        "severity": "medium",
        "enabled": True,
    },
    # --- Section 5: Access, Authentication & Authorization ---
    {
        "id": "xccdf_org.ssgproject.content_rule_restrict_at_cron_authorized_users",
        "title": "5.1.1 Ensure cron is restricted to authorised users",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_crontab",
        "title": "5.1.2 Ensure permissions on /etc/crontab are configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_cron_hourly",
        "title": "5.1.3 Ensure permissions on /etc/cron.hourly are configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_cron_daily",
        "title": "5.1.4 Ensure permissions on /etc/cron.daily are configured",
        "severity": "medium",
        "enabled": True,
    },
    # SSH
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_root_login",
        "title": "5.2.1 Ensure SSH root login is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_set_max_auth_tries",
        "title": "5.2.2 Ensure SSH MaxAuthTries is set to 4 or less",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_use_approved_macs",
        "title": "5.2.3 Ensure only approved MAC algorithms are used",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_use_approved_ciphers",
        "title": "5.2.4 Ensure only approved ciphers are used",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_empty_passwords",
        "title": "5.2.5 Ensure SSH PermitEmptyPasswords is disabled",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_user_known_hosts",
        "title": "5.2.6 Ensure SSH IgnoreUserKnownHosts is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_rhosts",
        "title": "5.2.7 Ensure SSH IgnoreRhosts is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_set_idle_timeout",
        "title": "5.2.8 Ensure SSH Idle Timeout is configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_set_login_grace_time",
        "title": "5.2.9 Ensure SSH LoginGraceTime is set to 60 seconds or less",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_enable_warning_banner",
        "title": "5.2.10 Ensure SSH warning banner is configured",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_sshd_config",
        "title": "5.2.11 Ensure sshd_config permissions are 600",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_owner_sshd_config",
        "title": "5.2.12 Ensure sshd_config is owned by root",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_allow_only_protocol2",
        "title": "5.2.13 Ensure only SSHv2 protocol is used",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_use_priv_separation",
        "title": "5.2.14 Ensure SSH privilege separation is enabled",
        "severity": "medium",
        "enabled": True,
    },
    # PAM & Passwords
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_minlen_login_defs",
        "title": "5.3.1 Ensure minimum password length is 14+",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_minlen",
        "title": "5.3.2 Ensure PAM minimum password length is 14+",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_dcredit",
        "title": "5.3.3 Ensure password complexity requires digits",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_ucredit",
        "title": "5.3.4 Ensure password complexity requires uppercase",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_ocredit",
        "title": "5.3.5 Ensure password complexity requires special characters",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_lcredit",
        "title": "5.3.6 Ensure password complexity requires lowercase",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_retry",
        "title": "5.3.7 Ensure password retry limit is 3 or less",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_unix_remember",
        "title": "5.3.8 Ensure password reuse is limited to last 5",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_empty_passwords",
        "title": "5.3.9 Ensure no accounts with empty passwords",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_maxrepeat",
        "title": "5.3.10 Ensure no more than 3 consecutive identical characters",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_maximum_age_login_defs",
        "title": "5.4.1 Ensure password expiration is 365 days or fewer",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_minimum_age_login_defs",
        "title": "5.4.2 Ensure minimum days between password changes is 1+",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_warn_age_login_defs",
        "title": "5.4.3 Ensure password expiry warning is 7+ days",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_max_concurrent_login_sessions",
        "title": "5.4.4 Ensure max concurrent sessions are limited",
        "severity": "low",
        "enabled": True,
    },
    # User accounts
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_umask_etc_login_defs",
        "title": "5.5.1 Ensure default umask is 027 or more restrictive",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_shelllogin_for_systemaccounts",
        "title": "5.5.2 Ensure system accounts are secured (no shell)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_no_uid_except_zero",
        "title": "5.5.3 Ensure only root has UID 0",
        "severity": "critical",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_root_path_dirs_no_write",
        "title": "5.5.4 Ensure root PATH integrity",
        "severity": "high",
        "enabled": True,
    },
    # sudo
    {
        "id": "xccdf_org.ssgproject.content_rule_sudo_remove_no_authenticate",
        "title": "5.6.1 Ensure sudo requires authentication",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sudo_require_reauthentication",
        "title": "5.6.2 Ensure sudo re-authentication timeout",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sudoers_validate_passwd",
        "title": "5.6.3 Ensure sudo log file is configured",
        "severity": "low",
        "enabled": True,
    },
    # --- Section 6: System Maintenance ---
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_passwd",
        "title": "6.1.1 Ensure permissions on /etc/passwd are 644",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_owner_etc_passwd",
        "title": "6.1.2 Ensure /etc/passwd is owned by root",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_shadow",
        "title": "6.1.3 Ensure permissions on /etc/shadow are 640 or stricter",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_owner_etc_shadow",
        "title": "6.1.4 Ensure /etc/shadow is owned by root",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_group",
        "title": "6.1.5 Ensure permissions on /etc/group are 644",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_owner_etc_group",
        "title": "6.1.6 Ensure /etc/group is owned by root",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_gshadow",
        "title": "6.1.7 Ensure permissions on /etc/gshadow are 640 or stricter",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_world_writeable_files",
        "title": "6.1.8 Ensure no world-writable files exist",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_files_unowned_by_user",
        "title": "6.1.9 Ensure no unowned files or directories exist",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_ungroupowned",
        "title": "6.1.10 Ensure no files without group ownership exist",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_all_shadowed",
        "title": "6.2.1 Ensure password fields are not empty",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_legacy_plus_entries_in_passwd",
        "title": "6.2.2 Ensure no legacy '+' entries in /etc/passwd",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_legacy_plus_entries_in_shadow",
        "title": "6.2.3 Ensure no legacy '+' entries in /etc/shadow",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_legacy_plus_entries_in_group",
        "title": "6.2.4 Ensure no legacy '+' entries in /etc/group",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_no_uid_except_zero",
        "title": "6.2.5 Ensure no duplicate UIDs exist",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_account_unique_name",
        "title": "6.2.6 Ensure no duplicate user names exist",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_group_unique_name",
        "title": "6.2.7 Ensure no duplicate group names exist",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_root_gid_zero",
        "title": "6.2.8 Ensure root GID is 0",
        "severity": "medium",
        "enabled": True,
    },
]

_UBUNTU22_CIS_L2 = _UBUNTU22_CIS_L1 + [
    {
        "id": "xccdf_org.ssgproject.content_rule_apparmor_enforce_all",
        "title": "1.3.3 Ensure all AppArmor profiles are in enforce mode (not complain)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_password",
        "title": "1.4.1 Ensure bootloader password is set (L2)",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_ntp_enabled",
        "title": "2.2.1 Ensure chrony/ntp is configured with authorised time servers",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_dac_modification_chmod",
        "title": "4.1.L2 Ensure DAC permission modification events are collected (chmod)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_dac_modification_chown",
        "title": "4.1.L2 Ensure DAC permission modification events are collected (chown)",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_media_export",
        "title": "4.1.L2 Ensure successful mounts are collected",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_nodev",
        "title": "1.1.L2 Ensure /var is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_log_nodev",
        "title": "1.1.L2 Ensure /var/log is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_log_nosuid",
        "title": "1.1.L2 Ensure /var/log is mounted with nosuid",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_log_noexec",
        "title": "1.1.L2 Ensure /var/log is mounted with noexec",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ufw_default_deny_output",
        "title": "3.4.L2 Ensure ufw default deny outbound policy is set",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_x11_forwarding",
        "title": "5.2.L2 Ensure SSH X11 forwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_tcp_forwarding",
        "title": "5.2.L2 Ensure SSH AllowTcpForwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
]

# RHEL9 / Rocky 9 / Amazon Linux 2023 Level 1
_RHEL9_CIS_L1 = [
    # Section 1: Initial Setup
    {
        "id": "xccdf_org.ssgproject.content_rule_partition_for_tmp",
        "title": "1.1.1 Ensure /tmp is a separate partition",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_nodev",
        "title": "1.1.2 Ensure /tmp mounted with nodev",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_nosuid",
        "title": "1.1.3 Ensure /tmp mounted with nosuid",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_tmp_noexec",
        "title": "1.1.4 Ensure /tmp mounted with noexec",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_kernel_module_usb_storage_disabled",
        "title": "1.1.5 Ensure USB storage is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_ensure_gpgcheck_globally_activated",
        "title": "1.2.1 Ensure GPG keys are configured",
        "severity": "high",
        "enabled": True,
    },
    # SELinux
    {
        "id": "xccdf_org.ssgproject.content_rule_selinux_state",
        "title": "1.3.1 Ensure SELinux is in enforcing mode",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_selinux_policytype",
        "title": "1.3.2 Ensure SELinux policy is targeted",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_setroubleshoot_removed",
        "title": "1.3.3 Ensure SETroubleshoot is not installed",
        "severity": "low",
        "enabled": True,
    },
    # Boot / Process hardening
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_password",
        "title": "1.4.1 Ensure bootloader password is set",
        "severity": "high",
        "enabled": False,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_coredump_disable_storage",
        "title": "1.5.1 Ensure core dump storage is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_randomize_va_space",
        "title": "1.5.2 Ensure ASLR is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_dmesg_restrict",
        "title": "1.5.3 Ensure dmesg access is restricted",
        "severity": "low",
        "enabled": True,
    },
    # Section 2: Services
    {
        "id": "xccdf_org.ssgproject.content_rule_service_xinetd_disabled",
        "title": "2.1.1 Ensure xinetd is not installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_timesyncd_enabled",
        "title": "2.2.1 Ensure time synchronisation is in use",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_xorg_x11_disabled",
        "title": "2.2.2 Ensure X Window System is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_avahi_daemon_disabled",
        "title": "2.2.3 Ensure Avahi Server is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_cups_removed",
        "title": "2.2.4 Ensure CUPS is not installed",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_dhcp_removed",
        "title": "2.2.5 Ensure DHCP Server is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_telnet_removed",
        "title": "2.2.6 Ensure telnet is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_rsh_removed",
        "title": "2.2.7 Ensure rsh is not installed",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_nis_removed",
        "title": "2.2.8 Ensure NIS is not installed",
        "severity": "high",
        "enabled": True,
    },
    # Section 3: Network
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_ip_forward",
        "title": "3.1.1 Ensure IP forwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_send_redirects",
        "title": "3.1.2 Ensure packet redirect sending is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_accept_source_route",
        "title": "3.2.1 Ensure source routed packets are not accepted",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_accept_redirects",
        "title": "3.2.2 Ensure ICMP redirects are not accepted",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_icmp_echo_ignore_broadcasts",
        "title": "3.2.3 Ensure broadcast ICMP requests are ignored",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_conf_all_rp_filter",
        "title": "3.2.4 Ensure Reverse Path Filtering is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_tcp_syncookies",
        "title": "3.2.5 Ensure TCP SYN Cookies is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_firewalld_installed",
        "title": "3.4.1 Ensure firewalld is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_firewalld_enabled",
        "title": "3.4.2 Ensure firewalld is enabled",
        "severity": "medium",
        "enabled": True,
    },
    # Section 4: Logging & Audit
    {
        "id": "xccdf_org.ssgproject.content_rule_package_audit_installed",
        "title": "4.1.1 Ensure auditd is installed",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_service_auditd_enabled",
        "title": "4.1.2 Ensure auditd service is enabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_audit_argument",
        "title": "4.1.3 Ensure auditing for processes before auditd starts",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_login_events",
        "title": "4.1.4 Ensure login events are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_usergroup_modification",
        "title": "4.1.5 Ensure user/group modification events are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_networkconfig_modification",
        "title": "4.1.6 Ensure network env modification events are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_privileged_commands",
        "title": "4.1.7 Ensure privileged command use is collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_unsuccessful_file_modification",
        "title": "4.1.8 Ensure unsuccessful file access attempts are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_file_deletion_events",
        "title": "4.1.9 Ensure file deletion events are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_sysadmin_actions",
        "title": "4.1.10 Ensure sysadmin actions (sudolog) are collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_kernel_module_loading",
        "title": "4.1.11 Ensure kernel module loading/unloading is collected",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_package_rsyslog_installed",
        "title": "4.2.1 Ensure rsyslog is installed and enabled",
        "severity": "medium",
        "enabled": True,
    },
    # Section 5: Access & Auth
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_root_login",
        "title": "5.2.1 Ensure SSH root login is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_set_max_auth_tries",
        "title": "5.2.2 Ensure SSH MaxAuthTries ≤ 4",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_use_approved_ciphers",
        "title": "5.2.3 Ensure only approved ciphers are used",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_use_approved_macs",
        "title": "5.2.4 Ensure only approved MACs are used",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_empty_passwords",
        "title": "5.2.5 Ensure SSH PermitEmptyPasswords is disabled",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_set_idle_timeout",
        "title": "5.2.6 Ensure SSH Idle Timeout is set",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_enable_warning_banner",
        "title": "5.2.7 Ensure SSH warning banner is configured",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_minlen_login_defs",
        "title": "5.3.1 Ensure minimum password length is 14+",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_pam_minlen",
        "title": "5.3.2 Ensure PAM enforces minimum password length",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_empty_passwords",
        "title": "5.3.3 Ensure no accounts with empty passwords",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_maximum_age_login_defs",
        "title": "5.4.1 Ensure password expiration is 365 days or less",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_minimum_age_login_defs",
        "title": "5.4.2 Ensure minimum days between password changes is 1+",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_umask_etc_login_defs",
        "title": "5.5.1 Ensure default umask is 027 or more restrictive",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_shelllogin_for_systemaccounts",
        "title": "5.5.2 Ensure system accounts do not have a shell",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_no_uid_except_zero",
        "title": "5.5.3 Ensure only root has UID 0",
        "severity": "critical",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sudo_remove_no_authenticate",
        "title": "5.6.1 Ensure sudo requires authentication",
        "severity": "high",
        "enabled": True,
    },
    # Section 6: Maintenance
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_passwd",
        "title": "6.1.1 Ensure /etc/passwd permissions are 644",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_file_permissions_shadow",
        "title": "6.1.2 Ensure /etc/shadow permissions are 000",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_world_writeable_files",
        "title": "6.1.3 Ensure no world-writable files exist",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_no_files_unowned_by_user",
        "title": "6.1.4 Ensure no unowned files exist",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_password_all_shadowed",
        "title": "6.2.1 Ensure all accounts have shadowed passwords",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_accounts_no_uid_except_zero",
        "title": "6.2.2 Ensure no duplicate UIDs exist",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_account_unique_name",
        "title": "6.2.3 Ensure no duplicate user names exist",
        "severity": "high",
        "enabled": True,
    },
]

_RHEL9_CIS_L2 = _RHEL9_CIS_L1 + [
    {
        "id": "xccdf_org.ssgproject.content_rule_sudo_require_reauthentication",
        "title": "5.6.L2 Ensure sudo re-authentication timeout is configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_networkconfig_modification",
        "title": "4.1.L2 Ensure network config audit rules are comprehensive",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_nodev",
        "title": "1.1.L2 Ensure /var is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_mount_option_var_log_nodev",
        "title": "1.1.L2 Ensure /var/log is mounted with nodev",
        "severity": "low",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_x11_forwarding",
        "title": "5.2.L2 Ensure SSH X11 forwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sshd_disable_tcp_forwarding",
        "title": "5.2.L2 Ensure SSH TCP forwarding is disabled",
        "severity": "medium",
        "enabled": True,
    },
]

_RHEL9_STIG = _RHEL9_CIS_L2 + [
    {
        "id": "xccdf_org.ssgproject.content_rule_configure_crypto_policy",
        "title": "STIG Ensure system crypto policy is FIPS:OSPP",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_privileged_commands_su",
        "title": "STIG Ensure privileged command 'su' use is audited",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_audit_rules_privileged_commands_sudo",
        "title": "STIG Ensure privileged command 'sudo' use is audited",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_smartcard_auth",
        "title": "STIG Ensure smart card login is enabled",
        "severity": "medium",
        "enabled": False,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_configure_usbguard",
        "title": "STIG Ensure USBGuard is installed and configured",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_grub2_pti_argument",
        "title": "STIG Ensure Kernel Page-Table Isolation (KPTI) is enabled",
        "severity": "high",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_kptr_restrict",
        "title": "STIG Ensure kernel pointer exposure is restricted",
        "severity": "medium",
        "enabled": True,
    },
    {
        "id": "xccdf_org.ssgproject.content_rule_sysctl_kernel_yama_ptrace_scope",
        "title": "STIG Ensure ptrace is restricted to direct process descendants",
        "severity": "medium",
        "enabled": True,
    },
]

CIS_CONTROLS: dict[str, dict[str, list[dict]]] = {
    "ubuntu22.04": {
        "cis-l1": _UBUNTU22_CIS_L1,
        "cis-l2": _UBUNTU22_CIS_L2,
    },
    "ubuntu24.04": {
        "cis-l1": _UBUNTU22_CIS_L1,
        "cis-l2": _UBUNTU22_CIS_L2,
    },
    "rocky9": {
        "cis-l1": _RHEL9_CIS_L1,
        "cis-l2": _RHEL9_CIS_L2,
        "stig": _RHEL9_STIG,
    },
    "rhel9": {
        "cis-l1": _RHEL9_CIS_L1,
        "cis-l2": _RHEL9_CIS_L2,
        "stig": _RHEL9_STIG,
    },
    "alma9": {
        "cis-l1": _RHEL9_CIS_L1,
        "cis-l2": _RHEL9_CIS_L2,
    },
    "amazon-linux-2023": {
        "cis-l1": _RHEL9_CIS_L1,
        "cis-l2": _RHEL9_CIS_L2,
    },
    "debian12": {
        "cis-l1": _UBUNTU22_CIS_L1,
        "cis-l2": _UBUNTU22_CIS_L2,
    },
}
