from datetime import date, timedelta

import pytest
from django.core.cache import caches
from django.urls import reverse
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from propertylist_app.models import Room


@pytest.mark.django_db
def test_authenticated_user_room_creation_is_throttled(
    django_user_model,
    settings,
    monkeypatch,
):
    """
    The same authenticated user may create two rooms when the test rate is
    2/hour. The third rapid creation attempt must return HTTP 429.
    """

    monkeypatch.setitem(
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "room-create",
        "2/hour",
    )

    api_settings.reload()
    caches["default"].clear()

    user = django_user_model.objects.create_user(
        username="room_spammer",
        email="room_spammer@example.com",
        password="TestPass123!",
    )

    client = APIClient()
    client.force_authenticate(user=user)

    url = reverse("api:room-list")
    future_available_from = (date.today() + timedelta(days=30)).isoformat()

    def make_payload(index):
        return {
            "title": f"Throttle test room {index}",
            "description": (
                "This is a bright and spacious room with plenty of natural "
                "light, modern furnishings, fast broadband, secure entry, "
                "and excellent transport links to shops and the city centre."
            ),
            "location": "SW1A 1AA",
            "price_per_month": "800.00",
            "security_deposit": "800.00",
            "available_from": future_available_from,
            "availability_from_time": "10:00",
            "availability_to_time": "18:00",
            "view_available_days_mode": "everyday",
            "min_stay_months": 1,
            "max_stay_months": 6,
            "furnished": False,
            "bills_included": False,
            "property_type": "flat",
            "parking_available": False,
            "action": "next",
        }

    first_response = client.post(
        url,
        make_payload(1),
        format="json",
    )
    assert first_response.status_code == 201, first_response.data

    second_response = client.post(
        url,
        make_payload(2),
        format="json",
    )
    assert second_response.status_code == 201, second_response.data

    third_response = client.post(
        url,
        make_payload(3),
        format="json",
    )

    assert third_response.status_code == 429, third_response.data
    assert Room.objects.filter(property_owner=user).count() == 2