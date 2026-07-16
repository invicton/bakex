# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""ProfileRegistry unit tests — httpx and boto3 mocked, no network calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from statim.core.registry import (
    ProfileRegistry,
    RegistrySource,
    get_registry,
    init_registry,
)

# ---------------------------------------------------------------------------
# Minimal valid YAML for a ComplianceProfile
# ---------------------------------------------------------------------------

_VALID_YAML = """\
statim_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: test-ubuntu22-cis
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

_VALID_YAML_2 = """\
statim_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: test-rocky9-cis
  version: "1.0.0"
target:
  os: rocky9
  provider: aws
  base_image: ami-11111111
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_RHEL9
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
controls: {}
"""


# ---------------------------------------------------------------------------
# _load_yaml_text — static parser
# ---------------------------------------------------------------------------


def test_load_yaml_text_returns_profile():
    profile = ProfileRegistry._load_yaml_text(_VALID_YAML, "Official")
    assert profile is not None
    assert profile.metadata.name == "test-ubuntu22-cis"
    assert profile.metadata.source_badge == "Official"


def test_load_yaml_text_stamps_badge():
    for badge in ("Official", "Community", "Private", "Local"):
        p = ProfileRegistry._load_yaml_text(_VALID_YAML, badge)
        assert p.metadata.source_badge == badge


def test_load_yaml_text_invalid_yaml_returns_none():
    result = ProfileRegistry._load_yaml_text("{{ not yaml: [", "Community")
    assert result is None


def test_load_yaml_text_not_a_dict_returns_none():
    result = ProfileRegistry._load_yaml_text("- item1\n- item2\n", "Community")
    assert result is None


def test_load_yaml_text_missing_required_field_returns_none():
    # Missing compliance section → Pydantic validation error
    bad_yaml = "statim_version: '0.1.0'\nkind: ComplianceProfile\nmetadata:\n  name: x\n  version: '1'\n"
    result = ProfileRegistry._load_yaml_text(bad_yaml, "Community")
    assert result is None


# ---------------------------------------------------------------------------
# Basic API — list / get / count
# ---------------------------------------------------------------------------


def test_empty_registry():
    reg = ProfileRegistry()
    assert reg.list() == []
    assert reg.get("nonexistent") is None
    assert reg.count() == 0


def test_list_returns_all_profiles():
    reg = ProfileRegistry()
    p1 = ProfileRegistry._load_yaml_text(_VALID_YAML, "Official")
    p2 = ProfileRegistry._load_yaml_text(_VALID_YAML_2, "Community")
    reg._profiles["test-ubuntu22-cis"] = p1
    reg._profiles["test-rocky9-cis"] = p2
    assert reg.count() == 2
    names = {p.metadata.name for p in reg.list()}
    assert names == {"test-ubuntu22-cis", "test-rocky9-cis"}


def test_get_returns_correct_profile():
    reg = ProfileRegistry()
    p1 = ProfileRegistry._load_yaml_text(_VALID_YAML, "Official")
    reg._profiles["test-ubuntu22-cis"] = p1
    result = reg.get("test-ubuntu22-cis")
    assert result is not None
    assert result.metadata.name == "test-ubuntu22-cis"


def test_get_nonexistent_returns_none():
    reg = ProfileRegistry()
    assert reg.get("no-such-profile") is None


# ---------------------------------------------------------------------------
# _sync_local — filesystem sync
# ---------------------------------------------------------------------------


def test_sync_local_loads_yaml_files(tmp_path):
    (tmp_path / "ubuntu.yaml").write_text(_VALID_YAML)
    (tmp_path / "rocky.yaml").write_text(_VALID_YAML_2)
    source = RegistrySource("local", str(tmp_path), "Local")
    reg = ProfileRegistry()
    names = reg._sync_local(source)
    assert set(names) == {"test-ubuntu22-cis", "test-rocky9-cis"}
    assert reg.count() == 2


def test_sync_local_skips_invalid_yaml(tmp_path):
    (tmp_path / "good.yaml").write_text(_VALID_YAML)
    (tmp_path / "bad.yaml").write_text("{{ invalid")
    source = RegistrySource("local", str(tmp_path), "Local")
    reg = ProfileRegistry()
    names = reg._sync_local(source)
    assert names == ["test-ubuntu22-cis"]


def test_sync_local_nonexistent_dir_returns_empty():
    source = RegistrySource("local", "/nonexistent/path/12345", "Local")
    reg = ProfileRegistry()
    names = reg._sync_local(source)
    assert names == []


def test_sync_local_stamps_local_badge(tmp_path):
    (tmp_path / "p.yaml").write_text(_VALID_YAML)
    source = RegistrySource("local", str(tmp_path), "Private")
    reg = ProfileRegistry()
    reg._sync_local(source)
    assert reg.get("test-ubuntu22-cis").metadata.source_badge == "Private"


def test_sync_local_caches_to_dir(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "p.yaml").write_text(_VALID_YAML)
    cache_dir = tmp_path / "cache"
    source = RegistrySource("local", str(src_dir), "Local")
    reg = ProfileRegistry(local_cache_dir=cache_dir)
    # Local sync doesn't write to cache_dir (only GitHub does), but should not error
    reg._sync_local(source)
    assert reg.count() == 1


# ---------------------------------------------------------------------------
# _sync_github — httpx mocked
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sync_github_success():
    reg = ProfileRegistry()
    source = RegistrySource("github", "https://raw.example.com/registry", "Community")

    mock_client = AsyncMock()
    index_resp = MagicMock()
    index_resp.raise_for_status = MagicMock()
    index_resp.json.return_value = ["ubuntu22.yaml"]

    yaml_resp = MagicMock()
    yaml_resp.raise_for_status = MagicMock()
    yaml_resp.text = _VALID_YAML

    mock_client.get = AsyncMock(side_effect=[index_resp, yaml_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        names = await reg._sync_github(source)

    assert "test-ubuntu22-cis" in names
    assert reg.count() == 1


@pytest.mark.anyio
async def test_sync_github_index_fetch_failure_returns_empty():
    reg = ProfileRegistry()
    source = RegistrySource("github", "https://raw.example.com/registry", "Community")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        names = await reg._sync_github(source)

    assert names == []
    assert reg.count() == 0


@pytest.mark.anyio
async def test_sync_github_caches_yaml_to_disk(tmp_path):
    reg = ProfileRegistry(local_cache_dir=tmp_path)
    source = RegistrySource("github", "https://raw.example.com/registry", "Community")

    mock_client = AsyncMock()
    index_resp = MagicMock()
    index_resp.raise_for_status = MagicMock()
    index_resp.json.return_value = ["ubuntu22.yaml"]

    yaml_resp = MagicMock()
    yaml_resp.raise_for_status = MagicMock()
    yaml_resp.text = _VALID_YAML

    mock_client.get = AsyncMock(side_effect=[index_resp, yaml_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await reg._sync_github(source)

    assert (tmp_path / "ubuntu22.yaml").exists()


# ---------------------------------------------------------------------------
# _sync_s3 — boto3 mocked
# ---------------------------------------------------------------------------


def test_sync_s3_loads_yaml(tmp_path):
    reg = ProfileRegistry()
    source = RegistrySource("s3", "my-bucket", "Private", prefix="profiles/")

    mock_boto3 = MagicMock()
    mock_s3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    paginator = MagicMock()
    page = {"Contents": [{"Key": "profiles/ubuntu22.yaml"}]}
    paginator.paginate.return_value = [page]
    mock_s3.get_paginator.return_value = paginator

    obj_body = MagicMock()
    obj_body.read.return_value = _VALID_YAML.encode()
    mock_s3.get_object.return_value = {"Body": obj_body}

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        names = reg._sync_s3(source)

    assert "test-ubuntu22-cis" in names


def test_sync_s3_boto3_not_installed_returns_empty():
    reg = ProfileRegistry()
    source = RegistrySource("s3", "my-bucket", "Private")

    with patch.dict("sys.modules", {"boto3": None}):
        names = reg._sync_s3(source)

    assert names == []


# ---------------------------------------------------------------------------
# sync() — async dispatch to _sync_local/_sync_github
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sync_aggregates_multiple_sources(tmp_path):
    (tmp_path / "rocky.yaml").write_text(_VALID_YAML_2)

    reg = ProfileRegistry(
        sources=[
            RegistrySource("local", str(tmp_path), "Local"),
        ]
    )
    synced = await reg.sync()
    assert "test-rocky9-cis" in synced


# ---------------------------------------------------------------------------
# Module-level singleton — init_registry / get_registry
# ---------------------------------------------------------------------------


def test_get_registry_before_init_raises():
    import statim.core.registry as reg_mod

    original = reg_mod._registry_instance
    reg_mod._registry_instance = None
    try:
        with pytest.raises(RuntimeError, match="not been initialised"):
            get_registry()
    finally:
        reg_mod._registry_instance = original


def test_init_registry_sets_singleton():
    reg = init_registry(sources=[])
    assert get_registry() is reg


def test_init_registry_legacy_base_url():
    reg = init_registry(base_url="https://raw.example.com/registry")
    assert reg.count() == 0
    assert len(reg._sources) == 1
    assert reg._sources[0].kind == "github"
