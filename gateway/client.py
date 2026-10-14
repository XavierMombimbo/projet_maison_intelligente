import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class GatewayAPIError(RuntimeError):
    pass


class GatewayAuthorizationError(GatewayAPIError):
    pass


def validate_server_url(value: str) -> str:
    value = value.rstrip("/") + "/"
    parsed = urlsplit(value)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in local_hosts
    ):
        raise ValueError("Le serveur doit utiliser HTTPS, sauf pour localhost.")
    return value


def local_proxy_headers(server_url: str) -> dict[str, str]:
    parsed = urlsplit(server_url)
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return {"X-Forwarded-Proto": "https"}
    return {}


@dataclass(frozen=True)
class DeviceCredentials:
    server_url: str
    camera_id: str
    device_id: str
    device_secret: str
    event_signing_key: str


class GatewayAPIClient:
    def __init__(self, server_url: str, *, timeout: float = 10.0):
        self.server_url = validate_server_url(server_url)
        self.timeout = timeout

    def _request(self, path: str, *, method="GET", payload=None, token=None):
        headers = {"Accept": "application/json", **local_proxy_headers(self.server_url)}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            urljoin(self.server_url, path.lstrip("/")),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise GatewayAuthorizationError("Acces camera refuse par le serveur.") from None
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail")
            except (ValueError, UnicodeDecodeError):
                detail = None
            raise GatewayAPIError(detail or f"Réponse serveur HTTP {exc.code}.") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise GatewayAPIError("Serveur Sentinelle indisponible.") from exc

    def pair(self, code: str) -> DeviceCredentials:
        data = self._request("api/camera/appairer/", method="POST", payload={"code": code})
        return DeviceCredentials(
            server_url=self.server_url,
            camera_id=data["camera_id"],
            device_id=data["device_id"],
            device_secret=data["device_secret"],
            event_signing_key=data["event_signing_key"],
        )

    def token(self, credentials: DeviceCredentials) -> str:
        data = self._request(
            "api/camera/token/",
            method="POST",
            payload={
                "device_id": credentials.device_id,
                "device_secret": credentials.device_secret,
            },
        )
        if data.get("camera_id") != credentials.camera_id:
            raise GatewayAPIError("Le serveur a renvoyé une autre identité caméra.")
        return data["access_token"]

    def state(self, token: str) -> dict:
        return self._request("api/camera/me/etat/", token=token)

    def source(self, token: str) -> dict:
        return self._request("api/camera/me/source/", token=token)

    def heartbeat(self, token: str, *, monitoring_active: bool | None = None,
                  schedule_version: str | None = None) -> dict:
        payload = {}
        if monitoring_active is not None:
            payload["monitoring_active"] = monitoring_active
        if schedule_version is not None:
            payload["schedule_version"] = schedule_version
        return self._request(
            "api/camera/me/presence/", method="POST", payload=payload, token=token
        )

    def biometric_profiles(self, token: str) -> dict:
        return self._request("api/camera/me/profils-biometriques/", token=token)

    def acknowledge_biometric_purges(self, token: str, purges: list[dict]) -> dict:
        return self._request(
            "api/camera/me/profils-biometriques/purges/",
            method="POST",
            payload={"purges": purges},
            token=token,
        )
