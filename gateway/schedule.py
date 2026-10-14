import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .credentials import CredentialStoreError, protect_local_data, unprotect_local_data


class ScheduleError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign_schedule(payload, key):
    version = hashlib.sha256(_canonical(payload)).hexdigest()
    envelope = {"version": version, "payload": payload}
    return {**envelope, "signature": hmac.new(
        key.encode("utf-8"), _canonical(envelope), hashlib.sha256,
    ).hexdigest()}


def verify_schedule(manifest, *, camera_id, key):
    try:
        payload = manifest["payload"]
        version = manifest["version"]
        signature = manifest["signature"]
        if str(uuid.UUID(str(payload["camera_id"]))) != str(uuid.UUID(str(camera_id))):
            raise ValueError("wrong camera")
        if not hmac.compare_digest(version, hashlib.sha256(_canonical(payload)).hexdigest()):
            raise ValueError("wrong version")
        expected = hmac.new(
            key.encode("utf-8"), _canonical({"version": version, "payload": payload}),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("wrong signature")
        return payload
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ScheduleError("Planning local invalide ou signe pour une autre camera.") from exc


def default_schedule_path(camera_id):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "SentinelleMaison" / "schedules" / f"{uuid.UUID(str(camera_id))}.schedule"


class EncryptedScheduleCache:
    def __init__(self, camera_id, signing_key, path=None):
        self.camera_id = camera_id
        self.signing_key = signing_key
        self.path = Path(path) if path is not None else default_schedule_path(camera_id)

    def save(self, manifest):
        verify_schedule(manifest, camera_id=self.camera_id, key=self.signing_key)
        try:
            encrypted = protect_local_data(_canonical(manifest))
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_suffix(".tmp")
            try:
                with temporary.open("wb") as stream:
                    stream.write(encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except (CredentialStoreError, OSError) as exc:
            raise ScheduleError("Sauvegarde chiffree du planning impossible.") from exc

    def load(self):
        try:
            manifest = json.loads(unprotect_local_data(self.path.read_bytes()))
            verify_schedule(manifest, camera_id=self.camera_id, key=self.signing_key)
            return manifest
        except (CredentialStoreError, OSError, ValueError, TypeError) as exc:
            raise ScheduleError("Planning local absent ou illisible.") from exc

    def revoke(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise ScheduleError("Revocation du planning local impossible.") from exc


def evaluate_schedule(payload, *, at=None):
    if not payload["camera_enabled"]:
        return False, "camera"
    if not (payload["windows"] or payload["exceptions"] or payload["override"]):
        return True, "camera"
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ScheduleError("Heure locale non horodatee.")

    override = payload["override"]
    if override and datetime.fromisoformat(override["expires_at"]) > at:
        return override["active"], "manual"

    exceptions = [item for item in payload["exceptions"] if (
        datetime.fromisoformat(item["starts_at"]) <= at
        < datetime.fromisoformat(item["ends_at"])
    )]
    if exceptions:
        item = max(exceptions, key=lambda value: (
            value["priority"], value["created_at"], value["id"],
        ))
        return item["active"], "exception"

    try:
        local = at.astimezone(ZoneInfo(payload["timezone"]))
    except ZoneInfoNotFoundError:
        local = at.astimezone(timezone.utc)
    weekday = local.weekday()
    local_time = local.time().replace(tzinfo=None)
    for window in payload["windows"]:
        if not window["active"]:
            continue
        start = datetime.strptime(window["starts_at"], "%H:%M:%S").time()
        end = datetime.strptime(window["ends_at"], "%H:%M:%S").time()
        if start < end:
            matches = window["day"] == weekday and start <= local_time < end
        else:
            matches = (
                (window["day"] == weekday and local_time >= start)
                or ((window["day"] + 1) % 7 == weekday and local_time < end)
            )
        if matches:
            return True, "schedule"
    return False, "default"
