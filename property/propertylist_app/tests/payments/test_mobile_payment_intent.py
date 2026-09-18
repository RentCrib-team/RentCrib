from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.api.views import payments as payments_views
from propertylist_app.models import Payment, Room, RoomCategorie, UserProfile


pytestmark = pytest.mark.django_db

User = get_user_model()


class DummyPaymentIntent:
    id = "pi_mobile_test_123"
    client_secret = "pi_mobile_test_123_secret_abc"
    status = "requires_payment_method"


class DummyCustomerSession:
    id = "cuss_mobile_test_123"
    client_secret = "cuss_mobile_test_123_secret_abc"


class DummyPaymentIntentAPI:
    create_calls = []
    retrieve_calls = []

    @classmethod
    def reset(cls):
        cls.create_calls = []
        cls.retrieve_calls = []

    @classmethod
    def create(cls, **kwargs):
        cls.create_calls.append(kwargs)
        assert kwargs["amount"] == 799
        assert kwargs["currency"] == "gbp"
        assert kwargs["idempotency_key"].startswith(
            "rentcrib-mobile-listing-payment-"
        )
        return DummyPaymentIntent()

    @classmethod
    def retrieve(cls, intent_id):
        cls.retrieve_calls.append(intent_id)
        return DummyPaymentIntent()


class DummyCustomerSessionAPI:
    create_calls = []

    @classmethod
    def reset(cls):
        cls.create_calls = []

    @classmethod
    def create(cls, **kwargs):
        cls.create_calls.append(kwargs)
        assert kwargs["components"]["mobile_payment_element"]["enabled"] is True
        return DummyCustomerSession()


class DummyStripe:
    PaymentIntent = DummyPaymentIntentAPI
    CustomerSession = DummyCustomerSessionAPI


def _owner_room(*, username="mobile_landlord"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.stripe_customer_id = "cus_mobile_test"
    profile.save(update_fields=["stripe_customer_id"])

    cat = RoomCategorie.objects.create(
        name=f"Mobile Paid {username}",
        active=True,
    )

    room = Room.objects.create(
        property_owner=user,
        title=f"Mobile Payment Room {username}",
        category=cat,
        price_per_month=500,
    )

    return user, room


def test_owner_can_create_mobile_listing_payment_intent(monkeypatch):
    user, room = _owner_room()
    DummyPaymentIntentAPI.reset()
    DummyCustomerSessionAPI.reset()

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
    assert set(body["data"]) == {
        "payment_id",
        "payment_intent_id",
        "client_secret",
        "customer_id",
        "customer_session_client_secret",
        "publishable_key",
    }
    assert body["data"]["payment_intent_id"] == "pi_mobile_test_123"
    assert body["data"]["client_secret"] == "pi_mobile_test_123_secret_abc"
    assert body["data"]["customer_id"] == "cus_mobile_test"
    assert (
        body["data"]["customer_session_client_secret"]
        == "cuss_mobile_test_123_secret_abc"
    )
    assert body["data"]["publishable_key"] == "pk_test_dummy"

    payment = Payment.objects.get(room=room, user=user)

    assert body["data"]["payment_id"] == payment.id
    assert payment.amount == Decimal("7.99")
    assert payment.currency == "GBP"
    assert payment.stripe_payment_intent_id == "pi_mobile_test_123"
    assert payment.status == Payment.Status.REQUIRES_PAYMENT

    assert len(DummyPaymentIntentAPI.create_calls) == 1
    create_kwargs = DummyPaymentIntentAPI.create_calls[0]
    assert create_kwargs["amount"] == 799
    assert create_kwargs["metadata"] == {
        "payment_id": str(payment.id),
        "room_id": str(room.id),
        "user_id": str(user.id),
    }
    assert create_kwargs["idempotency_key"] == (
        f"rentcrib-mobile-listing-payment-{payment.id}"
    )

    assert len(DummyCustomerSessionAPI.create_calls) == 1
    assert DummyCustomerSessionAPI.create_calls[0]["customer"] == "cus_mobile_test"


def test_repeated_mobile_request_reuses_payment_and_payment_intent(monkeypatch):
    user, room = _owner_room(username="mobile_retry_owner")
    DummyPaymentIntentAPI.reset()
    DummyCustomerSessionAPI.reset()

    monkeypatch.setattr(
        payments_views,
        "_stripe_mod",
        lambda: DummyStripe,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/payments/payment-intent/rooms/{room.id}/"

    first = client.post(url, {}, format="json")
    second = client.post(url, {}, format="json")

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.data["data"]["payment_id"] == second.data["data"]["payment_id"]
    assert (
        first.data["data"]["payment_intent_id"]
        == second.data["data"]["payment_intent_id"]
        == "pi_mobile_test_123"
    )

    assert Payment.objects.filter(room=room, user=user).count() == 1
    assert len(DummyPaymentIntentAPI.create_calls) == 1
    assert DummyPaymentIntentAPI.retrieve_calls == ["pi_mobile_test_123"]

    # A fresh CustomerSession is safe and gives PaymentSheet a current
    # scoped customer-session client secret on every app retry.
    assert len(DummyCustomerSessionAPI.create_calls) == 2


def test_retry_after_ambiguous_stripe_create_reuses_same_idempotency_key(monkeypatch):
    user, room = _owner_room(username="mobile_network_retry")
    DummyCustomerSessionAPI.reset()

    class FlakyPaymentIntentAPI:
        attempts = 0
        keys = []

        @classmethod
        def create(cls, **kwargs):
            cls.attempts += 1
            cls.keys.append(kwargs["idempotency_key"])
            if cls.attempts == 1:
                raise RuntimeError("simulated network failure")
            return DummyPaymentIntent()

        @classmethod
        def retrieve(cls, intent_id):
            raise AssertionError("retrieve should not run before an intent id is saved")

    class FlakyStripe:
        PaymentIntent = FlakyPaymentIntentAPI
        CustomerSession = DummyCustomerSessionAPI

    monkeypatch.setattr(
        payments_views,
        "_stripe_mod",
        lambda: FlakyStripe,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/v1/payments/payment-intent/rooms/{room.id}/"

    first = client.post(url, {}, format="json")
    second = client.post(url, {}, format="json")

    assert first.status_code == 502
    assert second.status_code == 200

    payments = Payment.objects.filter(room=room, user=user)
    assert payments.count() == 1
    payment = payments.get()

    assert FlakyPaymentIntentAPI.attempts == 2
    assert FlakyPaymentIntentAPI.keys == [
        f"rentcrib-mobile-listing-payment-{payment.id}",
        f"rentcrib-mobile-listing-payment-{payment.id}",
    ]


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

        @staticmethod
        def retrieve(intent_id):
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
