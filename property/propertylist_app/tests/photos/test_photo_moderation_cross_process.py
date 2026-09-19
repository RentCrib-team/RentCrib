import io
from unittest.mock import patch

import pytest
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.image_moderation_tasks import moderate_room_image
from propertylist_app.models import Room, RoomCategorie, RoomImage
from propertylist_app.services.image import prepare_moderation_task_payload


User = get_user_model()


def _image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (500, 500), color=(120, 160, 200)).save(
        buffer,
        format="JPEG",
        quality=90,
    )
    return buffer.getvalue()


def _upload(name="room.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        _image_bytes(),
        content_type="image/jpeg",
    )


@pytest.mark.django_db
def test_moderation_payload_does_not_require_worker_storage_file(tmp_path):
    """
    The Render web service and Celery worker do not share the web service's
    persistent disk. A queued moderation payload must therefore work even when
    the RoomImage file path cannot be opened by the worker.
    """
    owner = User.objects.create_user(
        username="cross-process-owner",
        email="cross-process@example.com",
        password="pass12345",
    )
    category = RoomCategorie.objects.create(
        name="Cross Process Photos",
        active=True,
    )
    room = Room.objects.create(
        title="Cross Process Room",
        description="Photo moderation regression",
        price_per_month=700,
        location="Southampton SO14 1AA",
        category=category,
        property_owner=owner,
        property_type="flat",
    )
    image = RoomImage.objects.create(
        room=room,
        image="room_images/file-only-on-web-service.jpg",
        status=RoomImage.STATUS_PENDING,
        moderation_reason=RoomImage.MODERATION_AWAITING_CHECK,
        moderation_notes="Awaiting automated moderation.",
    )

    payload = prepare_moderation_task_payload(_upload())

    def approve_from_payload(file_obj):
        file_obj.seek(0)
        assert file_obj.read(2) == b"\xff\xd8"
        return {
            "approved": True,
            "reason": RoomImage.MODERATION_AUTO_APPROVED,
            "notes": "Payload was readable without shared filesystem storage.",
        }

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        with patch(
            "propertylist_app.services.image.should_auto_approve_upload",
            side_effect=approve_from_payload,
        ):
            moderate_room_image.run(
                image.pk,
                image_payload=payload,
            )

    image.refresh_from_db()
    assert image.status == RoomImage.STATUS_APPROVED
    assert image.moderation_reason == RoomImage.MODERATION_AUTO_APPROVED
    assert "Payload was readable" in image.moderation_notes


@pytest.mark.django_db(transaction=True)
def test_room_photo_upload_queues_moderation_payload(tmp_path):
    owner = User.objects.create_user(
        username="payload-upload-owner",
        email="payload-upload@example.com",
        password="pass12345",
    )
    category = RoomCategorie.objects.create(
        name="Payload Upload Photos",
        active=True,
    )
    room = Room.objects.create(
        title="Payload Upload Room",
        description="Photo moderation queue regression",
        price_per_month=700,
        location="Southampton SO14 1AA",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        with patch(
            "propertylist_app.image_moderation_tasks.moderate_room_image.apply_async"
        ) as mocked_apply_async:
            response = client.post(
                url,
                {"image": _upload()},
                format="multipart",
            )

    assert response.status_code == 201, response.data
    image = RoomImage.objects.get(room=room)

    mocked_apply_async.assert_called_once()
    _, kwargs = mocked_apply_async.call_args
    assert kwargs["args"] == [image.pk]
    assert kwargs["retry"] is False

    queued_payload = kwargs["kwargs"]["image_payload"]
    assert isinstance(queued_payload, str)
    assert len(queued_payload) > 100
