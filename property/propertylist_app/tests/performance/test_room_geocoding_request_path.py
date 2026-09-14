import pytest
from django.utils import timezone

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_room_update_does_not_geocode_postcode_synchronously(
    django_user_model,
    monkeypatch,
):
    owner = django_user_model.objects.create_user(
        username="geocode_perf_owner",
        email="geocode_perf_owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Geocode performance",
        active=True,
    )
    room = Room.objects.create(
        title="Geocode performance room",
        category=category,
        property_owner=owner,
        price_per_month=650,
        location="Southampton SO14 7DW",
        property_type="flat",
        available_from=timezone.localdate(),
    )

    synchronous_calls = []

    def fake_synchronous_geocode(postcode):
        synchronous_calls.append(postcode)
        return 50.9097, -1.4044

    monkeypatch.setattr(
        "propertylist_app.api.serializers.geocode_postcode_cached",
        fake_synchronous_geocode,
    )

    serializer = RoomSerializer()
    serializer.update(
        room,
        {
            "location": "Southampton SO15 1AB",
        },
    )

    room.refresh_from_db()

    assert room.location == "Southampton SO15 1AB"
    assert synchronous_calls == []
