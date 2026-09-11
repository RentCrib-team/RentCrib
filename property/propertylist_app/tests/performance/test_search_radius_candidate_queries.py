from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views.public import SearchRoomsView
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_radius_search_prefilters_candidates_in_database(django_user_model):
    landlord = django_user_model.objects.create_user(
        username="search_radius_perf_landlord",
    )
    category = RoomCategorie.objects.create(
        name="Search radius perf category",
        active=True,
    )

    paid_until = timezone.localdate() + timedelta(days=30)
    Room.objects.bulk_create(
        [
            Room(
                title=f"Search radius perf room {index}",
                description="x",
                price_per_month=600 + index,
                location="Southampton",
                category=category,
                property_owner=landlord,
                status="active",
                is_available=True,
                paid_until=paid_until,
                latitude=50.90 + (index * 0.01),
                longitude=-1.40 + (index * 0.01),
            )
            for index in range(65)
        ]
    )

    factory = APIRequestFactory()
    request = factory.get(
        "/api/v1/search/rooms/?postcode=SO14%200AA&radius_miles=10"
    )
    view = SearchRoomsView()
    view.request = view.initialize_request(request)
    view.args = ()
    view.kwargs = {}

    with patch(
        "propertylist_app.api.views.public.geocode_postcode_cached",
        return_value=(50.90, -1.40),
    ):
        with CaptureQueriesContext(connection) as captured:
            view.get_queryset()

    candidate_queries = [
        query["sql"]
        for query in captured.captured_queries
        if 'SELECT "propertylist_app_room"."id", "propertylist_app_room"."latitude", "propertylist_app_room"."longitude"' in query["sql"]
        and '"propertylist_app_room"."latitude" IS NOT NULL' in query["sql"]
        and '"propertylist_app_room"."longitude" IS NOT NULL' in query["sql"]
    ]

    assert candidate_queries, "Radius-search candidate query was not captured."

    candidate_sql = candidate_queries[-1].upper()
    assert '"PROPERTYLIST_APP_ROOM"."LATITUDE" >=' in candidate_sql
    assert '"PROPERTYLIST_APP_ROOM"."LATITUDE" <=' in candidate_sql
    assert '"PROPERTYLIST_APP_ROOM"."LONGITUDE" >=' in candidate_sql
    assert '"PROPERTYLIST_APP_ROOM"."LONGITUDE" <=' in candidate_sql
