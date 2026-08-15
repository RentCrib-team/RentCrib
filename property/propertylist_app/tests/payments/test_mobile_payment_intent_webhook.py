import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import (
    Notification,
    Payment,
    Room,
    RoomCategorie,
)
from propertylist_app.api.views import payments as payments_views


pytestmark = pytest.mark.django_db

User = get_user_model()


def test_payment_intent_succeeded_activates_listing(monkeypatch):
    owner = User.objects.create_user(
        username="mobile_webhook_owner",
        email="mobile-webhook@example.com",
        password="testpass123",
    )

    cat = RoomCategorie.objects.create(
        name="Mobile Webhook Paid",
        active=True,
    )

    room = Room.objects.create(
        title="Mobile Webhook Room",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        status="draft",
        paid_until=None,
    )

    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=1,
        currency="GBP",
        status=Payment.Status.REQUIRES_PAYMENT,
        stripe_payment_intent_id="pi_mobile_webhook_123",
    )

    event = {
        "id": "evt_mobile_payment_intent_123",
        "type": "payment_intent.succeeded",
        "created": 1234567890,
        "livemode": False,
        "data": {
            "object": {
                "id": "pi_mobile_webhook_123",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(owner.id),
                },
            }
        },
    }

    monkeypatch.setattr(
        payments_views.stripe.Webhook,
        "construct_event",
        lambda **kwargs: event,
    )

    client = APIClient()

    response = client.post(
        reverse("v1:stripe-webhook"),
        data=json.dumps(event),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="test_signature",
    )

    assert response.status_code == 200

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.stripe_payment_intent_id == "pi_mobile_webhook_123"

    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until == timezone.now().date() + timedelta(days=30)

    assert Notification.objects.filter(
        user=owner,
        type="confirmation",
        target_type="payment",
        target_id=payment.id,
        title="Payment confirmed",
    ).exists()


def test_payment_intent_succeeded_is_idempotent(monkeypatch):
    owner = User.objects.create_user(
        username="mobile_idempotent_owner",
        email="mobile-idem@example.com",
        password="testpass123",
    )

    cat = RoomCategorie.objects.create(
        name="Mobile Idempotent Paid",
        active=True,
    )

    room = Room.objects.create(
        title="Mobile Idempotent Room",
        category=cat,
        price_per_month=900,
        property_owner=owner,
        status="draft",
        paid_until=None,
    )

    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=1,
        currency="GBP",
        status=Payment.Status.REQUIRES_PAYMENT,
        stripe_payment_intent_id="pi_mobile_idem_123",
    )

    event = {
        "id": "evt_mobile_idem_123",
        "type": "payment_intent.succeeded",
        "created": 1234567890,
        "livemode": False,
        "data": {
            "object": {
                "id": "pi_mobile_idem_123",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(owner.id),
                },
            }
        },
    }

    monkeypatch.setattr(
        payments_views.stripe.Webhook,
        "construct_event",
        lambda **kwargs: event,
    )

    client = APIClient()
    url = reverse("v1:stripe-webhook")

    response1 = client.post(
        url,
        data=json.dumps(event),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="test_signature",
    )

    assert response1.status_code == 200

    room.refresh_from_db()
    first_paid_until = room.paid_until

    response2 = client.post(
        url,
        data=json.dumps(event),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="test_signature",
    )

    assert response2.status_code == 200

    room.refresh_from_db()

    assert room.paid_until == first_paid_until

    assert Notification.objects.filter(
        user=owner,
        type="confirmation",
        target_type="payment",
        target_id=payment.id,
    ).count() == 1
    
    
    
    