import pytest
from django.utils import timezone

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Room, RoomCategorie


@pytest.mark.django_db
def test_unrelated_room_update_does_not_resync_availability_slots(
    django_user_model,
    monkeypatch,
):
    owner = django_user_model.objects.create_user(
        username="availability_update_perf_owner",
        email="availability_update_perf_owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Availability perf",
        active=True,
    )
    room = Room.objects.create(
        title="Original room title",
        category=category,
        property_owner=owner,
        price_per_month=650,
        location="Southampton SO14 7DW",
        property_type="flat",
        available_from=timezone.localdate(),
        latitude=50.9097,
        longitude=-1.4044,
    )

    sync_calls = []

    def fake_sync(self, synced_room):
        sync_calls.append(synced_room.id)

    monkeypatch.setattr(
        RoomSerializer,
        "_sync_availability_slots",
        fake_sync,
    )

    serializer = RoomSerializer()
    serializer.update(
        room,
        {
            "title": "Updated room title",
        },
    )

    room.refresh_from_db()

    assert room.title == "Updated room title"
    assert sync_calls == []
