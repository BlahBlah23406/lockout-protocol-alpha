"""DPAPI-backed secret storage — the Windows analogue of `Models/Keychain.swift`.

The macOS app keeps the Ollama API keys, the ntfy topic and the passcode hash in the login
Keychain. Windows has no Keychain; the equivalent user-scoped secret protection is DPAPI
(`CryptProtectData`), which encrypts with a key derived from the logged-in user's credentials. The
ciphertext is stored in one file next to the prefs; another user account on the same PC cannot
decrypt it.
"""

import ctypes
import json
import threading
from ctypes import wintypes

from ..paths import BUNDLE_ID, SECRETS_FILE

_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DataBlob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    _kernel32.LocalFree(blob.pbData)
    return out


# Entropy binds the ciphertext to this app, so another program running as the same user can't
# trivially decrypt Guardian's secrets by pointing DPAPI at the file.
_ENTROPY = BUNDLE_ID.encode("utf-8")


def _protect(plain: bytes) -> bytes:
    out = _DataBlob()
    ent = _blob(_ENTROPY)
    if not _crypt32.CryptProtectData(
        ctypes.byref(_blob(plain)), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)
    ):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    return _blob_bytes(out)


def _unprotect(cipher: bytes) -> bytes:
    out = _DataBlob()
    ent = _blob(_ENTROPY)
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(_blob(cipher)), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)
    ):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    return _blob_bytes(out)


class SecretStore:
    """Key/value secrets in one DPAPI-encrypted JSON blob. Mirrors Keychain.get/set/delete."""

    _lock = threading.RLock()
    _cache: dict | None = None

    @classmethod
    def _load(cls) -> dict:
        if cls._cache is not None:
            return cls._cache
        try:
            raw = SECRETS_FILE.read_bytes()
            cls._cache = json.loads(_unprotect(raw).decode("utf-8"))
        except Exception:
            # Missing, corrupt, or written by another user account: start clean rather than crash.
            cls._cache = {}
        return cls._cache

    @classmethod
    def _save(cls) -> None:
        data = json.dumps(cls._cache or {}).encode("utf-8")
        tmp = SECRETS_FILE.with_suffix(".tmp")
        tmp.write_bytes(_protect(data))
        tmp.replace(SECRETS_FILE)

    @classmethod
    def get(cls, key: str):
        with cls._lock:
            return cls._load().get(key)

    @classmethod
    def set(cls, key: str, value: str) -> None:
        with cls._lock:
            cls._load()[key] = value
            cls._save()

    @classmethod
    def delete(cls, key: str) -> None:
        with cls._lock:
            cls._load().pop(key, None)
            cls._save()
