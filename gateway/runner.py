import random
import time

from .client import GatewayAPIClient, GatewayAPIError
from .biometrics import BiometricCacheError, synchronize_biometric_profiles
from .rtsp import RTSPConnectionError, RTSPReader, UnsupportedCodecError


def reconnect_delay(attempt: int, *, maximum: float = 30.0, jitter=0.2) -> float:
    base = min(maximum, 2 ** max(0, attempt - 1))
    return min(maximum, base + random.uniform(0, base * jitter))


def run_gateway(
    credentials,
    *,
    once=False,
    sleep=time.sleep,
    output=print,
    reader_factory=RTSPReader,
    biometric_sync=synchronize_biometric_profiles,
):
    api = GatewayAPIClient(credentials.server_url)
    attempt = 0
    while True:
        reader = None
        try:
            token = api.token(credentials)
            state = api.state(token)
            try:
                biometric_sync(api, token)
            except (BiometricCacheError, GatewayAPIError) as exc:
                output(
                    "Profils biométriques indisponibles ; comparaison faciale désactivée "
                    f"({exc})."
                )
            if not state.get("monitoring_active"):
                api.heartbeat(token, monitoring_active=False,
                              schedule_version=state.get("schedule", {}).get("version"))
                if once:
                    raise GatewayAPIError("Activez la surveillance de cette caméra avant le test.")
                output("Surveillance désactivée ; nouveau contrôle dans 10 s.")
                sleep(10)
                continue
            source = api.source(token)
            safe_endpoint = source.get("endpoint", "caméra RTSP")
            reader = reader_factory(source)
            reader.open()
            _, info = reader.read(require_h264=True)
            api.heartbeat(token, monitoring_active=True,
                          schedule_version=state.get("schedule", {}).get("version"))
            output(
                f"Flux RTSP H.264 reçu : {safe_endpoint} — "
                f"{info.width}x{info.height}, codec {info.codec}."
            )
            if once:
                return 0
            attempt = 0
            last_heartbeat = time.monotonic()
            while True:
                reader.read(require_h264=True)
                if time.monotonic() - last_heartbeat >= 30:
                    state = api.state(token)
                    if not state.get("monitoring_active"):
                        api.heartbeat(token, monitoring_active=False,
                                      schedule_version=state.get("schedule", {}).get("version"))
                        output("Surveillance désactivée par le serveur.")
                        break
                    api.heartbeat(token, monitoring_active=True,
                                  schedule_version=state.get("schedule", {}).get("version"))
                    last_heartbeat = time.monotonic()
        except KeyboardInterrupt:
            output("Passerelle arrêtée.")
            return 0
        except UnsupportedCodecError:
            raise
        except (GatewayAPIError, RTSPConnectionError) as exc:
            if once:
                raise
            attempt += 1
            delay = reconnect_delay(attempt)
            output(f"Flux indisponible ({exc}). Reconnexion dans {delay:.1f} s.")
            sleep(delay)
        finally:
            if reader is not None:
                reader.close()
