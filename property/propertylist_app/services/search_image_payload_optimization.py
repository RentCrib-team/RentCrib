from rest_framework import serializers


def install_search_image_payload_optimization():
    """Use a lightweight serializer only for public search result cards."""
    from propertylist_app.api.serializers import RoomSerializer
    from propertylist_app.api.views.public import SearchRoomsView

    if getattr(SearchRoomsView, "_search_image_payload_optimization_installed", False):
        return

    class SearchRoomSerializer(RoomSerializer):
        photo_count = serializers.SerializerMethodField(read_only=True)

        def get_fields(self):
            fields = super().get_fields()
            fields.pop("other_images", None)
            return fields

        def get_photo_count(self, obj):
            prefetched = getattr(obj, "prefetched_approved_images", None)
            if prefetched is not None:
                return len(prefetched)

            images = self._room_images(obj)
            return sum(1 for image in images if image.status == "approved")

    SearchRoomsView.serializer_class = SearchRoomSerializer
    SearchRoomsView._search_image_payload_optimization_installed = True
