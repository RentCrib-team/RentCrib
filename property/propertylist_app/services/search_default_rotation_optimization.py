from django.db.models import Case, IntegerField, When


def install_search_default_rotation_optimization():
    """Limit default fair-rotation ordering to the first 40 rooms only."""
    from propertylist_app.api.views.public import SearchRoomsView

    if getattr(SearchRoomsView, "_bounded_fair_rotation_installed", False):
        return

    original_get_queryset = SearchRoomsView.get_queryset

    def get_queryset(self):
        qs = original_get_queryset(self)
        params = self.request.query_params
        postcode = (params.get("postcode") or "").strip()
        raw_ordering_param = params.get("ordering")

        apply_fair_rotation = (
            not postcode
            and self._ordered_ids is None
            and raw_ordering_param in (None, "", "default")
        )

        if not apply_fair_rotation:
            return qs

        room_ids = list(
            qs.order_by("-created_at")
            .values_list("id", flat=True)[:40]
        )
        if len(room_ids) <= 1:
            return qs

        # Reuse the already-shuffled order from the original view if possible.
        # The first 40 are the only cohort that RentCrib intentionally rotates;
        # everything after them should remain newest-first and be left for DB
        # pagination rather than materialised into Python.
        first_40_order = []
        ordering = getattr(qs.query, "order_by", ())
        if ordering:
            expression = ordering[0]
            case = getattr(expression, "expression", expression)
            cases = getattr(case, "cases", ())
            for when in cases[:40]:
                condition = getattr(when, "condition", None)
                children = getattr(condition, "children", ()) if condition is not None else ()
                for key, value in children:
                    if key in {"id", "id__exact"}:
                        first_40_order.append(value)
                        break

        if len(first_40_order) != len(room_ids):
            first_40_order = room_ids

        preserved_first_40 = Case(
            *[
                When(id=pk, then=position)
                for position, pk in enumerate(first_40_order)
            ],
            default=40,
            output_field=IntegerField(),
        )

        return qs.order_by(preserved_first_40, "-created_at")

    SearchRoomsView.get_queryset = get_queryset
    SearchRoomsView._bounded_fair_rotation_installed = True
