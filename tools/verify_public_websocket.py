"""Exercise the deployed alert socket with a disposable, unprivileged session."""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import ssl
import sys
import uuid
from importlib import import_module
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402


async def verify(hostname, session_key):
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            hostname, 443, ssl=ssl.create_default_context(), server_hostname=hostname
        ),
        timeout=15,
    )
    try:
        websocket_key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET /ws/alerts/ HTTP/1.1\r\n"
            f"Host: {hostname}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {websocket_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: https://{hostname}\r\n"
            f"Cookie: {settings.SESSION_COOKIE_NAME}={session_key}\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        headers = (await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)).decode(
            "latin-1"
        )
        if not headers.startswith("HTTP/1.1 101 "):
            raise RuntimeError(f"WebSocket handshake: {headers.splitlines()[0]}")
        expected_accept = base64.b64encode(
            hashlib.sha1(
                (websocket_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if f"sec-websocket-accept: {expected_accept.lower()}" not in headers.lower():
            raise RuntimeError("Invalid WebSocket accept header")

        first = await asyncio.wait_for(reader.readexactly(2), 15)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await reader.readexactly(8), "big")
        if opcode != 1 or length > 4096:
            raise RuntimeError(f"Unexpected WebSocket frame opcode={opcode}")
        message = json.loads((await reader.readexactly(length)).decode("utf-8"))
        if message != {"type": "connection.ready", "house_count": 0}:
            raise RuntimeError(f"Unexpected ready message: {message}")
        print("Authenticated public WebSocket: connection.ready, house_count=0")
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    hostname = sys.argv[1] if len(sys.argv) > 1 else "sentinelle.smartxcongo.com"
    username = f"ops-ws-{uuid.uuid4().hex[:16]}"
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@example.invalid", password=secrets.token_urlsafe(32)
    )
    session = import_module(settings.SESSION_ENGINE).SessionStore()
    try:
        session["_auth_user_id"] = str(user.pk)
        session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session["_auth_user_hash"] = user.get_session_auth_hash()
        session.save()
        asyncio.run(verify(hostname, session.session_key))
    finally:
        if session.session_key:
            session.delete()
        user.delete()


if __name__ == "__main__":
    main()
