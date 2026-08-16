import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Payment, Room, RoomCategorie, UserProfile
from propertylist_app.api.views import payments as payments_views


pytestmark = pytest.mark.django_db

User = get_user_model()


class DummyPaymentIntent:
    id = "pi_mobile_test_123"
    client_secret = "pi_mobile_test_123_secret_abc"


class DummyCustomerSession:
    id = "cuss_mobile_test_123"
    client_secret = "cuss_mobile_test_123_secret_abc"


class DummyPaymentIntentAPI:
    @staticmethod
    def create(**kwargs):
        return DummyPaymentIntent()


class DummyCustomerSessionAPI:
    @staticmethod
    def create(**kwargs):
        return DummyCustomerSession()


class DummyStripe:
    PaymentIntent = DummyPaymentIntentAPI
    CustomerSession = DummyCustomerSessionAPI


def test_owner_can_create_mobile_listing_payment_intent(monkeypatch):
    user = User.objects.create_user(
        username="mobile_landlord",
        email="mobile@example.com",
        password="testpass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.stripe_customer_id = "cus_mobile_test"
    profile.save(update_fields=["stripe_customer_id"])

    cat = RoomCategorie.objects.create(
        name="Mobile Paid",
        active=True,
    )

    room = Room.objects.create(
        property_owner=user,
        title="Mobile Payment Room",
        category=cat,
        price_per_month=500,
    )

    # Patch the exact Stripe resolver used by the production endpoint.
    monkeypatch.setattr(
        payments_views,
        "_stripe_mod",
        lambda: DummyStripe,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"/api/v1/payments/payment-intent/rooms/{room.id}/",
        {},
        format="json",
    )

    assert response.status_code == 200

    body = response.data

    assert body["ok"] is True
    assert body["data"]["payment_intent_id"] == "pi_mobile_test_123"
    assert body["data"]["client_secret"] == "pi_mobile_test_123_secret_abc"
    assert body["data"]["customer_id"] == "cus_mobile_test"
    assert (
        body["data"]["customer_session_client_secret"]
        == "cuss_mobile_test_123_secret_abc"
    )

    payment = Payment.objects.get(room=room, user=user)

    assert payment.amount == 1
    assert payment.currency == "GBP"
    assert payment.stripe_payment_intent_id == "pi_mobile_test_123"
    assert payment.status == Payment.Status.REQUIRES_PAYMENT


def test_non_owner_cannot_create_mobile_listing_payment_intent(monkeypatch):
    owner = User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="testpass123",
    )

    other_user = User.objects.create_user(
        username="other",
        email="other@example.com",
        password="testpass123",
    )

    cat = RoomCategorie.objects.create(
        name="Mobile Owner Paid",
        active=True,
    )

    room = Room.objects.create(
        property_owner=owner,
        title="Owner Room",
        category=cat,
        price_per_month=500,
    )

    called = {"value": False}

    class TrackingPaymentIntentAPI:
        @staticmethod
        def create(**kwargs):
            called["value"] = True
            return DummyPaymentIntent()

    class TrackingStripe:
        PaymentIntent = TrackingPaymentIntentAPI
        CustomerSession = DummyCustomerSessionAPI

    monkeypatch.setattr(
        payments_views,
        "_stripe_mod",
        lambda: TrackingStripe,
    )

    client = APIClient()
    client.force_authenticate(user=other_user)

    response = client.post(
        f"/api/v1/payments/payment-intent/rooms/{room.id}/",
        {},
        format="json",
    )

    assert response.status_code == 403
    assert called["value"] is False
    assert (
        Payment.objects.filter(
            room=room,
            user=other_user,
        ).exists()
        is False
    )