from propertylist_app.data.uk_cities import (
    OFFICIAL_UK_CITIES,
    OFFICIAL_UK_CITY_COUNT,
    SOUTHAMPTON_SLUG,
)
from propertylist_app.models import City


def seed_official_uk_cities():
    """
    Idempotently ensure the official UK city catalogue exists.

    Existing records are deliberately preserved so admin-managed images,
    featured flags, activation state and display order are never overwritten by
    a re-run of the seed command.
    """

    result = {
        "expected": OFFICIAL_UK_CITY_COUNT,
        "created": 0,
        "existing": 0,
    }

    for position, item in enumerate(OFFICIAL_UK_CITIES, start=1):
        city = City.objects.filter(slug=item["slug"]).first()

        if city is None and not item["name"].startswith("Bangor ("):
            city = City.objects.filter(name__iexact=item["name"]).first()

        if city is not None:
            result["existing"] += 1
            continue

        is_southampton = item["slug"] == SOUTHAMPTON_SLUG
        City.objects.create(
            name=item["name"],
            slug=item["slug"],
            image_alt=item["display_name"],
            is_active=True,
            is_featured=is_southampton,
            display_order=1 if is_southampton else 100 + position,
        )
        result["created"] += 1

    result["total"] = City.objects.filter(
        slug__in=[item["slug"] for item in OFFICIAL_UK_CITIES]
    ).count()
    return result
