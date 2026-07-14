from datetime import timedelta

from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from propertylist_app.models import Room, RoomImage


def get_admin_listing_metrics():
    today = timezone.localdate()
    pending_image_rooms = RoomImage.objects.filter(
        room=OuterRef("pk"),
        status="pending",
    )

    alive_rooms = Room.objects.filter(is_deleted=False).annotate(
        has_pending_image=Exists(pending_image_rooms)
    )

    return {
        "total_listing": Room.objects.count(),
        "active_listing": alive_rooms.filter(
            status="active",
            paid_until__isnull=False,
            paid_until__gte=today,
        ).count(),
        "pending_listing": alive_rooms.filter(has_pending_image=True).count(),
        "hidden_listing": alive_rooms.filter(status="hidden").count(),
        "drafts_listing": alive_rooms.filter(
            Q(status="draft") | Q(paid_until__isnull=True)
        ).count(),
        "unpublished_listing": alive_rooms.filter(status="hidden").count(),
        "expired_listing": alive_rooms.filter(
            paid_until__isnull=False,
            paid_until__lt=today,
        ).count(),
        "edited_listing": alive_rooms.exclude(
          updated_at__date=models.F("created_at__date")
        ).count(),
        "deleted_listing": Room.objects.filter(is_deleted=True).count(),
    }


def get_admin_listings_queryset(params):
    today = timezone.localdate()

    pending_image_rooms = RoomImage.objects.filter(
        room=OuterRef("pk"),
        status="pending",
    )

    qs = (
        Room.objects.all()
        .select_related("property_owner", "category")
        .annotate(has_pending_image=Exists(pending_image_rooms))
    )

    search = (params.get("search") or params.get("q") or "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(location__icontains=search)
            | Q(property_owner__email__icontains=search)
            | Q(property_owner__first_name__icontains=search)
            | Q(property_owner__last_name__icontains=search)
            | Q(category__name__icontains=search)
        )

    status_filter = (params.get("status") or "").strip().lower()
    if status_filter in ("active",):
        qs = qs.filter(
            is_deleted=False,
            status="active",
            paid_until__isnull=False,
            paid_until__gte=today,
        )
    elif status_filter in ("pending",):
        qs = qs.filter(is_deleted=False, has_pending_image=True)
    elif status_filter in ("hidden",):
        qs = qs.filter(is_deleted=False, status="hidden")
    elif status_filter in ("draft", "drafts"):
        qs = qs.filter(is_deleted=False).filter(
            Q(status="draft") | Q(paid_until__isnull=True)
        )
    elif status_filter in ("unpublished",):
        qs = qs.filter(is_deleted=False, status="hidden")
    elif status_filter in ("expired",):
        qs = qs.filter(
            is_deleted=False,
            paid_until__isnull=False,
            paid_until__lt=today,
        )
    elif status_filter in ("edited",):
        qs = qs.filter(is_deleted=False).exclude(
            updated_at__date=models.F("created_at__date")
        )
    elif status_filter in ("deleted", "soft_deleted", "soft-deleted"):
        qs = qs.filter(is_deleted=True)
    elif status_filter in ("all", ""):
        pass

    category = (params.get("category") or "").strip()
    if category:
        qs = qs.filter(
            Q(category__id__iexact=category)
            | Q(category__name__iexact=category)
            | Q(category__slug__iexact=category)
        )

    furnished = params.get("furnished")
    if furnished in ("true", "1", "yes", "furnished"):
        qs = qs.filter(furnished=True)
    elif furnished in ("false", "0", "no", "unfurnished"):
        qs = qs.filter(furnished=False)

    bills = params.get("bills")
    if bills in ("true", "1", "yes", "included"):
        qs = qs.filter(bills_included=True)
    elif bills in ("false", "0", "no", "not_included", "not-included"):
        qs = qs.filter(bills_included=False)

    parking = params.get("parking")
    if parking in ("true", "1", "yes", "available"):
        qs = qs.filter(parking_available=True)
    elif parking in ("false", "0", "no", "not_available", "not-available"):
        qs = qs.filter(parking_available=False)

    availability = params.get("availability")
    if availability in ("true", "1", "yes", "available"):
        qs = qs.filter(is_available=True)
    elif availability in ("false", "0", "no", "not_available", "not-available"):
        qs = qs.filter(is_available=False)

    sort_by = (params.get("sort_by") or "most_recent").strip().lower()
    sort_map = {
        "most_recent": "-created_at",
        "oldest": "created_at",
        "price_high": "-price_per_month",
        "price_low": "price_per_month",
        "title": "title",
    }

    return qs.order_by(sort_map.get(sort_by, "-created_at"))


def get_listing_display_status(room):
    today = timezone.localdate()

    if room.is_deleted:
        return "deleted"

    if getattr(room, "has_pending_image", False):
        return "pending"

    if room.status == "draft" or not room.paid_until:
        return "draft"

    if room.paid_until and room.paid_until < today:
        return "expired"

    if room.status == "hidden":
        return "hidden"

    return room.status