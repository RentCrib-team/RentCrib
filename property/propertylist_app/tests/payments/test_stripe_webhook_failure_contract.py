import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Notification, Payment, Room, RoomCategorie, WebhookReceipt


pytestmark = pytest.mark.django_db
User = get_user_model()


def _make_room(owner, *, title):
    category = RoomCategorie.objects.create(
        name=f"Webhook QA {owner.id}",
        active=True,
    )
    return Room.objects.create(
        title=title,
        description="Stripe webhook failure regression",
        price_per_month=750,
        location="Southampton",
        category=category,
        property_owner=owner,
        status=Room.Lifecycle.ACTIVE,
        is_available=True,
        paid_until=timezone.localdate() + timedelta(days=2),
    )


def _make_payment(owner, room):
    return Payment.objects.create(
        user=owner,
        room=room,
        amount="1.00",
        currency="GBP",
        status=Payment.Status.CREATED,
    )


def _checkout_event(payment, room, owner, *, event_id):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": f"cs_{event_id}",
                "payment_intent": f"pi_{event_id}",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(owner.id),
                },
            }
        },
    }


def _deliver_webhook(monkeypatch, *, event):
    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        return event

    monkeypatch.setattr(
        views_mod.stripe.Webhook,
        "construct_event",
        fake_construct_event,
    )

    return APIClient().post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )


def test_checkout_processing_failure_returns_non_2xx_and_keeps_receipt_retryable(monkeypatch):
    owner = User.objects.create_user(
        username="webhook-failure-owner",
        password="pass123",
        email="webhook-failure@example.com",
    )
    room = _make_room(owner, title="Webhook core failure room")
    payment = _make_payment(owner, room)

    def fail_activation(self, new_status):
        raise RuntimeError("forced room activation failure")

    monkeypatch.setattr(Room, "set_status", fail_activation)

    response = _deliver_webhook(
        monkeypatch,
        event=_checkout_event(
            payment,
            room,
            owner,
            event_id="evt_checkout_core_failure",
        ),
    )

    assert response.status_code >= 500, response.data

    payment.refresh_from_db()
    room.refresh_from_db()
    receipt = WebhookReceipt.objects.get(
        source="stripe",
        event_id="evt_checkout_core_failure",
    )

    assert payment.status == Payment.Status.CREATED
    assert room.paid_until == timezone.localdate() + timedelta(days=2)
    assert receipt.processed is False
    assert receipt.processed_at is None


def test_notification_failure_does_not_rollback_successful_checkout_payment(monkeypatch):
    owner = User.objects.create_user(
        username="webhook-notification-owner",
        password="pass123",
        email="webhook-notification@example.com",
    )
    room = _make_room(owner, title="Webhook notification failure room")
    payment = _make_payment(owner, room)

    def fail_notification(*args, **kwargs):
        raise RuntimeError("forced notification failure")

    monkeypatch.setattr(Notification.objects, "create", fail_notification)

    response = _deliver_webhook(
        monkeypatch,
        event=_checkout_event(
            payment,
            room,
            owner,
            event_id="evt_checkout_notification_failure",
        ),
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()
    receipt = WebhookReceipt.objects.get(
        source="stripe",
        event_id="evt_checkout_notification_failure",
    )

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until >= timezone.localdate() + timedelta(days=31)
    assert receipt.processed is True
    assert receipt.processed_at is not None
