from django.db.models import Q

from propertylist_app.models import Tenancy


def get_tenancy_stats():
    return {
        "all_tenancies": Tenancy.objects.count(),
        "proposed_tenancies": Tenancy.objects.filter(
            status=Tenancy.STATUS_PROPOSED
        ).count(),
        "confirmed_tenancies": Tenancy.objects.filter(
            status=Tenancy.STATUS_CONFIRMED
        ).count(),
        "active_tenancies": Tenancy.objects.filter(
            status=Tenancy.STATUS_ACTIVE
        ).count(),
        "ended_tenancies": Tenancy.objects.filter(
            status=Tenancy.STATUS_ENDED
        ).count(),
        "cancelled_tenancies": Tenancy.objects.filter(
            status=Tenancy.STATUS_CANCELLED
        ).count(),
    }


def get_admin_tenancies_queryset(params):
    qs = (
        Tenancy.objects
        .select_related("tenant", "landlord", "room")
        .all()
        .order_by("-created_at")
    )

    status_filter = (params.get("status") or "").strip().lower()

    if status_filter:
        qs = qs.filter(status=status_filter)

    property_type = (params.get("property_type") or "").strip()
    if property_type:
        qs = qs.filter(room__property_type__iexact=property_type)

    search = (params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(tenant__username__icontains=search)
            | Q(tenant__email__icontains=search)
            | Q(landlord__username__icontains=search)
            | Q(landlord__email__icontains=search)
            | Q(room__title__icontains=search)
        )

    return qs


def serialize_admin_tenancy(tenancy):
    return {
        "id": tenancy.id,
        "tenancy_id": f"TN{tenancy.id:04d}",
        "tenant": tenancy.tenant.get_full_name() or tenancy.tenant.username,
        "tenant_email": tenancy.tenant.email,
        "landlord": tenancy.landlord.get_full_name() or tenancy.landlord.username,
        "landlord_email": tenancy.landlord.email,
        "room_id": tenancy.room.id,
        "room_title": tenancy.room.title,
        "property_type": tenancy.room.property_type,
        "move_in_date": tenancy.move_in_date,
        "duration_months": tenancy.duration_months,
        "status": tenancy.status,
        "created_at": tenancy.created_at,
    }