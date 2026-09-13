from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.public import SearchRoomsView
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_default_search_does_not_materialize_all_remaining_room_ids(django_user_model):
    landlord = django_user_model.objects.create_user(
        username="search_rotation_perf_landlord",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="Search rotation perf category",
        active=True,
    )

    paid_until = timezone.localdate() + timedelta(days=30)
    for index in range(65):
        Room.objects.create(
            title=f"Search rotation perf room {index}",
            description="x",
            price_per_month=600 + index,
            location="Southampton",
            category=category,
            property_owner=landlord,
            status="active",
            is_available=True,
            paid_until=paid_until,
        )

    factory = APIRequestFactory()
    request = factory.get("/api/v1/search/rooms/?limit=20&offset=0")
    view = SearchRoomsView()
    view.request = view.initialize_request(request)
    view.args = ()
    view.kwargs = {}

    with CaptureQueriesContext(connection) as captured:
        queryset = view.get_queryset()
        list(queryset[:20])

    unbounded_remaining_id_queries = [
        query["sql"]
        for query in captured.captured_queries
        if 'SELECT "propertylist_app_room"."id"' in query["sql"]
        and 'NOT ("propertylist_app_room"."id" IN' in query["sql"]
        and "LIMIT" not in query["sql"].upper()
    ]

    assert not unbounded_remaining_id_queries, "\n\n".join(
        unbounded_remaining_id_queries
    )
