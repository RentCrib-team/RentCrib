import math

from rest_framework.exceptions import ValidationError

from propertylist_app.validators import haversine_miles, validate_radius_miles
from propertylist_app.services.geo import geocode_postcode_cached


def install_search_radius_candidate_optimization():
    """Prefilter postcode-search candidates in SQL before Haversine work."""
    from propertylist_app.api.views.public import SearchRoomsView

    if getattr(SearchRoomsView, "_radius_candidate_optimization_installed", False):
        return

    original_get_queryset = SearchRoomsView.get_queryset

    def get_queryset(self):
        params = self.request.query_params
        postcode = (params.get("postcode") or "").strip()

        if not postcode:
            return original_get_queryset(self)

        raw_radius = params.get("radius_miles", 10)
        try:
            radius_miles = validate_radius_miles(raw_radius, max_miles=500)
        except ValidationError:
            radius_miles = 10

        lat, lon = geocode_postcode_cached(postcode)

        # Build the normal filtered queryset without entering the legacy
        # postcode branch, which materialises every geocoded candidate.
        mutable_params = self.request._request.GET.copy()
        mutable_params.pop("postcode", None)
        mutable_params.pop("radius_miles", None)
        mutable_params["ordering"] = "newest"
        original_params = self.request._request.GET
        self.request._request.GET = mutable_params
        try:
            qs = original_get_queryset(self)
        finally:
            self.request._request.GET = original_params

        # A cheap bounding box is a superset of the requested circle. The
        # exact Haversine check below remains the authority for inclusion.
        earth_radius_miles = 3958.7613
        angular_radius = radius_miles / earth_radius_miles
        latitude_delta = math.degrees(angular_radius)
        latitude_min = max(-90.0, lat - latitude_delta)
        latitude_max = min(90.0, lat + latitude_delta)

        cosine_latitude = abs(math.cos(math.radians(lat)))
        if cosine_latitude < 1e-12:
            longitude_delta = 180.0
        else:
            longitude_delta = min(
                180.0,
                math.degrees(angular_radius / cosine_latitude) * 1.01,
            )

        base_qs = qs.exclude(
            latitude__isnull=True,
        ).exclude(
            longitude__isnull=True,
        ).filter(
            latitude__gte=latitude_min,
            latitude__lte=latitude_max,
        )

        if longitude_delta < 180.0:
            longitude_min = lon - longitude_delta
            longitude_max = lon + longitude_delta
            if longitude_min >= -180.0 and longitude_max <= 180.0:
                base_qs = base_qs.filter(
                    longitude__gte=longitude_min,
                    longitude__lte=longitude_max,
                )
            elif longitude_min < -180.0:
                base_qs = base_qs.filter(
                    longitude__gte=longitude_min + 360.0,
                ) | base_qs.filter(
                    longitude__lte=longitude_max,
                )
            else:
                base_qs = base_qs.filter(
                    longitude__gte=longitude_min,
                ) | base_qs.filter(
                    longitude__lte=longitude_max - 360.0,
                )

        distances = []
        for room in base_qs.select_related(None).only("id", "latitude", "longitude"):
            distance = haversine_miles(lat, lon, room.latitude, room.longitude)
            if distance <= radius_miles:
                distances.append((room.id, distance))

        distances.sort(key=lambda item: item[1])
        ids_in_radius = [room_id for room_id, _ in distances]
        self._ordered_ids = ids_in_radius
        self._distance_by_id = {
            room_id: distance for room_id, distance in distances
        }
        qs = qs.filter(id__in=ids_in_radius)

        raw_ordering = params.get("ordering")
        ordering = (raw_ordering or "").strip()
        ui_sort_map = {
            "default": "-created_at",
            "newest": "-created_at",
            "last_updated": "-updated_at",
            "price_asc": "price_per_month",
            "price_desc": "-price_per_month",
            "distance": "distance_miles",
        }
        ordering = ui_sort_map.get(ordering, ordering)
        if not ordering:
            ordering = "distance_miles"

        if ordering not in {"distance_miles", "-distance_miles"}:
            allowed = {
                "price_per_month": "price_per_month",
                "-price_per_month": "-price_per_month",
                "avg_rating": "avg_rating",
                "-avg_rating": "-avg_rating",
                "created_at": "created_at",
                "-created_at": "-created_at",
                "updated_at": "updated_at",
                "-updated_at": "-updated_at",
            }
            mapped = allowed.get(ordering)
            if mapped:
                qs = qs.order_by(mapped)

        return qs

    SearchRoomsView.get_queryset = get_queryset
    SearchRoomsView._radius_candidate_optimization_installed = True
