import pytest
from django.core.cache import caches
from django.test import override_settings
from rest_framework.settings import api_settings


API_REFRESH_URL = "/api/v1/auth/token/refresh/"


@pytest.mark.django_db
@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.ScopedRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "token-refresh": "2/minute",
        },
        "DEFAULT_RENDERER_CLASSES": (
            "propertylist_app.api.renderers.EnvelopeJSONRenderer",
        ),
        "EXCEPTION_HANDLER": (
            "propertylist_app.api.exceptions.custom_exception_handler"
        ),
    }
)
def test_token_refresh_endpoint_is_throttled(api_client):
    api_settings.reload()
    caches["default"].clear()

    payload = {"refresh": "not-a-real-token"}

    first = api_client.post(API_REFRESH_URL, payload, format="json")
    second = api_client.post(API_REFRESH_URL, payload, format="json")
    third = api_client.post(API_REFRESH_URL, payload, format="json")

    assert first.status_code == 400
    assert second.status_code == 400
    assert third.status_code == 429