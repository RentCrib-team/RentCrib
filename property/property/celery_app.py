import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

app = Celery("property")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()
app.autodiscover_tasks(["propertylist_app"], related_name="city_image_tasks")


@app.on_after_configure.connect
def install_city_image_autofill_schedule(sender, **kwargs):
    sender.add_periodic_task(
        crontab(minute="*/10"),
        sender.signature("propertylist_app.enqueue_missing_city_images"),
        name="autofill-missing-city-images",
        expires=9 * 60,
    )
