import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .credentials import CredentialStoreError, protect_local_data, unprotect_local_data


class BiometricCacheError(RuntimeError):
    pass


class BiometricCacheExpired(BiometricCacheError):
    pass


def default_biometric_cache_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "SentinelleMaison" / "gateway.biometrics"


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Une date UTC avec fuseau est requise.")
    return parsed.astimezone(timezone.utc)


class BiometricCacheStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_biometric_cache_path()

    def apply_manifest(self, manifest: dict, *, now=None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        try:
            valid_until = _parse_utc(manifest["valid_until"])
            if valid_until <= now:
                raise BiometricCacheExpired("Le manifeste biométrique est déjà expiré.")
            revoked = {
                str(item["profile_id"]): int(item["version"])
                for item in manifest.get("revoked", [])
            }
            profiles = []
            for item in manifest.get("profiles", []):
                profile_id = str(item["profile_id"])
                if profile_id in revoked:
                    continue
                template = base64.b64decode(item["template"], validate=True)
                if not template:
                    raise ValueError("Gabarit vide.")
                profiles.append(
                    {
                        "profile_id": profile_id,
                        "version": int(item["version"]),
                        "format": str(item["format"]),
                        "template": base64.b64encode(template).decode("ascii"),
                    }
                )
            cached = {
                "generation": str(manifest["generation"]),
                "valid_until": valid_until.isoformat(),
                "profiles": profiles,
            }
        except BiometricCacheExpired:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise BiometricCacheError("Manifeste biométrique invalide.") from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        plaintext = json.dumps(cached, separators=(",", ":")).encode("utf-8")
        try:
            temporary.write_bytes(protect_local_data(plaintext))
            os.replace(temporary, self.path)
        except (CredentialStoreError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            raise BiometricCacheError("Impossible d’enregistrer le cache biométrique.") from exc
        return [
            {"profile_id": profile_id, "version": version}
            for profile_id, version in revoked.items()
        ]

    def profiles_for_comparison(self, *, now=None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        if not self.path.exists():
            return []
        try:
            cached = json.loads(unprotect_local_data(self.path.read_bytes()).decode("utf-8"))
            if _parse_utc(cached["valid_until"]) <= now:
                raise BiometricCacheExpired(
                    "Le cache biométrique a expiré ; comparaison désactivée jusqu’à la reconnexion."
                )
            return [
                {
                    **item,
                    "template": base64.b64decode(item["template"], validate=True),
                }
                for item in cached["profiles"]
            ]
        except BiometricCacheExpired:
            raise
        except (
            CredentialStoreError,
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            raise BiometricCacheError("Cache biométrique illisible.") from exc


def synchronize_biometric_profiles(api, token: str, *, store=None) -> dict:
    store = store or BiometricCacheStore()
    manifest = api.biometric_profiles(token)
    purges = store.apply_manifest(manifest)
    if purges:
        api.acknowledge_biometric_purges(token, purges)
    return manifest
