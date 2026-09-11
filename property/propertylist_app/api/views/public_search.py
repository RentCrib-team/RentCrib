from propertylist_app.services.city_assignment import resolve_city_lookup

from .public import SearchRoomsView as LegacySearchRoomsView


class SearchRoomsView(LegacySearchRoomsView):
    """Apply the city query parameter through Room.city, not Room.location."""

    def get_queryset(self):
        city_value = (self.request.query_params.get("city") or "").strip()
        if not city_value:
            return super().get_queryset()

        city = resolve_city_lookup(city_value, active_only=True)

        raw_request = self.request._request
        original_get = raw_request.GET
        params_without_city = original_get.copy()
        params_without_city.pop("city", None)
        raw_request.GET = params_without_city

        try:
            queryset = super().get_queryset()
        finally:
            raw_request.GET = original_get

        if city is None:
            return queryset.none()

        return queryset.filter(city_id=city.id)
