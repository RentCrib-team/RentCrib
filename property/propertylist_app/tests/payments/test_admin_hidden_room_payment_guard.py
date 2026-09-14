import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.admin_api.listings import services as listing_services
from propertylist_app.models import AuditLog, Payment, Room, RoomCategorie


pytestmark = pytest.mark.django_db
User = get_user_model()


def test_admin_hidden_room_stays_hidden_after_payment_intent(monkeypatch):
    owner = User.objects.create_user(
        username="admin-hidden-owner",
        password="pass123",
        email="admin-hidden@example.com",
    )
    category = RoomCategorie.objects.create(name="Admin hidden QA", active=True)
    room = Room.objects.create(
        title="Admin hidden paid room",
        description="Admin moderation hidden payment guard",
        price_per_month=750,
        location="Southampton",
        category=category,
        property_owner=owner,
        status=Room.Lifecycle.ACTIVE,
        is_available=True,
        paid_until=timezone.localdate() - timedelta(days=1),
    )

    listing_services.update_listing_action(room.id, "hide")
    room.refresh_from_db()
    assert room.status == Room.Lifecycle.HIDDEN
    assert AuditLog.objects.filter(
        action="room.hide",
        extra_data__room_id=room.id,
    ).exists()

    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount="1.00",
        currency="GBP",
        status=Payment.Status.CREATED,
    )

    event = {
        "id": "evt_admin_hidden_payment_guard",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_admin_hidden_payment_guard",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(owner.id),
                },
            }
        },
    }

    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        return event

    monkeypatch.setattr(
        views_mod.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )

    response = APIClient().post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.paid_until >= timezone.localdate() + timedelta(days=29)
    assert room.status == Room.Lifecycle.HIDDEN
