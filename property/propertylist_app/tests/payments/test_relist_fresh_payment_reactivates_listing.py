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


def test_fresh_relist_payment_after_qa_tenancy_end_restores_active_search_visibility(
    monkeypatch,
    user_factory,
    room_factory,
):
    landlord = user_factory(username="qa_relist_landlord")
    tenant = user_factory(username="qa_relist_tenant")
    room = room_factory(
        property_owner=landlord,
        title="QA ended tenancy fresh relist",
    )

    # Existing advert is live before the tenancy ends.
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

    # QA lifecycle contract: tenancy ending kills the old advert entitlement.
    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(update_fields=["status", "updated_at"])

    room.refresh_from_db()
    assert room.paid_until == date.today() - timedelta(days=1)
    assert room.relisted_at is None

    # The relist wizard can leave availability false in its submitted room state.
    # Successful fresh payment must be the final authoritative activation step.
    room.is_available = False
    room.save(update_fields=["is_available", "updated_at"])

    payment = Payment.objects.create(
        user=landlord,
        room=room,
        amount=7.99,
        currency="GBP",
        status=Payment.Status.CREATED,
    )

    monkeypatch.setattr(views_mod, "stripe", real_stripe, raising=False)

    def fake_construct_event(payload, sig_header, secret):
        return {
            "id": "evt_qa_relist_fresh_payment",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_qa_relist_fresh_payment",
                    "payment_intent": "pi_qa_relist_fresh_payment",
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
    assert room.status == "active"
    assert room.paid_until >= date.today()
    assert room.relisted_at is not None
    assert room.is_available is True

    search_response = client.get(
        reverse("v1:search-rooms"),
        {"q": room.title},
    )
    assert search_response.status_code == 200, search_response.data

    payload = search_response.data
    results = payload.get("results") or payload.get("data") or []
    assert any(item["id"] == room.id for item in results)
