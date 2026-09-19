import io
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from propertylist_app.api.throttling import RoomPhotoUploadThrottle
from propertylist_app.api.views.rooms import RoomPhotoUploadView
from propertylist_app.models import Room, RoomCategorie


def _image(name):
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (100, 140, 180)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@pytest.fixture
def owner_room(django_user_model):
    owner = django_user_model.objects.create_user(
        username="photo-throttle-owner",
        email="photo-throttle@example.com",
        password="TestPass123!",
    )
    category = RoomCategorie.objects.create(
        name="Photo throttle",
        active=True,
    )
    room = Room.objects.create(
        title="Photo throttle room",
        description="Room used to verify the independent photo allowance.",
        price_per_month=700,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )
    return owner, room


@pytest.mark.django_db
def test_photo_endpoint_replaces_global_throttles():
    throttle_types = [type(item) for item in RoomPhotoUploadView().get_throttles()]
    assert throttle_types == [RoomPhotoUploadThrottle]


@pytest.mark.django_db(transaction=True)
def test_photo_upload_has_its_own_limit_and_get_does_not_consume_it(
    owner_room,
    settings,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setitem(
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "photo-upload",
        "2/minute",
    )
    api_settings.reload()
    caches["default"].clear()

    owner, room = owner_room
    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    with (
        override_settings(MEDIA_ROOT=str(tmp_path)),
        patch(
            "propertylist_app.image_moderation_tasks."
            "moderate_room_image.apply_async"
        ),
    ):
        # Repeated status reads must not spend the upload allowance.
        for _ in range(5):
            assert client.get(url).status_code == 200

        first = client.post(url, {"image": _image("one.jpg")}, format="multipart")
        second = client.post(url, {"image": _image("two.jpg")}, format="multipart")
        third = client.post(url, {"image": _image("three.jpg")}, format="multipart")

    assert first.status_code == 201, first.data
    assert second.status_code == 201, second.data
    assert third.status_code == 429, third.data
