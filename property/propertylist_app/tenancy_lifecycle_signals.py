from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from propertylist_app.models import Message, Room, Tenancy


_TENANCY_END_TRANSITION_FLAG = "_tenancy_just_ended"
_LIVE_TENANCY_STATUSES = {
    Tenancy.STATUS_CONFIRMED,
    Tenancy.STATUS_ACTIVE,
}


@receiver(pre_save, sender=Tenancy)
def guard_single_live_tenancy_per_room(sender, instance, **kwargs):
    """Only one confirmed/active tenancy may own a room at a time."""
    if not instance.room_id or instance.status not in _LIVE_TENANCY_STATUSES:
        return

    # The row lock is only needed when this save is acquiring live ownership
    # of a room. Routine saves to an already-live tenancy (for example the
    # Celery tenancy reminder/review sweep updating review timestamps) run in
    # normal autocommit mode and must not try to use select_for_update().
    if instance.pk:
        previous = (
            Tenancy.objects
            .filter(pk=instance.pk)
            .values("status", "room_id")
            .first()
        )
        if (
            previous is not None
            and previous["status"] in _LIVE_TENANCY_STATUSES
            and previous["room_id"] == instance.room_id
        ):
            return

    # Serialize final ownership decisions on the room itself. This prevents
    # two stale proposals for different tenants from being confirmed at the
    # same time and both becoming live.
    Room.objects.select_for_update().get(pk=instance.room_id)

    competing_live_tenancy = (
        Tenancy.objects
        .filter(
            room_id=instance.room_id,
            status__in=_LIVE_TENANCY_STATUSES,
        )
        .exclude(pk=instance.pk)
        .first()
    )

    if competing_live_tenancy is not None:
        raise ValidationError(
            "This room already has a confirmed or active tenancy."
        )


@receiver(pre_save, sender=Tenancy)
def normalise_still_living_schedule_on_confirmation(
    sender,
    instance,
    update_fields=None,
    **kwargs,
):
    """QA: anchor Timer 2 to the final confirmation/update moment."""
    if not instance.pk:
        return

    if instance.status not in {
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    }:
        return

    if not instance.landlord_confirmed_at or not instance.tenant_confirmed_at:
        return

    previous_status = (
        Tenancy.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

    if previous_status != Tenancy.STATUS_PROPOSED:
        return

    # TEMPORARY QA RULE:
    # Timer 2 is due 10 minutes after the point at which both parties have
    # finalised the tenancy information. A one-time correction sets both
    # confirmation timestamps to the correction time, so it follows the same
    # rule automatically.
    #
    # PRODUCTION RULE:
    # Replace this QA offset with 7 days before the actual tenancy end date.
    finalised_at = max(
        instance.landlord_confirmed_at,
        instance.tenant_confirmed_at,
    )
    instance.still_living_check_at = finalised_at + timedelta(minutes=10)


@receiver(post_save, sender=Tenancy)
def retire_competing_proposals_after_confirmation(
    sender,
    instance,
    created,
    **kwargs,
):
    """Retire stale proposals as soon as one tenancy wins the room."""
    if instance.status not in _LIVE_TENANCY_STATUSES:
        return

    competing_proposals = list(
        Tenancy.objects
        .filter(
            room_id=instance.room_id,
            status=Tenancy.STATUS_PROPOSED,
        )
        .exclude(pk=instance.pk)
        .only("id")
    )

    if not competing_proposals:
        return

    competing_ids = [proposal.id for proposal in competing_proposals]
    Tenancy.objects.filter(id__in=competing_ids).update(
        status=Tenancy.STATUS_CANCELLED,
    )

    # The winning save is inside the tenancy response transaction. Queue the
    # closure notices only after it commits, so rolled-back confirmations can
    # never tell another seeker that the room was taken.
    def _queue_room_secured_notices():
        from propertylist_app.tasks import task_send_tenancy_notification

        for tenancy_id in competing_ids:
            task_send_tenancy_notification.delay(
                tenancy_id,
                "room_secured",
            )

    transaction.on_commit(_queue_room_secured_notices)


@receiver(pre_save, sender=Tenancy)
def prevent_review_close_before_ending_reminder(
    sender,
    instance,
    update_fields=None,
    **kwargs,
):
    """Do not let a stale review clock skip the ending-reminder stage."""
    if not instance.pk or instance.status != Tenancy.STATUS_ENDED:
        return

    if update_fields is not None and "status" not in update_fields:
        return

    previous_status = (
        Tenancy.objects.filter(pk=instance.pk)
        .values_list("status", flat=True)
        .first()
    )

    if previous_status not in _LIVE_TENANCY_STATUSES:
        return

    # This guard only applies to an automatic review-stage close: the review
    # clock is already due, Timer 2 was scheduled, but no ending-reminder
    # system message exists yet for this tenancy.
    if (
        instance.review_open_at is None
        or instance.review_open_at > timezone.now()
        or instance.still_living_check_at is None
    ):
        return

    ending_reminder_exists = Message.objects.filter(
        metadata__tenancy_id=instance.pk,
        metadata__event_type="still_living_check",
        metadata__system_event=True,
    ).exists()

    if ending_reminder_exists:
        return

    # Legacy/backfilled timestamps can put review_open_at in the past before
    # the Timer-2 reminder has actually been emitted. Keep the tenancy live so
    # the reminder stage cannot be skipped.
    instance.status = previous_status


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

    # Ending a tenancy is the hard boundary for the advert entitlement. A
    # legacy/QA room can have paid_until=None; leaving that value untouched is
    # unsafe because older public-room queries treated NULL as publishable.
    # Normalise both NULL and still-live entitlement to an already-expired date
    # so the same room is reusable but must be paid for before it can go live.
    if room.paid_until is None or room.paid_until >= today:
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
