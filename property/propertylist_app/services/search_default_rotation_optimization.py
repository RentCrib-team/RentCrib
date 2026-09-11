from django.db.models import Case, IntegerField, When


def install_search_default_rotation_optimization():
    """Bound default fair-rotation work to the first 40 rooms."""
    from propertylist_app.api.views.public import SearchRoomsView

    if getattr(SearchRoomsView, "_bounded_fair_rotation_installed", False):
        return

    original_get_queryset = SearchRoomsView.get_queryset

    def get_queryset(self):
        params = self.request.query_params
        postcode = (params.get("postcode") or "").strip()
        raw_ordering_param = params.get("ordering")
        apply_fair_rotation = (
            not postcode
            and raw_ordering_param in (None, "", "default")
        )

        if not apply_fair_rotation:
            return original_get_queryset(self)

        # Prevent the legacy implementation from entering its expensive
        # fair-rotation branch. Explicit newest ordering is logically the same
        # base order as default browsing, but it skips materialising every
        # remaining room id into Python.
        mutable_params = self.request._request.GET.copy()
        mutable_params["ordering"] = "newest"
        original_params = self.request._request.GET
        self.request._request.GET = mutable_params
        try:
            qs = original_get_queryset(self)
        finally:
            self.request._request.GET = original_params

        room_ids = list(
            qs.order_by("-created_at")
            .values_list("id", flat=True)[:40]
        )

        if len(room_ids) <= 1:
            return qs

        # Preserve RentCrib's existing behaviour: only the first 40 default
        # listings are shuffled. Everything after that remains newest-first and
        # is left to database pagination instead of being loaded into Python.
        import random

        random.shuffle(room_ids)
        preserved_first_40 = Case(
            *[
                When(id=pk, then=position)
                for position, pk in enumerate(room_ids)
            ],
            default=40,
            output_field=IntegerField(),
        )

        return qs.order_by(preserved_first_40, "-created_at")

    SearchRoomsView.get_queryset = get_queryset
    SearchRoomsView._bounded_fair_rotation_installed = True
