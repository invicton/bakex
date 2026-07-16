# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Blueprint registry — fetches ComplianceProfile YAMLs from multiple sources.

Supported source types:
  - github  : raw GitHub URL hosting an index.json + YAML files
  - s3      : S3 bucket prefix (requires boto3 optional dep)
  - local   : local filesystem directory (profiles_dir)

Each profile gets a ``metadata.source_badge`` of "Official", "Community",
"Private", or "Local" depending on which source it came from.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import yaml

from statim.core.blueprint import ComplianceProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source descriptor
# ---------------------------------------------------------------------------


@dataclass
class RegistrySource:
    """Describes a single blueprint source."""

    kind: Literal["github", "s3", "local"]
    url_or_bucket: str
    badge: Literal["Official", "Community", "Private", "Local"] = "Community"
    prefix: str = ""  # S3 key prefix or sub-path


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ProfileRegistry:
    """Aggregates ComplianceProfiles from one or more sources.

    Backward-compatible API:
        sync()  → list[str]  (profile names synced)
        list()  → list[ComplianceProfile]
        get()   → ComplianceProfile | None
        count() → int
    """

    def __init__(
        self,
        sources: list[RegistrySource] | None = None,
        local_cache_dir: Path | None = None,
        # Legacy single-URL constructor still accepted
        base_url: str | None = None,
    ) -> None:
        self._cache_dir = local_cache_dir
        self._profiles: dict[str, ComplianceProfile] = {}

        if sources is not None:
            self._sources = sources
        elif base_url:
            # Legacy path: wrap old base_url as a Community GitHub source
            self._sources = [RegistrySource("github", base_url.rstrip("/"), "Community")]
        else:
            self._sources = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync(self) -> list[str]:
        """Fetch profiles from all configured sources.

        Returns a list of successfully loaded profile names.
        """
        synced: list[str] = []
        for source in self._sources:
            try:
                if source.kind == "github":
                    names = await self._sync_github(source)
                elif source.kind == "s3":
                    names = await asyncio.to_thread(self._sync_s3, source)
                elif source.kind == "local":
                    names = self._sync_local(source)
                else:
                    logger.warning("Unknown registry source kind: %s", source.kind)
                    names = []
                synced.extend(names)
                logger.info("Registry: synced %d profiles from %s (%s)", len(names), source.kind, source.url_or_bucket)
            except Exception as exc:
                logger.warning("Registry: source %s/%s failed: %s", source.kind, source.url_or_bucket, exc)
        return synced

    def list(self) -> list[ComplianceProfile]:
        return list(self._profiles.values())

    def get(self, name: str) -> ComplianceProfile | None:
        return self._profiles.get(name)

    def count(self) -> int:
        return len(self._profiles)

    # ------------------------------------------------------------------
    # Source sync implementations
    # ------------------------------------------------------------------

    async def _sync_github(self, source: RegistrySource) -> list[str]:
        """Fetch index.json + YAMLs from a raw GitHub URL."""
        synced: list[str] = []
        base = source.url_or_bucket.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(f"{base}/index.json")
                resp.raise_for_status()
                index: list[str] = resp.json()
            except Exception as exc:
                logger.warning("Registry GitHub sync failed to fetch index from %s: %s", base, exc)
                return synced

            for filename in index:
                try:
                    yaml_resp = await client.get(f"{base}/{filename}")
                    yaml_resp.raise_for_status()
                    profile = self._load_yaml_text(yaml_resp.text, source.badge)
                    if profile:
                        self._profiles[profile.metadata.name] = profile
                        synced.append(profile.metadata.name)
                        if self._cache_dir is not None:
                            cache_path = self._cache_dir / filename
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(yaml_resp.text)
                except Exception as exc:
                    logger.warning("Registry: failed to sync %s from %s: %s", filename, base, exc)
        return synced

    def _sync_s3(self, source: RegistrySource) -> list[str]:
        """List + download YAML blueprints from an S3 bucket prefix.

        Requires boto3; silently skipped if not installed.
        """
        synced: list[str] = []
        try:
            import boto3  # noqa: PLC0415
        except ImportError:
            logger.warning("Registry: boto3 not installed — S3 source %s skipped", source.url_or_bucket)
            return synced

        try:
            s3 = boto3.client("s3")
            paginator = s3.get_paginator("list_objects_v2")
            prefix = source.prefix.lstrip("/")
            for page in paginator.paginate(Bucket=source.url_or_bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.endswith((".yaml", ".yml")):
                        continue
                    try:
                        body = s3.get_object(Bucket=source.url_or_bucket, Key=key)["Body"].read().decode()
                        profile = self._load_yaml_text(body, source.badge)
                        if profile:
                            self._profiles[profile.metadata.name] = profile
                            synced.append(profile.metadata.name)
                    except Exception as exc:
                        logger.warning("Registry: S3 object %s failed: %s", key, exc)
        except Exception as exc:
            logger.warning("Registry: S3 sync failed for bucket %s: %s", source.url_or_bucket, exc)
        return synced

    def _sync_local(self, source: RegistrySource) -> list[str]:
        """Load YAML blueprints from a local directory."""
        synced: list[str] = []
        local_dir = Path(source.url_or_bucket)
        if not local_dir.is_dir():
            logger.warning("Registry: local source path does not exist: %s", local_dir)
            return synced
        for p in sorted(local_dir.rglob("*.yaml")):
            try:
                text = p.read_text()
                profile = self._load_yaml_text(text, source.badge)
                if profile:
                    self._profiles[profile.metadata.name] = profile
                    synced.append(profile.metadata.name)
            except Exception as exc:
                logger.warning("Registry: local file %s failed: %s", p, exc)
        return synced

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml_text(text: str, badge: str) -> ComplianceProfile | None:
        """Parse YAML text into a ComplianceProfile and stamp the source badge."""
        try:
            raw = yaml.safe_load(text)
            if not isinstance(raw, dict):
                return None
            profile = ComplianceProfile.model_validate(raw)
            profile.metadata.source_badge = badge
            return profile
        except Exception as exc:
            logger.debug("Registry: YAML parse error: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry_instance: ProfileRegistry | None = None


def get_registry() -> ProfileRegistry:
    if _registry_instance is None:
        raise RuntimeError("ProfileRegistry has not been initialised — check main.py lifespan")
    return _registry_instance


def init_registry(
    sources: list[RegistrySource] | None = None,
    cache_dir: Path | None = None,
    # Legacy positional arg
    base_url: str | None = None,
) -> ProfileRegistry:
    global _registry_instance
    _registry_instance = ProfileRegistry(sources=sources, local_cache_dir=cache_dir, base_url=base_url)
    return _registry_instance
