from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from propertylist_app.models import Room, Tenancy


_RELIST_PAYMENT_FLAG = "_paid_relist_should_stamp"


@receiver(pre_save, sender=Room)
def remember_paid_relist_transition(sender, instance: Room, update_fields=None, **kwargs):
    """Detect an ended-tenancy room receiving a new paid advertising period."""
    setattr(instance, _RELIST_PAYMENT_FLAG, False)

    if not instance.pk or instance.relisted_at is not None:
        return

    if update_fields is not None and "paid_until" not in update_fields:
        return

    previous = (
        Room.objects.filter(pk=instance.pk)
        .values("paid_until")
        .first()
    )
    if previous is None:
        return

    today = timezone.localdate()
    previous_paid_until = previous["paid_until"]

    was_unpaid = (
        previous_paid_until is None
        or previous_paid_until < today
    )
    is_now_paid = (
        instance.paid_until is not None
        and instance.paid_until >= today
    )

    if not (
        was_unpaid
        and is_now_paid
        and instance.status == Room.Lifecycle.ACTIVE
    ):
        return

    has_ended_tenancy = Tenancy.objects.filter(
        room_id=instance.pk,
        status=Tenancy.STATUS_ENDED,
    ).exists()

    if has_ended_tenancy:
        setattr(instance, _RELIST_PAYMENT_FLAG, True)


@receiver(post_save, sender=Room)
def stamp_paid_relist_transition(sender, instance: Room, **kwargs):
    """Stamp the new listing cycle after successful payment reactivates the room."""
    if not getattr(instance, _RELIST_PAYMENT_FLAG, False):
        return

    relisted_at = timezone.now()
    updated = Room.objects.filter(
        pk=instance.pk,
        relisted_at__isnull=True,
    ).update(relisted_at=relisted_at)

    if updated:
        instance.relisted_at = relisted_at
