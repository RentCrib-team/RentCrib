import datetime as dt

from django.contrib.auth import get_user_model
from django.utils import timezone

from propertylist_app.api.views.common import _listing_state_for_room
from propertylist_app.models import Room, RoomCategorie
from propertylist_app.tasks import task_expire_paid_listings


def test_expire_paid_listings_keeps_natural_expiry_out_of_hidden(db):
    User = get_user_model()

    owner = User.objects.create_user(
        username="expiry_owner",
        email="expiry_owner@example.com",
        password="x",
    )

    category = RoomCategorie.objects.create(
        name="Expiry Test Category",
        active=True,
    )

    r = Room.objects.create(
        property_owner=owner,
        category=category,
        title="Test",
        description="d",
        price_per_month=500,
        location="L",
        paid_until=timezone.localdate() - dt.timedelta(days=1),
    )

    assert r.status == Room.Lifecycle.ACTIVE
    assert _listing_state_for_room(r) == "expired"

    res = task_expire_paid_listings()

    r.refresh_from_db()

    assert r.status == Room.Lifecycle.ACTIVE
    assert _listing_state_for_room(r) == "expired"
    assert res >= 1