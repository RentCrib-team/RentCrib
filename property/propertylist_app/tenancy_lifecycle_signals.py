from datetime import timedelta

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from propertylist_app.models import Tenancy


_TENANCY_END_TRANSITION_FLAG = "_tenancy_just_ended"


@receiver(pre_save, sender=Tenancy)
def remember_tenancy_end_transition(sender, instance, update_fields=None, **kwargs):
    """Record only a real transition from a non-ended tenancy into ended."""
    setattr(instance, _TENANCY_END_TRANSITION_FLAG, False)

    if not instance.pk or instance.status != Tenancy.STATUS_ENDED:
        return

    if update_fields is not None and "status" not in update_fields:
        return

    previous_status = (
        Tenancy.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

    if previous_status != Tenancy.STATUS_ENDED:
        setattr(instance, _TENANCY_END_TRANSITION_FLAG, True)


@receiver(post_save, sender=Tenancy)
def release_room_when_tenancy_ends(
    sender,
    instance,
    created,
    update_fields,
    **kwargs,
):
    if created or not getattr(instance, _TENANCY_END_TRANSITION_FLAG, False):
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
