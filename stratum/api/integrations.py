# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Encrypted, file-backed provider credential store + save/load endpoints."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

# KDF parameters — changing these invalidates existing encrypted files.
_KDF_SALT = b"stratum-credential-store-v1"
_KDF_ITERATIONS = 300_000


class CredentialStore:
    """AES-128 Fernet encrypted credential store backed by a file on disk.

    Key resolution order:
    1. ``secret_key`` argument (STRATUM_SECRET_KEY env var) — PBKDF2-derived,
       deterministic across restarts (no key file needed).
    2. Existing ``data_dir/.stratum_key`` — loaded from disk.
    3. Auto-generated random key written to ``data_dir/.stratum_key`` (chmod 600).

    Credentials are stored as a Fernet-encrypted JSON blob at
    ``data_dir/credentials.enc`` (chmod 600).
    """

    def __init__(self, data_dir: Path, secret_key: str | None = None) -> None:
        self._data_dir = data_dir
        self._creds_file = data_dir / "credentials.enc"
        self._key_file = data_dir / ".stratum_key"
        self._store: dict[str, dict] = {}
        self._fernet = self._init_fernet(secret_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_fernet(self, secret_key: str | None) -> Fernet:
        self._data_dir.mkdir(parents=True, exist_ok=True)

        if secret_key:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=_KDF_SALT,
                iterations=_KDF_ITERATIONS,
            )
            key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
            logger.info("Credential store: using PBKDF2-derived key from STRATUM_SECRET_KEY")
        elif self._key_file.exists():
            key = self._key_file.read_bytes().strip()
            logger.info("Credential store: loaded key from %s", self._key_file)
        else:
            key = Fernet.generate_key()
            self._key_file.write_bytes(key)
            self._key_file.chmod(0o600)
            logger.info("Credential store: generated new key at %s", self._key_file)

        return Fernet(key)

    def _persist(self) -> None:
        """Encrypt and write credential store to disk.

        Failures are logged as warnings rather than raised — the credential
        store always works in-memory even if disk persistence is unavailable
        (e.g. read-only filesystem or stale file owned by root).
        """
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            encrypted = self._fernet.encrypt(json.dumps(self._store).encode())
            self._creds_file.write_bytes(encrypted)
            try:
                self._creds_file.chmod(0o600)
            except OSError:
                pass
        except Exception as exc:
            logger.warning(
                "Could not persist credentials to disk (%s). "
                "Credentials are saved in-memory for this session only. "
                "Fix file permissions with: sudo chown $USER data/credentials.enc",
                exc,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Decrypt and load credentials from disk (called once at startup)."""
        if not self._creds_file.exists():
            return
        try:
            encrypted = self._creds_file.read_bytes()
            self._store = json.loads(self._fernet.decrypt(encrypted))
            logger.info("Loaded persisted credentials for: %s", list(self._store.keys()))
        except InvalidToken:
            logger.warning(
                "Credential file exists but could not be decrypted — "
                "the encryption key may have changed. Credentials reset."
            )
        except Exception as exc:
            logger.warning("Could not load persisted credentials: %s", exc)

    def set(self, provider: str, creds: dict) -> None:
        self._store[provider] = creds
        self._persist()

    def get(self, provider: str) -> dict | None:
        return self._store.get(provider)

    def delete(self, provider: str) -> None:
        self._store.pop(provider, None)
        self._persist()


# ---------------------------------------------------------------------------
# Module-level store — initialised lazily so Settings are available at import
# ---------------------------------------------------------------------------


def _make_store() -> CredentialStore:
    from stratum.config import settings  # avoid circular import at module level

    return CredentialStore(
        data_dir=settings.data_dir,
        secret_key=settings.stratum_secret_key,
    )


credential_store: CredentialStore = _make_store()


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

_SAVED_HTML = (
    '<div class="rounded-xl border border-emerald-800/50 bg-emerald-950/20 p-4 space-y-3">'
    '<div class="flex items-center gap-2 text-emerald-400 font-semibold text-sm">'
    '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>'
    "</svg> Credentials saved &amp; encrypted</div>"
    '<p class="text-xs text-slate-400">What would you like to do next?</p>'
    '<div class="flex gap-3">'
    '<a href="/builder" class="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 '
    'text-white text-xs font-semibold rounded-lg transition-all">'
    '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
    'd="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158'
    "a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 "
    "1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414"
    'l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>'
    "Build an Image</a>"
    '<a href="/auditor/scan-image" class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 '
    'hover:bg-slate-600 border border-slate-600 text-slate-200 text-xs font-semibold rounded-lg transition-all">'
    '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
    'd="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>'
    "Scan Existing Image</a>"
    "</div></div>"
)


@router.post("/{provider_name}", response_class=HTMLResponse)
async def save_credentials(request: Request, provider_name: str) -> str:
    form_data = await request.form()
    credential_store.set(provider_name, dict(form_data))
    return _SAVED_HTML


@router.get("/{provider_name}")
async def get_credentials_api(provider_name: str) -> dict:
    return credential_store.get(provider_name) or {}


@router.post("/{provider_name}/test", response_class=HTMLResponse)
async def test_credentials(request: Request, provider_name: str) -> str:
    form_data = await request.form()
    creds = dict(form_data)

    if provider_name == "aws":
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            session_args: dict = {}
            if creds.get("region"):
                session_args["region_name"] = creds["region"]
            if creds.get("aws_access_key_id") and creds.get("aws_secret_access_key"):
                session_args["aws_access_key_id"] = creds["aws_access_key_id"]
                session_args["aws_secret_access_key"] = creds["aws_secret_access_key"]
            elif creds.get("aws_profile"):
                session_args["profile_name"] = creds["aws_profile"]

            session = boto3.Session(**session_args)
            role_arn = creds.get("role_arn")
            external_id = creds.get("external_id")

            if role_arn:
                sts = session.client("sts")
                assume_kwargs = {
                    "RoleArn": role_arn,
                    "RoleSessionName": "StratumConnectionTest",
                }
                if external_id:
                    assume_kwargs["ExternalId"] = external_id
                assumed = sts.assume_role(**assume_kwargs)
                credentials = assumed["Credentials"]
                session = boto3.Session(
                    aws_access_key_id=credentials["AccessKeyId"],
                    aws_secret_access_key=credentials["SecretAccessKey"],
                    aws_session_token=credentials["SessionToken"],
                    region_name=creds.get("region", "us-east-1"),
                )

            sts_client = session.client("sts")
            identity = sts_client.get_caller_identity()
            account_id = identity.get("Account")
            arn = identity.get("Arn")

            ec2_client = session.client("ec2")
            ec2_client.describe_security_groups(MaxResults=5)

            short_arn = arn.split("/")[-1] if arn else "unknown"
            return (
                '<span class="text-emerald-400 font-medium text-sm flex items-center gap-1">'
                '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>'
                f"</svg> Connected to Account {account_id} as {short_arn}</span>"
            )

        except (ClientError, BotoCoreError) as exc:
            from botocore.exceptions import NoCredentialsError, PartialCredentialsError

            if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
                label = "No Credentials Found"
            else:
                label = "AWS Error"
            return _err_html(f"{label}: {exc}")
        except Exception as exc:
            return _err_html(str(exc))

    if provider_name == "gcp":
        return await _test_gcp(creds)

    if provider_name == "azure":
        return await _test_azure(creds)

    if provider_name in ("digitalocean",):
        return await _test_digitalocean(creds)

    if provider_name == "linode":
        return await _test_linode(creds)

    if provider_name == "proxmox":
        return await _test_proxmox(creds)

    return '<span class="text-slate-400 font-medium text-sm">Test connection not implemented for this provider.</span>'


# ---------------------------------------------------------------------------
# Per-provider test helpers
# ---------------------------------------------------------------------------


def _ok_html(msg: str) -> str:
    return (
        '<span class="text-emerald-400 font-medium text-sm flex items-center gap-1">'
        '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>'
        f"</svg> {msg}</span>"
    )


def _err_html(msg: str) -> str:
    safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    return (
        '<div class="relative flex items-start gap-2 text-rose-400 text-sm'
        ' bg-rose-950/30 border border-rose-800/40 rounded-lg px-3 py-2.5">'
        '<button onclick="this.parentElement.remove()" '
        'class="absolute top-1.5 right-1.5 text-rose-500 hover:text-rose-300'
        ' p-0.5 rounded hover:bg-rose-900/40 transition-colors" title="Dismiss">'
        '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"'
        ' d="M6 18L18 6M6 6l12 12"></path></svg></button>'
        '<div class="flex flex-col gap-1 pr-5">'
        '<div class="flex items-center gap-1.5 font-medium">'
        '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"'
        ' d="M6 18L18 6M6 6l12 12"></path></svg>'
        "Connection failed</div>"
        f'<div class="text-xs font-mono bg-rose-900/20 p-2 rounded max-w-xl'
        f' overflow-x-auto whitespace-pre-wrap">{safe}</div>'
        "</div></div>"
    )


async def _test_gcp(creds: dict) -> str:
    project_id = creds.get("project_id", "").strip()
    if not project_id:
        return _err_html("project_id is required")
    try:
        from google.cloud import compute_v1
    except ImportError:
        return _err_html("google-cloud-compute not installed. Install stratum[gcp].")
    try:
        sa_json = creds.get("service_account_json", "").strip()
        if sa_json:
            import json as _json

            from google.oauth2 import service_account as _sa

            info = _json.loads(sa_json)
            gc = _sa.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            client = compute_v1.RegionsClient(credentials=gc)
        else:
            client = compute_v1.RegionsClient()  # Application Default Credentials
        regions = list(client.list(project=project_id))
        return _ok_html(f"Connected to project <strong>{project_id}</strong> — {len(regions)} regions available")
    except Exception as exc:
        return _err_html(str(exc))


async def _test_azure(creds: dict) -> str:
    for key in ("tenant_id", "client_id", "client_secret", "subscription_id"):
        if not creds.get(key, "").strip():
            return _err_html(f"{key} is required")
    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.resource import SubscriptionClient
    except ImportError:
        return _err_html("azure-identity / azure-mgmt-resource not installed. Install stratum[azure].")
    try:
        credential = ClientSecretCredential(
            tenant_id=creds["tenant_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )
        sub_client = SubscriptionClient(credential)
        sub = sub_client.subscriptions.get(creds["subscription_id"])
        return _ok_html(f"Connected to subscription <strong>{sub.display_name}</strong> ({sub.subscription_id})")
    except Exception as exc:
        return _err_html(str(exc))


async def _test_digitalocean(creds: dict) -> str:
    token = creds.get("api_token", "").strip()
    if not token:
        return _err_html("api_token is required")
    try:
        import requests as _requests
    except ImportError:
        return _err_html("requests not installed. Install stratum[digitalocean].")
    try:
        resp = _requests.get(
            "https://api.digitalocean.com/v2/account",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        account = resp.json().get("account", {})
        email = account.get("email", "unknown")
        status = account.get("status", "")
        return _ok_html(f"Connected as <strong>{email}</strong> (status: {status})")
    except Exception as exc:
        return _err_html(str(exc))


async def _test_linode(creds: dict) -> str:
    token = creds.get("api_token", "").strip()
    if not token:
        return _err_html("api_token is required")
    try:
        import requests as _requests
    except ImportError:
        return _err_html("requests not installed. Install stratum[linode].")
    try:
        resp = _requests.get(
            "https://api.linode.com/v4/account",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        account = resp.json()
        email = account.get("email", "unknown")
        company = account.get("company", "")
        label = f"{email}" + (f" ({company})" if company else "")
        return _ok_html(f"Connected as <strong>{label}</strong>")
    except Exception as exc:
        return _err_html(str(exc))


async def _test_proxmox(creds: dict) -> str:
    for key in ("host", "user", "token_name", "token_value"):
        if not creds.get(key, "").strip():
            return _err_html(f"{key} is required")
    try:
        from proxmoxer import ProxmoxAPI
    except ImportError:
        return _err_html("proxmoxer not installed. Install stratum[proxmox].")
    try:
        proxmox = ProxmoxAPI(
            host=creds["host"],
            user=creds["user"],
            token_name=creds["token_name"],
            token_value=creds["token_value"],
            verify_ssl=False,
        )
        version_info = proxmox.version.get()
        ver = version_info.get("version", "unknown")
        release = version_info.get("release", "")
        return _ok_html(f"Connected to Proxmox VE <strong>{ver}</strong> (release {release})")
    except Exception as exc:
        return _err_html(str(exc))


# ---------------------------------------------------------------------------
# Helper used by subprocess providers
# ---------------------------------------------------------------------------


def get_credentials(provider: str) -> dict | None:
    """Retrieve stored credentials for a provider (used by subprocess_provider)."""
    return credential_store.get(provider)
