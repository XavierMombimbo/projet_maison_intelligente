"""Reject oversized capture bodies before Django can spool them to disk."""
import re

MAX_CAPTURE_BODY = 530 * 1024
CAPTURE_PATH = re.compile(r"/maisons/\d+/profils-biometriques/[0-9a-fA-F-]{36}/enroler/")


class FacialCaptureBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("method") != "POST" or not CAPTURE_PATH.fullmatch(scope.get("path", "")):
            return await self.app(scope, receive, send)
        async def reject():
            await send({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json"), (b"cache-control", b"no-store, private"),
            ]})
            await send({"type": "http.response.body", "body": b'{"detail":"Capture trop volumineuse. Reessayez avec la camera."}'})
        try:
            lengths = [int(value) for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
            if any(value < 0 or value > MAX_CAPTURE_BODY for value in lengths):
                return await reject()
        except ValueError:
            return await reject()
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_CAPTURE_BODY:
                return await reject()
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return await self.app(scope, replay, send)
