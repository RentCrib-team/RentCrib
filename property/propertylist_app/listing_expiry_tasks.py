from __future__ import annotations

import os
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import DateTimeField, OuterRef, Subquery
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Notification, Payment, Room, UserProfile
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event


PRODUCTION_WARNING_DAYS = 7
QA_WARNING_AFTER_MINUTES = 15


def _qa_mode() -> bool:
    """Enable accelerated warning timing on QA/staging, never production by accident."""
    explicit = os.getenv("LISTING_EXPIRY_QA_MODE", "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}

    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    if environment in {"staging", "qa", "test"}:
        return True

    configured_urls = " ".join(
        str(getattr(settings, name, "") or "").lower()
        for name in ("SITE_URL", "FRONTEND_BASE_URL", "FRONTEND_URL", "WEB_URL")
    )
    return "staging" in configured_urls


def _active_paid_rooms_with_cycle_start():
    """Rooms eligible for advert-expiry processing, with latest paid-cycle time."""
    latest_payment = (
        Payment.objects.filter(
            room_id=OuterRef("pk"),
            status=Payment.Status.SUCCEEDED,
        )
        .order_by("-updated_at")
    )

    return (
        Room.objects.select_related("property_owner")
        .filter(
            status=Room.Lifecycle.ACTIVE,
            is_deleted=False,
            is_available=True,
            paid_until__isnull=False,
        )
        .annotate(
            paid_cycle_started_at=Subquery(
                latest_payment.values("updated_at")[:1],
                output_field=DateTimeField(),
            ),
            paid_cycle_id=Subquery(latest_payment.values("id")[:1]),
        )
    )


def _cycle_key(room: Room) -> str:
    if getattr(room, "paid_cycle_id", None):
        return f"payment:{room.paid_cycle_id}"
    return f"room:{room.pk}:paid-until:{room.paid_until}"


def _notifications_allowed(owner) -> bool:
    profile, _ = UserProfile.objects.get_or_create(user=owner)
    return bool(getattr(profile, "notify_reminders", True))


def _queue_email(*, room: Room, template_key: str, cycle_key: str, room_paid_until: str) -> bool:
    template = NotificationTemplate.objects.filter(
        key=template_key,
        is_active=True,
        channel=NotificationTemplate.CHANNEL_EMAIL,
    ).first()
    if template is None:
        return False

    owner = room.property_owner
    exists = OutboundNotification.objects.filter(
        user=owner,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context__room_id=room.pk,
        context__cycle_key=cycle_key,
    ).exists()
    if exists:
        return False

    OutboundNotification.objects.create(
        user=owner,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        scheduled_for=timezone.now(),
        context={
            "user": {
                "first_name": owner.first_name or owner.username,
            },
            "room": {
                "id": room.pk,
                "title": room.title,
                "paid_until": room_paid_until,
            },
            "room_id": room.pk,
            "paid_until": str(room.paid_until or ""),
            "cycle_key": cycle_key,
            "deep_link": f"/app/listings/{room.pk}",
            "renew_url": build_absolute_url("/my-listings", force_login=False),
            "cta_url": build_absolute_url("/my-listings", force_login=False),
        },
    )
    return True


def _create_bell_once(*, room: Room, notification_type: str, title: str, body: str, cycle_start) -> bool:
    owner = room.property_owner
    existing = Notification.objects.filter(
        user=owner,
        type=notification_type,
        target_type="room",
        target_id=room.pk,
    )
    if cycle_start is not None:
        existing = existing.filter(created_at__gte=cycle_start)
    if existing.exists():
        return False

    notification = Notification.objects.create(
        user=owner,
        type=notification_type,
        target_type="room",
        target_id=room.pk,
        title=title,
        body=body,
        audience=Notification.Audience.LANDLORD,
    )
    push_user_realtime_event(
        owner.id,
        "new_notification",
        {
            "kind": notification_type,
            "notification_id": notification.id,
            "target_type": "room",
            "target_id": room.pk,
        },
    )
    return True


@shared_task(name="propertylist_app.listing_expiry_warning_sweep")
def listing_expiry_warning_sweep() -> int:
    """Queue exactly one pre-expiry warning per paid advertising cycle."""
    now = timezone.now()
    today = timezone.localdate()
    qa_mode = _qa_mode()
    rooms = _active_paid_rooms_with_cycle_start().filter(paid_until__gte=today)

    if qa_mode:
        rooms = rooms.filter(
            paid_cycle_started_at__isnull=False,
            paid_cycle_started_at__lte=(
                now - timedelta(minutes=QA_WARNING_AFTER_MINUTES)
            ),
        )
    else:
        rooms = rooms.filter(
            paid_until__lte=today + timedelta(days=PRODUCTION_WARNING_DAYS)
        )

    queued = 0
    for room in rooms:
        owner = room.property_owner
        if not _notifications_allowed(owner):
            continue

        cycle_key = _cycle_key(room)
        if qa_mode:
            room_paid_until = str(room.paid_until)
            body = (
                f"QA reminder: your listing '{room.title}' has been active for "
                f"at least {QA_WARNING_AFTER_MINUTES} minutes. Its paid listing "
                f"period still expires on {room.paid_until}."
            )
        else:
            room_paid_until = str(room.paid_until)
            body = (
                f"Your listing '{room.title}' is expiring on {room.paid_until}. "
                "Renew it to keep it visible."
            )

        _create_bell_once(
            room=room,
            notification_type="listing_expiring",
            title="Your listing is expiring soon",
            body=body,
            cycle_start=getattr(room, "paid_cycle_started_at", None),
        )
        if _queue_email(
            room=room,
            template_key="listing.expiring",
            cycle_key=cycle_key,
            room_paid_until=room_paid_until,
        ):
            queued += 1

    return queued


@shared_task(name="propertylist_app.listing_expiry_sweep")
def listing_expiry_sweep() -> int:
    """Expire adverts only when their real paid advertising period has ended."""
    today = timezone.localdate()
    rooms = _active_paid_rooms_with_cycle_start().filter(paid_until__lt=today)

    expired = 0
    for room in rooms:
        cycle_start = getattr(room, "paid_cycle_started_at", None)
        cycle_key = _cycle_key(room)
        original_paid_until = room.paid_until

        owner = room.property_owner
        if _notifications_allowed(owner):
            _create_bell_once(
                room=room,
                notification_type="listing_expired",
                title="Your listing has expired",
                body=(
                    f"Your listing '{room.title}' has now expired and is no "
                    "longer publicly visible. Renew it from Ads Expired to "
                    "advertise it again."
                ),
                cycle_start=cycle_start,
            )
            _queue_email(
                room=room,
                template_key="listing.expired",
                cycle_key=cycle_key,
                room_paid_until=str(original_paid_until or ""),
            )

        expired += 1

    return expired
