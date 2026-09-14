from __future__ import annotations


def install_room_geocoding_request_optimization() -> None:
    from propertylist_app.api.serializers import RoomSerializer
    from propertylist_app.services.room_geocoding_async import task_geocode_room

    if getattr(RoomSerializer, "_room_geocoding_request_optimization_installed", False):
        return

    original_create = RoomSerializer.create
    original_update = RoomSerializer.update

    def _queue(room):
        location = (room.location or "").strip()
        if not location:
            return

        task_geocode_room.delay(room.id, expected_location=location)

    def create(self, validated_data):
        original_apply_geocode = self._apply_geocode
        self._apply_geocode = lambda room: None
        try:
            room = original_create(self, validated_data)
        finally:
            self._apply_geocode = original_apply_geocode

        _queue(room)
        return room

    def update(self, instance, validated_data):
        old_location = (instance.location or "").strip()
        had_coordinates = bool(instance.latitude and instance.longitude)

        original_apply_geocode = self._apply_geocode
        self._apply_geocode = lambda room: None
        try:
            room = original_update(self, instance, validated_data)
        finally:
            self._apply_geocode = original_apply_geocode

        new_location = (room.location or "").strip()
        if old_location != new_location or not had_coordinates:
            _queue(room)

        return room

    RoomSerializer.create = create
    RoomSerializer.update = update
    RoomSerializer._room_geocoding_request_optimization_installed = True
