def install_search_image_payload_optimization():
    """Use a lightweight serializer only for public search result cards."""
    from propertylist_app.api.serializers import RoomCardSerializer
    from propertylist_app.api.views.public import SearchRoomsView

    if getattr(SearchRoomsView, "_search_image_payload_optimization_installed", False):
        return

    SearchRoomsView.serializer_class = RoomCardSerializer
    SearchRoomsView._search_image_payload_optimization_installed = True
