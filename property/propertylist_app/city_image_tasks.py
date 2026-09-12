import logging

from celery import shared_task
from django.core.cache import cache

from propertylist_app.services.city_image_autofill import (
    DEFAULT_BATCH_LIMIT,
    autofill_missing_city_images,
)


logger = logging.getLogger(__name__)
LOCK_KEY = "rentcrib:city-image-autofill"
LOCK_SECONDS = 9 * 60


@shared_task(
    name="propertylist_app.autofill_missing_city_images",
    soft_time_limit=240,
    time_limit=300,
)
def task_autofill_missing_city_images(limit=DEFAULT_BATCH_LIMIT):
    if not cache.add(LOCK_KEY, "1", timeout=LOCK_SECONDS):
        return {
            "status": "locked",
            "attempted": 0,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

    try:
        result = autofill_missing_city_images(limit=limit)
        if result.get("failed"):
            logger.warning("City image autofill completed with failures: %s", result)
        else:
            logger.info("City image autofill completed: %s", result)
        return result
    finally:
        cache.delete(LOCK_KEY)
