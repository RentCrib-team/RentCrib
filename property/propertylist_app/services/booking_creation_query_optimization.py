"""Query optimization for booking creation signal side effects."""

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Booking, Message, MessageThread, Notification, UserProfile
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event


_INSTALLED = False


def _booking_thread(*, landlord, seeker, room):
    thread = (
        MessageThread.objects
        .filter(room=room, landlord=landlord, seeker=seeker)
        .order_by("id")
        .first()
    )
    if thread is not None:
        return thread

    legacy_thread = (
        MessageThread.objects
        .filter(Q(room=room) | Q(room__isnull=True))
        .filter(participants=landlord)
        .filter(participants=seeker)
        .distinct()
        .order_by("id")
        .first()
    )
    if legacy_thread is not None:
        update_fields = []
        if legacy_thread.room_id is None:
            legacy_thread.room = room
            update_fields.append("room")
        if legacy_thread.landlord_id is None:
            legacy_thread.landlord = landlord
            update_fields.append("landlord")
        if legacy_thread.seeker_id is None:
            legacy_thread.seeker = seeker
            update_fields.append("seeker")
        if update_fields:
            legacy_thread.save(update_fields=update_fields)
        return legacy_thread

    try:
        with transaction.atomic():
            thread = MessageThread.objects.create(room=room, landlord=landlord, seeker=seeker)
            through = MessageThread.participants.through
            through.objects.bulk_create(
                [
                    through(messagethread_id=thread.id, user_id=landlord.id),
                    through(messagethread_id=thread.id, user_id=seeker.id),
                ],
                ignore_conflicts=True,
            )
            return thread
    except IntegrityError:
        return MessageThread.objects.get(room=room, landlord=landlord, seeker=seeker)


def _queue_booking_emails(*, owner, booker, room, booking, booking_deep_link, booking_full_url):
    active_keys = set(
        NotificationTemplate.objects.filter(
            key__in=["booking.new", "booking.confirmation"],
            channel=NotificationTemplate.CHANNEL_EMAIL,
            is_active=True,
        ).values_list("key", flat=True)
    )

    queued = []
    if owner and "booking.new" in active_keys:
        booker_name = (
            booker.get_full_name().strip()
            or booker.username
            or booker.first_name
            or "A prospective tenant"
        )
        queued.append(
            OutboundNotification(
                user=owner,
                channel=NotificationTemplate.CHANNEL_EMAIL,
                template_key="booking.new",
                context={
                    "user": {"first_name": owner.first_name},
                    "booker": {"name": booker_name},
                    "room": {"title": room.title},
                    "booking_id": booking.id,
                    "room_id": room.id,
                    "deep_link": booking_deep_link,
                    "cta_url": booking_full_url,
                },
            )
        )

    if booker and "booking.confirmation" in active_keys:
        owner_name = ""
        if owner:
            owner_name = owner.get_full_name() or owner.username or owner.first_name or ""
        queued.append(
            OutboundNotification(
                user=booker,
                channel=NotificationTemplate.CHANNEL_EMAIL,
                template_key="booking.confirmation",
                context={
                    "user": {"first_name": booker.first_name},
                    "room": {"title": room.title, "owner_name": owner_name},
                    "booking_id": booking.id,
                    "room_id": room.id,
                    "deep_link": booking_deep_link,
                    "cta_url": booking_full_url,
                },
            )
        )

    if queued:
        OutboundNotification.objects.bulk_create(queued)


def _optimized_booking_created_queue_emails(sender, instance: Booking, created, **kwargs):
    if not created:
        return

    room = instance.room
    owner = getattr(room, "property_owner", None)
    booker = instance.user

    if owner and booker:
        thread = _booking_thread(landlord=owner, seeker=booker, room=room)
        event_key = f"booking:{instance.id}:created"
        system_message = Message.objects.create(
            thread=thread,
            sender=booker,
            body=(
                "Viewing booked\n\n"
                f"A viewing has been booked for {room.title}.\n\n"
                f"Viewing time: {timezone.localtime(instance.start).strftime('%d %b %Y, %H:%M')}"
            ),
            message_type=Message.TYPE_TEXT,
            metadata={
                "system_event": True,
                "event_type": "booking_created",
                "event_key": event_key,
                "booking_id": instance.id,
                "room_id": room.id,
                "room_title": room.title,
                "start": instance.start.isoformat(),
                "end": instance.end.isoformat() if instance.end else None,
            },
        )

        for user in (owner, booker):
            push_user_realtime_event(
                user.id,
                "new_message",
                {"message_id": system_message.id, "thread_id": thread.id, "sender_id": system_message.sender_id},
            )

        owner_profile = UserProfile.objects.filter(user=owner).only("notify_confirmations").first()
        notify_confirmations = True if owner_profile is None else owner_profile.notify_confirmations
        if notify_confirmations:
            owner_notification = Notification.objects.create(
                user=owner,
                type="booking_created",
                target_type="message",
                target_id=system_message.id,
                thread=thread,
                message=system_message,
                audience=Notification.Audience.LANDLORD,
                title="New viewing booked",
                body=f"A viewing has been booked for {room.title}.",
            )
            push_user_realtime_event(
                owner.id,
                "new_notification",
                {
                    "kind": "booking_created",
                    "notification_id": owner_notification.id,
                    "message_id": system_message.id,
                    "thread_id": thread.id,
                },
            )

    booking_deep_link = f"/app/bookings/{instance.id}"
    booking_full_url = build_absolute_url(f"/viewings/{instance.id}", force_login=True)
    _queue_booking_emails(
        owner=owner,
        booker=booker,
        room=room,
        booking=instance,
        booking_deep_link=booking_deep_link,
        booking_full_url=booking_full_url,
    )


def install_booking_creation_query_optimization():
    global _INSTALLED
    if _INSTALLED:
        return

    from propertylist_app.signals import booking_created_queue_emails

    post_save.disconnect(booking_created_queue_emails, sender=Booking)
    post_save.connect(
        _optimized_booking_created_queue_emails,
        sender=Booking,
        dispatch_uid="booking_creation_query_optimization",
    )
    _INSTALLED = True
