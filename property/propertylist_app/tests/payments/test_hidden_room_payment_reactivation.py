import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Payment, Report, Room, RoomCategorie, RoomImage


pytestmark = pytest.mark.django_db
User = get_user_model()


def _make_room(owner, *, title):
    category = RoomCategorie.objects.create(
        name=f"Pay QA {owner.id}",
        active=True,
    )
    room = Room.objects.create(
        title=title,
        description="Webhook reactivation regression",
        price_per_month=750,
        location="Southampton",
        category=category,
        property_owner=owner,
        status="active",
        is_available=True,
        paid_until=timezone.localdate() - timedelta(days=1),
    )
    for index in range(3):
        RoomImage.objects.create(
            room=room,
            image=f"room_images/{room.id}-reactivation-{index}.jpg",
            status=RoomImage.STATUS_APPROVED,
        )
    return room


def _make_payment(owner, room):
    return Payment.objects.create(
        user=owner,
        room=room,
        amount="1.00",
        currency="GBP",
        status=Payment.Status.CREATED,
    )


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


def _payment_intent_event(payment, room, owner, *, event_id):
    return {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_{event_id}",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(owner.id),
                },
            }
        },
    }


def _search_contains_room(room):
    response = APIClient().get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert response.status_code == 200, response.data
    payload = response.data
    items = payload.get("results") or payload.get("data") or []
    return any(item["id"] == room.id for item in items)


def test_checkout_payment_reactivates_landlord_hidden_expired_room(monkeypatch):
    owner = User.objects.create_user(
        username="hidden-checkout-owner",
        password="pass123",
        email="hidden-checkout@example.com",
    )
    room = _make_room(owner, title="Hidden checkout payment room")

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    unpublish_response = owner_client.post(
        reverse("v1:room-unpublish", kwargs={"pk": room.pk}),
        {},
        format="json",
    )
    assert unpublish_response.status_code == 200, unpublish_response.data

    room.refresh_from_db()
    assert room.status == Room.Lifecycle.HIDDEN
    assert room.paid_until < timezone.localdate()

    payment = _make_payment(owner, room)
    response = _deliver_webhook(
        monkeypatch,
        event=_checkout_event(
            payment,
            room,
            owner,
            event_id="evt_hidden_checkout_reactivation",
        ),
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until >= timezone.localdate() + timedelta(days=29)
    assert room.is_available is True
    assert _search_contains_room(room)


def test_payment_intent_reactivates_landlord_hidden_expired_room(monkeypatch):
    owner = User.objects.create_user(
        username="hidden-intent-owner",
        password="pass123",
        email="hidden-intent@example.com",
    )
    room = _make_room(owner, title="Hidden payment intent room")

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    unpublish_response = owner_client.post(
        reverse("v1:room-unpublish", kwargs={"pk": room.pk}),
        {},
        format="json",
    )
    assert unpublish_response.status_code == 200, unpublish_response.data

    payment = _make_payment(owner, room)
    response = _deliver_webhook(
        monkeypatch,
        event=_payment_intent_event(
            payment,
            room,
            owner,
            event_id="evt_hidden_intent_reactivation",
        ),
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until >= timezone.localdate() + timedelta(days=29)
    assert room.is_available is True
    assert _search_contains_room(room)


def test_payment_does_not_reactivate_room_hidden_by_moderation(monkeypatch):
    owner = User.objects.create_user(
        username="moderation-hidden-owner",
        password="pass123",
        email="moderation-hidden@example.com",
    )
    reporter = User.objects.create_user(
        username="moderation-reporter",
        password="pass123",
    )
    moderator = User.objects.create_user(
        username="moderation-admin",
        password="pass123",
        is_staff=True,
    )
    room = _make_room(owner, title="Moderation hidden payment room")

    report = Report.objects.create(
        reporter=reporter,
        target_type="room",
        content_type=ContentType.objects.get_for_model(Room),
        object_id=room.id,
        reason="abuse",
        details="Regression moderation hide",
    )

    moderation_client = APIClient()
    moderation_client.force_authenticate(user=moderator)
    moderation_response = moderation_client.post(
        f"/api/v1/reports/{report.id}/moderate/",
        {
            "action": "resolve",
            "hide_room": True,
            "resolution_notes": "Keep hidden after payment",
        },
        format="json",
    )
    assert moderation_response.status_code == 200, moderation_response.data

    room.refresh_from_db()
    assert room.status == Room.Lifecycle.HIDDEN

    payment = _make_payment(owner, room)
    response = _deliver_webhook(
        monkeypatch,
        event=_checkout_event(
            payment,
            room,
            owner,
            event_id="evt_moderation_hidden_payment",
        ),
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.paid_until >= timezone.localdate() + timedelta(days=29)
    assert room.status == Room.Lifecycle.HIDDEN
    assert not _search_contains_room(room)
