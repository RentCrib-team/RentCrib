import json

from channels.generic.websocket import AsyncWebsocketConsumer

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.core import signing

from propertylist_app.api.views.realtime import (
    REALTIME_TICKET_MAX_AGE_SECONDS,
    REALTIME_TICKET_SALT,
)



class WebSocketHealthConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.ready",
                    "ok": True,
                    "message": "RentCrib WebSocket connected",
                }
            )
        )

    async def receive(self, text_data=None, bytes_data=None):
        if text_data == "ping":
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "pong",
                        "ok": True,
                    }
                )
            )
            
            


class RealtimeConsumer(AsyncWebsocketConsumer):
    """
    Authenticated per-user RentCrib realtime connection.

    Authentication is performed with the short-lived signed ticket issued by:
        POST /api/v1/realtime/ticket/

    This does not use or modify the user's normal auth cookies or refresh token.
    """

    async def connect(self):
        ticket = self._get_ticket()

        if not ticket:
            await self.close(code=4401)
            return

        try:
            payload = signing.loads(
                ticket,
                salt=REALTIME_TICKET_SALT,
                max_age=REALTIME_TICKET_MAX_AGE_SECONDS,
            )
        except (
            signing.BadSignature,
            signing.SignatureExpired,
        ):
            await self.close(code=4401)
            return

        user_id = payload.get("user_id")

        if not user_id:
            await self.close(code=4401)
            return

        user = await self._get_active_user(user_id)

        if not user:
            await self.close(code=4401)
            return

        self.user_id = user.id
        self.user_group_name = f"user_{user.id}"

        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name,
        )

        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.ready",
                    "ok": True,
                    "user_id": user.id,
                }
            )
        )

    async def disconnect(self, close_code):
        group_name = getattr(
            self,
            "user_group_name",
            None,
        )

        if group_name:
            await self.channel_layer.group_discard(
                group_name,
                self.channel_name,
            )

    async def receive(self, text_data=None, bytes_data=None):
        if text_data == "ping":
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "pong",
                        "ok": True,
                    }
                )
            )
            
    
    async def realtime_event(self, event):
        """
        Deliver a backend realtime event to this authenticated user's socket.
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": event.get("event_type"),
                    "data": event.get("data", {}),
                }
            )
        )
    
    
            

    def _get_ticket(self):
        query_string = self.scope.get(
            "query_string",
            b"",
        ).decode("utf-8")

        from urllib.parse import parse_qs

        params = parse_qs(query_string)
        values = params.get("ticket") or []

        return values[0] if values else None

    @database_sync_to_async
    def _get_active_user(self, user_id):
        User = get_user_model()

        return (
            User.objects
            .filter(
                id=user_id,
                is_active=True,
            )
            .first()
        )            