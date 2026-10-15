import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

from .client import DeviceCredentials


class CredentialStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def default_credentials_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "SentinelleMaison" / "gateway.credentials"


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError(
            "Le stockage persistant exige Windows DPAPI. Utilisez les variables d’environnement sur cet OS."
        )
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "Sentinelle Maison", None, None, None, 0, ctypes.byref(output)
    ):
        raise CredentialStoreError("DPAPI n’a pas pu chiffrer les identifiants.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("Ce fichier d’identifiants nécessite Windows DPAPI.")
    source, source_buffer = _blob(data)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise CredentialStoreError("DPAPI n’a pas pu déchiffrer les identifiants.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def protect_local_data(data: bytes) -> bytes:
    return _protect(data)


def unprotect_local_data(data: bytes) -> bytes:
    return _unprotect(data)


def save_credentials(credentials: DeviceCredentials, path: Path | None = None) -> Path:
    path = path or default_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(credentials.__dict__, separators=(",", ":")).encode("utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_protect(payload))
    os.replace(temporary, path)
    return path


def load_credentials(path: Path | None = None) -> DeviceCredentials:
    path = path or default_credentials_path()
    if not path.exists():
        raise CredentialStoreError("Passerelle non appairée. Exécutez d’abord la commande pair.")
    try:
        data = json.loads(_unprotect(path.read_bytes()).decode("utf-8"))
        return DeviceCredentials(**data)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise CredentialStoreError("Fichier d’identifiants invalide.") from exc

