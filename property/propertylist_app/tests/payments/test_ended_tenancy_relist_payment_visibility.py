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


def test_web_relist_payment_after_ended_tenancy_releases_room_and_makes_search_visible(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="paid_relist_landlord")
    tenant = user_factory(username="paid_relist_tenant")
    room = room_factory(
        property_owner=landlord,
        title="Ended tenancy paid relist visibility regression",
    )

    # Reproduce the broken legacy state seen in the web flow: the tenancy
    # is already ended, but the room still carries the old availability
    # flag and a paid period that has not yet expired.
    previous_paid_until = date.today() + timedelta(days=5)
    room.status = "active"
    room.is_available = False
    room.paid_until = previous_paid_until
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
            "id": "evt_ended_tenancy_relist_visibility",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_ended_tenancy_relist_visibility",
                    "payment_intent": "pi_ended_tenancy_relist_visibility",
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
    webhook_response = client.post(
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
    assert room.paid_until == previous_paid_until + timedelta(days=30)
    assert room.is_available is True
    assert room.relisted_at is not None
    assert room.relisted_at >= before_payment

    search_response = client.get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert search_response.status_code == 200, search_response.data

    payload = search_response.data
    results = payload.get("results") or payload.get("data") or []
    assert any(item["id"] == room.id for item in results)
