#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Trigger Statim official blueprint builds via the REST API.

Iterates all profiles in the profiles/ directory that are tagged "official"
(or all profiles when --all is passed), posts a build job for each, and
reports a summary.

Usage:
    uv run python scripts/trigger_official_builds.py
    uv run python scripts/trigger_official_builds.py --all
    uv run python scripts/trigger_official_builds.py --profile rocky9-cis-l1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx not installed — run: uv sync", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("pyyaml not installed — run: uv sync", file=sys.stderr)
    sys.exit(1)

STATIM_API_URL = os.environ.get("STATIM_API_URL", "http://localhost:8000")
PROFILES_DIR = Path(__file__).parent.parent / "profiles"
OFFICIAL_TAG = "official"
BUILD_TIMEOUT_SECONDS = 7200  # 2 hours per build
POLL_INTERVAL = 30


def load_profile_names(profiles_dir: Path, only_official: bool = True, specific: str | None = None) -> list[str]:
    names = []
    for p in sorted(profiles_dir.rglob("*.yaml")):
        if p.name == "generic-hardening-blueprint.yaml":
            continue
        try:
            raw = yaml.safe_load(p.read_text())
            if not isinstance(raw, dict):
                continue
            meta = raw.get("metadata", {})
            name = meta.get("name", "")
            if not name:
                continue
            if specific and name != specific:
                continue
            if only_official and not specific:
                tags = [t.lower() for t in meta.get("tags", [])]
                if OFFICIAL_TAG not in tags:
                    continue
            names.append(name)
        except Exception as exc:
            print(f"  WARN  could not parse {p}: {exc}")
    return names


def trigger_build(client: httpx.Client, profile_name: str) -> str | None:
    """POST /api/builder/start and return the job_id."""
    # We trigger a build using the profile; provider is inferred from profile target.
    # For the weekly refresh, we always use aws as the default provider.
    provider = os.environ.get("STATIM_BUILD_PROVIDER", "aws")
    region = os.environ.get("STATIM_BUILD_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    try:
        resp = client.post(
            f"{STATIM_API_URL}/api/builder/start",
            json={"profile_name": profile_name, "provider": provider, "region": region},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("job_id")
    except Exception as exc:
        print(f"  ERROR trigger failed for '{profile_name}': {exc}")
        return None


def poll_job(client: httpx.Client, job_id: str, profile_name: str) -> str:
    """Poll a build job until it completes. Returns final status string."""
    deadline = time.time() + BUILD_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            resp = client.get(f"{STATIM_API_URL}/api/builder/jobs/{job_id}", timeout=15)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "unknown")
            if status in ("complete", "failed"):
                return status
            print(f"  ...  [{profile_name}] status={status}")
        except Exception as exc:
            print(f"  WARN [{profile_name}] poll error: {exc}")
        time.sleep(POLL_INTERVAL)
    return "timeout"


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Statim official blueprint builds")
    parser.add_argument("--all", action="store_true", help="Build ALL profiles, not just official ones")
    parser.add_argument("--profile", help="Build a single named profile")
    parser.add_argument("--no-wait", action="store_true", help="Fire-and-forget; don't poll for completion")
    args = parser.parse_args()

    only_official = not args.all
    profiles = load_profile_names(PROFILES_DIR, only_official=only_official, specific=args.profile)

    if not profiles:
        qualifier = "official" if only_official else "all"
        print(f"No {qualifier} profiles found in {PROFILES_DIR}.")
        return 0

    print(f"Triggering builds for {len(profiles)} profile(s): {profiles}")
    print(f"Target API: {STATIM_API_URL}")

    results: dict[str, str] = {}
    with httpx.Client() as client:
        for name in profiles:
            print(f"\n  → Triggering: {name}")
            job_id = trigger_build(client, name)
            if job_id is None:
                results[name] = "trigger_failed"
                continue
            print(f"     Job ID: {job_id}")
            if args.no_wait:
                results[name] = "triggered"
            else:
                status = poll_job(client, job_id, name)
                results[name] = status
                icon = "✓" if status == "complete" else "✗"
                print(f"     {icon} {name}: {status}")

    # Summary
    print("\n=== Build Summary ===")
    passed = [n for n, s in results.items() if s in ("complete", "triggered")]
    failed = [n for n, s in results.items() if s not in ("complete", "triggered")]
    for name, status in results.items():
        icon = "✓" if status in ("complete", "triggered") else "✗"
        print(f"  {icon} {name}: {status}")

    print(f"\n  Passed: {len(passed)}  Failed: {len(failed)}")

    if failed:
        print("\nFailed builds:")
        for name in failed:
            print(f"  - {name}: {results[name]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
