from __future__ import annotations


def install_room_update_availability_sync_optimization() -> None:
    from propertylist_app.api.serializers import RoomSerializer

    if getattr(
        RoomSerializer,
        "_room_update_availability_sync_optimization_installed",
        False,
    ):
        return

    original_update = RoomSerializer.update

    availability_fields = {
        "available_from",
        "view_available_days_mode",
        "view_available_custom_dates",
        "availability_from_time",
        "availability_to_time",
    }

    def update(self, instance, validated_data):
        if availability_fields.intersection(validated_data):
            return original_update(self, instance, validated_data)

        original_sync = self._sync_availability_slots
        self._sync_availability_slots = lambda room: None
        try:
            return original_update(self, instance, validated_data)
        finally:
            self._sync_availability_slots = original_sync

    RoomSerializer.update = update
    RoomSerializer._room_update_availability_sync_optimization_installed = True
