from rest_framework import serializers


class AdminNotificationDropdownItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField()
    type = serializers.CharField()
    is_read = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class AdminNotificationDropdownDataSerializer(serializers.Serializer):
    notifications = AdminNotificationDropdownItemSerializer(many=True)
    unread_count = serializers.IntegerField()


class AdminNotificationDropdownResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminNotificationDropdownDataSerializer()