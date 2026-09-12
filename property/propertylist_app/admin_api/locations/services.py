from django.db import transaction

from .selectors import get_admin_city
from .serializers import AdminCitySerializer


def _delete_storage_file_safely(storage, name):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:
        # A stale/orphaned file must not make a successful city update fail.
        pass


def create_city(*, data):
    serializer = AdminCitySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    city = serializer.save()
    return get_admin_city(city.pk)


def update_city(*, city_id, data):
    city = get_admin_city(city_id)

    old_image_name = ""
    old_image_storage = None
    if city.image:
        old_image_name = city.image.name
        old_image_storage = city.image.storage

    serializer = AdminCitySerializer(city, data=data, partial=True)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        city = serializer.save()
        new_image_name = city.image.name if city.image else ""

        if old_image_name and old_image_name != new_image_name:
            transaction.on_commit(
                lambda storage=old_image_storage, name=old_image_name: (
                    _delete_storage_file_safely(storage, name)
                )
            )

    return get_admin_city(city.pk)
