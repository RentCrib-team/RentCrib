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

    paid_period_extended = (
        instance.paid_until is not None
        and instance.paid_until >= today
        and (
            previous_paid_until is None
            or instance.paid_until > previous_paid_until
        )
    )

    if not (
        paid_period_extended
        and instance.status == Room.Lifecycle.ACTIVE
    ):
        return

    has_ended_tenancy = Tenancy.objects.filter(
        room_id=instance.pk,
        status=Tenancy.STATUS_ENDED,
    ).exists()
    has_live_tenancy = Tenancy.objects.filter(
        room_id=instance.pk,
        status__in=[
            Tenancy.STATUS_CONFIRMED,
            Tenancy.STATUS_ACTIVE,
        ],
    ).exists()

    if has_ended_tenancy and not has_live_tenancy:
        setattr(instance, _RELIST_PAYMENT_FLAG, True)


@receiver(post_save, sender=Room)
def stamp_paid_relist_transition(sender, instance: Room, **kwargs):
    """Stamp and release the new listing cycle after successful relist payment."""
    if not getattr(instance, _RELIST_PAYMENT_FLAG, False):
        return

    relisted_at = timezone.now()
    updates = {
        "relisted_at": relisted_at,
    }

    if not instance.is_available:
        updates["is_available"] = True

    updated = Room.objects.filter(
        pk=instance.pk,
        relisted_at__isnull=True,
    ).update(**updates)

    if updated:
        instance.relisted_at = relisted_at
        if "is_available" in updates:
            instance.is_available = True
