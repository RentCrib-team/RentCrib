"""
ASGI config for property project.

Supports:
- normal Django HTTP traffic
- RentCrib WebSocket traffic
"""

import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "property.settings",
)

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django_asgi_application = get_asgi_application()

from propertylist_app.routing import websocket_urlpatterns


application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": URLRouter(
            websocket_urlpatterns
        ),
    }
)