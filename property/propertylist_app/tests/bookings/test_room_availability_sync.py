import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Room, RoomCategorie, AvailabilitySlot

User = get_user_model()


@pytest.mark.django_db
def test_room_custom_dates_generate_public_booking_slots():
    landlord = User.objects.create_user(
        username="slot_landlord",
        email="slot_landlord@test.com",
        password="pass12345",
    )

    category = RoomCategorie.objects.create(name="General", active=True)

    room = Room.objects.create(
        title="Room with synced slots",
        description="This is a valid room description with enough words to satisfy the listing validation rules for testing availability slot generation.",
        location="SW1A 1AA",
        category=category,
        property_owner=landlord,
        price_per_month=900,
        security_deposit=200,
    )

    viewing_date = (date.today() + timedelta(days=5)).isoformat()

    serializer = RoomSerializer(
        room,
        data={
            "view_available_days_mode": "custom",
            "view_available_custom_dates": [viewing_date],
            "availability_from_time": "09:00",
            "availability_to_time": "10:00",
        },
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()

    assert AvailabilitySlot.objects.filter(room=room).count() == 2

    client = APIClient()
    url = reverse("v1:room-slots-public", args=[room.id])

    dates_response = client.get(url, {"mode": "dates", "only_free": "true"})
    assert dates_response.status_code == 200
    assert dates_response.data == {"available_dates": [viewing_date]}

    slots_response = client.get(url, {"date": viewing_date, "only_free": "true"})
    assert slots_response.status_code == 200
    assert len(slots_response.data.get("results", [])) == 2