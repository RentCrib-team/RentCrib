import logging

from celery import shared_task
from django.utils import timezone

from propertylist_app.models import RoomImage


logger = logging.getLogger(__name__)


def _normalise_moderation_result(result) -> dict:
    if isinstance(result, bool):
        return {
            "approved": result,
            "reason": (
                RoomImage.MODERATION_AUTO_APPROVED
                if result
                else RoomImage.MODERATION_MANUAL_REVIEW
            ),
            "notes": (
                "Automatically approved."
                if result
                else "Held for manual moderation review."
            ),
        }

    return result or {}


@shared_task(
    name="propertylist_app.moderate_room_image",
    ignore_result=True,
)
def moderate_room_image(room_image_id: int) -> None:
    image = RoomImage.objects.filter(pk=room_image_id).first()

    if image is None:
        return

    # Never overwrite a manual moderation decision that happened while this
    # background job was waiting in the queue.
    if (
        image.status != RoomImage.STATUS_PENDING
        or image.moderation_reason
        != RoomImage.MODERATION_AWAITING_CHECK
    ):
        return

    try:
        from propertylist_app.services.image import (
            should_auto_approve_upload,
        )

        if not image.image:
            raise ValueError("Room image file is missing.")

        with image.image.open("rb") as stored_file:
            moderation_result = _normalise_moderation_result(
                should_auto_approve_upload(stored_file)
            )

        approved = bool(moderation_result.get("approved"))

        image.status = (
            RoomImage.STATUS_APPROVED
            if approved
            else RoomImage.STATUS_PENDING
        )
        image.moderation_reason = (
            moderation_result.get("reason")
            or (
                RoomImage.MODERATION_AUTO_APPROVED
                if approved
                else RoomImage.MODERATION_MANUAL_REVIEW
            )
        )
        image.moderation_notes = (
            moderation_result.get("notes")
            or "Moderation completed without additional notes."
        )
        image.moderation_checked_at = timezone.now()

        image.save(
            update_fields=[
                "status",
                "moderation_reason",
                "moderation_notes",
                "moderation_checked_at",
            ]
        )

    except Exception as exc:
        logger.exception(
            "Automated moderation failed for RoomImage id=%s",
            room_image_id,
        )

        # Only mark the original pending upload as unavailable. If an admin
        # changed the row while the task was running, leave that decision alone.
        RoomImage.objects.filter(
            pk=room_image_id,
            status=RoomImage.STATUS_PENDING,
            moderation_reason=RoomImage.MODERATION_AWAITING_CHECK,
        ).update(
            moderation_reason=RoomImage.MODERATION_SERVICE_UNAVAILABLE,
            moderation_notes=(
                "Unexpected moderation workflow failure. "
                f"{exc.__class__.__name__}: {exc}"
            )[:2000],
            moderation_checked_at=timezone.now(),
        )
