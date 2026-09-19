import pytest
from datetime import date, timedelta

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
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner):
    category = RoomCategorie.objects.create(name="Still living schedule")
    return Room.objects.create(
        title="QA tenancy timer room",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=category,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_confirmed_tenancy_schedules_still_living_check_ten_minutes_after_confirmation():
    landlord = _make_user("schedule_landlord")
    tenant = _make_user("schedule_tenant")
    room = _make_room(landlord)

    now = timezone.now()
    Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2) + timedelta(minutes=30),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    move_in_date = date.today() + timedelta(days=7)
    landlord_client = _client_for(landlord)
    tenant_client = _client_for(tenant)

    response = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(move_in_date),
            "duration_months": 1,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    tenancy_id = response.data.get("data", response.data)["id"]

    before_confirmation = timezone.now()
    response = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )
    after_confirmation = timezone.now()

    assert response.status_code == 200, response.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert (
        before_confirmation + timedelta(minutes=10)
        <= tenancy.still_living_check_at
        <= after_confirmation + timedelta(minutes=10)
    )
