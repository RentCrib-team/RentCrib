from django.apps import apps
from django.db.models import Avg, Count
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import (
    Booking,
    Message,
    MessageThread,
    Notification,
    Review,
    Room,
    UserProfile,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.reviews import (
    update_room_rating_from_revealed_reviews,
)


def _recalc_room_rating(room: Room) -> None:
    """
    Recalculate a room's rating using only active, revealed
    tenant-to-landlord tenancy reviews.
    """
    now = timezone.now()

    aggregate = Review.objects.filter(
        tenancy__room=room,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        active=True,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    ).aggregate(
        avg=Avg("overall_rating"),
        count=Count("id"),
    )

    room.avg_rating = float(aggregate["avg"] or 0.0)
    room.number_rating = int(aggregate["count"] or 0)

    room.save(
        update_fields=[
            "avg_rating",
            "number_rating",
        ]
    )


@receiver(post_save, sender=Review)
def review_saved_update_room_rating(
    sender,
    instance: Review,
    created,
    **kwargs,
) -> None:
    tenancy = getattr(instance, "tenancy", None)
    room = getattr(tenancy, "room", None)

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)


@receiver(post_delete, sender=Review)
def review_deleted_update_room_rating(
    sender,
    instance: Review,
    **kwargs,
) -> None:
    tenancy = getattr(instance, "tenancy", None)
    room = getattr(tenancy, "room", None)

    if not room:
        return

    update_room_rating_from_revealed_reviews(room)


def _queue_email(
    *,
    user,
    template_key: str,
    context: dict | None = None,
) -> None:
    """
    Queue an email through the notifications pipeline.

    The email is queued only when an active email template exists for
    the supplied template key. It is not sent immediately.
    """
    if not user:
        return

    template_exists = NotificationTemplate.objects.filter(
        key=template_key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).exists()

    if not template_exists:
        return

    OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context=context or {},
    )


@receiver(post_save, sender=Booking)
def booking_created_queue_emails(
    sender,
    instance: Booking,
    created,
    **kwargs,
) -> None:
    if not created:
        return
    

    room = instance.room
    owner = getattr(room, "property_owner", None)
    booker = instance.user

    booking_deep_link = f"/app/bookings/{instance.id}"
    booking_full_url = build_absolute_url(
        booking_deep_link,
        force_login=True,
    )

    if owner:
        booker_name = (
            booker.get_full_name().strip()
            or booker.username
            or booker.first_name
            or "A prospective tenant"
        )

        _queue_email(
            user=owner,
            template_key="booking.new",
            context={
                "user": {
                    "first_name": owner.first_name,
                },
                "booker": {
                    "name": booker_name,
                },
                "room": {
                    "title": room.title,
                },
                "booking_id": instance.id,
                "room_id": room.id,
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
            },
        )

    if booker:
        owner_name = ""

        if owner:
            owner_name = (
                owner.get_full_name()
                or owner.username
                or owner.first_name
                or ""
            )

        _queue_email(
            user=booker,
            template_key="booking.confirmation",
            context={
                "user": {
                    "first_name": booker.first_name,
                },
                "room": {
                    "title": room.title,
                    "owner_name": owner_name,
                },
                "booking_id": instance.id,
                "room_id": room.id,
                "deep_link": booking_deep_link,
                "cta_url": booking_full_url,
            },
        )


@receiver(post_save, sender=Message)
def message_created_create_notifications(
    sender,
    instance: Message,
    created,
    **kwargs,
) -> None:
    if not created:
        return
    
    if instance.message_type != Message.TYPE_TEXT:
        return
    
    metadata = instance.metadata or {}

    if metadata.get("system_event") is True:
        return

    thread: MessageThread = instance.thread

    recipients = thread.participants.exclude(
        pk=instance.sender_id
    ).all()

    notifications_to_create = []

    deep_link = f"/app/threads/{thread.id}"
    full_url = build_absolute_url(
        deep_link,
        force_login=True,
    )

    sender_name = (
        instance.sender.get_full_name()
        or instance.sender.get_username()
    )

    message_snippet = instance.body[:200] if instance.body else ""

    for user in recipients:
        profile, _ = UserProfile.objects.get_or_create(user=user)

        if not getattr(profile, "notify_messages", True):
            continue

        notifications_to_create.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                thread=thread,
                message=instance,
                title="New message",
                body=message_snippet,
            )
        )

        _queue_email(
            user=user,
            template_key="message.new",
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "sender": {
                    "name": sender_name,
                },
                "thread_id": thread.id,
                "message_id": instance.id,
                "deep_link": deep_link,
                "cta_url": full_url,

                # Backwards-compatible variables for older templates.
                "thread_url": full_url,
                "snippet": message_snippet,
            },
        )

    if notifications_to_create:
        Notification.objects.bulk_create(
            notifications_to_create,
            ignore_conflicts=True,
        )


