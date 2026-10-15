"""Verify that the configured Channels layer delivers across processes."""

import asyncio
import multiprocessing
import os
import sys
import uuid
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def layer():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from channels.layers import get_channel_layer
    from django.conf import settings

    backend = settings.CHANNEL_LAYERS.get("default", {}).get("BACKEND")
    if backend != "channels_redis.core.RedisChannelLayer":
        raise RuntimeError("A RedisChannelLayer is required for this test")
    return get_channel_layer()


def receive(ready, result, group):
    async def run():
        channel_layer = layer()
        channel = await channel_layer.new_channel()
        await channel_layer.group_add(group, channel)
        ready.set()
        try:
            message = await asyncio.wait_for(channel_layer.receive(channel), timeout=15)
            result.put(message.get("value"))
        finally:
            await channel_layer.group_discard(group, channel)

    try:
        asyncio.run(run())
    except Exception as exc:
        result.put(f"error:{type(exc).__name__}")
        ready.set()


def main():
    group = f"sentinelle-transport-test-{uuid.uuid4().hex}"
    token = uuid.uuid4().hex
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    result = context.Queue()
    worker = context.Process(target=receive, args=(ready, result, group))
    worker.start()
    try:
        if not ready.wait(timeout=15):
            raise RuntimeError("Receiver did not become ready")
        from asgiref.sync import async_to_sync

        async_to_sync(layer().group_send)(group, {"type": "transport.test", "value": token})
        received = result.get(timeout=20)
        if received != token:
            raise RuntimeError("Cross-process message was not delivered")
        print("Redis Channels cross-process delivery: OK")
    finally:
        worker.join(timeout=5)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)
        result.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Redis Channels cross-process delivery: FAILED ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1)
