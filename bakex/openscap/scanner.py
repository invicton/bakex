# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Run `oscap xccdf eval` and return the path to the ARF XML result file."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from bakex.core.blueprint import ComplianceProfile
from bakex.openscap.tailoring import TAILORED_PROFILE_ID, write_tailoring

logger = logging.getLogger(__name__)

# oscap exit codes
_EXIT_PASS = 0
_EXIT_FAIL_WITH_FINDINGS = 2


class ScanError(RuntimeError):
    """Raised when oscap fails for a reason other than policy findings."""


def run_scan(
    profile: ComplianceProfile,
    target_host: str | None = None,
    ssh_user: str = "root",
    output_dir: Path | None = None,
) -> Path:
    """Execute ``oscap xccdf eval`` and return the ARF result file path.

    Args:
        profile: The ComplianceProfile describing the benchmark + datastream.
        target_host: Remote host (IP or FQDN) for remote scans via SSH.
                     Pass ``None`` to scan localhost.
        ssh_user: SSH user for remote scans (ignored for localhost).
        output_dir: Where to write result files. Uses a temp dir if None.

    Returns:
        Path to the generated ARF XML file.

    Raises:
        ScanError: If oscap exits with an unexpected code (not 0 or 2).
    """
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="bakex-scan-"))
    output_dir.mkdir(parents=True, exist_ok=True)

    arf_path = output_dir / "results-arf.xml"
    report_path = output_dir / "report.html"

    # Compile the blueprint's `controls` block into a tailoring file so rule overrides
    # actually affect the scan. None when the blueprint declares no overrides, which
    # keeps the common path identical to an untailored run.
    tailoring_path = write_tailoring(profile, output_dir)

    cmd = _build_command(profile, target_host, ssh_user, arf_path, report_path, tailoring_path)
    logger.info("Running oscap: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    logger.debug("oscap stdout: %s", result.stdout)

    if result.returncode not in (_EXIT_PASS, _EXIT_FAIL_WITH_FINDINGS):
        raise ScanError(f"oscap exited with code {result.returncode}.\nstderr: {result.stderr}")

    if result.returncode == _EXIT_FAIL_WITH_FINDINGS:
        logger.warning("oscap found policy violations on %s", target_host or "localhost")

    return arf_path


def _build_command(
    profile: ComplianceProfile,
    target_host: str | None,
    ssh_user: str,
    arf_path: Path,
    report_path: Path,
    tailoring_path: Path | None = None,
) -> list[str]:
    cmd = ["oscap"]

    if target_host:
        cmd += ["--ssh-option=StrictHostKeyChecking=no"]
        cmd += [f"ssh://{ssh_user}@{target_host}"]

    # With a tailoring file, --profile must name the *tailored* profile. Passing the
    # original ID here is the classic mistake: oscap accepts it and silently evaluates
    # the untailored profile, so every override is ignored with no error.
    selected_profile = TAILORED_PROFILE_ID if tailoring_path else profile.compliance.profile

    cmd += [
        "xccdf",
        "eval",
        "--benchmark-id",
        profile.compliance.benchmark,
        "--profile",
        selected_profile,
    ]

    if tailoring_path:
        cmd += ["--tailoring-file", str(tailoring_path)]

    cmd += [
        "--results-arf",
        str(arf_path),
        "--report",
        str(report_path),
        profile.compliance.datastream,
    ]
    return cmd
