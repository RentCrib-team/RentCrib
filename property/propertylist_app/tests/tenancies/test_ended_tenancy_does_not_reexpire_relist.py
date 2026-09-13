from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import RoomImage, Tenancy


pytestmark = pytest.mark.django_db


def _results(payload):
    if isinstance(payload, list):
        return payload
    return payload.get("results") or payload.get("data") or []


def test_saving_already_ended_tenancy_does_not_expire_fresh_relist_payment(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="ended_relist_landlord")
    tenant = user_factory(username="ended_relist_tenant")
    room = room_factory(
        property_owner=landlord,
        title="Ended tenancy relist must stay active",
    )

    # Start from the QA lifecycle state before the tenancy ends: the advert is
    # paid, but the room is occupied and therefore unavailable to seekers.
    room.status = "active"
    room.is_available = False
    room.paid_until = date.today() + timedelta(days=20)
    room.relisted_at = timezone.now() - timedelta(days=40)
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=2,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=timezone.now() - timedelta(days=90),
        tenant_confirmed_at=timezone.now() - timedelta(days=90),
    )

    # The real status transition to ENDED must kill only the old advertising
    # entitlement.
    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status", "updated_at"])

    room.refresh_from_db()
    assert room.paid_until == date.today() - timedelta(days=1)
    assert room.relisted_at is None
    assert room.is_available is True

    # Reproduce the state after a successful fresh relist payment. The new
    # advertising period must survive all later saves to the historical ended
    # tenancy record.
    fresh_paid_until = date.today() + timedelta(days=30)
    fresh_relisted_at = timezone.now()
    room.status = "active"
    room.is_available = True
    room.paid_until = fresh_paid_until
    room.relisted_at = fresh_relisted_at
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )

    for _ in range(3):
        RoomImage.objects.create(
            room=room,
            status=RoomImage.STATUS_APPROVED,
            moderation_reason=RoomImage.MODERATION_AUTO_APPROVED,
        )

    # Ended tenancy rows continue to receive unrelated lifecycle/review updates
    # after move-out. A normal save here must NOT be mistaken for another
    # ACTIVE -> ENDED transition and must not kill the newly purchased advert.
    tenancy.review_deadline_at = timezone.now() + timedelta(days=60)
    tenancy.save()

    room.refresh_from_db()
    assert room.paid_until == fresh_paid_until
    assert room.relisted_at == fresh_relisted_at
    assert room.is_available is True

    owner_client = APIClient()
    owner_client.force_authenticate(user=landlord)

    active_response = owner_client.get(
        reverse("v1:my-listings"),
        {"state": "active"},
    )
    assert active_response.status_code == 200, active_response.data
    assert any(item["id"] == room.id for item in _results(active_response.data))

    expired_response = owner_client.get(
        reverse("v1:my-listings"),
        {"state": "expired"},
    )
    assert expired_response.status_code == 200, expired_response.data
    assert all(item["id"] != room.id for item in _results(expired_response.data))

    public_client = APIClient()
    search_response = public_client.get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert search_response.status_code == 200, search_response.data
    assert any(item["id"] == room.id for item in _results(search_response.data))
