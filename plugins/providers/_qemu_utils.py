#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""QEMU/KVM + cloud-init helpers shared by the local ``kvm`` provider.

Parallel to ``_provider_utils.py`` (SSH/Ansible/oscap helpers, reused
unchanged) — this module owns everything specific to booting a local VM:
base-image resolution, overlay creation, cloud-init seed generation, process
lifecycle, and disk-format conversion.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Official generic cloud images per OS identifier, plus the checksum manifest
# each distro publishes at the same host (verified before first use).
_BASE_IMAGE_SOURCES: dict[str, dict[str, str]] = {
    "ubuntu22.04": {
        "url": "https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img",
        "checksum_url": "https://cloud-images.ubuntu.com/releases/22.04/release/SHA256SUMS",
        "checksum_kind": "sha256sums",
    },
    "ubuntu24.04": {
        "url": "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img",
        "checksum_url": "https://cloud-images.ubuntu.com/releases/24.04/release/SHA256SUMS",
        "checksum_kind": "sha256sums",
    },
    "debian12": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "checksum_url": "https://cloud.debian.org/images/cloud/bookworm/latest/SHA512SUMS",
        "checksum_kind": "sha512sums",
    },
}


class BaseImageError(RuntimeError):
    """Raised when a base image can't be resolved, downloaded, or verified."""


def resolve_base_image(base_image: str, os_name: str, cache_dir: Path) -> Path:
    """Return a local qcow2 path for *base_image*.

    ``base_image`` is either:
      - an absolute/relative filesystem path to a qcow2 the caller already has
        (BYO — used as-is, no download, no checksum available), or
      - empty/a recognised OS slug — triggers a checksum-verified download of
        the official upstream cloud image, cached under *cache_dir*.
    """
    candidate = Path(base_image) if base_image else None
    if candidate is not None and candidate.is_file():
        logger.info("Using bring-your-own base image: %s", candidate)
        return candidate

    source = _BASE_IMAGE_SOURCES.get(os_name)
    if source is None:
        raise BaseImageError(
            f"No downloadable base image for os={os_name!r} and 'target.base_image' "
            f"is not an existing file path. Known downloadable OS slugs: "
            f"{sorted(_BASE_IMAGE_SOURCES)}"
        )
    return _download_and_cache(os_name, source, cache_dir)


def _download_and_cache(os_name: str, source: dict[str, str], cache_dir: Path) -> Path:
    os_dir = cache_dir / os_name
    os_dir.mkdir(parents=True, exist_ok=True)

    filename = source["url"].rsplit("/", maxsplit=1)[-1]
    dest = os_dir / filename
    checksum_file = dest.with_suffix(dest.suffix + ".sha256")

    if dest.is_file() and checksum_file.is_file():
        logger.info("Using cached base image: %s", dest)
        return dest

    logger.info("Downloading base image for %s: %s", os_name, source["url"])
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(source["url"], tmp_dest)  # noqa: S310 — fixed, hardcoded HTTPS URLs only

    expected = _fetch_expected_checksum(source, filename)
    actual = _sha256_file(tmp_dest)
    if expected is not None and expected.lower() != actual:
        tmp_dest.unlink(missing_ok=True)
        raise BaseImageError(
            f"Checksum mismatch downloading {source['url']}: expected {expected}, got sha256:{actual}. "
            "Refusing to use a base image that doesn't match the publisher's checksum."
        )
    if expected is None:
        logger.warning(
            "Could not verify checksum for %s against %s — proceeding without verification.",
            filename,
            source.get("checksum_url"),
        )

    tmp_dest.rename(dest)
    checksum_file.write_text(f"{actual}\n")
    logger.info("Cached base image %s (sha256:%s)", dest, actual[:16])
    return dest


def _fetch_expected_checksum(source: dict[str, str], filename: str) -> str | None:
    """Best-effort fetch of the publisher's checksum for *filename*.

    Returns None (not an error) if the checksum manifest can't be fetched or
    parsed — caller logs a warning and proceeds, matching the "detect and
    warn, don't hard-fail" convention used elsewhere in this codebase.
    """
    try:
        with urllib.request.urlopen(source["checksum_url"], timeout=30) as resp:  # noqa: S310
            text = resp.read().decode()
    except Exception as exc:
        logger.warning("Could not fetch checksum manifest %s: %s", source.get("checksum_url"), exc)
        return None

    # Ubuntu's SHA256SUMS / Debian's SHA512SUMS: "<hex>  <filename>" per line.
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            return parts[0]
    logger.warning("Filename %s not found in checksum manifest", filename)
    return None


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    """Public wrapper for hashing an output artifact (not a base image)."""
    return _sha256_file(path)


# ---------------------------------------------------------------------------
# Disk image lifecycle
# ---------------------------------------------------------------------------


