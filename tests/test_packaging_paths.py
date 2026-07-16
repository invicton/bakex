# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Packaging-path tests — the app must work from any CWD (pip install, not just repo checkout).

PKG-01  bakex.paths constants are package-anchored and exist
PKG-02  UI + template endpoints render with CWD outside the repo (subprocess)
PKG-03  Settings falls back to bundled profiles/ and plugins/catalog when
        the CWD-relative defaults are missing
PKG-04  Explicitly-set dirs are never silently swapped for bundled ones
PKG-05  registry_url default points at the real community blueprints location
PKG-06  GitHub sync caches nested index filenames (e.g. "rocky/9/x.yaml")
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_VALID_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: test-nested-cache
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
controls: {}
"""


# ---------------------------------------------------------------------------
# PKG-01 — package-anchored path constants
# ---------------------------------------------------------------------------


def test_paths_module_is_package_anchored():
    import bakex
    from bakex.paths import PACKAGE_DIR, STATIC_DIR, TEMPLATES_DIR

    pkg_root = Path(bakex.__file__).resolve().parent
    assert PACKAGE_DIR == pkg_root
    for d in (TEMPLATES_DIR, STATIC_DIR):
        assert d.is_absolute()
        assert d.is_dir()
        assert d.parent == pkg_root


def test_no_cwd_relative_template_or_static_literals():
    """No module may hardcode the CWD-relative 'bakex/templates' / 'bakex/static' strings."""
    offenders = []
    for py in (REPO_ROOT / "bakex").rglob("*.py"):
        text = py.read_text()
        if '"bakex/templates' in text or '"bakex/static' in text:
            offenders.append(str(py.relative_to(REPO_ROOT)))
    assert offenders == []


# ---------------------------------------------------------------------------
# PKG-02 — app renders UI from a foreign CWD
# ---------------------------------------------------------------------------


def test_ui_renders_from_foreign_cwd(tmp_path):
    """Simulate a pip-installed run: import the app with CWD in an empty dir.

    Template pages, HTML partials, and static assets must all resolve.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            from fastapi.testclient import TestClient

            from bakex.main import app

            with TestClient(app) as client:
                auth = ("admin", "probe-token")
                for path in ("/", "/blueprints", "/api/plugins/available"):
                    r = client.get(path, auth=auth)
                    assert r.status_code == 200, f"{path} -> {r.status_code}"
                # static mount must serve real assets regardless of CWD
                r = client.get("/static/js/htmx.min.js", auth=auth)
                assert r.status_code == 200, f"static asset -> {r.status_code}"
            print("PKG-02 OK")
            """
        )
    )
    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": str(REPO_ROOT),
            "BAKEX_ADMIN_TOKEN": "probe-token",
            "PATH": "/usr/bin:/bin",
        },
        timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "PKG-02 OK" in result.stdout


# ---------------------------------------------------------------------------
# PKG-03 / PKG-04 — bundled-data fallback in Settings
# ---------------------------------------------------------------------------


def _make_bundled(tmp_path: Path) -> Path:
    bundled = tmp_path / "bundled"
    (bundled / "profiles" / "templates").mkdir(parents=True)
    (bundled / "plugins" / "catalog").mkdir(parents=True)
    (bundled / "plugins" / "catalog" / "index.json").write_text("{}")
    return bundled


def test_settings_fall_back_to_bundled_dirs(tmp_path, monkeypatch):
    from bakex import paths
    from bakex.config import Settings

    bundled = _make_bundled(tmp_path)
    monkeypatch.setattr(paths, "BUNDLED_DIR", bundled)
    monkeypatch.chdir(tmp_path)  # no profiles/ or plugins/catalog here

    s = Settings(_env_file=None)
    assert s.profiles_dir == bundled / "profiles"
    assert s.catalog_dir == bundled / "plugins" / "catalog"


def test_settings_prefer_cwd_dirs_when_present(tmp_path, monkeypatch):
    from bakex import paths
    from bakex.config import Settings

    bundled = _make_bundled(tmp_path)
    monkeypatch.setattr(paths, "BUNDLED_DIR", bundled)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "plugins" / "catalog").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    s = Settings(_env_file=None)
    assert s.profiles_dir == Path("profiles")
    assert s.catalog_dir == Path("plugins/catalog")


def test_settings_never_override_explicit_dirs(tmp_path, monkeypatch):
    from bakex import paths
    from bakex.config import Settings

    bundled = _make_bundled(tmp_path)
    monkeypatch.setattr(paths, "BUNDLED_DIR", bundled)
    monkeypatch.chdir(tmp_path)

    explicit = tmp_path / "does-not-exist-yet"
    s = Settings(_env_file=None, profiles_dir=explicit, catalog_dir=explicit)
    assert s.profiles_dir == explicit
    assert s.catalog_dir == explicit


# ---------------------------------------------------------------------------
# PKG-05 — registry default URL
# ---------------------------------------------------------------------------


def test_registry_url_default_points_at_bakex_blueprints():
    from bakex.config import Settings

    s = Settings(_env_file=None)
    assert s.registry_url == "https://raw.githubusercontent.com/bakex/BakeX/main/blueprints"


# ---------------------------------------------------------------------------
# PKG-06 — nested cache filenames from the community index
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sync_github_caches_nested_filename(tmp_path):
    from bakex.core.registry import ProfileRegistry, RegistrySource

    reg = ProfileRegistry(local_cache_dir=tmp_path)
    source = RegistrySource("github", "https://raw.example.com/registry", "Community")

    index_resp = MagicMock()
    index_resp.raise_for_status = MagicMock()
    index_resp.json.return_value = ["rocky/9/cis-l1-aws.yaml"]

    yaml_resp = MagicMock()
    yaml_resp.raise_for_status = MagicMock()
    yaml_resp.text = _VALID_YAML

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[index_resp, yaml_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        names = await reg._sync_github(source)

    assert "test-nested-cache" in names
    assert (tmp_path / "rocky" / "9" / "cis-l1-aws.yaml").exists()
