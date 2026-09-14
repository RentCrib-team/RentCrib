import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Payment, Room, RoomCategorie, RoomImage


@pytest.mark.django_db
def test_paid_draft_without_live_tenancy_does_not_become_rented(monkeypatch):
    owner = User.objects.create_user(
        username="draft-owner",
        password="pass123",
        email="draft-owner@example.com",
    )
    category = RoomCategorie.objects.create(name="Draft QA", active=True)
    room = Room.objects.create(
        title="Draft should become active",
        category=category,
        price_per_month=820,
        property_owner=owner,
        status="draft",
        is_available=False,
        paid_until=None,
    )

    for index in range(3):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/draft-payment-{index}.jpg",
            status=RoomImage.STATUS_APPROVED,
        )

    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=1.00,
        currency="GBP",
        status="created",
    )

    client = APIClient()
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        return {
            "id": "evt_draft_payment_not_rented",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_draft_payment_not_rented",
                    "payment_intent": "pi_draft_payment_not_rented",
                    "metadata": {
                        "payment_id": str(payment.id),
                        "room_id": str(room.id),
                        "user_id": str(owner.id),
                    },
                }
            },
        }

    monkeypatch.setattr(
        views_mod.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )

    webhook_response = client.post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )
    assert webhook_response.status_code == 200, webhook_response.content

    room.refresh_from_db()
    assert room.status == "active"
    assert room.is_available is True

    client.force_authenticate(user=owner)
    listings_response = client.get(reverse("v1:my-listings"))
    assert listings_response.status_code == 200, listings_response.content

    payload = listings_response.json()
    listings = payload.get("data", payload)
    listing = next(item for item in listings if item["id"] == room.id)

    assert listing["listing_state"] == "active"
