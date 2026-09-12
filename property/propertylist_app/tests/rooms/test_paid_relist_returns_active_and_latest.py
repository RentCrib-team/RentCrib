import json
from datetime import date, timedelta

import pytest
import stripe as real_stripe
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
from propertylist_app.models import Payment, Room, Tenancy


pytestmark = pytest.mark.django_db


def test_successful_paid_relist_returns_room_to_active_and_latest(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="paid_relist_landlord")
    tenant = user_factory(username="paid_relist_tenant")

    room = room_factory(
        property_owner=landlord,
        title="Mordern double room| bills included| excellent transport links",
    )
    room.status = Room.Lifecycle.ACTIVE
    room.is_available = True
    room.paid_until = date.today() - timedelta(days=1)
    room.relisted_at = None
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )
    Room.objects.filter(pk=room.pk).update(
        created_at=timezone.now() - timedelta(days=90),
    )

    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=2,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=timezone.now() - timedelta(days=90),
        tenant_confirmed_at=timezone.now() - timedelta(days=90),
    )

    newer_room = room_factory(
        property_owner=landlord,
        title="Newer untouched room",
    )
    newer_room.status = Room.Lifecycle.ACTIVE
    newer_room.paid_until = date.today() + timedelta(days=30)
    newer_room.relisted_at = None
    newer_room.save(
        update_fields=[
            "status",
            "paid_until",
            "relisted_at",
            "updated_at",
        ]
    )
    Room.objects.filter(pk=newer_room.pk).update(
        created_at=timezone.now() - timedelta(hours=1),
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
            "id": "evt_paid_relist_active_latest",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_paid_relist_active_latest",
                    "payment_intent": "pi_paid_relist_active_latest",
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

    before_payment = timezone.now()
    client = APIClient()
    response = client.post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )

    assert response.status_code == 200, response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == Room.Lifecycle.ACTIVE
    assert room.paid_until >= date.today() + timedelta(days=29)
    assert room.relisted_at is not None
    assert room.relisted_at >= before_payment

    homepage = client.get(reverse("api:api-home"))
    assert homepage.status_code == 200, homepage.data

    latest_rooms = homepage.data["data"]["latest_rooms"]
    latest_room_ids = [item["id"] for item in latest_rooms]

    assert room.id in latest_room_ids
    assert newer_room.id in latest_room_ids
    assert latest_room_ids.index(room.id) < latest_room_ids.index(newer_room.id)
