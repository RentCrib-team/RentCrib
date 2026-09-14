import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Room, RoomCategorie, Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _make_user(username):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass12345",
    )


def _make_room(owner):
    category = RoomCategorie.objects.create(name="Standard")
    return Room.objects.create(
        title="Room tenancy exclusivity test",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=category,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _make_completed_viewing(user, room):
    now = timezone.now()
    return Booking.objects.create(
        user=user,
        room=room,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2) + timedelta(minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_second_tenant_cannot_propose_when_room_already_has_active_tenancy():
    landlord = _make_user("room_exclusivity_landlord")
    first_tenant = _make_user("room_exclusivity_tenant_a")
    second_tenant = _make_user("room_exclusivity_tenant_b")
    room = _make_room(landlord)

    _make_completed_viewing(first_tenant, room)
    _make_completed_viewing(second_tenant, room)

    now = timezone.now()
    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=first_tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate(),
        duration_months=6,
        landlord_confirmed_at=now,
        tenant_confirmed_at=now,
        status=Tenancy.STATUS_ACTIVE,
    )

    response = _client_for(second_tenant).post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(timezone.localdate()),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert Tenancy.objects.filter(room=room).count() == 1
