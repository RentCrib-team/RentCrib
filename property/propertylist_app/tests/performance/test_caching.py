from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.test.utils import CaptureQueriesContext, override_settings
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model
from propertylist_app.models import Room, RoomCategorie, RoomImage, SavedRoom

User = get_user_model()

TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tests-locmem-cache",  # stable location so hits persist in-process
    }
}

# Disable DRF auth classes for these tests to avoid "Vary: Cookie" etc.
REST_FRAMEWORK_MINIMAL = {"DEFAULT_AUTHENTICATION_CLASSES": []}


def _active_room(*, owner, category, title):
    return Room.objects.create(
        title=title,
        description="Caching performance room",
        price_per_month=900,
        location="Southampton SO14 1AA",
        category=category,
        property_owner=owner,
        property_type="flat",
        status="active",
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=30),
    )


def _add_approved_images(room, count=3):
    for index in range(count):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/cache-{room.id}-{index}.jpg",
            status=RoomImage.STATUS_APPROVED,
        )


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_search_rooms_response_is_cached():
    cache.clear()

    owner = User.objects.create_user(username="o", password="pass123", email="o@example.com")
    cat = RoomCategorie.objects.create(name="Any", active=True)
    Room.objects.create(
        title="Cozy flat in London",
        description="Nice place",
        price_per_month=1000,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
        avg_rating=4.5,
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    # First call: should hit DB
    with CaptureQueriesContext(connection) as q1:
        r1 = client.get(url, {"q": "cozy"})
    assert r1.status_code == 200
    first_queries = len(q1)

    # Second identical call: should come from cache
    with CaptureQueriesContext(connection) as q2:
        r2 = client.get(url, {"q": "cozy"})
    assert r2.status_code == 200
    second_queries = len(q2)

    assert second_queries < first_queries, f"Expected cached response. first={first_queries}, second={second_queries}"


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_rooms_alt_list_response_is_cached():
    cache.clear()

    owner = User.objects.create_user(username="owner2", password="pass123", email="o2@example.com")
    cat = RoomCategorie.objects.create(name="Any2", active=True)
    for i in range(3):
        Room.objects.create(
            title=f"Room {i}",
            description="...",
            price_per_month=900 + i * 10,
            location="Manchester M1 1AA",
            category=cat,
            property_owner=owner,
            avg_rating=4.0 + (i * 0.1),
        )

    client = APIClient()
    url = reverse("v1:room-list-alt")

    with CaptureQueriesContext(connection) as q1:
        r1 = client.get(url)
    assert r1.status_code == 200
    first_queries = len(q1)

    with CaptureQueriesContext(connection) as q2:
        r2 = client.get(url)
    assert r2.status_code == 200
    second_queries = len(q2)

    assert second_queries < first_queries, f"Expected cached response. first={first_queries}, second={second_queries}"


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_authenticated_room_list_cache_is_scoped_per_user():
    cache.clear()

    owner = User.objects.create_user(
        username="cache-owner",
        password="pass123",
        email="cache-owner@example.com",
    )
    viewer_a = User.objects.create_user(
        username="cache-viewer-a",
        password="pass123",
        email="cache-viewer-a@example.com",
    )
    viewer_b = User.objects.create_user(
        username="cache-viewer-b",
        password="pass123",
        email="cache-viewer-b@example.com",
    )
    category = RoomCategorie.objects.create(name="Cache Rooms", active=True)
    room = _active_room(owner=owner, category=category, title="Scoped cache room")
    SavedRoom.objects.create(user=viewer_a, room=room)

    client = APIClient()
    url = reverse("v1:room-list")

    client.force_authenticate(user=viewer_a)
    with CaptureQueriesContext(connection) as first_queries:
        first = client.get(url)
    assert first.status_code == 200
    assert first.data["results"][0]["is_saved"] is True

    with CaptureQueriesContext(connection) as cached_queries:
        second = client.get(url)
    assert second.status_code == 200
    assert second.data == first.data
    assert len(cached_queries) < len(first_queries)

    client.force_authenticate(user=viewer_b)
    other_user = client.get(url)
    assert other_user.status_code == 200
    assert other_user.data["results"][0]["is_saved"] is False


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_room_detail_cache_does_not_leak_owner_hidden_room():
    cache.clear()

    owner = User.objects.create_user(
        username="hidden-owner",
        password="pass123",
        email="hidden-owner@example.com",
    )
    stranger = User.objects.create_user(
        username="hidden-stranger",
        password="pass123",
        email="hidden-stranger@example.com",
    )
    category = RoomCategorie.objects.create(name="Hidden Cache", active=True)
    room = _active_room(owner=owner, category=category, title="Private hidden room")
    room.status = "hidden"
    room.save(update_fields=["status", "updated_at"])

    client = APIClient()
    url = reverse("v1:room-detail", kwargs={"pk": room.pk})

    client.force_authenticate(user=owner)
    owner_response = client.get(url)
    assert owner_response.status_code == 200
    assert owner_response.data["data"]["id"] == room.id

    client.force_authenticate(user=stranger)
    stranger_response = client.get(url)
    assert stranger_response.status_code == 404


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_room_patch_bumps_buster_and_invalidates_cached_detail():
    from propertylist_app.utils.cache import get_buster

    cache.clear()

    owner = User.objects.create_user(
        username="invalidate-owner",
        password="pass123",
        email="invalidate-owner@example.com",
    )
    category = RoomCategorie.objects.create(name="Invalidate Cache", active=True)
    room = _active_room(owner=owner, category=category, title="Old cached title")

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("v1:room-detail", kwargs={"pk": room.pk})

    first = client.get(url)
    assert first.status_code == 200
    assert first.data["data"]["title"] == "Old cached title"

    before = get_buster()
    updated = client.patch(url, {"title": "Fresh title"}, format="json")
    assert updated.status_code == 200, updated.data
    assert get_buster() != before

    refreshed = client.get(url)
    assert refreshed.status_code == 200
    assert refreshed.data["data"]["title"] == "Fresh title"


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_room_list_query_count_does_not_scale_with_room_count():
    cache.clear()

    owner = User.objects.create_user(
        username="query-owner",
        password="pass123",
        email="query-owner@example.com",
    )
    viewer = User.objects.create_user(
        username="query-viewer",
        password="pass123",
        email="query-viewer@example.com",
    )
    category = RoomCategorie.objects.create(name="Query Cache", active=True)

    first_room = _active_room(owner=owner, category=category, title="Query room 0")
    _add_approved_images(first_room)
    SavedRoom.objects.create(user=viewer, room=first_room)

    client = APIClient()
    client.force_authenticate(user=viewer)
    url = reverse("v1:room-list")

    cache.clear()
    with CaptureQueriesContext(connection) as one_room_queries:
        one_room_response = client.get(url)
    assert one_room_response.status_code == 200

    for index in range(1, 5):
        room = _active_room(
            owner=owner,
            category=category,
            title=f"Query room {index}",
        )
        _add_approved_images(room)
        SavedRoom.objects.create(user=viewer, room=room)

    cache.clear()
    with CaptureQueriesContext(connection) as five_room_queries:
        five_room_response = client.get(url)
    assert five_room_response.status_code == 200
    assert len(five_room_response.data["results"]) == 5

    assert len(five_room_queries) <= len(one_room_queries) + 2, (
        "Room list query count should stay effectively constant when more "
        "rooms are serialized. "
        f"one_room={len(one_room_queries)}, five_rooms={len(five_room_queries)}"
    )


@override_settings(CACHES=TEST_CACHES, REST_FRAMEWORK=REST_FRAMEWORK_MINIMAL)
@pytest.mark.django_db
def test_save_toggle_invalidates_cached_is_saved_value():
    cache.clear()

    owner = User.objects.create_user(
        username="save-cache-owner",
        password="pass123",
        email="save-cache-owner@example.com",
    )
    viewer = User.objects.create_user(
        username="save-cache-viewer",
        password="pass123",
        email="save-cache-viewer@example.com",
    )
    category = RoomCategorie.objects.create(name="Save Cache", active=True)
    room = _active_room(owner=owner, category=category, title="Save cache room")

    client = APIClient()
    client.force_authenticate(user=viewer)
    list_url = reverse("v1:room-list")
    toggle_url = reverse("v1:room-save-toggle", kwargs={"pk": room.pk})

    initial = client.get(list_url)
    assert initial.status_code == 200
    assert initial.data["results"][0]["is_saved"] is False

    cached = client.get(list_url)
    assert cached.status_code == 200
    assert cached.data["results"][0]["is_saved"] is False

    toggled = client.post(toggle_url)
    assert toggled.status_code == 200, toggled.data
    assert toggled.data["data"]["saved"] is True

    refreshed = client.get(list_url)
    assert refreshed.status_code == 200
    assert refreshed.data["results"][0]["is_saved"] is True
