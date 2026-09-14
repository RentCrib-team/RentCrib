from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.rooms import RoomAV
from propertylist_app.models import Room, RoomCategorie


def _run_room_list_request():
    factory = APIRequestFactory()
    request = factory.get("/api/v1/rooms/?limit=20")
    view = RoomAV.as_view()

    with CaptureQueriesContext(connection) as captured:
        response = view(request)
        assert response.status_code == 200

    return len(captured)


@pytest.mark.django_db
def test_room_list_queries_do_not_scale_per_room(django_user_model):
    owner = django_user_model.objects.create_user(
        username="room_list_perf_owner",
        email="room_list_perf_owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Room list perf",
        active=True,
    )

    today = timezone.localdate()

    Room.objects.create(
        title="Room 1",
        category=category,
        property_owner=owner,
        price_per_month=650,
        location="Southampton SO14 7DW",
        property_type="flat",
        available_from=today,
        status="active",
        paid_until=today + timedelta(days=28),
    )

    one_room_queries = _run_room_list_request()

    for index in range(2, 6):
        Room.objects.create(
            title=f"Room {index}",
            category=category,
            property_owner=owner,
            price_per_month=650 + index,
            location="Southampton SO14 7DW",
            property_type="flat",
            available_from=today,
            status="active",
            paid_until=today + timedelta(days=28),
        )

    five_room_queries = _run_room_list_request()

    assert five_room_queries - one_room_queries <= 2, (
        f"Room list query count grew from {one_room_queries} to "
        f"{five_room_queries} when only four rooms were added."
    )
