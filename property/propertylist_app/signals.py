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
    MessageThreadState,
    Notification,
    Review,
    Room,
    UserProfile,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event
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

    booking_deep_link = f"/viewings/{instance.id}"
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

    # A genuine new incoming message must restore the conversation
    # for its recipients. Otherwise a thread previously placed in the
    # bin remains hidden even though the recipient has received a new
    # message, notification and email.
    MessageThreadState.objects.filter(
        user__in=recipients,
        thread=thread,
        in_bin=True,
    ).update(
        in_bin=False,
    )

    notifications_to_create = []

    deep_link = f"/messages?thread={thread.id}"
    full_url = build_absolute_url(
        deep_link,
        force_login=False,
    )

    sender_name = (
        instance.sender.get_full_name()
        or instance.sender.get_username()
    )

    message_snippet = instance.body[:200] if instance.body else ""

    for user in recipients:
        # Realtime chat delivery is independent of email/in-app notification
        # preferences. The actual message must still arrive instantly.
        push_user_realtime_event(
            user.id,
            "new_message",
            {
                "message_id": instance.id,
                "thread_id": thread.id,
                "sender_id": instance.sender_id,
            },
        )

        profile, _ = UserProfile.objects.get_or_create(user=user)
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
        
        
        push_user_realtime_event(
            user.id,
            "new_notification",
            {
                "kind": "message",
                "message_id": instance.id,
                "thread_id": thread.id,
            },
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

        profile, _ = UserProfile.objects.get_or_create(
            user=user,
        )

        if not getattr(
            profile,
            "notify_confirmations",
            True,
        ):
            return

        proposed_by = getattr(
            instance,
            "proposed_by",
            None,
        )

        proposer_name = ""

        if proposed_by:
            proposer_name = (
                proposed_by.get_full_name()
                or proposed_by.username
                or proposed_by.first_name
                or ""
            )

        proposed_start_date = getattr(
            instance,
            "proposed_start_date",
            None,
        )

        proposed_start_date_value = (
            proposed_start_date.isoformat()
            if proposed_start_date
            else ""
        )

        _queue_email(
            user=user,
            template_key=template_key,
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "tenancy_id": tenancy.id,
                "extension_id": instance.id,
                "room_title": tenancy.room.title,
                "proposer_name": proposer_name,
                "proposed_start_date": (
                    proposed_start_date_value
                ),
                "proposed_duration_months": (
                    instance.proposed_duration_months
                ),
                "deep_link": deep_link,
                "cta_url": cta_url,
            },
        )

    proposed_start_date = getattr(
        instance,
        "proposed_start_date",
        None,
    )

    if proposed_start_date:
        proposed_start_date_text = (
            proposed_start_date.strftime("%d %B %Y")
        )
    else:
        proposed_start_date_text = (
            "the agreed renewal date"
        )

    proposed_duration_months = getattr(
        instance,
        "proposed_duration_months",
        None,
    )

    duration_text = (
        f"{proposed_duration_months} "
        f"month{'s' if proposed_duration_months != 1 else ''}"
        if proposed_duration_months
        else "the agreed duration"
    )

    proposed_start_date = getattr(
        instance,
        "proposed_start_date",
        None,
    )

    proposed_start_date_text = (
        proposed_start_date.strftime("%d %B %Y")
        if proposed_start_date
        else "the agreed renewal date"
    )

    proposed_duration_months = getattr(
        instance,
        "proposed_duration_months",
        None,
    )

    duration_text = (
        f"{proposed_duration_months} "
        f"month{'s' if proposed_duration_months != 1 else ''}"
        if proposed_duration_months
        else "the agreed duration"
    )

    if created:
        other_party = _ext_other_party(instance)

        if not other_party:
            return

        Notification.objects.get_or_create(
            user=other_party,
            type="tenancy_extension_proposed",
            target_type="tenancy_extension",
            target_id=instance.id,
            defaults={
                "title": "Tenancy renewal proposed",
                "body": (
                    f"A renewal has been proposed for "
                    f"{tenancy.room.title}, starting "
                    f"{proposed_start_date_text} for "
                    f"{duration_text}. Review the renewal "
                    "information and respond."
                ),
            },
        )

        maybe_queue_email(
            other_party,
            "tenancy.extension.proposed",
        )
        return

    old_status = getattr(
        instance,
        "_old_status",
        None,
    )
    new_status = instance.status

    if old_status == new_status:
        return

    if new_status == instance.STATUS_ACCEPTED:
        for user in (
            tenancy.landlord,
            tenancy.tenant,
        ):
            if not user:
                continue

            Notification.objects.get_or_create(
                user=user,
                type="tenancy_extension_accepted",
                target_type="tenancy_extension",
                target_id=instance.id,
                defaults={
                    "title": "Tenancy renewal accepted",
                    "body": (
                        f"The renewal for "
                        f"{tenancy.room.title} has been "
                        f"accepted. The new tenancy period "
                        f"starts {proposed_start_date_text} "
                        f"and continues for {duration_text}."
                    ),
                },
            )

            maybe_queue_email(
                user,
                "tenancy.extension.accepted",
            )

    elif new_status == instance.STATUS_REJECTED:
        proposer = instance.proposed_by

        if not proposer:
            return

        Notification.objects.get_or_create(
            user=proposer,
            type="tenancy_extension_rejected",
            target_type="tenancy_extension",
            target_id=instance.id,
            defaults={
                "title": "Tenancy renewal declined",
                "body": (
                    f"The proposed renewal for "
                    f"{tenancy.room.title}, starting "
                    f"{proposed_start_date_text} for "
                    f"{duration_text}, was declined. "
                    "The existing tenancy information "
                    "remains unchanged."
                ),
            },
        )

        maybe_queue_email(
            proposer,
            "tenancy.extension.rejected",
        )