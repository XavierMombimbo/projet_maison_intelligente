import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit


class RTSPError(RuntimeError):
    pass


class RTSPConnectionError(RTSPError):
    pass


class UnsupportedCodecError(RTSPError):
    pass


def authenticated_rtsp_url(url: str, username: str = "", password: str = "") -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise RTSPConnectionError("Adresse RTSP invalide.")
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if username:
        userinfo = quote(username, safe="")
        if password:
            userinfo += ":" + quote(password, safe="")
        netloc = f"{userinfo}@{netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def fourcc_name(value: float) -> str:
    integer = int(value)
    return "".join(chr((integer >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00")


@dataclass(frozen=True)
class FrameInfo:
    width: int
    height: int
    codec: str


class RTSPReader:
    H264_CODECS = {"H264", "h264", "avc1", "AVC1", "X264", "x264"}

    def __init__(self, source: dict, *, open_timeout_ms=8000, read_timeout_ms=5000, cv2=None):
        self.source = source
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self._cv2 = cv2
        self.capture = None

    def _backend(self):
        if self._cv2 is None:
            os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
            try:
                import cv2
            except ImportError as exc:
                raise RTSPConnectionError(
                    "OpenCV absent. Installez requirements-gateway.txt."
                ) from exc
            self._cv2 = cv2
        if hasattr(self._cv2, "setLogLevel"):
            self._cv2.setLogLevel(0)
        return self._cv2

    def open(self):
        cv2 = self._backend()
        url = authenticated_rtsp_url(
            self.source["url"], self.source.get("username", ""), self.source.get("password", "")
        )
        params = [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            self.open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            self.read_timeout_ms,
        ]
        self.capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
        if not self.capture.isOpened():
            self.close()
            raise RTSPConnectionError("Connexion au flux RTSP impossible.")

    def read(self, *, require_h264=True):
        if self.capture is None:
            self.open()
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RTSPConnectionError("Aucune image RTSP reçue avant le délai maximal.")
        cv2 = self._backend()
        codec = fourcc_name(self.capture.get(cv2.CAP_PROP_FOURCC))
        if require_h264 and codec not in self.H264_CODECS:
            raise UnsupportedCodecError(
                f"Codec {codec or 'inconnu'} reçu ; le pilote exige H.264."
            )
        height, width = frame.shape[:2]
        return frame, FrameInfo(width=width, height=height, codec=codec or "inconnu")

    def close(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None

