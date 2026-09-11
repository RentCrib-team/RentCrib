from django.db.models import Count, Q
from rest_framework.exceptions import NotFound

from propertylist_app.models import City


def _parse_bool(value):
    if value is None or value == "":
        return None

    value = str(value).strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def get_admin_cities_queryset(params):
    qs = City.objects.annotate(room_count=Count("rooms", distinct=True))

    search = (params.get("search") or params.get("q") or "").strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(slug__icontains=search)
        )

    is_active = _parse_bool(params.get("is_active"))
    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    is_featured = _parse_bool(params.get("is_featured"))
    if is_featured is not None:
        qs = qs.filter(is_featured=is_featured)

    return qs.order_by("display_order", "name")


def get_admin_city(city_id):
    try:
        return (
            City.objects
            .annotate(room_count=Count("rooms", distinct=True))
            .get(pk=city_id)
        )
    except City.DoesNotExist as exc:
        raise NotFound("City not found.") from exc
