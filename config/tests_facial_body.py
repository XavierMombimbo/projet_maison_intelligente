from django.test import SimpleTestCase
from .facial_body import FacialCaptureBodyLimit, MAX_CAPTURE_BODY


class CaptureBodyLimitTests(SimpleTestCase):
    path = "/maisons/1/profils-biometriques/00000000-0000-0000-0000-000000000001/enroler/"

    async def run_capture(self, *, chunks, headers=(), path=None):
        messages = [{"type": "http.request", "body": value, "more_body": i < len(chunks)-1}
                    for i, value in enumerate(chunks)]
        received, sent = [], []
        async def receive():
            return messages.pop(0)
        async def send(message):
            sent.append(message)
        async def inner(scope, receiver, sender):
            received.append(await receiver())
        await FacialCaptureBodyLimit(inner)({"method": "POST", "path": path or self.path,
                                            "headers": headers}, receive, send)
        return received, sent, messages

    async def test_header_rejection_never_calls_django_or_reads_image(self):
        received, sent, unread = await self.run_capture(chunks=[b"capture"],
            headers=[(b"content-length", str(MAX_CAPTURE_BODY+1).encode())])
        self.assertFalse(received)
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(len(unread), 1)

    async def test_chunked_oversize_is_stopped_before_django(self):
        received, sent, _ = await self.run_capture(chunks=[b"x" * MAX_CAPTURE_BODY, b"x"])
        self.assertFalse(received)
        self.assertEqual(sent[0]["status"], 413)

    async def test_small_capture_is_replayed_without_modification(self):
        received, sent, _ = await self.run_capture(chunks=[b'{"image":', b'"fixture"}'])
        self.assertEqual(received[0]["body"], b'{"image":"fixture"}')
        self.assertFalse(sent)

    async def test_other_routes_are_unchanged(self):
        received, sent, _ = await self.run_capture(chunks=[b"first", b"second"], path="/health/")
        self.assertEqual(received[0]["body"], b"first")
        self.assertTrue(received[0]["more_body"])
