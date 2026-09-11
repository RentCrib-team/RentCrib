from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from propertylist_app.api.views import public_locations
from propertylist_app.models import City, Room, RoomCategorie, UserProfile


class _ProfileTouchingCanonicalHomeSerializer:
    """Exercise the owner-profile relations needed by the real room serializer."""

    def __init__(self, payload, context=None):
        self.payload = payload

    @property
    def data(self):
        featured = list(self.payload["featured_rooms"])
        latest = list(self.payload["latest_rooms"])

        for room in [*featured, *latest]:
            profile = room.property_owner.profile
            _ = profile.role_detail
            _ = profile.advertiser_verified
            _ = profile.allow_search_indexing_default

        # Force evaluation of the canonical City queryset inside the guarded block.
        list(self.payload["popular_cities"])

        return {
            "featured_rooms": [],
            "latest_rooms": [],
            "popular_cities": [],
            "stats": self.payload["stats"],
            "app_links": self.payload["app_links"],
        }


@pytest.mark.django_db
def test_canonical_city_list_applies_limit_offset_in_database():
    City.objects.all().delete()
    for index in range(30):
        City.objects.create(
            name=f"Canonical City {index:02d}",
            display_order=index,
            is_active=True,
        )

    request = APIRequestFactory().get(
        "/api/v1/cities/?limit=5&offset=5"
    )

    with CaptureQueriesContext(connection) as captured:
        response = public_locations.CityListView.as_view()(request)

    assert response.status_code == 200

    city_select_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "propertylist_app_city" in query["sql"].lower()
        and "select" in query["sql"].lower()
    ]

    assert city_select_queries, "No canonical City SELECT query was captured."
    assert any(
        "LIMIT 5" in sql.upper() and "OFFSET 5" in sql.upper()
        for sql in city_select_queries
    ), "\n\n".join(city_select_queries)


@pytest.mark.django_db
def test_canonical_homepage_fetches_owner_profiles_without_per_room_queries(
    django_user_model,
    django_assert_num_queries,
    monkeypatch,
):
    City.objects.all().update(is_featured=False)
    City.objects.create(
        name="Canonical Southampton Perf",
        is_active=True,
        is_featured=True,
        display_order=1,
    )
    category = RoomCategorie.objects.create(
        name="Canonical homepage perf",
        active=True,
    )

    for index in range(2):
        landlord = django_user_model.objects.create_user(
            username=f"canonical_home_perf_landlord_{index}",
            email=f"canonical_home_perf_landlord_{index}@example.com",
            password="testpass123",
        )
        profile, _ = UserProfile.objects.get_or_create(user=landlord)
        profile.role = "landlord"
        profile.role_detail = "live_out_landlord"
        profile.advertiser_verified = True
        profile.save(update_fields=["role", "role_detail", "advertiser_verified"])

        Room.objects.create(
            title=f"Canonical homepage performance room {index}",
            description="A canonical homepage performance regression room.",
            location="SO14 0AA",
            price_per_month=700 + index,
            security_deposit=700,
            property_owner=landlord,
            category=category,
            status="active",
            is_available=True,
            paid_until=timezone.localdate() + timedelta(days=30),
        )

    monkeypatch.setattr(
        public_locations,
        "PublicHomeSummarySerializer",
        _ProfileTouchingCanonicalHomeSerializer,
    )

    request = APIRequestFactory().get("/api/v1/home/")

    # Fixed cost: featured + latest + canonical-city aggregation + 3 stats.
    # Touching each owner's profile must not add per-room queries.
    with django_assert_num_queries(6):
        response = public_locations.HomePageView.as_view()(request)

    assert response.status_code == 200
