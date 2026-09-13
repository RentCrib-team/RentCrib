import logging

from celery import shared_task
from celery.signals import worker_ready
from django.apps import apps
from django.core.cache import cache
from django.db.models import Q

from propertylist_app.services.city_image_autofill import autofill_city_image


logger = logging.getLogger(__name__)
ENQUEUE_LOCK_KEY = "rentcrib:city-image-autofill:enqueue"
ENQUEUE_LOCK_SECONDS = 8 * 60
CITY_LOCK_PREFIX = "rentcrib:city-image-autofill:city"
CITY_LOCK_SECONDS = 2 * 60


def _missing_city_ids(city_model=None):
    city_model = city_model or apps.get_model("propertylist_app", "City")
    return list(
        city_model.objects.filter(is_active=True)
        .filter(
            Q(image="")
            | Q(image__isnull=True)
            | Q(image_is_approved=False)
        )
        .order_by("display_order", "name")
        .values_list("pk", flat=True)
    )


def enqueue_missing_city_images(*, city_model=None, enqueue=None):
    ids = _missing_city_ids(city_model=city_model)
    enqueue = enqueue or (
        lambda city_id: task_autofill_city_image.apply_async(args=[city_id])
    )
    for city_id in ids:
        enqueue(city_id)
    return {"queued": len(ids), "city_ids": ids}


def _autofill_and_approve_city_image(city_id, *, city_model=None, autofill=None):
    city_model = city_model or apps.get_model("propertylist_app", "City")
    autofill = autofill or autofill_city_image

    city = city_model.objects.get(pk=city_id)
    previous_image_name = getattr(city.image, "name", "") or ""
    previous_approved = bool(getattr(city, "image_is_approved", False))

    if previous_image_name and not previous_approved:
        city.image = None
        city.save(update_fields=["image", "updated_at"])

    result = autofill(city_id)

    city.refresh_from_db()
    if result.get("status") == "imported" and city.image:
        if not city.image_is_approved:
            city.image_is_approved = True
            city.save(update_fields=["image_is_approved", "updated_at"])
        return result

    if previous_image_name and not city.image:
        city.image = previous_image_name
        city.image_is_approved = previous_approved
        city.save(update_fields=["image", "image_is_approved", "updated_at"])

    return result


@shared_task(
    name="propertylist_app.autofill_city_image",
    soft_time_limit=50,
    time_limit=60,
)
def task_autofill_city_image(city_id):
    lock_key = f"{CITY_LOCK_PREFIX}:{city_id}"
    if not cache.add(lock_key, "1", timeout=CITY_LOCK_SECONDS):
        return {"status": "locked", "city_id": city_id}
    try:
        result = _autofill_and_approve_city_image(city_id)
        if result.get("status") == "failed":
            logger.warning("City image autofill failed: %s", result)
        else:
            logger.info("City image autofill completed: %s", result)
        return result
    finally:
        cache.delete(lock_key)


@shared_task(name="propertylist_app.enqueue_missing_city_images")
def task_enqueue_missing_city_images():
    if not cache.add(ENQUEUE_LOCK_KEY, "1", timeout=ENQUEUE_LOCK_SECONDS):
        return {"status": "locked", "queued": 0}
    try:
        result = enqueue_missing_city_images()
        result["status"] = "ok"
        return result
    finally:
        cache.delete(ENQUEUE_LOCK_KEY)


@worker_ready.connect
def queue_city_image_autofill_on_worker_start(**kwargs):
    """Kick off population immediately after a worker starts/redeploys."""
    try:
        task_enqueue_missing_city_images.delay()
    except Exception:
        logger.exception("Could not queue initial city image autofill")
