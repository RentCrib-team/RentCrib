import pytest

from propertylist_app import city_image_tasks
from propertylist_app.models import City


def _seeded_city(name):
    city = City.objects.get(name__iexact=name)
    city.image = f"city_images/{city.slug}-old.webp"
    city.image_is_approved = False
    city.is_active = True
    city.save(update_fields=["image", "image_is_approved", "is_active", "updated_at"])
    return city


@pytest.mark.django_db
def test_unapproved_city_image_is_requeued_replaced_and_new_autofill_image_is_approved():
    unapproved = _seeded_city("London")
    approved = City.objects.get(name__iexact="Leeds")
    approved.image = "city_images/leeds.webp"
    approved.image_is_approved = True
    approved.is_active = True
    approved.save(update_fields=["image", "image_is_approved", "is_active", "updated_at"])

    queued = []
    result = city_image_tasks.enqueue_missing_city_images(
        city_model=City,
        enqueue=queued.append,
    )

    assert unapproved.pk in result["city_ids"]
    assert unapproved.pk in queued
    assert approved.pk not in queued

    def fake_autofill(city_id):
        city = City.objects.get(pk=city_id)
        assert city.image.name == ""
        assert city.image_is_approved is False
        city.image = "city_images/london-new.webp"
        city.save(update_fields=["image", "updated_at"])
        return {
            "status": "imported",
            "city_id": city_id,
            "slug": "london",
            "image": "city_images/london-new.webp",
        }

    autofill_result = city_image_tasks._autofill_and_approve_city_image(
        unapproved.pk,
        city_model=City,
        autofill=fake_autofill,
    )

    unapproved.refresh_from_db()
    assert autofill_result["status"] == "imported"
    assert unapproved.image.name == "city_images/london-new.webp"
    assert unapproved.image_is_approved is True


@pytest.mark.django_db
def test_failed_replacement_restores_previous_unapproved_city_image():
    city = _seeded_city("London")

    def fake_autofill(city_id):
        current = City.objects.get(pk=city_id)
        assert current.image.name == ""
        return {
            "status": "failed",
            "city_id": city_id,
            "slug": "london",
            "error": "Pexels unavailable",
        }

    result = city_image_tasks._autofill_and_approve_city_image(
        city.pk,
        city_model=City,
        autofill=fake_autofill,
    )

    city.refresh_from_db()
    assert result["status"] == "failed"
    assert city.image.name == "city_images/london-old.webp"
    assert city.image_is_approved is False
