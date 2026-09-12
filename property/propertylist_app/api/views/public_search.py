from django.db.models import Q

from propertylist_app.services.city_assignment import resolve_city_lookup

from .public import SearchRoomsView as LegacySearchRoomsView


class SearchRoomsView(LegacySearchRoomsView):
    """Apply city searches through Room.city, with a legacy null-city bridge."""

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

        # Canonical city assignment is authoritative. During rollout, however,
        # existing rooms can legitimately have city=NULL until the controlled
        # backfill command has processed them. Preserve search visibility for
        # only those legacy rows by falling back to their address text.
        return queryset.filter(
            Q(city_id=city.id)
            | Q(city__isnull=True, location__icontains=city.name)
        )
