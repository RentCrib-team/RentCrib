from rest_framework import serializers


class AdminTenancyStatsSerializer(serializers.Serializer):
    all_tenancies = serializers.IntegerField()
    proposed_tenancies = serializers.IntegerField()
    confirmed_tenancies = serializers.IntegerField()
    active_tenancies = serializers.IntegerField()
    ended_tenancies = serializers.IntegerField()
    cancelled_tenancies = serializers.IntegerField()


class AdminTenancyTableItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tenancy_id = serializers.CharField()
    tenant = serializers.CharField()
    tenant_email = serializers.EmailField()
    landlord = serializers.CharField()
    landlord_email = serializers.EmailField()
    room_id = serializers.IntegerField()
    room_title = serializers.CharField()
    property_type = serializers.CharField(allow_null=True)
    move_in_date = serializers.DateField()
    duration_months = serializers.IntegerField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class AdminTenancyOverviewDataSerializer(serializers.Serializer):
    stats = AdminTenancyStatsSerializer()
    tenancies = AdminTenancyTableItemSerializer(many=True)


class AdminTenancyOverviewResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminTenancyOverviewDataSerializer()
    
    
    
    
class AdminTenancyDetailDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tenancy_id = serializers.CharField()
    status = serializers.CharField()
    confirmation = serializers.CharField()
    move_in_date = serializers.DateField()
    duration_months = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    tenant = serializers.DictField()
    landlord = serializers.DictField()
    listing = serializers.DictField()


class AdminTenancyDetailResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminTenancyDetailDataSerializer()





