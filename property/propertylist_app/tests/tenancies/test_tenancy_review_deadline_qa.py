import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Booking, Room, RoomCategorie, Tenancy


pytestmark = pytest.mark.django_db
API_PREFIX = "/api/v1"


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _user(username):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass12345",
    )


def test_confirmation_uses_ten_minute_private_review_deadline():
    landlord = _user("qa_deadline_landlord")
    tenant = _user("qa_deadline_tenant")
    category = RoomCategorie.objects.create(name="QA Deadline")
    room = Room.objects.create(
        title="QA review deadline room",
        description="QA room",
        price_per_month="500.00",
        location="Southampton",
        category=category,
        furnished=False,
        bills_included=False,
        property_owner=landlord,
        property_type="flat",
    )

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

    proposal = _client(landlord).post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert proposal.status_code == 201, proposal.data
    tenancy_id = proposal.data.get("data", proposal.data)["id"]

    confirmation = _client(tenant).post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )
    assert confirmation.status_code == 200, confirmation.data

    tenancy = Tenancy.objects.get(pk=tenancy_id)
    assert tenancy.status == Tenancy.STATUS_CONFIRMED
    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    assert tenancy.review_deadline_at - tenancy.review_open_at == timedelta(minutes=10)
