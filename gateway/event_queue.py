import base64
import binascii
import json
import os
import time
import uuid
from pathlib import Path

from .credentials import CredentialStoreError, protect_local_data, unprotect_local_data


MAX_PENDING_EVENTS = 20
MAX_CAPTURE_BYTES = 2 * 1024 * 1024


def default_queue_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "SentinelleMaison" / "webcam-events"


class EventQueueError(RuntimeError):
    pass


class EncryptedEventQueue:
    def __init__(self, camera_id, path=None):
        self.path = Path(path or default_queue_path()) / str(uuid.UUID(str(camera_id)))
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _files(self):
        return sorted(self.path.glob("*.event"))

    def enqueue(self, *, capture, detection, rule_context, event_id, observed_at,
                model_name, model_version, contract_version=2):
        if len(self._files()) >= MAX_PENDING_EVENTS:
            raise EventQueueError("File locale pleine ; aucun evenement supplementaire n'est capture.")
        if not capture or len(capture) > MAX_CAPTURE_BYTES:
            raise EventQueueError("Capture locale absente ou trop volumineuse.")
        payload = json.dumps({
            "event_id": str(event_id), "observed_at": observed_at,
            "model_name": model_name, "model_version": model_version,
            "contract_version": int(contract_version),
            "capture": base64.b64encode(capture).decode("ascii"),
            "detection": detection, "rule_context": rule_context,
        }, separators=(",", ":")).encode("utf-8")
        try:
            encrypted = protect_local_data(payload)
        except CredentialStoreError as exc:
            raise EventQueueError("Chiffrement local indisponible.") from exc
        destination = self.path / f"{time.time_ns():020d}-{uuid.uuid4().hex}.event"
        temporary = destination.with_suffix(".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            raise EventQueueError("Ecriture de la file locale impossible.") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def oldest(self):
        files = self._files()
        if not files:
            return None
        path = files[0]
        try:
            data = json.loads(unprotect_local_data(path.read_bytes()))
            data["capture"] = base64.b64decode(data["capture"], validate=True)
            return path, data
        except (CredentialStoreError, ValueError, KeyError, TypeError, binascii.Error, OSError) as exc:
            raise EventQueueError("Evenement local illisible ; intervention requise.") from exc

    def acknowledge(self, path):
        try:
            path.unlink()
        except OSError as exc:
            raise EventQueueError("Suppression de l'evenement confirme impossible.") from exc
