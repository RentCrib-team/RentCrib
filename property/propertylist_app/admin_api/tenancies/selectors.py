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
    
    
    
def get_tenancy_confirmation_status(tenancy):
    if tenancy.landlord_confirmed_at and tenancy.tenant_confirmed_at:
        return "confirmed"

    return "pending"


def get_admin_tenancy_detail(tenancy_id):
    tenancy = (
        Tenancy.objects
        .select_related(
            "tenant",
            "tenant__profile",
            "landlord",
            "landlord__profile",
            "room",
            "room__property_owner",
        )
        .get(id=tenancy_id)
    )

    tenant_profile = getattr(tenancy.tenant, "profile", None)
    landlord_profile = getattr(tenancy.landlord, "profile", None)
    room = tenancy.room

    return {
        "id": tenancy.id,
        "tenancy_id": f"T{tenancy.id:05d}",
        "status": tenancy.status,
        "confirmation": get_tenancy_confirmation_status(tenancy),
        "move_in_date": tenancy.move_in_date,
        "duration_months": tenancy.duration_months,
        "created_at": tenancy.created_at,
        "updated_at": tenancy.updated_at,

        "tenant": {
            "id": tenancy.tenant.id,
            "name": tenancy.tenant.get_full_name() or tenancy.tenant.username,
            "email": tenancy.tenant.email,
            "phone": getattr(tenant_profile, "phone", None),
            "avatar": tenant_profile.avatar.url if tenant_profile and tenant_profile.avatar else None,
        },

        "landlord": {
            "id": tenancy.landlord.id,
            "name": tenancy.landlord.get_full_name() or tenancy.landlord.username,
            "email": tenancy.landlord.email,
            "phone": getattr(landlord_profile, "phone", None),
            "avatar": landlord_profile.avatar.url if landlord_profile and landlord_profile.avatar else None,
        },

        "listing": {
            "id": room.id,
            "title": room.title,
            "property_type": room.property_type,
            "price": str(room.price_per_month),
            "owner": room.property_owner.get_full_name() or room.property_owner.username,
            "description": room.description,
        },
    }    