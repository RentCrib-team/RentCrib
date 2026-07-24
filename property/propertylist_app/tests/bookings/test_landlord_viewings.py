from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Room, RoomCategorie


def create_room(*, owner, category, title):
    return Room.objects.create(
        title=title,
        description="",
        price_per_month=Decimal("750"),
        location="",
        category=category,
        property_owner=owner,
        number_of_bedrooms=1,
        number_of_bathrooms=1,
        property_type="flat",
        avg_rating=4.0,
    )


@pytest.mark.django_db
def test_landlord_viewings_returns_only_bookings_for_owned_rooms():
    landlord = User.objects.create_user(
        username="landlord",
        email="landlord@example.com",
        password="pass12345",
    )
    other_landlord = User.objects.create_user(
        username="other_landlord",
        email="other-landlord@example.com",
        password="pass12345",
    )
    tenant_one = User.objects.create_user(
        username="tenant_one",
        email="tenant-one@example.com",
        password="pass12345",
    )
    tenant_two = User.objects.create_user(
        username="tenant_two",
        email="tenant-two@example.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="Central",
        active=True,
    )

    landlord_room_one = create_room(
        owner=landlord,
        category=category,
        title="Landlord Room One",
    )
    landlord_room_two = create_room(
        owner=landlord,
        category=category,
        title="Landlord Room Two",
    )
    other_landlord_room = create_room(
        owner=other_landlord,
        category=category,
        title="Other Landlord Room",
    )

    now = timezone.now()

    booking_one = Booking.objects.create(
        user=tenant_one,
        room=landlord_room_one,
        start=now + timedelta(days=1),
        end=now + timedelta(days=1, hours=1),
    )
    booking_two = Booking.objects.create(
        user=tenant_two,
        room=landlord_room_two,
        start=now + timedelta(days=2),
        end=now + timedelta(days=2, hours=1),
    )
    other_landlord_booking = Booking.objects.create(
        user=tenant_one,
        room=other_landlord_room,
        start=now + timedelta(days=3),
        end=now + timedelta(days=3, hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.get(
        reverse("v1:landlord-viewings-list")
    )

    assert response.status_code == 200

    returned_ids = [
        booking["id"]
        for booking in response.data["results"]
    ]

    assert set(returned_ids) == {
        booking_one.id,
        booking_two.id,
    }
    assert other_landlord_booking.id not in returned_ids


@pytest.mark.django_db
def test_landlord_viewings_excludes_soft_deleted_bookings():
    landlord = User.objects.create_user(
        username="landlord",
        email="landlord@example.com",
        password="pass12345",
    )
    tenant = User.objects.create_user(
        username="tenant",
        email="tenant@example.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="Central",
        active=True,
    )
    room = create_room(
        owner=landlord,
        category=category,
        title="Landlord Room",
    )

    now = timezone.now()

    visible_booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=now + timedelta(days=1),
        end=now + timedelta(days=1, hours=1),
    )
    deleted_booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=now + timedelta(days=2),
        end=now + timedelta(days=2, hours=1),
    )

    Booking.objects.filter(
        pk=deleted_booking.pk
    ).update(
        is_deleted=True
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.get(
        reverse("v1:landlord-viewings-list")
    )

    assert response.status_code == 200

    returned_ids = [
        booking["id"]
        for booking in response.data["results"]
    ]

    assert visible_booking.id in returned_ids
    assert deleted_booking.id not in returned_ids


@pytest.mark.django_db
def test_user_without_owned_rooms_gets_empty_landlord_viewings_list():
    landlord = User.objects.create_user(
        username="landlord",
        email="landlord@example.com",
        password="pass12345",
    )
    tenant = User.objects.create_user(
        username="tenant",
        email="tenant@example.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(
        name="Central",
        active=True,
    )
    room = create_room(
        owner=landlord,
        category=category,
        title="Landlord Room",
    )

    now = timezone.now()

    Booking.objects.create(
        user=tenant,
        room=room,
        start=now + timedelta(days=1),
        end=now + timedelta(days=1, hours=1),
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.get(
        reverse("v1:landlord-viewings-list")
    )

    assert response.status_code == 200
    assert response.data["results"] == []
    assert response.data["count"] in (0, None)


@pytest.mark.django_db
def test_landlord_viewings_requires_authentication():
    client = APIClient()

    response = client.get(
        reverse("v1:landlord-viewings-list")
    )

    assert response.status_code == 401