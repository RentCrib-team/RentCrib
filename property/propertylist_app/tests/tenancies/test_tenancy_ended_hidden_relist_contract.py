import json
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

import propertylist_app.api.views as views_mod
import stripe as real_stripe
from propertylist_app.models import Payment, Tenancy


pytestmark = pytest.mark.django_db


def test_tenancy_ended_hidden_room_payment_then_publish_restores_relist_contract(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="hidden_relist_landlord")
    tenant = user_factory(username="hidden_relist_tenant")
    room = room_factory(
        property_owner=landlord,
        title="Ended hidden relist contract",
    )

    room.status = "active"
    room.is_available = False
    room.paid_until = date.today() + timedelta(days=10)
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

    # This is the reported edge case: after the old tenancy ends, the owner
    # has the listing hidden before paying to relist it.
    room.status = "hidden"
    room.is_available = False
    room.save(update_fields=["status", "is_available", "updated_at"])

    payment = Payment.objects.create(
        user=landlord,
        room=room,
        amount="7.99",
        currency="GBP",
        status=Payment.Status.CREATED,
    )

    event = {
        "id": "evt_hidden_ended_relist_contract",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_hidden_ended_relist_contract",
                "metadata": {
                    "payment_id": str(payment.id),
                    "room_id": str(room.id),
                    "user_id": str(landlord.id),
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

    webhook_response = APIClient().post(
        reverse("v1:stripe-webhook"),
        data=json.dumps({"ok": True}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=validsig",
    )
    assert webhook_response.status_code == 200, webhook_response.data

    payment.refresh_from_db()
    room.refresh_from_db()

    assert payment.status == Payment.Status.SUCCEEDED
    assert room.status == "active"
    assert room.paid_until >= date.today() + timedelta(days=29)

    owner_client = APIClient()
    owner_client.force_authenticate(user=landlord)
    publish_response = owner_client.post(reverse("v1:room-publish", args=[room.id]))
    assert publish_response.status_code == 200, publish_response.data

    room.refresh_from_db()
    assert room.status == "active"
    assert room.is_available is True
    assert room.relisted_at is not None
