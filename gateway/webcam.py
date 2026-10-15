import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import cv2
import numpy as np
import requests

from .client import GatewayAPIClient, GatewayAPIError, GatewayAuthorizationError, local_proxy_headers
from .event_queue import EncryptedEventQueue, EventQueueError
from .schedule import EncryptedScheduleCache, ScheduleError, evaluate_schedule
from .tracking import GeometricTracker
from .model_policy import MODEL_SHA256, ModelApprovalError, require_webcam_approval


MODEL_SIZE = 320
MODEL_VERSION = "320@18eac4f9d291"
DETECTION_PATH = "api/camera/me/detections/"
CLASSES = {"person": 0, "cat": 15, "dog": 16}
DEFAULT_THRESHOLDS = {"person": 0.45, "cat": 0.50, "dog": 0.50}


class WebcamError(RuntimeError):
    pass


class WebcamConfigurationError(WebcamError):
    pass


class LocalFaceClassifier:
    """Attach only a non-identifying local comparison state to a person event."""

    def __init__(self, embedder, profiles, *, threshold=0.45):
        self.embedder = embedder
        self.profiles = profiles
        self.threshold = float(threshold)

    def classify(self, frame) -> str:
        from .biometrics import BiometricCacheError
        from .facial import FaceQualityError, FaceRecognitionError, compare_embedding

        try:
            query = self.embedder.embedding_from_bgr(frame)
            result = compare_embedding(query, self.profiles(), threshold=self.threshold)
        except (BiometricCacheError, FaceQualityError, FaceRecognitionError):
            return "unavailable"
        return {"matched": "recognized", "unknown": "unknown"}.get(result.state, "unavailable")


def create_face_classifier(api, token, model_root, *, threshold=0.45, cache_store=None):
    """Prepare voluntary profile comparison without storing a frame or identity."""
    from .biometrics import BiometricCacheStore, synchronize_biometric_profiles
    from .facial import ArcFaceEmbedder
    from .model_policy import require_arcface_academic_approval

    root = Path(model_root)
    require_arcface_academic_approval(root)
    os.environ.setdefault("INSIGHTFACE_HOME", str(root))
    store = cache_store or BiometricCacheStore()
    synchronize_biometric_profiles(api, token, store=store)
    return LocalFaceClassifier(
        ArcFaceEmbedder.from_model_root(root), store.profiles_for_comparison,
        threshold=threshold,
    )


def check_model_mode(allow_development_model):
    if not allow_development_model:
        try:
            require_webcam_approval()
        except ModelApprovalError as exc:
            raise WebcamConfigurationError(str(exc)) from exc


