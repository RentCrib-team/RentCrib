from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room


pytestmark = pytest.mark.django_db


def _ids_from_list_response(response):
    payload = response.data
    items = payload.get("results") or payload.get("data") or []
    if isinstance(items, dict):
        items = items.get("results") or items.get("data") or []
    return {item["id"] for item in items}


def _set_public_state(room, *, status="active", is_available=True, paid_until=None):
    room.status = status
    room.is_available = is_available
    room.paid_until = paid_until
    room.save(
        update_fields=[
            "status",
            "is_available",
            "paid_until",
            "updated_at",
        ]
    )
    return room


def test_public_room_surfaces_only_show_current_advertisable_rooms(
    user_factory,
    room_factory,
):
    owner = user_factory(username="public_visibility_owner")
    today = timezone.localdate()

    visible = _set_public_state(
        room_factory(property_owner=owner, title="Visible paid room"),
        paid_until=today,
    )

    # First establish a normal paid advert. RentCrib's paid-activation signal
    # intentionally restores availability at that moment when no live tenancy
    # exists. Then make the room unavailable in a separate state transition,
    # which mirrors a real room becoming reserved/rented after payment.
    unavailable = _set_public_state(
        room_factory(property_owner=owner, title="Rented unavailable room"),
        paid_until=today + timedelta(days=7),
    )
    unavailable.is_available = False
    unavailable.save(update_fields=["is_available", "updated_at"])

    never_paid = _set_public_state(
        room_factory(property_owner=owner, title="Never paid active room"),
        paid_until=None,
    )
    expired = _set_public_state(
        room_factory(property_owner=owner, title="Expired room"),
        paid_until=today - timedelta(days=1),
    )
    draft = _set_public_state(
        room_factory(property_owner=owner, title="Draft room"),
        status=Room.Lifecycle.DRAFT,
        paid_until=today + timedelta(days=7),
    )

    allowed_ids = {visible.id}
    forbidden_rooms = {
        unavailable.id: unavailable,
        never_paid.id: never_paid,
        expired.id: expired,
        draft.id: draft,
    }
    forbidden_ids = set(forbidden_rooms)

    client = APIClient()

    for route_name in ("api:room-list", "api:room-list-alt"):
        response = client.get(reverse(route_name))
        assert response.status_code == 200, response.data
        returned_ids = _ids_from_list_response(response)
        assert allowed_ids <= returned_ids
        assert forbidden_ids.isdisjoint(returned_ids)

    homepage_response = client.get(reverse("api:api-home"))
    assert homepage_response.status_code == 200, homepage_response.data

    homepage = homepage_response.data["data"]
    featured_ids = {item["id"] for item in homepage["featured_rooms"]}
    latest_ids = {item["id"] for item in homepage["latest_rooms"]}

    assert allowed_ids <= featured_ids
    assert allowed_ids <= latest_ids
    assert forbidden_ids.isdisjoint(featured_ids)
    assert forbidden_ids.isdisjoint(latest_ids)
    assert homepage["stats"]["total_active_rooms"] == 1

    # Public users must not be able to bypass discovery rules by opening an
    # old room-detail URL directly.
    visible_detail = client.get(
        reverse("api:room-detail", kwargs={"pk": visible.id})
    )
    assert visible_detail.status_code == 200, visible_detail.data

    for room in forbidden_rooms.values():
        detail = client.get(
            reverse("api:room-detail", kwargs={"pk": room.id})
        )
        assert detail.status_code == 404, detail.data

    # The landlord still needs private access to manage, edit, pay for, or
    # relist their own non-public rooms.
    client.force_authenticate(user=owner)
    for room in forbidden_rooms.values():
        detail = client.get(
            reverse("api:room-detail", kwargs={"pk": room.id})
        )
        assert detail.status_code == 200, detail.data
