# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""CredentialStore unit tests — encrypted file-backed credential storage."""

from __future__ import annotations

from stratum.api.integrations import CredentialStore

# ---------------------------------------------------------------------------
# Construction — key resolution paths
# ---------------------------------------------------------------------------


def test_credential_store_creates_data_dir(tmp_path):
    store_dir = tmp_path / "creds"
    CredentialStore(store_dir)
    assert store_dir.exists()


def test_credential_store_generates_key_file(tmp_path):
    CredentialStore(tmp_path)
    assert (tmp_path / ".stratum_key").exists()


def test_credential_store_key_file_permissions(tmp_path):
    CredentialStore(tmp_path)
    key_file = tmp_path / ".stratum_key"
    import stat

    mode = key_file.stat().st_mode
    assert not (mode & stat.S_IRWXG)  # no group permissions
    assert not (mode & stat.S_IRWXO)  # no other permissions


def test_credential_store_pbkdf2_key(tmp_path):
    # Providing secret_key should not generate a key file
    store1 = CredentialStore(tmp_path, secret_key="my-secret")
    store2 = CredentialStore(tmp_path, secret_key="my-secret")
    # Both instances derived from same password should encrypt/decrypt each other's data
    store1.set("aws", {"access_key": "AKIA123"})
    store2.get("aws")
    # store2 doesn't share store1's in-memory state — but they share the same key
    # so the persisted creds file should be readable by store2 after a fresh load
    store2.load()
    assert store2.get("aws") == {"access_key": "AKIA123"}


def test_credential_store_loads_existing_key_file(tmp_path):
    # First store generates key file
    store1 = CredentialStore(tmp_path)
    store1.set("gcp", {"project": "my-project"})
    # Second store reads existing key file
    store2 = CredentialStore(tmp_path)
    store2.load()
    assert store2.get("gcp") == {"project": "my-project"}


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def test_set_and_get(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("aws", {"region": "us-east-1", "token": "tok"})
    assert store.get("aws") == {"region": "us-east-1", "token": "tok"}


def test_get_nonexistent_returns_none(tmp_path):
    store = CredentialStore(tmp_path)
    assert store.get("no_such_provider") is None


def test_delete_removes_credential(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("azure", {"tenant_id": "t123"})
    store.delete("azure")
    assert store.get("azure") is None


def test_delete_nonexistent_is_noop(tmp_path):
    store = CredentialStore(tmp_path)
    store.delete("nonexistent")  # should not raise


def test_set_overwrites_existing(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("aws", {"region": "us-east-1"})
    store.set("aws", {"region": "eu-west-1"})
    assert store.get("aws") == {"region": "eu-west-1"}


def test_multiple_providers(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("aws", {"region": "us-east-1"})
    store.set("azure", {"tenant_id": "t123"})
    store.set("gcp", {"project": "my-proj"})
    assert store.get("aws")["region"] == "us-east-1"
    assert store.get("azure")["tenant_id"] == "t123"
    assert store.get("gcp")["project"] == "my-proj"


# ---------------------------------------------------------------------------
# Persistence — encrypt/decrypt round-trip
# ---------------------------------------------------------------------------


def test_persist_and_reload(tmp_path):
    store1 = CredentialStore(tmp_path)
    store1.set("digitalocean", {"api_token": "do-tok-abc123"})

    store2 = CredentialStore(tmp_path)
    store2.load()
    assert store2.get("digitalocean") == {"api_token": "do-tok-abc123"}


def test_encrypted_file_created_on_set(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("aws", {"region": "us-east-1"})
    assert (tmp_path / "credentials.enc").exists()


def test_encrypted_file_is_not_plaintext(tmp_path):
    store = CredentialStore(tmp_path)
    store.set("aws", {"secret_key": "super-secret-value"})
    enc_bytes = (tmp_path / "credentials.enc").read_bytes()
    # The plaintext secret must NOT appear as raw bytes in the encrypted file
    assert b"super-secret-value" not in enc_bytes


def test_invalid_token_on_load_is_handled(tmp_path):
    # Create a store with one key, write junk to the creds file, reload with different key
    store1 = CredentialStore(tmp_path)
    store1.set("aws", {"region": "us-east-1"})
    # Corrupt the encrypted file
    (tmp_path / "credentials.enc").write_bytes(b"not-valid-fernet-token")
    # Load should not raise — just log and leave store empty
    store2 = CredentialStore(tmp_path)
    store2.load()  # must not raise
    assert store2.get("aws") is None


def test_no_creds_file_load_is_noop(tmp_path):
    store = CredentialStore(tmp_path)
    store.load()  # no file exists — must not raise
    assert store.get("anything") is None
