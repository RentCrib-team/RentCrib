from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import AvailabilitySlot, Room


@pytest.mark.django_db
def test_step1_0915_stays_0915_and_generates_0915_first_slot(django_user_model):
    landlord = django_user_model.objects.create_user(
        username="availability_0915_landlord",
        email="availability_0915_landlord@example.com",
        password="testpass123",
    )

    client = APIClient()
    client.force_authenticate(user=landlord)

    available_from = (
        timezone.localdate() + timedelta(days=2)
    ).isoformat()

    payload = {
        "title": "09:15 availability flow room",
        "description": (
            "This is a bright and spacious room with plenty of natural light, "
            "modern furnishings, fast broadband, secure entry, and excellent "
            "transport links to shops and the city centre."
        ),
        "location": "SW1A 1AA",
        "price_per_month": "800.00",
        "security_deposit": "800.00",
        "available_from": available_from,
        "availability_from_time": "09:15",
        "availability_to_time": "10:15",
        "view_available_days_mode": "everyday",
        "min_stay_months": 1,
        "max_stay_months": 6,
        "furnished": False,
        "bills_included": False,
        "property_type": "flat",
        "parking_available": False,
        "action": "next",
    }

    response = client.post(
        reverse("api:room-list"),
        payload,
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.data

    room_id = response.data["data"]["id"]
    room = Room.objects.get(id=room_id)

    # Check 1: what the Step 1-style API request stores on the Room.
    assert room.availability_from_time == time(9, 15)
    assert room.availability_to_time == time(10, 15)

    # Check 2: what bookable AvailabilitySlot rows the backend generates.
    first_two_slots = list(
        AvailabilitySlot.objects
        .filter(room=room)
        .order_by("start")[:2]
    )

    assert len(first_two_slots) == 2

    local_boundaries = [
        (
            timezone.localtime(slot.start).strftime("%H:%M"),
            timezone.localtime(slot.end).strftime("%H:%M"),
        )
        for slot in first_two_slots
    ]

    assert local_boundaries == [
        ("09:15", "09:45"),
        ("09:45", "10:15"),
    ]
