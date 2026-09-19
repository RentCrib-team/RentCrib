import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from propertylist_app.image_moderation_tasks import moderate_room_image
from propertylist_app.models import Room, RoomCategorie, RoomImage


User = get_user_model()


def _valid_image(name="room.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 160, 200)).save(
        buffer,
        format="JPEG",
        quality=90,
    )
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="image/jpeg",
    )


@pytest.mark.django_db(transaction=True)
def test_room_image_upload_queues_moderation_without_running_ai_inline(
    tmp_path,
):
    owner = User.objects.create_user(
        username="moderation-workload-owner",
        email="moderation-workload@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Moderation workload",
        active=True,
    )
    room = Room.objects.create(
        title="Moderation workload room",
        description="desc",
        price_per_month=650,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    with override_settings(MEDIA_ROOT=str(tmp_path), USE_S3=True):
        with (
            patch(
                "propertylist_app.image_moderation_tasks."
                "moderate_room_image.apply_async"
            ) as enqueue,
            patch(
                "propertylist_app.services.image."
                "should_auto_approve_upload"
            ) as moderate,
        ):
            response = client.post(
                url,
                {"image": _valid_image()},
                format="multipart",
            )

    assert response.status_code == 201, response.data
    moderate.assert_not_called()

    image = RoomImage.objects.get(room=room)

    enqueue.assert_called_once_with(
        args=[image.id],
        retry=False,
    )

    assert image.status == RoomImage.STATUS_PENDING
    assert (
        image.moderation_reason
        == RoomImage.MODERATION_AWAITING_CHECK
    )
    assert image.moderation_checked_at is None



@pytest.mark.django_db(transaction=True)
def test_local_media_upload_moderates_saved_file_inside_api_process(tmp_path):
    owner = User.objects.create_user(
        username="moderation-local-owner",
        email="moderation-local@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Moderation local",
        active=True,
    )
    room = Room.objects.create(
        title="Moderation local room",
        description="desc",
        price_per_month=650,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    url = reverse("v1:room-photo-upload", kwargs={"pk": room.pk})

    with override_settings(MEDIA_ROOT=str(tmp_path), USE_S3=False):
        with (
            patch(
                "propertylist_app.image_moderation_tasks."
                "moderate_room_image.apply_async"
            ) as enqueue,
            patch(
                "propertylist_app.services.image."
                "should_auto_approve_upload",
                return_value={
                    "approved": True,
                    "reason": RoomImage.MODERATION_AUTO_APPROVED,
                    "notes": "Stored file moderation passed.",
                },
            ) as moderate,
        ):
            response = client.post(
                url,
                {"image": _valid_image("local-room.jpg")},
                format="multipart",
            )

    assert response.status_code == 201, response.data
    enqueue.assert_not_called()
    moderate.assert_called_once()

    moderated_file = moderate.call_args.args[0]
    assert "room_images" in str(getattr(moderated_file, "name", ""))

    image = RoomImage.objects.get(room=room)
    assert image.status == RoomImage.STATUS_APPROVED
    assert image.moderation_reason == RoomImage.MODERATION_AUTO_APPROVED
    assert image.moderation_notes == "Stored file moderation passed."
    assert image.moderation_checked_at is not None



@pytest.mark.django_db
def test_room_image_moderation_worker_applies_approval_result(tmp_path):
    owner = User.objects.create_user(
        username="moderation-worker-owner",
        email="moderation-worker@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Moderation worker",
        active=True,
    )
    room = Room.objects.create(
        title="Moderation worker room",
        description="desc",
        price_per_month=650,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        image = RoomImage.objects.create(
            room=room,
            image=_valid_image("stored-room.jpg"),
            status=RoomImage.STATUS_PENDING,
            moderation_reason=RoomImage.MODERATION_AWAITING_CHECK,
            moderation_notes="Awaiting automated moderation.",
        )

        with patch(
            "propertylist_app.services.image."
            "should_auto_approve_upload",
            return_value={
                "approved": True,
                "reason": RoomImage.MODERATION_AUTO_APPROVED,
                "notes": "Automated moderation passed.",
            },
        ) as moderate:
            moderate_room_image(image.id)

    moderate.assert_called_once()

    image.refresh_from_db()
    assert image.status == RoomImage.STATUS_APPROVED
    assert (
        image.moderation_reason
        == RoomImage.MODERATION_AUTO_APPROVED
    )
    assert image.moderation_notes == "Automated moderation passed."
    assert image.moderation_checked_at is not None


@pytest.mark.django_db
def test_room_image_moderation_worker_does_not_overwrite_manual_decision(
    tmp_path,
):
    owner = User.objects.create_user(
        username="moderation-manual-owner",
        email="moderation-manual@example.com",
        password="pass123",
    )
    category = RoomCategorie.objects.create(
        name="Moderation manual",
        active=True,
    )
    room = Room.objects.create(
        title="Moderation manual room",
        description="desc",
        price_per_month=650,
        location="SO14",
        category=category,
        property_owner=owner,
        property_type="flat",
    )

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        image = RoomImage.objects.create(
            room=room,
            image=_valid_image("manual-room.jpg"),
            status=RoomImage.STATUS_REJECTED,
            moderation_reason=RoomImage.MODERATION_MANUAL_REVIEW,
            moderation_notes="Rejected by admin.",
        )

        with patch(
            "propertylist_app.services.image."
            "should_auto_approve_upload"
        ) as moderate:
            moderate_room_image(image.id)

    moderate.assert_not_called()

    image.refresh_from_db()
    assert image.status == RoomImage.STATUS_REJECTED
    assert (
        image.moderation_reason
        == RoomImage.MODERATION_MANUAL_REVIEW
    )
    assert image.moderation_notes == "Rejected by admin."