class WebcamReader:
    def __init__(self, index=0, *, cv=cv2):
        self.index = index
        self.cv = cv
        self.capture = None

    def open(self):
        backend = self.cv.CAP_DSHOW if os.name == "nt" else self.cv.CAP_ANY
        self.capture = self.cv.VideoCapture(self.index, backend)
        if not self.capture.isOpened():
            self.close()
            raise WebcamError("Webcam indisponible ou deja utilisee par une autre application.")
        self.capture.set(self.cv.CAP_PROP_BUFFERSIZE, 1)

    def read(self):
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise WebcamError("Lecture webcam interrompue.")
        return frame

    def close(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None


class YoloWebcamDetector:
    def __init__(self, model_path=None, *, cv=cv2):
        self.cv = cv
        self.path = Path(model_path or Path(__file__).resolve().parents[1] / "static/vendor/yolo/yolo11n.onnx")
        if not self.path.is_file() or hashlib.sha256(self.path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise WebcamConfigurationError("Modele YOLO local absent ou empreinte invalide.")
        self.net = cv.dnn.readNetFromONNX(str(self.path))

    def detect(self, frame, thresholds=None):
        height, width = frame.shape[:2]
        scale = min(MODEL_SIZE / width, MODEL_SIZE / height)
        new_width = round(width * scale)
        new_height = round(height * scale)
        left = (MODEL_SIZE - new_width) // 2
        top = (MODEL_SIZE - new_height) // 2
        canvas = np.full((MODEL_SIZE, MODEL_SIZE, 3), 128, dtype=np.uint8)
        canvas[top:top + new_height, left:left + new_width] = self.cv.resize(frame, (new_width, new_height))
        blob = self.cv.dnn.blobFromImage(canvas, scalefactor=1 / 255, size=(MODEL_SIZE, MODEL_SIZE), swapRB=True)
        self.net.setInput(blob)
        output = self.net.forward()[0]
        if output.shape[0] != 84:
            output = output.T
        settings = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        detections = []
        for label, class_index in CLASSES.items():
            boxes = []
            scores = []
            for column in output.T:
                confidence = float(column[4 + class_index])
                if confidence < settings[label]:
                    continue
                cx, cy, box_width, box_height = map(float, column[:4])
                x = max(0.0, (cx - box_width / 2 - left) / scale)
                y = max(0.0, (cy - box_height / 2 - top) / scale)
                w = min(box_width / scale, width - x)
                h = min(box_height / scale, height - y)
                if w <= 0 or h <= 0:
                    continue
                boxes.append([int(x), int(y), int(w), int(h)])
                scores.append(confidence)
            indexes = self.cv.dnn.NMSBoxes(boxes, scores, settings[label], 0.45)
            for index in np.array(indexes).reshape(-1):
                x, y, w, h = boxes[int(index)]
                detections.append({
                    "label": label, "confidence": scores[int(index)],
                    "bbox": [x / width, y / height, w / width, h / height],
                    "track_id": f"webcam-{label}",
                })
        return detections


class PresenceRule:
    def __init__(self):
        self.since = {}

    def evaluate(self, detections, analysis, now):
        zone = analysis.get("zone") or {"x": 0, "y": 0, "width": 1, "height": 1}
        required = float(analysis.get("presence_seconds") or 1)
        inside = {}
        for item in detections:
            x, y, width, height = item["bbox"]
            center_x, center_y = x + width / 2, y + height / 2
            if zone["x"] <= center_x <= zone["x"] + zone["width"] and zone["y"] <= center_y <= zone["y"] + zone["height"]:
                track_id = item["track_id"]
                inside[track_id] = item
        self.since = {track_id: self.since.get(track_id, now) for track_id in inside}
        for track_id, item in inside.items():
            duration = now - self.since[track_id]
            if duration >= required:
                context = {"id": "presence-zone", "version": 1, "type": "presence_prolonged",
                           "duration_seconds": duration, "zone": zone,
                           "track_ids": [item["track_id"]]}
                return item, context
        return None


def _sign_event(credentials, *, path, timestamp, nonce, event_id, observed_at,
                model_name, model_version, objects, capture, rule_context, contract_version=2):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from homes.request_signing import sign_event_payload

    return sign_event_payload(
        credentials.event_signing_key, contract_version=contract_version, method="POST", path=path,
        camera_id=credentials.camera_id, timestamp=timestamp, nonce=nonce,
        event_id=event_id, observed_at=observed_at, model_name=model_name,
        model_version=model_version, objects=objects, simulated=False,
        capture_type="image/jpeg", capture_digest=hashlib.sha256(capture).hexdigest(),
        rule_context=rule_context,
    )


def make_detection_event(frame, detection, rule_context):
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
    if not ok:
        raise WebcamError("Encodage de la capture impossible.")
    return {
        "capture": encoded.tobytes(),
        "detection": detection,
        "rule_context": rule_context,
        "event_id": str(uuid.uuid4()),
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "model_name": "yolo11n", "model_version": MODEL_VERSION,
        "contract_version": 3 if detection.get("face_status") else 2,
    }


def send_detection(api, credentials, token, frame, detection, rule_context, *, session=requests, event=None):
    event = event or make_detection_event(frame, detection, rule_context)
    capture = event["capture"]
    event_id = uuid.UUID(event["event_id"])
    observed_at = event["observed_at"]
    nonce = uuid.uuid4()
    timestamp = int(time.time())
    url = urljoin(api.server_url, DETECTION_PATH)
    signature = _sign_event(
        credentials, path=urlsplit(url).path, timestamp=timestamp, nonce=nonce,
        event_id=event_id, observed_at=observed_at,
        model_name=event["model_name"], model_version=event["model_version"],
        objects=[event["detection"]], capture=capture,
        rule_context=event["rule_context"], contract_version=event.get("contract_version", 2),
    )
    try:
        response = session.post(
            url,
            headers={"Authorization": f"Bearer {token}", **local_proxy_headers(api.server_url),
                     "X-Camera-Timestamp": str(timestamp),
                     "X-Camera-Nonce": str(nonce), "X-Camera-Signature": signature},
            data={"contract_version": str(event.get("contract_version", 2)), "event_id": str(event_id),
                  "observed_at": observed_at, "model_name": event["model_name"],
                  "model_version": event["model_version"], "objects": json.dumps([event["detection"]]),
                  "rule_context": json.dumps(event["rule_context"])},
            files={"capture": ("detection.jpg", capture, "image/jpeg")}, timeout=10,
        )
    except requests.RequestException as exc:
        raise GatewayAPIError("Transmission de detection indisponible.") from exc
    if not response.ok:
        if response.status_code in (401, 403):
            raise GatewayAuthorizationError("Acces camera refuse pour la detection.")
        raise GatewayAPIError(f"Detection refusee par le serveur (HTTP {response.status_code}).")
    return response.json()


def deliver_oldest(queue, api, credentials, token):
    pending = queue.oldest()
    if pending is None:
        return False
    path, event = pending
    send_detection(api, credentials, token, None, event["detection"], event["rule_context"], event=event)
    queue.acknowledge(path)
    return True


def run_webcam(credentials, *, index=0, once=False, allow_development_model=False,
               reader_factory=WebcamReader, detector_factory=YoloWebcamDetector,
               sleep=time.sleep, clock=time.monotonic, output=print,
               queue_factory=EncryptedEventQueue, schedule_cache_factory=EncryptedScheduleCache,
               face_model_root=None, face_threshold=0.45, face_classifier_factory=create_face_classifier):
    check_model_mode(allow_development_model)
    api = GatewayAPIClient(credentials.server_url)
    detector = detector_factory()
    reader = reader_factory(index)
    queue = None if once else queue_factory(credentials.camera_id)
    schedule_cache = None if once else schedule_cache_factory(
        credentials.camera_id, credentials.event_signing_key,
    )
    rule = PresenceRule()
    tracker = GeometricTracker()
    last_heartbeat = last_state = last_token = last_sent = 0.0
    next_connection_attempt = 0.0
    token = None
    state = None
    reported_decision = None
    face_classifier = None
    try:
        reader.open()
        while True:
            now = clock()
            if (token is None and now >= next_connection_attempt) or (
                token is not None and now - last_token >= 240
            ):
                try:
                    token = api.token(credentials)
                    last_token = now
                    last_state = 0
                    if face_model_root is not None:
                        try:
                            face_classifier = face_classifier_factory(
                                api, token, face_model_root, threshold=face_threshold,
                            )
                        except (GatewayAPIError, WebcamError, ValueError, OSError) as exc:
                            face_classifier = None
                            output(f"Comparaison faciale locale indisponible ({exc}).")
                except GatewayAuthorizationError:
                    raise
                except GatewayAPIError:
                    token = None
                    next_connection_attempt = now + 10
                    state = None
                    if schedule_cache is None or not schedule_cache.path.is_file():
                        raise
            if token is not None and (last_state == 0 or now - last_state >= 10):
                try:
                    state = api.state(token)
                    if schedule_cache is not None and "schedule" in state:
                        schedule_cache.save(state["schedule"])
                    last_state = now
                except GatewayAuthorizationError:
                    raise
                except GatewayAPIError:
                    token = None
                    state = None
                    next_connection_attempt = now + 10
                    if schedule_cache is None or not schedule_cache.path.is_file():
                        raise
            if state is None:
                if schedule_cache is None:
                    raise GatewayAPIError("Etat de surveillance indisponible.")
                payload = schedule_cache.load()["payload"]
                active, source = evaluate_schedule(payload)
                state = {"monitoring_active": active, "monitoring_source": source,
                         "analysis": payload["analysis"]}
            elif token is None:
                payload = schedule_cache.load()["payload"]
                active, source = evaluate_schedule(payload)
                state = {"monitoring_active": active, "monitoring_source": source,
                         "analysis": payload["analysis"]}
            if state.get("analysis", {}).get("line"):
                raise WebcamConfigurationError("La regle de ligne n'est pas prise en charge par la webcam autonome.")
            decision = (bool(state.get("monitoring_active")), token is None)
            if not once and decision != reported_decision:
                activity = "active" if decision[0] else "arretee"
                origin = "planning local hors ligne" if decision[1] else "serveur"
                output(f"Surveillance {activity} ({origin}).")
                reported_decision = decision
            if not state.get("monitoring_active"):
                rule.since.clear()
                tracker.reset()
                if token is not None and (now - last_heartbeat >= 30 or last_heartbeat == 0):
                    api._request("api/camera/me/presence/", method="POST",
                                 payload={"monitoring_active": False, "analysis_state": "inactive",
                                          **({"schedule_version": state["schedule"]["version"]}
                                             if state.get("schedule") else {})}, token=token)
                    last_heartbeat = now
                if once:
                    raise WebcamError("Activer la surveillance avant le test webcam.")
                sleep(2)
                continue
            if queue is not None and token is not None:
                deliver_oldest(queue, api, credentials, token)
            frame = reader.read()
            try:
                detections = detector.detect(frame, state.get("analysis", {}).get("alert_thresholds"))
            except Exception as exc:
                if token is not None:
                    api._request("api/camera/me/presence/", method="POST",
                                 payload={"monitoring_active": True, "analysis_state": "failed",
                                          **({"schedule_version": state["schedule"]["version"]}
                                             if state.get("schedule") else {})}, token=token)
                raise WebcamError("Inference du modele indisponible.") from exc
            now = clock()
            detections = tracker.update(detections, now)
            match = rule.evaluate(detections, state.get("analysis", {}), now)
            if token is not None and (now - last_heartbeat >= 30 or last_heartbeat == 0):
                api._request("api/camera/me/presence/", method="POST",
                             payload={"monitoring_active": True, "analysis_state": "running",
                                      **({"schedule_version": state["schedule"]["version"]}
                                         if state.get("schedule") else {})}, token=token)
                last_heartbeat = now
            if once:
                output(f"Webcam lue et analysee : {len(detections)} objet(s) retenu(s).")
                return 0
            if match and (not last_sent or now - last_sent >= 30):
                detection, rule_context = match
                detection = dict(detection)
                if detection.get("label") == "person" and face_classifier is not None:
                    detection["face_status"] = face_classifier.classify(frame)
                event = make_detection_event(frame, detection, rule_context)
                queue.enqueue(**event)
                last_sent = now
                if token is not None:
                    deliver_oldest(queue, api, credentials, token)
            sleep(0.5)
    except GatewayAuthorizationError as exc:
        if schedule_cache is not None:
            schedule_cache.revoke()
        raise WebcamConfigurationError("Appairage ou acces camera refuse ou revoque.") from exc
    except KeyboardInterrupt:
        output("Webcam autonome arretee.")
        return 0
    finally:
        reader.close()


def watch_webcam(credentials, *, once=False, sleep=time.sleep, output=print, **options):
    check_model_mode(options.get("allow_development_model"))
    attempts = 0
    while True:
        try:
            return run_webcam(credentials, once=once, sleep=sleep, output=output, **options)
        except WebcamConfigurationError:
            raise
        except (EventQueueError, ScheduleError) as exc:
            raise WebcamConfigurationError(str(exc)) from exc
        except (GatewayAPIError, WebcamError):
            if once:
                raise
            attempts += 1
            delay = min(30, 2 ** min(attempts - 1, 5))
            output(f"Webcam ou serveur indisponible ; nouvel essai dans {delay} s.")
            try:
                sleep(delay)
            except KeyboardInterrupt:
                output("Webcam autonome arretee.")
                return 0
