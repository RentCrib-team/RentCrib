from __future__ import annotations

from celery import shared_task

from propertylist_app.models import Room
from propertylist_app.services.geo import geocode_postcode_cached


def _extract_postcode(location: str) -> str:
    parts = (location or "").strip().split()
    if not parts:
        return ""

    if len(parts) >= 2 and len(parts[-1]) <= 3:
        return f"{parts[-2]} {parts[-1]}"

    return parts[-1]


def geocode_room_by_id(room_id: int, expected_location: str | None = None) -> bool:
    """Geocode one room outside the request path and persist its coordinates."""
    room = Room.objects.filter(pk=room_id).first()
    if room is None:
        return False

    location = (room.location or "").strip()
    if not location:
        return False

    if expected_location is not None and location != expected_location.strip():
        return False

    postcode = _extract_postcode(location)
    if not postcode:
        return False

    try:
        latitude, longitude = geocode_postcode_cached(postcode)
    except Exception:
        return False

    Room.objects.filter(pk=room_id, location=location).update(
        latitude=latitude,
        longitude=longitude,
    )
    return True


@shared_task(name="propertylist_app.geocode_room")
def task_geocode_room(room_id: int, expected_location: str | None = None) -> int:
    return int(geocode_room_by_id(room_id, expected_location=expected_location))
