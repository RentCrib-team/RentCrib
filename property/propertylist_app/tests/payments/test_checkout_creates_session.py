from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from django.contrib.auth.models import User
from propertylist_app.models import Room, RoomCategorie, Payment, UserProfile

# Import the same module your view imports 'stripe' from
import propertylist_app.api.views as views_mod


@pytest.mark.django_db
def test_checkout_creates_session_for_owner_room(monkeypatch):
    """
    Owner requests a checkout session for their room:
      - returns 200 with {"checkout_url", "session_id"}
      - creates a Payment(row) with status="created" and links the Session id
    """

    # Arrange: owner + room
    owner = User.objects.create_user(username="owner", password="pass123", email="o@x.com")
    cat = RoomCategorie.objects.create(name="Paid", active=True)
    room = Room.objects.create(
        title="My Listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
    )

    # Fake Stripe Customer + Session objects
    class FakeCustomer:
        id = "cus_test_123"

    class FakeSession:
        id = "cs_test_456"
        url = "https://stripe.test/cs_test_456"

    def fake_customer_create(**kwargs):
        return FakeCustomer()

    def fake_session_create(**kwargs):
        assert kwargs.get("mode") == "payment"
        assert "metadata" in kwargs
        assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 799
        assert kwargs["payment_intent_data"]["metadata"] == kwargs["metadata"]
        return FakeSession()

    # Patch BOTH Stripe calls used in the view
    monkeypatch.setattr(views_mod.stripe.Customer, "create", fake_customer_create)
    monkeypatch.setattr(views_mod.stripe.checkout.Session, "create", fake_session_create)


    

    client = APIClient()
    client.force_authenticate(user=owner)

    url = reverse("v1:payments-checkout-room", kwargs={"pk": room.pk})

    # Act
    r = client.post(url, {}, format="json")

    
    # Assert HTTP + payload
    assert r.status_code == 200, r.content
    assert r.data.get("ok") is True
    assert isinstance(r.data.get("data"), dict)
    assert r.data["data"].get("session_id") == "cs_test_456"
    assert r.data["data"].get("checkout_url") is not None

    # Assert DB side-effects
    p = Payment.objects.get(room=room)
    assert p.user == owner
    assert p.amount == Decimal("7.99")
    assert p.currency == "GBP"
    assert p.status == "created"
    assert p.stripe_checkout_session_id == "cs_test_456"


@pytest.mark.django_db
def test_checkout_reuses_pending_payment_and_session(monkeypatch):
    owner = User.objects.create_user(username="owner2", password="pass123")
    UserProfile.objects.create(user=owner, stripe_customer_id="cus_existing")
    cat = RoomCategorie.objects.create(name="Paid reuse", active=True)
    room = Room.objects.create(
        title="Reusable listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
    )
    payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("7.99"),
        currency="GBP",
        status=Payment.Status.CREATED,
        stripe_checkout_session_id="cs_existing",
    )

    class ExistingSession:
        id = "cs_existing"
        url = "https://stripe.test/cs_existing"
        status = "open"

    monkeypatch.setattr(
        views_mod.stripe.checkout.Session,
        "retrieve",
        lambda session_id: ExistingSession(),
    )
    monkeypatch.setattr(
        views_mod.stripe.checkout.Session,
        "create",
        lambda **kwargs: pytest.fail("must not create a second Checkout Session"),
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("v1:payments-checkout-room", kwargs={"pk": room.pk}),
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["data"] == {
        "checkout_url": "https://stripe.test/cs_existing",
        "session_id": "cs_existing",
    }
    assert Payment.objects.filter(room=room).count() == 1
    assert Payment.objects.get(room=room).pk == payment.pk


@pytest.mark.django_db
def test_checkout_rejects_room_with_active_paid_period(monkeypatch):
    from django.utils import timezone

    owner = User.objects.create_user(username="owner3", password="pass123")
    UserProfile.objects.create(user=owner, stripe_customer_id="cus_existing")
    cat = RoomCategorie.objects.create(name="Already paid", active=True)
    room = Room.objects.create(
        title="Paid listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
        paid_until=timezone.localdate(),
    )
    monkeypatch.setattr(
        views_mod.stripe.checkout.Session,
        "create",
        lambda **kwargs: pytest.fail("must not create a Checkout Session"),
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("v1:payments-checkout-room", kwargs={"pk": room.pk}),
        {},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "listing_already_paid"
    assert not Payment.objects.filter(room=room).exists()


@pytest.mark.django_db
def test_checkout_replaces_expired_session(monkeypatch):
    owner = User.objects.create_user(username="owner4", password="pass123")
    UserProfile.objects.create(user=owner, stripe_customer_id="cus_existing")
    cat = RoomCategorie.objects.create(name="Expired checkout", active=True)
    room = Room.objects.create(
        title="Retry listing",
        category=cat,
        price_per_month=800,
        property_owner=owner,
    )
    expired_payment = Payment.objects.create(
        user=owner,
        room=room,
        amount=Decimal("7.99"),
        currency="GBP",
        status=Payment.Status.CREATED,
        stripe_checkout_session_id="cs_expired",
    )

    class ExpiredSession:
        id = "cs_expired"
        url = None
        status = "expired"

    class NewSession:
        id = "cs_new"
        url = "https://stripe.test/cs_new"
        status = "open"

    monkeypatch.setattr(
        views_mod.stripe.checkout.Session,
        "retrieve",
        lambda session_id: ExpiredSession(),
    )
    monkeypatch.setattr(
        views_mod.stripe.checkout.Session,
        "create",
        lambda **kwargs: NewSession(),
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("v1:payments-checkout-room", kwargs={"pk": room.pk}),
        {},
        format="json",
    )

    assert response.status_code == 200
    expired_payment.refresh_from_db()
    assert expired_payment.status == Payment.Status.CANCELED
    assert Payment.objects.filter(room=room).count() == 2
    assert response.data["data"]["session_id"] == "cs_new"
