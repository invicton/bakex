# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Scan a local container image against an OS SCAP datastream via oscap-podman.

This is a host-local scanner (no SSH, no VM): oscap-podman/oscap-docker mount
the image's filesystem and evaluate it against a datastream that lives on the
host, producing the same ARF that the SSH/cloud scan paths do — so the entire
parse → grade → report → badge → SARIF pipeline downstream is reused unchanged.

Scope: OS-level configuration compliance of the image *contents* — not the CIS
Docker Benchmark (daemon/runtime) and not CVE scanning.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from statim.openscap.scanner import ScanError

logger = logging.getLogger(__name__)

# oscap exit codes: 0 = all pass, 2 = completed with rule failures. Both mean the
# scan ran; anything else is a real error.
_EXIT_PASS = 0
_EXIT_FAIL_WITH_FINDINGS = 2

# Preferred engine first. oscap-podman uses podman; oscap-docker uses docker.
_ENGINES = ("oscap-podman", "oscap-docker")


def select_engine() -> str:
    """Return the first available oscap container engine, or raise ScanError."""
    for engine in _ENGINES:
        if shutil.which(engine):
            return engine
    raise ScanError(
        "No container scan engine found — install oscap-podman (openscap-utils, with podman) "
        "or oscap-docker (with docker). e.g. apt install openscap-utils podman"
    )


def run_container_scan(
    image_ref: str,
    benchmark_id: str,
    profile_id: str,
    datastream: str,
    output_dir: Path | None = None,
    engine: str | None = None,
) -> Path:
    """Scan *image_ref* against *datastream* and return the ARF result path.

    Args:
        image_ref: Local image name:tag or image ID (present on podman/docker).
        benchmark_id / profile_id: XCCDF benchmark and profile IDs.
        datastream: Path to the SCAP datastream on the host.
        output_dir: Where to write results (temp dir if None).
        engine: Force a specific engine; auto-selected if None.

    Raises:
        ScanError: If no engine is available or oscap exits unexpectedly.
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="statim-container-scan-"))
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = engine or select_engine()
    arf_path = output_dir / "results-arf.xml"
    report_path = output_dir / "report.html"

    cmd = _build_command(engine, image_ref, benchmark_id, profile_id, arf_path, report_path, datastream)
    logger.info("Scanning container image %s: %s", image_ref, " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.debug("%s stdout: %s", engine, result.stdout)

    if result.returncode not in (_EXIT_PASS, _EXIT_FAIL_WITH_FINDINGS):
        raise ScanError(
            f"{engine} exited with code {result.returncode} scanning '{image_ref}'.\nstderr: {result.stderr.strip()}"
        )
    if result.returncode == _EXIT_FAIL_WITH_FINDINGS:
        logger.warning("Scan of %s completed with policy findings", image_ref)

    return arf_path


def _build_command(
    engine: str,
    image_ref: str,
    benchmark_id: str,
    profile_id: str,
    arf_path: Path,
    report_path: Path,
    datastream: str,
) -> list[str]:
    # oscap-podman/oscap-docker take the image ref, then the same xccdf eval args
    # as plain oscap, then the datastream last.
    return [
        engine,
        image_ref,
        "xccdf",
        "eval",
        "--benchmark-id",
        benchmark_id,
        "--profile",
        profile_id,
        "--results-arf",
        str(arf_path),
        "--report",
        str(report_path),
        datastream,
    ]
