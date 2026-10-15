from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Camera, Evenement
from .realtime import alert_group_name


class AlertConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.user = user
        house_ids = await self._visible_house_ids(user)
        self.alert_groups = [alert_group_name(house_id) for house_id in house_ids]
        for group_name in self.alert_groups:
            await self.channel_layer.group_add(group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {"type": "connection.ready", "house_count": len(self.alert_groups)}
        )

    async def disconnect(self, close_code):
        for group_name in getattr(self, "alert_groups", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def alert_created(self, event):
        await self._send_authorized_event(event, "alert.created")

    async def alert_updated(self, event):
        await self._send_authorized_event(event, "alert.updated")

    async def _send_authorized_event(self, event, message_type):
        payload = event.get("payload", {})
        event_id = payload.get("event_id")
        if event_id and await self._can_view_event(self.user, event_id):
            await self.send_json({"type": message_type, **payload})

    @database_sync_to_async
    def _visible_house_ids(self, user):
        return list(
            Camera.objects.visible_to(user)
            .order_by()
            .values_list("maison_id", flat=True)
            .distinct()
        )

    @database_sync_to_async
    def _can_view_event(self, user, event_id):
        return Evenement.objects.visible_to(user).filter(pk=event_id).exists()
