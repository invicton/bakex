#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Refresh the fallback AMI IDs in stratum/core/os_catalog.py.

Queries AWS describe_images for each OS entry that has an aws_image_query,
then rewrites the fallback ami-xxx comment in os_catalog.py in-place.

Usage:
    AWS_DEFAULT_REGION=us-east-1 python scripts/refresh_ami_catalog.py

Requires boto3 and valid AWS credentials.
The refresh is best-effort: any OS that fails a lookup keeps its existing
fallback and the script exits 0 so CI is not broken by transient API errors.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import boto3
except ImportError:
    print("boto3 not installed — run: pip install boto3", file=sys.stderr)
    sys.exit(1)

CATALOG_PATH = Path(__file__).parent.parent / "stratum" / "core" / "os_catalog.py"
REGION = "us-east-1"


def latest_ami(ec2_client, owner: str, name_pattern: str) -> str | None:
    resp = ec2_client.describe_images(
        Owners=[owner],
        Filters=[
            {"Name": "name", "Values": [name_pattern]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
            {"Name": "virtualization-type", "Values": ["hvm"]},
        ],
    )
    images = sorted(
        resp.get("Images", []),
        key=lambda img: img.get("CreationDate", ""),
        reverse=True,
    )
    if not images:
        return None
    return images[0]["ImageId"], images[0].get("Name", "")


def main() -> None:
    # Load catalog dynamically
    import importlib.util

    spec = importlib.util.spec_from_file_location("os_catalog", CATALOG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    catalog = mod.OS_CATALOG

    ec2 = boto3.client("ec2", region_name=REGION)
    source = CATALOG_PATH.read_text()
    updated = source
    changed = 0

    for slug, data in catalog.items():
        query = data.get("aws_image_query")
        if not query:
            continue
        old_fallback = data.get("default_base_image", {}).get("aws", "")
        if not old_fallback or not old_fallback.startswith("ami-"):
            continue

        print(f"  {slug}: querying owner={query['owner']} pattern={query['name_pattern']!r} …", end=" ", flush=True)
        try:
            result = latest_ami(ec2, query["owner"], query["name_pattern"])
            if result is None:
                print("no results, keeping existing fallback")
                continue
            new_ami, name = result
        except Exception as exc:
            print(f"ERROR ({exc}), keeping existing fallback")
            continue

        if new_ami == old_fallback:
            print(f"unchanged ({new_ami})")
            continue

        # Replace the exact ami-xxx string in the source (quoted, in default_base_image block)
        # Pattern: "aws": "ami-XXXXXXXXXXXXXXXXX",  (with optional comment)
        old_pattern = re.escape(f'"aws": "{old_fallback}"')
        new_value = f'"aws": "{new_ami}"'
        new_src, n = re.subn(old_pattern, new_value, updated, count=1)
        if n:
            updated = new_src
            changed += 1
            print(f"{old_fallback} → {new_ami}  ({name})")
        else:
            print(f"pattern not found in source for {old_fallback}, skipping")

    if changed:
        CATALOG_PATH.write_text(updated)
        print(f"\nUpdated {changed} AMI(s) in {CATALOG_PATH}")
    else:
        print("\nAll AMIs are current — no changes.")


if __name__ == "__main__":
    main()
