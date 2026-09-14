import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Payment, Room, RoomImage


pytestmark = pytest.mark.django_db


def _results(payload):
    if isinstance(payload, list):
        return payload
    return payload.get("results") or payload.get("data") or []


def test_web_checkout_payment_moves_draft_listing_to_active_and_search_visible(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="web_draft_payment_landlord")
    room = room_factory(
        property_owner=landlord,
        title="Paid web checkout draft activation regression",
    )

    # Reproduce the web wizard contract: a newly-created listing remains a
    # draft, with no advertising entitlement, until Stripe confirms payment.
    room.status = Room.Lifecycle.DRAFT
    room.is_available = True
    room.paid_until = None
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )

    # My Listings requires three approved images before a paid listing belongs
    # in Active rather than Under Review. Keep that independent moderation
    # contract satisfied so this regression isolates payment activation only.
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
            "id": "evt_web_draft_payment_activation",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_web_draft_payment_activation",
                    "payment_intent": "pi_web_draft_payment_activation",
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

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.is_available is True
    assert room.paid_until == timezone.localdate() + timedelta(days=30)

    owner_client = APIClient()
    owner_client.force_authenticate(user=landlord)
    active_response = owner_client.get(
        reverse("v1:my-listings"),
        {"state": "active"},
    )
    assert active_response.status_code == 200, active_response.data

    active_results = _results(active_response.data)
    assert any(item["id"] == room.id for item in active_results)

    draft_response = owner_client.get(
        reverse("v1:my-listings"),
        {"state": "draft"},
    )
    assert draft_response.status_code == 200, draft_response.data

    draft_results = _results(draft_response.data)
    assert all(item["id"] != room.id for item in draft_results)

    search_response = anonymous.get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert search_response.status_code == 200, search_response.data

    search_results = _results(search_response.data)
    assert any(item["id"] == room.id for item in search_results)
