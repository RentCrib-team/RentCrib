from rest_framework import serializers


class DashboardOverviewDataSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    active_listings = serializers.IntegerField()
    pending_reviews = serializers.IntegerField()
    open_reports = serializers.IntegerField()
    payment_exceptions = serializers.IntegerField()
    unresolved_contact_messages = serializers.IntegerField()


class DashboardOverviewResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = DashboardOverviewDataSerializer()