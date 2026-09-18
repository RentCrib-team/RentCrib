from __future__ import annotations

import os
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import DateTimeField, OuterRef, Subquery
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import (
    Notification,
    Payment,
    Room,
    RoomListingBenefit,
    UserProfile,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.listing_entitlements import (
    consume_complimentary_listing_benefit,
    notify_complimentary_listing_auto_renewal,
)
from propertylist_app.services.realtime import push_user_realtime_event


PRODUCTION_WARNING_DAYS = 7
QA_WARNING_AFTER_MINUTES = 15
QA_EXPIRY_AFTER_MINUTES = 20


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
    """
    Rooms eligible for advert-expiry processing.

    A complimentary period is a new advertising cycle even though it has no
    Payment row, so QA timing uses the later of payment.updated_at and the
    benefit's consumed_at timestamp.
    """
    latest_payment = (
        Payment.objects.filter(
            room_id=OuterRef("pk"),
            status=Payment.Status.SUCCEEDED,
        )
        .order_by("-updated_at")
    )
    benefit = RoomListingBenefit.objects.filter(room_id=OuterRef("pk"))

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
            complimentary_cycle_started_at=Subquery(
                benefit.values("consumed_at")[:1],
                output_field=DateTimeField(),
            ),
            complimentary_cycle_id=Subquery(benefit.values("id")[:1]),
        )
    )


def _effective_cycle_start(room: Room):
    starts = [
        value
        for value in (
            getattr(room, "paid_cycle_started_at", None),
            getattr(room, "complimentary_cycle_started_at", None),
        )
        if value is not None
    ]
    return max(starts) if starts else None


def _cycle_key(room: Room) -> str:
    paid_start = getattr(room, "paid_cycle_started_at", None)
    complimentary_start = getattr(room, "complimentary_cycle_started_at", None)

    if (
        complimentary_start is not None
        and (
            paid_start is None
            or complimentary_start >= paid_start
        )
        and getattr(room, "complimentary_cycle_id", None)
    ):
        return f"benefit:{room.complimentary_cycle_id}"

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
    """Queue exactly one pre-expiry warning per advertising cycle."""
    now = timezone.now()
    today = timezone.localdate()
    qa_mode = _qa_mode()

    rooms = _active_paid_rooms_with_cycle_start().filter(paid_until__gte=today)
    if not qa_mode:
        rooms = rooms.filter(
            paid_until__lte=today + timedelta(days=PRODUCTION_WARNING_DAYS)
        )

    queued = 0
    for room in rooms:
        cycle_start = _effective_cycle_start(room)
        if qa_mode:
            if (
                cycle_start is None
                or cycle_start > now - timedelta(minutes=QA_WARNING_AFTER_MINUTES)
            ):
                continue

        owner = room.property_owner
        if not _notifications_allowed(owner):
            continue

        cycle_key = _cycle_key(room)
        if qa_mode:
            room_paid_until = "in about 5 minutes (QA test)"
            body = (
                f"QA reminder: your listing '{room.title}' has been active for "
                f"at least {QA_WARNING_AFTER_MINUTES} minutes. Its current "
                f"listing period still expires on {room.paid_until}."
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
            cycle_start=cycle_start,
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
    """
    End an advertising cycle, consuming the room's reserved complimentary
    30-day benefit first when the room is still actively available.
    """
    now = timezone.now()
    today = timezone.localdate()
    qa_mode = _qa_mode()

    rooms = _active_paid_rooms_with_cycle_start()
    if qa_mode:
        # Only a currently-live entitlement can reach the accelerated
        # 20-minute boundary. Once we normalise it to yesterday below, the
        # next sweep must ignore that same cycle.
        rooms = rooms.filter(paid_until__gte=today)
    else:
        rooms = rooms.filter(paid_until__lt=today)

    processed = 0

    for room in rooms:
        cycle_start = _effective_cycle_start(room)
        if qa_mode:
            if (
                cycle_start is None
                or cycle_start > now - timedelta(minutes=QA_EXPIRY_AFTER_MINUTES)
            ):
                continue

        original_paid_until = room.paid_until

        activated = consume_complimentary_listing_benefit(
            room,
            reason=RoomListingBenefit.ConsumptionReason.AUTOMATIC_EXTENSION,
            base_date=original_paid_until,
        )
        if activated is not None:
            renewed_room, benefit = activated
            notify_complimentary_listing_auto_renewal(
                renewed_room,
                benefit,
            )
            processed += 1
            continue

        # In accelerated QA mode the real paid_until date may still be weeks
        # away. Once the 20-minute cycle elapses, normalise to an expired date.
        if qa_mode and room.paid_until >= today:
            expired_date = today - timedelta(days=1)
            Room.objects.filter(pk=room.pk).update(
                paid_until=expired_date,
                updated_at=now,
            )
            room.paid_until = expired_date

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
                cycle_key=_cycle_key(room),
                room_paid_until=str(original_paid_until or ""),
            )

        processed += 1

    return processed
