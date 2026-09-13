import re

from django.db import transaction

from propertylist_app.models import City, Room


UK_POSTCODE_AT_END_RE = re.compile(
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\s*$",
    re.IGNORECASE,
)


def resolve_city_lookup(value, *, active_only=True):
    """Resolve a city by exact slug or exact name. Never inspect Room.location."""

    raw = str(value or "").strip()
    if not raw:
        return None

    qs = City.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)

    return qs.filter(slug__iexact=raw).first() or qs.filter(name__iexact=raw).first()


def _normalise_whitespace(value):
    return " ".join(str(value or "").strip().split())


def infer_city_from_location(location, *, cities=None):
    """
    Conservatively infer a canonical City from an existing property address.

    This is only for migration/backfill of legacy listings. It deliberately
    avoids broad substring matching so an address such as "London Road,
    Southampton, SO14 1AA" is not incorrectly assigned to London.

    Safe matches are:
    1. an exact comma-separated address segment equal to a city name; or
    2. a city name immediately before the postcode at the end of the address.
    """

    text = _normalise_whitespace(location)
    if not text:
        return None

    if cities is None:
        cities = list(City.objects.all().order_by("-name"))
    else:
        cities = list(cities)

    if not cities:
        return None

    segment_values = {
        _normalise_whitespace(segment).casefold()
        for segment in re.split(r"[,\n|]", text)
        if _normalise_whitespace(segment)
    }

    exact_segment_matches = [
        city for city in cities if city.name.casefold() in segment_values
    ]
    if len(exact_segment_matches) == 1:
        return exact_segment_matches[0]
    if len(exact_segment_matches) > 1:
        return None

    if not UK_POSTCODE_AT_END_RE.search(text):
        return None

    matches = []
    for city in cities:
        city_name = re.escape(_normalise_whitespace(city.name))
        pattern = re.compile(
            rf"\b{city_name}\b\s*,?\s*[A-Z]{{1,2}}\d[A-Z\d]?\s*\d[A-Z]{{2}}\s*$",
            re.IGNORECASE,
        )
        if pattern.search(text):
            matches.append(city)

    return matches[0] if len(matches) == 1 else None


def backfill_room_cities(*, queryset=None, apply=False):
    """
    Safely map legacy rooms with no city to canonical City records.

    Returns counters and only writes when apply=True. Ambiguous/unrecognised
    addresses are intentionally left untouched for manual review.
    """

    rooms = queryset if queryset is not None else Room.objects.filter(city__isnull=True)
    cities = list(City.objects.all())

    result = {
        "scanned": 0,
        "matched": 0,
        "updated": 0,
        "unmatched": 0,
    }

    pending_updates = []
    for room in rooms.iterator():
        result["scanned"] += 1
        city = infer_city_from_location(room.location, cities=cities)
        if city is None:
            result["unmatched"] += 1
            continue

        result["matched"] += 1
        if apply:
            room.city = city
            pending_updates.append(room)

    if apply and pending_updates:
        with transaction.atomic():
            Room.objects.bulk_update(pending_updates, ["city"])
        result["updated"] = len(pending_updates)

    return result
