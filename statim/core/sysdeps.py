# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""System-dependency diagnostics.

Statim shells out to system tools for hardening, scanning, and local image
builds. Missing tools historically surfaced mid-build as subprocess noise;
this module is the single source of truth for what the host needs, so the
health endpoint, the dashboard banner, and build preflights can all report
the same actionable facts.

Note: provider plugin scripts (plugins/providers/*.py) run as isolated
subprocesses and deliberately do not import this module — they carry their
own minimal checks. Keep the binary lists in sync when adding tools.
"""

from __future__ import annotations

import shutil

# name → (needed_for, install_hint). Alternatives are expressed as a tuple of
# names where any one present satisfies the requirement.
_DEPS: list[dict] = [
    {
        "name": "ansible-playbook",
        "needed_for": "hardening (all providers)",
        "install_hint": "apt install ansible  |  dnf install ansible  |  pip install ansible-core",
    },
    {
        "name": "ansible-galaxy",
        "needed_for": "installing Ansible-Lockdown roles (all providers)",
        "install_hint": "ships with ansible-core — apt install ansible | dnf install ansible",
    },
    {
        "name": "ssh",
        "needed_for": "connecting to build/scan targets",
        "install_hint": "apt install openssh-client  |  dnf install openssh-clients",
    },
    {
        "name": "oscap",
        "needed_for": "local OpenSCAP scans (remote targets get it auto-installed)",
        "install_hint": "apt install openscap-scanner (Ubuntu 24.04+/Debian)  |  dnf install openscap-scanner",
    },
    {
        "name": "qemu-system-x86_64",
        "needed_for": "local kvm image builds",
        "install_hint": "apt install qemu-system-x86  |  dnf install qemu-kvm",
    },
    {
        "name": "qemu-img",
        "needed_for": "local kvm image builds",
        "install_hint": "apt install qemu-utils  |  dnf install qemu-img",
    },
    {
        "name": ("cloud-localds", "genisoimage"),
        "needed_for": "cloud-init seed ISO for local kvm builds",
        "install_hint": "apt install cloud-image-utils (or genisoimage)  |  dnf install genisoimage",
    },
]


def check_system_deps() -> list[dict]:
    """Return a per-dependency report: name, present, path, needed_for, install_hint.

    For alternative groups (e.g. cloud-localds/genisoimage) the entry is
    present if any alternative resolves; ``name`` reports the group joined
    with " | " and ``path`` the first hit.
    """
    report = []
    for dep in _DEPS:
        names = dep["name"] if isinstance(dep["name"], tuple) else (dep["name"],)
        path = next((p for n in names if (p := shutil.which(n))), None)
        report.append(
            {
                "name": " | ".join(names),
                "present": path is not None,
                "path": path,
                "needed_for": dep["needed_for"],
                "install_hint": dep["install_hint"],
            }
        )
    return report


def missing_system_deps() -> list[dict]:
    """Just the absent entries — what the dashboard banner shows."""
    return [d for d in check_system_deps() if not d["present"]]
