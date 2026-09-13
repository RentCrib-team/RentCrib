from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from propertylist_app.models import Tenancy


@receiver(post_save, sender=Tenancy)
def release_room_when_tenancy_ends(
    sender,
    instance,
    created,
    update_fields,
    **kwargs,
):
    if created or instance.status != Tenancy.STATUS_ENDED:
        return

    if update_fields is not None and "status" not in update_fields:
        return

    room = instance.room
    room_update_fields = []

    if not room.is_available:
        room.is_available = True
        room_update_fields.append("is_available")

    today = timezone.localdate()

    if room.paid_until is not None and room.paid_until >= today:
        room.paid_until = today - timedelta(days=1)
        room_update_fields.append("paid_until")

    if room.relisted_at is not None:
        room.relisted_at = None
        room_update_fields.append("relisted_at")

    if not room_update_fields:
        return

    room_update_fields.append("updated_at")
    room.save(
        update_fields=room_update_fields,
    )