def create_overlay(base_path: Path, overlay_path: Path, size_gb: int | None = None) -> None:
    """Create a qcow2 overlay backed by *base_path*, never mutating the base.

    ``-F qcow2`` pins the backing file's format so qemu-img/qemu never have to
    probe it — avoids the backing-file format-autodetection CVE class.

    *size_gb*, when given, makes the overlay's virtual disk larger than the
    base image — official cloud images ship a minimal (~2GB) root partition,
    and cloud-init's growpart/resizefs modules only have room to expand into
    if the overlay actually has extra space. Without this, package installs
    during hardening reliably fail with "No space left on device".
    """
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        "-F",
        "qcow2",
        "-b",
        str(base_path.resolve()),
        str(overlay_path),
    ]
    if size_gb:
        cmd.append(f"{size_gb}G")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def convert_to_raw(qcow2_path: Path, raw_path: Path) -> None:
    subprocess.run(
        ["qemu-img", "convert", "-O", "raw", str(qcow2_path), str(raw_path)],
        check=True,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# cloud-init seed ISO
# ---------------------------------------------------------------------------


def build_seed_iso(tmpdir: Path, ssh_pubkey: str, ssh_user: str, hostname: str) -> Path:
    """Build a cloud-init NoCloud seed ISO granting SSH access to *ssh_user*.

    Key-only auth: no password is ever set, matching every other BakeX
    provider's ephemeral-credential convention.
    """
    user_data = (
        "#cloud-config\n"
        "users:\n"
        f"  - name: {ssh_user}\n"
        "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
        "    shell: /bin/bash\n"
        "    lock_passwd: true\n"
        "    ssh_authorized_keys:\n"
        f"      - {ssh_pubkey}\n"
        "ssh_pwauth: false\n"
        "disable_root: true\n"
        "chpasswd:\n"
        "  expire: false\n"
    )
    meta_data = f"instance-id: bakex-{hostname}\nlocal-hostname: {hostname}\n"

    (tmpdir / "user-data").write_text(user_data)
    (tmpdir / "meta-data").write_text(meta_data)

    seed_path = tmpdir / "seed.iso"
    if shutil.which("cloud-localds"):
        subprocess.run(
            ["cloud-localds", str(seed_path), str(tmpdir / "user-data"), str(tmpdir / "meta-data")],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        subprocess.run(
            [
                "genisoimage",
                "-output",
                str(seed_path),
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                str(tmpdir / "user-data"),
                str(tmpdir / "meta-data"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return seed_path


def wait_for_ssh_ready(
    host: str, user: str, key_path: Path, port: int, timeout: int = 120, interval: float = 3.0
) -> None:
    """Block until *host* accepts and executes a real SSH command.

    wait_for_ssh only confirms the TCP listener is up; sshd commonly resets
    the first several connections while it finishes starting (regenerating
    host keys, etc.), and the failure mode varies run to run — sometimes a
    named error ("kex_exchange_identification"), sometimes an empty one — so
    this retries on *any* failure rather than matching specific error text
    (unlike _provider_utils.run_remote_cmd_with_retry, which intentionally
    only retries known-transient errors during real command execution).
    A bare ``true`` has no legitimate failure mode of its own, so retrying
    unconditionally here is safe.
    """
    import _provider_utils as utils  # local import: this module has no hard dependency on it otherwise

    deadline = time.time() + timeout
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            utils.run_remote_cmd(host, user, key_path, "true", timeout=10, port=port)
            return
        except Exception as exc:  # noqa: BLE001 — intentionally broad, see docstring
            last_exc = exc
            time.sleep(interval)
    raise TimeoutError(f"SSH on {host}:{port} did not become truly ready within {timeout}s: {last_exc}")


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kvm_available() -> bool:
    """Whether hardware acceleration is usable — never hard-fail on its absence."""
    kvm_dev = Path("/dev/kvm")
    return kvm_dev.exists() and os.access(kvm_dev, os.R_OK | os.W_OK)


# ---------------------------------------------------------------------------
# QEMU process lifecycle
# ---------------------------------------------------------------------------


def launch_qemu(
    overlay_path: Path,
    seed_iso_path: Path,
    ssh_port: int,
    serial_log_path: Path,
    memory_mb: int = 2048,
    cpus: int = 2,
    use_kvm: bool | None = None,
) -> subprocess.Popen:
    """Launch a background QEMU process booting *overlay_path*.

    Uses KVM acceleration when available (``use_kvm=None`` autodetects),
    falling back to TCG software emulation — much slower, but works
    everywhere, matching the "detect and warn, don't hard-fail" convention.

    Guest serial console output is redirected to *serial_log_path* rather than
    an unconsumed pipe — a long build's console chatter would otherwise fill
    the OS pipe buffer and make QEMU block on write().
    """
    if use_kvm is None:
        use_kvm = kvm_available()
    accel = "kvm" if use_kvm else "tcg"
    if not use_kvm:
        logger.warning("No usable /dev/kvm — falling back to TCG software emulation (builds will be much slower)")

    cmd = [
        "qemu-system-x86_64",
        "-name",
        "bakex-kvm-build",
        "-machine",
        f"accel={accel}",
        "-cpu",
        "host" if use_kvm else "qemu64",
        "-smp",
        str(cpus),
        "-m",
        str(memory_mb),
        "-drive",
        f"file={overlay_path},if=virtio,format=qcow2",
        "-drive",
        f"file={seed_iso_path},if=ide,media=cdrom",
        "-netdev",
        f"user,id=net0,hostfwd=tcp::{ssh_port}-:22",
        "-device",
        "virtio-net-pci,netdev=net0",
        "-serial",
        f"file:{serial_log_path}",
        "-monitor",
        "none",
        "-display",
        "none",
    ]
    logger.info("Launching QEMU (accel=%s, port=%d): %s", accel, ssh_port, overlay_path)
    # QEMU's own stdout/stderr (not the guest's) go to DEVNULL, not PIPE — an
    # unconsumed pipe can fill and block QEMU on write() over a long build.
    # Diagnosis on failure relies on the exit code plus serial_log_path.
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def terminate_qemu(proc: subprocess.Popen, timeout: int = 30) -> None:
    """Terminate a QEMU process, escalating to SIGKILL if it won't exit cleanly."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("QEMU process %d did not exit after terminate(); killing", proc.pid)
        proc.kill()
        proc.wait(timeout=10)


def wait_for_process_exit(proc: subprocess.Popen, timeout: int = 60) -> bool:
    """Wait for a guest-initiated shutdown to end the QEMU process on its own."""
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False
