"""engine/win_dpapi.py — machine-scoped secret protection (Windows DPAPI).

protect(data) -> str and unprotect(b64) -> bytes round-trip on Windows using
CryptProtectData/CryptUnprotectData. If DPAPI fails for any reason (no
crypt32, foreign machine, API change) we fall back to XOR-obfuscation with a
per-install key kept at <data_dir>/vault.key so the caller never crashes.

Blobs are prefixed to record the scheme: "d1:" (DPAPI) vs "x1:" (XOR).
"""

from __future__ import annotations

import base64
import ctypes
import os
import secrets
from pathlib import Path

from .config import settings


class DPAPIError(Exception):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]


def _crypt_protect(data: bytes) -> bytes | None:
    """Return DPAPI-protected bytes, or None on any failure."""
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return None
    try:
        buf = ctypes.create_string_buffer(data)
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
        blob_out = _DATA_BLOB()
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return None
        try:
            n = int(blob_out.cbData)
            ptr = ctypes.cast(blob_out.pbData, ctypes.POINTER(ctypes.c_ubyte))
            return bytes(ptr[i] for i in range(n))
        finally:
            kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))
    except Exception:
        return None


def _crypt_unprotect(data: bytes) -> bytes | None:
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return None
    try:
        buf = ctypes.create_string_buffer(data)
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
        blob_out = _DATA_BLOB()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return None
        try:
            n = int(blob_out.cbData)
            ptr = ctypes.cast(blob_out.pbData, ctypes.POINTER(ctypes.c_ubyte))
            return bytes(ptr[i] for i in range(n))
        finally:
            kernel32.LocalFree(ctypes.c_void_p(blob_out.pbData))
    except Exception:
        return None


def _vault_key() -> bytes:
    """Per-install 32-byte XOR key, created once at <data_dir>/vault.key."""
    path = settings.data_dir() / "vault.key"
    if path.exists():
        try:
            return base64.b64decode(path.read_text("utf-8").strip())
        except Exception:
            pass
    key = secrets.token_bytes(32)
    path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
    return key


def _xor(data: bytes, key: bytes) -> bytes:
    n = len(key)
    return bytes(b ^ key[i % n] for i, b in enumerate(data))


def protect(data: bytes) -> str:
    """Protect `data`, returning a portable "d1:"/ "x1:" prefixed base64 blob."""
    dpapi = _crypt_protect(data)
    if dpapi is not None:
        return "d1:" + base64.b64encode(dpapi).decode("ascii")
    return "x1:" + base64.b64encode(_xor(data, _vault_key())).decode("ascii")


def unprotect(b64: str) -> bytes:
    """Reverse protect(). Raises DPAPIError for unknown schemes / bad input."""
    if not isinstance(b64, str) or not b64:
        raise DPAPIError("Chuỗi bảo mật rỗng")
    scheme, _, payload = b64.partition(":")
    if scheme == "d1":
        out = _crypt_unprotect(base64.b64decode(payload))
        if out is None:
            raise DPAPIError("Không giải mã được (DPAPI) — liên kết lại Google")
        return out
    if scheme == "x1":
        return _xor(base64.b64decode(payload), _vault_key())
    raise DPAPIError("Sai định dạng chuỗi bảo mật")
