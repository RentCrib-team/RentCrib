from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import (
    Notification,
    Payment,
    Room,
    RoomListingBenefit,
    Tenancy,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event


COMPLIMENTARY_LISTING_DAYS = 30


def listing_fee_gbp() -> Decimal:
    """Single backend source of truth for the landlord listing fee."""
    return Decimal(str(getattr(settings, "LISTING_FEE_GBP", "7.99")))


def grant_complimentary_listing_benefit(payment: Payment):
    """
    Grant a room exactly one complimentary 30-day listing benefit.

    Legacy listing payments are grandfathered. If a room was successfully paid
    for under the old £1 QA/listing price before the £7.99 programme launched,
    that historical payment still counts as the room's qualifying first paid
    listing. We preserve the original Payment amount for audit accuracy and
    attach the benefit to the earliest successful payment instead of rewriting
    transaction history.

    The RoomListingBenefit one-to-one relation is the source of truth for
    whether the room has already received its one-time benefit. Later payments
    can never replenish it.
    """
    if payment.status != Payment.Status.SUCCEEDED or payment.room_id is None:
        return None, False

    existing = RoomListingBenefit.objects.filter(room_id=payment.room_id).first()
    if existing is not None:
        return existing, False

    qualifying_payment = (
        Payment.objects.filter(
            room_id=payment.room_id,
            status=Payment.Status.SUCCEEDED,
        )
        .order_by("created_at", "id")
        .first()
    )
    if qualifying_payment is None:
        return None, False

    return RoomListingBenefit.objects.get_or_create(
        room_id=payment.room_id,
        defaults={
            "granted_from_payment": qualifying_payment,
            "granted_at": timezone.now(),
        },
    )


@transaction.atomic
def consume_complimentary_listing_benefit(
    room: Room,
    *,
    reason: str,
    base_date=None,
):
    """
    Atomically consume the room's reserved complimentary listing period.

    Returns (locked_room, benefit) when activated, otherwise None.
    """
    locked_room = Room.all_objects.select_for_update().get(pk=room.pk)

    if locked_room.is_deleted:
        return None

    live_tenancy_exists = Tenancy.objects.filter(
        room_id=locked_room.pk,
        status__in=[
            Tenancy.STATUS_CONFIRMED,
            Tenancy.STATUS_ACTIVE,
        ],
    ).exists()
    if live_tenancy_exists:
        return None

    benefit = (
        RoomListingBenefit.objects.select_for_update()
        .filter(
            room_id=locked_room.pk,
            consumed_at__isnull=True,
        )
        .first()
    )
    if benefit is None:
        return None

    now = timezone.now()
    today = timezone.localdate()

    if reason == RoomListingBenefit.ConsumptionReason.AUTOMATIC_EXTENSION:
        if (
            locked_room.status != Room.Lifecycle.ACTIVE
            or not locked_room.is_available
        ):
            return None
        entitlement_base = base_date or locked_room.paid_until or today
        period_start = entitlement_base + timedelta(days=1)
        period_end = entitlement_base + timedelta(
            days=COMPLIMENTARY_LISTING_DAYS
        )
    elif reason == RoomListingBenefit.ConsumptionReason.FUTURE_RELIST:
        period_start = today
        period_end = today + timedelta(days=COMPLIMENTARY_LISTING_DAYS)
    else:
        raise ValueError("Unsupported complimentary listing consumption reason.")

    benefit.consumed_at = now
    benefit.consumed_reason = reason
    benefit.complimentary_period_start = period_start
    benefit.complimentary_period_end = period_end
    benefit.save(
        update_fields=[
            "consumed_at",
            "consumed_reason",
            "complimentary_period_start",
            "complimentary_period_end",
            "updated_at",
        ]
    )

    locked_room.paid_until = period_end
    locked_room.status = Room.Lifecycle.ACTIVE
    locked_room.is_available = True

    update_fields = [
        "paid_until",
        "status",
        "is_available",
        "updated_at",
    ]

    if reason == RoomListingBenefit.ConsumptionReason.FUTURE_RELIST:
        locked_room.relisted_at = now
        update_fields.append("relisted_at")

    locked_room.save(update_fields=update_fields)
    return locked_room, benefit


def notify_complimentary_listing_auto_renewal(
    room: Room,
    benefit: RoomListingBenefit,
) -> None:
    """Create exactly one bell + queued email for the automatic free renewal."""
    owner = room.property_owner
    title = "Your listing has been renewed free for 30 days"
    body = (
        f"Your room '{room.title}' has been automatically renewed for another "
        "30 days at no charge because it was still available at the end of "
        "your paid listing period."
    )

    notification, created = Notification.objects.get_or_create(
        user=owner,
        type="listing_complimentary_renewed",
        target_type="room",
        target_id=room.pk,
        defaults={
            "title": title,
            "body": body,
            "audience": Notification.Audience.LANDLORD,
        },
    )

    if created:
        push_user_realtime_event(
            owner.id,
            "new_notification",
            {
                "kind": "listing_complimentary_renewed",
                "notification_id": notification.id,
                "target_type": "room",
                "target_id": room.pk,
            },
        )

    template_exists = NotificationTemplate.objects.filter(
        key="listing.complimentary_renewed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).exists()
    if not template_exists:
        return

    already_queued = OutboundNotification.objects.filter(
        user=owner,
        template_key="listing.complimentary_renewed",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        context__benefit_id=benefit.pk,
    ).exists()
    if already_queued:
        return

    cta_path = f"/my-listings?tab=active&room={room.pk}"
    OutboundNotification.objects.create(
        user=owner,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="listing.complimentary_renewed",
        scheduled_for=timezone.now(),
        context={
            "user": {
                "first_name": owner.first_name or owner.username,
            },
            "room": {
                "id": room.pk,
                "title": room.title,
                "paid_until": str(room.paid_until or ""),
            },
            "room_id": room.pk,
            "benefit_id": benefit.pk,
            "deep_link": f"/app/listings/{room.pk}",
            "cta_url": build_absolute_url(cta_path, force_login=True),
        },
    )
