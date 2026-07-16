# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Subprocess-isolated provider adapter: runs provider scripts over JSON-RPC stdio."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from bakex.core.blueprint import ComplianceProfile
from bakex.plugins.base_provider import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

SUBPROCESS_SENTINEL = "PROVIDER_NAME"


def _build_params(profile: ComplianceProfile, credentials: dict | None = None) -> dict:
    """Extract build parameters from a ComplianceProfile / HardeningBlueprint."""
    params: dict = {
        "base_image": profile.target.base_image,
        "os": profile.target.os,
        "arch": profile.target.arch,
        "instance_type": profile.target.instance_type,
        "root_volume_size_gb": profile.target.root_volume_size_gb,
        "benchmark": profile.compliance.benchmark,
        "profile": profile.compliance.profile,
        "datastream": profile.compliance.datastream,
        "profile_name": profile.metadata.name,
        "profile_version": profile.metadata.version,
    }

    # Pass expanded blueprint sections so subprocess providers can apply them
    if profile.system is not None:
        params["system"] = profile.system.model_dump()
    if profile.filesystem:
        params["filesystem"] = [m.model_dump() for m in profile.filesystem]
    if profile.users is not None:
        params["users"] = profile.users.model_dump()
    params["hardening"] = profile.hardening.model_dump()

    # Generate pre-hardening playbook YAML string for subprocess providers
    try:
        from bakex.core.playbook_gen import generate_prehard_playbook

        playbook_path = generate_prehard_playbook(profile)
        if playbook_path is not None:
            params["prehard_playbook_yaml"] = playbook_path.read_text()
    except Exception as exc:
        logger.warning("Could not generate pre-hardening playbook: %s", exc)

    if credentials:
        params["credentials"] = credentials
    return params


def _call_rpc(
    script_path: Path,
    method: str,
    params: dict,
    rpc_id: int = 1,
    timeout_seconds: int = 600,
) -> dict:
    """Invoke a JSON-RPC method on a subprocess provider script.

    Returns:
        The ``result`` dict from a successful JSON-RPC response.

    Raises:
        RuntimeError: on non-zero exit, empty stdout, invalid JSON, or error response.
        subprocess.TimeoutExpired: if the script exceeds *timeout_seconds*.
    """
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": rpc_id,
        }
    )

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=request,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if proc.stderr:
        for line in proc.stderr.splitlines():
            # Provider scripts log to stderr; surface as INFO so build logs are visible
            logger.info("[%s] %s", script_path.name, line)

    if proc.returncode != 0:
        raise RuntimeError(
            f"Provider script {script_path.name} exited with code {proc.returncode}: {proc.stderr.strip()}"
        )

    if not proc.stdout.strip():
        raise RuntimeError(f"Provider script {script_path.name} produced no output")

    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Provider script {script_path.name} returned invalid JSON: {exc}") from exc

    if "error" in response:
        err = response["error"]
        raise RuntimeError(
            f"JSON-RPC error from {script_path.name}: [{err.get('code', '?')}] {err.get('message', str(err))}"
        )

    return response["result"]


class SubprocessProvider(BaseProvider):
    """Adapter that delegates all build work to an external JSON-RPC script.

    Concrete subclasses are created at load time via ``make_subprocess_provider_class``.
    """

    handles_full_lifecycle: ClassVar[bool] = True
    _script_path: ClassVar[Path]

    def provision(self, profile: ComplianceProfile, **kwargs) -> str:
        return "__subprocess_deferred__"

    def run_ansible(self, instance_id: str, profile: ComplianceProfile) -> None:
        return None

    def teardown(self, instance_id: str) -> None:
        return None

    def snapshot(self, instance_id: str, profile: ComplianceProfile) -> ProviderResult:
        from bakex.api.integrations import get_credentials

        credentials = get_credentials(self.name)
        params = _build_params(profile, credentials=credentials)
        result = _call_rpc(self._script_path, "execute_build", params)
        if "artifact_id" not in result:
            raise RuntimeError(f"execute_build response from {self._script_path.name} missing 'artifact_id'")
        return ProviderResult(
            artifact_id=result["artifact_id"],
            artifact_type=result.get("artifact_type", self.name),
            region=result.get("region", ""),
            metadata=result.get("metadata", {}),
        )

    def audit(self, target_id: str, profile: ComplianceProfile) -> dict:
        """Invoke execute_audit on the subprocess script. Returns raw_xml."""
        from bakex.api.integrations import get_credentials

        credentials = get_credentials(self.name)
        params = {**_build_params(profile, credentials=credentials), "target_id": target_id}
        return _call_rpc(self._script_path, "execute_audit", params, timeout_seconds=700)

    def scan_image(self, params: dict) -> dict:
        """Invoke execute_scan_image on the subprocess script. Returns raw_xml."""
        from bakex.api.integrations import get_credentials

        credentials = get_credentials(self.name)
        if credentials:
            params = {**params, "credentials": credentials}
        return _call_rpc(self._script_path, "execute_scan_image", params, timeout_seconds=900)


def make_subprocess_provider_class(
    script_path: Path,
    provider_name: str,
) -> type[SubprocessProvider]:
    """Create a named concrete SubprocessProvider subclass bound to *script_path*."""
    return type(
        f"{provider_name.capitalize()}SubprocessProvider",
        (SubprocessProvider,),
        {
            "name": provider_name,
            "_script_path": script_path,
        },
    )