# -------------------------------------------------------------------
# TenancyExtension notifications
# -------------------------------------------------------------------


def _ext_other_party(extension):
    """
    Return the party who should be notified about a new proposal.

    Landlord proposal: notify the tenant.
    Tenant proposal: notify the landlord.
    """
    tenancy = extension.tenancy

    if extension.proposed_by_id == getattr(
        tenancy,
        "landlord_id",
        None,
    ):
        return tenancy.tenant

    return tenancy.landlord


@receiver(
    pre_save,
    sender=apps.get_model(
        "propertylist_app",
        "TenancyExtension",
    ),
)
def tenancy_extension_cache_old_status(
    sender,
    instance,
    **kwargs,
) -> None:
    if not instance.pk:
        instance._old_status = None
        return

    instance._old_status = sender.objects.filter(
        pk=instance.pk
    ).values_list(
        "status",
        flat=True,
    ).first()


@receiver(
    post_save,
    sender=apps.get_model(
        "propertylist_app",
        "TenancyExtension",
    ),
)
def tenancy_extension_notifications(
    sender,
    instance,
    created,
    **kwargs,
) -> None:
    if not getattr(instance, "tenancy_id", None):
        return

    tenancy = instance.tenancy

    deep_link = f"/app/tenancies/{tenancy.id}"
    cta_url = build_absolute_url(
        deep_link,
        force_login=True,
    )

    def maybe_queue_email(user, template_key: str) -> None:
        if not user:
            return

        profile, _ = UserProfile.objects.get_or_create(user=user)

        if not getattr(profile, "notify_confirmations", True):
            return

        _queue_email(
            user=user,
            template_key=template_key,
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "tenancy_id": tenancy.id,
                "room_title": tenancy.room.title,
                "deep_link": deep_link,
                "cta_url": cta_url,
            },
        )

    if created:
        other_party = _ext_other_party(instance)

        if not other_party:
            return

        Notification.objects.create(
            user=other_party,
            type="tenancy_extension_proposed",
            title="Tenancy extension proposed",
            body=(
                "A tenancy extension was proposed for "
                f"{tenancy.room.title}."
            ),
            target_type="tenancy_extension",
            target_id=tenancy.id,
        )

        maybe_queue_email(
            other_party,
            "tenancy.extension.proposed",
        )
        return

    old_status = getattr(instance, "_old_status", None)
    new_status = instance.status

    if old_status == new_status:
        return

    if new_status == instance.STATUS_ACCEPTED:
        for user in (tenancy.landlord, tenancy.tenant):
            if not user:
                continue

            Notification.objects.create(
                user=user,
                type="tenancy_extension_accepted",
                title="Tenancy extension accepted",
                body=(
                    "The tenancy extension for "
                    f"{tenancy.room.title} was accepted."
                ),
                target_type="tenancy_extension",
                target_id=tenancy.id,
            )

            maybe_queue_email(
                user,
                "tenancy.extension.accepted",
            )

    elif new_status == instance.STATUS_REJECTED:
        proposer = instance.proposed_by

        if not proposer:
            return

        Notification.objects.create(
            user=proposer,
            type="tenancy_extension_rejected",
            title="Tenancy extension rejected",
            body=(
                "The tenancy extension for "
                f"{tenancy.room.title} was rejected."
            ),
            target_type="tenancy_extension",
            target_id=tenancy.id,
        )

        maybe_queue_email(
            proposer,
            "tenancy.extension.rejected",
        )