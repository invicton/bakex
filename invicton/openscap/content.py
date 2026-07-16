# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""SCAP content resolution for host-local scans.

Resolves an OS slug + compliance tier to its (benchmark, profile, datastream)
from the single-source-of-truth OS_CATALOG, and ensures the datastream file is
actually present on the host — using the installed system content when
available, otherwise downloading the matching datastream from a
ComplianceAsCode/content release (the same verified fallback the remote
provider path uses, lifted here so both share one implementation).
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
import zipfile
from pathlib import Path

from invicton.config import settings
from invicton.core.os_catalog import OS_CATALOG

logger = logging.getLogger(__name__)


class ScanContentError(RuntimeError):
    """Raised when the SCAP datastream for a target cannot be located or fetched."""


# ComplianceAsCode/content release used as the fallback SCAP-content source when
# the host doesn't have the datastream installed. Only the release .zip ships
# the prebuilt ssg-<os>-ds.xml datastreams (under scap-security-guide-<ver>/).
_SCAP_CONTENT_VERSION = "0.1.81"
_SCAP_CONTENT_ZIP_URL = (
    f"https://github.com/ComplianceAsCode/content/releases/download/"
    f"v{_SCAP_CONTENT_VERSION}/scap-security-guide-{_SCAP_CONTENT_VERSION}.zip"
)
_SCAP_CONTENT_SHA512_URL = _SCAP_CONTENT_ZIP_URL + ".sha512"

# tier slug (as used across the app) → the key inside cis_profile_suffixes
_TIER_TO_SUFFIX_KEY = {"cis-l1": "l1", "cis-l2": "l2"}


def resolve_scan_spec(os_slug: str, tier: str = "cis-l1") -> tuple[str, str, str]:
    """Return ``(benchmark_id, profile_id, datastream_path)`` for *os_slug* + *tier*.

    Raises ValueError (listing supported OSes/tiers) if the combination is unknown.
    """
    entry = OS_CATALOG.get(os_slug)
    if entry is None:
        supported = ", ".join(sorted(OS_CATALOG))
        raise ValueError(f"Unknown OS '{os_slug}'. Supported: {supported}")

    suffix_key = _TIER_TO_SUFFIX_KEY.get(tier)
    suffixes = entry.get("cis_profile_suffixes", {})
    if suffix_key is None or suffix_key not in suffixes:
        supported_tiers = ", ".join(entry.get("supported_tiers", []) or ["cis-l1"])
        raise ValueError(f"Unsupported tier '{tier}' for '{os_slug}'. Supported: {supported_tiers}")

    benchmark = entry["scap_benchmark"]
    profile = entry["scap_profile_prefix"] + suffixes[suffix_key]
    datastream = entry["scap_datastream"]
    return benchmark, profile, datastream


def ensure_datastream(datastream_path: str, cache_dir: Path | None = None) -> Path:
    """Return a local path to *datastream_path*.

    Uses the host path if it already exists (system-installed content); otherwise
    downloads the matching datastream from a ComplianceAsCode release into the
    cache. Raises ScanContentError if it cannot be produced.
    """
    host_path = Path(datastream_path)
    if host_path.is_file():
        return host_path

    if cache_dir is None:
        cache_dir = Path(settings.data_dir) / "scap-content"

    downloaded = _download_datastream(datastream_path, cache_dir)
    if downloaded is None:
        raise ScanContentError(
            f"SCAP datastream not found at {datastream_path} and could not be downloaded. "
            f"Install the OS's SCAP content (e.g. apt install ssg-debderived / "
            f"dnf install scap-security-guide) or place the datastream at that path."
        )
    return downloaded


def _download_datastream(datastream_path: str, cache_dir: Path) -> Path | None:
    """Download+cache the ComplianceAsCode release zip once and extract the
    datastream matching *datastream_path*'s basename. Returns the local path, or
    None if unavailable — best-effort, not a hard dependency.
    """
    filename = os.path.basename(datastream_path)
    if not filename:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = cache_dir / filename
    if extracted_path.is_file():
        return extracted_path

    zip_path = cache_dir / f"scap-security-guide-{_SCAP_CONTENT_VERSION}.zip"
    try:
        if not zip_path.is_file():
            logger.info("Downloading ComplianceAsCode content v%s for SCAP fallback…", _SCAP_CONTENT_VERSION)
            tmp_path = zip_path.with_suffix(".part")
            urllib.request.urlretrieve(_SCAP_CONTENT_ZIP_URL, tmp_path)  # noqa: S310 — fixed HTTPS URL

            expected = None
            try:
                with urllib.request.urlopen(_SCAP_CONTENT_SHA512_URL, timeout=30) as resp:  # noqa: S310
                    expected = resp.read().decode().split()[0].strip().lower()
            except Exception as exc:
                logger.warning("Could not fetch ComplianceAsCode checksum: %s", exc)

            h = hashlib.sha512()
            with open(tmp_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            if expected is not None and expected != h.hexdigest():
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f"ComplianceAsCode content checksum mismatch for {filename}")
            tmp_path.rename(zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            member = f"scap-security-guide-{_SCAP_CONTENT_VERSION}/{filename}"
            with zf.open(member) as src, open(extracted_path, "wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
        return extracted_path
    except KeyError:
        logger.warning("ComplianceAsCode release v%s does not contain %s", _SCAP_CONTENT_VERSION, filename)
        return None
    except Exception as exc:
        logger.warning("Could not prepare ComplianceAsCode SCAP content for %s: %s", filename, exc)
        return None
