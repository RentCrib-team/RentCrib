from django.urls import path

from propertylist_app.consumers import (
    RealtimeConsumer,
    WebSocketHealthConsumer,
)


websocket_urlpatterns = [
    path(
        "ws/health/",
        WebSocketHealthConsumer.as_asgi(),
        name="ws-health",
    ),
    path(
        "ws/realtime/",
        RealtimeConsumer.as_asgi(),
        name="ws-realtime",
    ),
]