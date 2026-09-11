from datetime import timedelta
from unittest.mock import patch

import pytest
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
    rooms = []
    for index in range(65):
        if index < 5:
            latitude = 50.90 + (index * 0.002)
            longitude = -1.40 + (index * 0.002)
        else:
            latitude = 52.00 + (index * 0.01)
            longitude = -3.00 + (index * 0.01)

        rooms.append(
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
                latitude=latitude,
                longitude=longitude,
            )
        )

    Room.objects.bulk_create(rooms)

    factory = APIRequestFactory()
    request = factory.get(
        "/api/v1/search/rooms/?postcode=SO14%200AA&radius_miles=10"
    )
    view = SearchRoomsView()
    view.request = view.initialize_request(request)
    view.args = ()
    view.kwargs = {}

    from propertylist_app.services import search_radius_candidate_optimization

    real_haversine = search_radius_candidate_optimization.haversine_miles

    with patch(
        "propertylist_app.services.search_radius_candidate_optimization.geocode_postcode_cached",
        return_value=(50.90, -1.40),
    ), patch(
        "propertylist_app.services.search_radius_candidate_optimization.haversine_miles",
        wraps=real_haversine,
    ) as haversine_mock:
        view.get_queryset()

    assert 0 < haversine_mock.call_count < 65, (
        "Radius search should calculate exact Haversine distance for nearby "
        "database-prefiltered candidates, not every geocoded room."
    )
