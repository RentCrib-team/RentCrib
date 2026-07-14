from rest_framework import serializers


class AdminBookingStatsSerializer(serializers.Serializer):
    all_bookings = serializers.IntegerField()
    confirmed_bookings = serializers.IntegerField()
    suspended_bookings = serializers.IntegerField()
    cancelled_bookings = serializers.IntegerField()
    deleted_bookings = serializers.IntegerField()


class AdminBookingTableItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    booking_id = serializers.CharField()
    user = serializers.CharField()
    user_email = serializers.EmailField()
    property_type = serializers.CharField(allow_null=True)
    room_id = serializers.IntegerField()
    room_title = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    status = serializers.CharField()
    is_deleted = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class AdminBookingOverviewDataSerializer(serializers.Serializer):
    stats = AdminBookingStatsSerializer()
    bookings = AdminBookingTableItemSerializer(many=True)


class AdminBookingOverviewResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminBookingOverviewDataSerializer()


class AdminBookingActionRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            ("suspend", "Suspend"),
            ("cancel", "Cancel"),
            ("restore", "Restore"),
            ("soft_delete", "Soft delete"),
        ]
    )


class AdminBookingActionResponseDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    is_deleted = serializers.BooleanField()


class AdminBookingActionResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminBookingActionResponseDataSerializer()
    
    
    
class AdminBookingDetailDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    booking_id = serializers.CharField()
    booking_date = serializers.DateField()
    booking_time = serializers.CharField()
    booking_created = serializers.DateTimeField()
    status = serializers.CharField()
    canceled_at = serializers.DateTimeField(allow_null=True)

    tenant = serializers.DictField()
    listing = serializers.DictField()


class AdminBookingDetailResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminBookingDetailDataSerializer()    