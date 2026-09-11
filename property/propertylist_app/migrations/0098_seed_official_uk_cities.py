from django.db import migrations

from propertylist_app.data.uk_cities import (
    OFFICIAL_UK_CITIES,
    SOUTHAMPTON_SLUG,
)


def seed_official_uk_cities(apps, schema_editor):
    City = apps.get_model("propertylist_app", "City")

    for position, item in enumerate(OFFICIAL_UK_CITIES, start=1):
        city = City.objects.filter(slug=item["slug"]).first()

        if city is None and not item["name"].startswith("Bangor ("):
            city = City.objects.filter(name__iexact=item["name"]).first()

        if city is not None:
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


def unseed_official_uk_cities(apps, schema_editor):
    """
    Reverse only rows that are still pristine seed records.

    Admin-edited rows, cities with images, and cities linked to rooms are kept so
    reversing this data migration cannot destroy managed or referenced data.
    """

    City = apps.get_model("propertylist_app", "City")
    Room = apps.get_model("propertylist_app", "Room")

    for position, item in enumerate(OFFICIAL_UK_CITIES, start=1):
        is_southampton = item["slug"] == SOUTHAMPTON_SLUG
        expected_order = 1 if is_southampton else 100 + position

        city = City.objects.filter(
            slug=item["slug"],
            name=item["name"],
            image="",
            image_alt=item["display_name"],
            is_active=True,
            is_featured=is_southampton,
            display_order=expected_order,
        ).first()

        if city is None:
            continue
        if Room.objects.filter(city_id=city.id).exists():
            continue

        city.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0097_city_room_city"),
    ]

    operations = [
        migrations.RunPython(
            seed_official_uk_cities,
            reverse_code=unseed_official_uk_cities,
        ),
    ]
