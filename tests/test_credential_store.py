# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""CredentialStore unit tests — encrypted file-backed credential storage."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from statim.api.integrations import CredentialStore

# ---------------------------------------------------------------------------
# Construction — key resolution paths
# ---------------------------------------------------------------------------


def test_credential_store_creates_data_dir(tmp_path):
    store_dir = tmp_path / "creds"
    CredentialStore(store_dir)
    assert store_dir.exists()


def test_credential_store_generates_key_file(tmp_path):
    CredentialStore(tmp_path)
    assert (tmp_path / ".statim_key").exists()


def test_credential_store_key_file_permissions(tmp_path):
    CredentialStore(tmp_path)
    key_file = tmp_path / ".statim_key"
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


# ---------------------------------------------------------------------------
# PBKDF2 salt — per-install random salt + migration from the legacy fixed salt
# ---------------------------------------------------------------------------


def test_pbkdf2_salt_is_random_per_data_dir(tmp_path):
    """Two installs with the same passphrase but different data dirs must not
    derive the same key — the salt must not be a fixed, shared constant."""
    dir_a = tmp_path / "install-a"
    dir_b = tmp_path / "install-b"
    store_a = CredentialStore(dir_a, secret_key="same-passphrase")
    store_b = CredentialStore(dir_b, secret_key="same-passphrase")

    salt_a = (dir_a / ".statim_salt").read_bytes()
    salt_b = (dir_b / ".statim_salt").read_bytes()
    assert salt_a != salt_b

    store_a.set("aws", {"region": "us-east-1"})
    enc = (dir_a / "credentials.enc").read_bytes()
    # store_b's key (different salt) must not be able to decrypt store_a's file
    import json

    try:
        json.loads(store_b._fernet.decrypt(enc))
        raised = False
    except InvalidToken:
        raised = True
    assert raised, "different salts must derive different keys"


def test_legacy_fixed_salt_credentials_migrate_on_load(tmp_path):
    """Credentials encrypted under the old fixed salt (pre-fix installs) must
    still load, and get transparently re-encrypted under the new per-install
    random salt so the legacy salt is no longer relied on afterwards."""
    from statim.api import integrations as integrations_mod

    secret_key = "existing-install-passphrase"

    # Simulate a pre-fix install: encrypt directly with the legacy fixed salt,
    # no .statim_salt file involved.
    legacy_store = CredentialStore(tmp_path, secret_key=secret_key)
    legacy_fernet = Fernet(legacy_store._derive_key(secret_key, integrations_mod._LEGACY_KDF_SALT))
    (tmp_path / "credentials.enc").write_bytes(legacy_fernet.encrypt(b'{"aws": {"region": "us-east-1"}}'))
    (tmp_path / ".statim_salt").unlink()  # pre-fix installs never had this file

    # New store (post-fix code) using the same passphrase should migrate on load.
    store = CredentialStore(tmp_path, secret_key=secret_key)
    store.load()
    assert store.get("aws") == {"region": "us-east-1"}

    # After migration, the file on disk must be re-encrypted under the new,
    # per-install random salt — decryptable with the current store's key,
    # and no longer with the legacy fixed-salt key.
    reloaded_raw = (tmp_path / "credentials.enc").read_bytes()
    assert store._fernet.decrypt(reloaded_raw)
    try:
        legacy_fernet.decrypt(reloaded_raw)
        migrated = False
    except InvalidToken:
        migrated = True
    assert migrated, "credentials must be re-encrypted under the new salt after migration"
