import json
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Payment, RoomImage, Tenancy


pytestmark = pytest.mark.django_db


def _results(payload):
    if isinstance(payload, list):
        return payload
    return payload.get("results") or payload.get("data") or []


def test_tenancy_ended_fresh_payment_returns_active_contract_to_web(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="ended_active_contract_landlord")
    tenant = user_factory(username="ended_active_contract_tenant")
    room = room_factory(
        property_owner=landlord,
        title="Tenancy ended active contract regression",
    )

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

    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status", "updated_at"])

    room.refresh_from_db()
    assert room.paid_until == date.today() - timedelta(days=1)
    assert room.relisted_at is None
    assert room.is_available is True

    for _ in range(3):
        RoomImage.objects.create(
            room=room,
            status=RoomImage.STATUS_APPROVED,
            moderation_reason=RoomImage.MODERATION_AUTO_APPROVED,
        )

    payment = Payment.objects.create(
        user=landlord,
        room=room,
        amount=1.00,
        currency="GBP",
        status=Payment.Status.CREATED,
    )

    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        return {
            "id": "evt_tenancy_ended_active_contract",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_tenancy_ended_active_contract",
                    "payment_intent": "pi_tenancy_ended_active_contract",
                    "metadata": {
                        "payment_id": str(payment.id),
                        "room_id": str(room.id),
                        "user_id": str(landlord.id),
                    },
                }
            },
        }

    monkeypatch.setattr(
        views_mod.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )

    anonymous = APIClient()
    webhook_response = anonymous.post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )
    assert webhook_response.status_code == 200, webhook_response.data

    room.refresh_from_db()
    assert room.status == "active"
    assert room.is_available is True
    assert room.paid_until >= date.today()
    assert room.relisted_at is not None

    owner_client = APIClient()
    owner_client.force_authenticate(user=landlord)
    response = owner_client.get(reverse("v1:my-listings"))
    assert response.status_code == 200, response.data

    listing = next(
        item for item in _results(response.data)
        if item["id"] == room.id
    )

    # This is the exact backend contract the web Tenancy Ended/Active tabs use.
    # Once a fresh relist payment succeeds, the room must be returned as active
    # with a non-null relist marker so the old ended tenancy cannot win the tab.
    assert listing["listing_state"] == "active"
    assert listing["relisted_at"] is not None

    search_response = anonymous.get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert search_response.status_code == 200, search_response.data
    assert any(item["id"] == room.id for item in _results(search_response.data))
