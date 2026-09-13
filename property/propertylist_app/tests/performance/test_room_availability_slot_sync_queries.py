from datetime import time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import AvailabilitySlot, Room, RoomCategorie


@pytest.mark.django_db
def test_room_availability_slot_sync_keeps_existing_slot_queries_bounded(
    django_user_model,
):
    owner = django_user_model.objects.create_user(
        username="availability_perf_owner",
        email="availability_perf_owner@example.com",
    )
    category = RoomCategorie.objects.create(
        name="Availability performance",
        active=True,
    )
    room = Room.objects.create(
        title="Availability performance room",
        category=category,
        property_owner=owner,
        price_per_month=650,
        location="Southampton SO14 7DW",
        property_type="flat",
        available_from=timezone.localdate() + timedelta(days=1),
        view_available_days_mode="everyday",
        availability_from_time=time(9, 0),
        availability_to_time=time(10, 0),
    )

    serializer = RoomSerializer()

    # First sync creates the expected recurring slots. Keep setup outside the
    # measured block so the regression measures the cost of re-syncing an
    # already-populated listing, as happens on ordinary listing updates.
    serializer._sync_availability_slots(room)
    assert AvailabilitySlot.objects.filter(room=room).count() >= 50

    with CaptureQueriesContext(connection) as queries:
        serializer._sync_availability_slots(room)

    # Re-sync cost must stay bounded rather than growing by one booking-exists
    # query for every future availability slot.
    assert len(queries) <= 5
