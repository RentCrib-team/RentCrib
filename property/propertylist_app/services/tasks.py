from __future__ import annotations
from datetime import date,timedelta
from typing import Optional

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from celery import shared_task
from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Room, Message, Notification, UserProfile,Booking


def expire_paid_listings(today: Optional[date] = None) -> int:
    """
    Hide rooms whose paid_until is in the past and notify the owner.
    Returns the count of rooms affected.
    """
    today = today or timezone.localdate()
    # Lock in a transaction to avoid partial updates
    with transaction.atomic():
        to_hide = (
            Room.objects
            .filter(paid_until__isnull=False, paid_until__lt=today, status="active", is_deleted=False)
            .select_related("property_owner")
        )

        updated_count = 0
        for room in to_hide:
            room.status = "hidden"
            room.save(update_fields=["status"])
            # Create a lightweight notification
            try:
                profile, _ = UserProfile.objects.get_or_create(user=room.property_owner)

                # Respect Account -> Notifications -> Reminders toggle
                if getattr(profile, "notify_reminders", True):
                    Notification.objects.create(
                        user=room.property_owner,
                        type="listing_expired",
                        title="Your listing has expired",
                        body=f"Room '{room.title}' is now hidden because the payment period ended.",
                    )
            except Exception:
                # Never let a notification failure block the job
                pass

            updated_count += 1

        return updated_count


def send_new_message_email(message_id: int) -> int:
    """
    Send a simple email to the other participant in the message thread.
    Returns 1 if sent, 0 otherwise.
    """
    try:
        msg = Message.objects.select_related("thread", "sender").get(pk=message_id)
    except Message.DoesNotExist:
        return 0

    # Determine recipient: the other participant in a 2-person thread
    participants = list(msg.thread.participants.all())
    if len(participants) != 2:
        return 0

    recipient = participants[0] if participants[1].id == msg.sender_id else participants[1]
    if not recipient.email:
        return 0

    subject = f"New message from {msg.sender.username}"
    body = (
        f"You have a new message in your RentOut inbox.\n\n"
        f"From: {msg.sender.username}\n"
        f"Message: {msg.body}\n"
        f"\nLog in to reply."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")

    try:
        sent = send_mail(subject, body, from_email, [recipient.email], fail_silently=True)
        return int(bool(sent))
    except Exception:
        return 0



@shared_task
def notify_upcoming_bookings(minutes_ahead: int = 5) -> int:
    """
    Queue an upcoming-viewing reminder shortly before the viewing starts.

    Temporary staging/testing rule:
    - Reminder becomes eligible 5 minutes before booking.start.

    Production rule later:
    - Change the default to 24 hours:
      minutes_ahead = 24 * 60

    Creates only once per booking:
      1) in-app notification
      2) queued booking.reminder email
    """
    now = timezone.now()
    window_end = now + timedelta(minutes=minutes_ahead)

    bookings = (
        Booking.objects
        .filter(
            is_deleted=False,
            canceled_at__isnull=True,
            start__gte=now,
            start__lte=window_end,
        )
        .select_related("user", "room")
    )

    template = (
        NotificationTemplate.objects.filter(
            key="booking.reminder",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )

    processed = 0

    for booking in bookings:
        user = getattr(booking, "user", None)
        if not user:
            continue

        profile, _ = UserProfile.objects.get_or_create(user=user)

        if not getattr(profile, "notify_reminders", True):
            continue

        room = getattr(booking, "room", None)
        room_title = getattr(room, "title", "your room")

        start_local = timezone.localtime(booking.start)
        start_str = start_local.strftime("%d %b %Y, %H:%M")

        title = "Upcoming viewing"
        body = (
            f"Reminder: your viewing for '{room_title}' starts on "
            f"{start_str}. (booking_id={booking.id})"
        )

        # 1. Create the in-app reminder once per booking.
        already_in_app = Notification.objects.filter(
            user=user,
            type="booking_reminder",
            body__icontains=f"(booking_id={booking.id})",
        ).exists()

        if not already_in_app:
            Notification.objects.create(
                user=user,
                type="booking_reminder",
                title=title,
                body=body,
            )

        # 2. Queue the email once per booking.
        if template:
            already_queued = OutboundNotification.objects.filter(
                user=user,
                template_key="booking.reminder",
                channel=NotificationTemplate.CHANNEL_EMAIL,
                context__booking_id=booking.id,
            ).exists()

            if not already_queued:
                frontend_base_url = getattr(
                    settings,
                    "FRONTEND_BASE_URL",
                    "http://localhost:3000",
                ).rstrip("/")

                OutboundNotification.objects.create(
                    user=user,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.reminder",
                    scheduled_for=now,
                    context={
                        "user": {
                            "first_name": user.first_name,
                        },
                        "booking_id": booking.id,
                        "room_title": room_title,
                        "starts_at": start_str,
                        "cta_url": f"{frontend_base_url}/inbox",
                    },
                )

        processed += 1

    return processed
                
                