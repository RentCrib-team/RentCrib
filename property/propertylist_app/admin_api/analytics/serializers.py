from rest_framework import serializers


class ListingGrowthItemSerializer(serializers.Serializer):
    day = serializers.DateField()
    total = serializers.IntegerField()


class ListingGrowthResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField()
    
    
    
class BookingTrendsItemSerializer(serializers.Serializer):
    day = serializers.DateField()
    total = serializers.IntegerField()


class BookingTrendsResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField()    
    
    
class PaymentStatusMixItemSerializer(serializers.Serializer):
    status = serializers.CharField()
    total = serializers.IntegerField()


class PaymentStatusMixResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField()    
    
    
    
class ModerationBacklogTrendsItemSerializer(serializers.Serializer):
    day = serializers.DateField()
    total = serializers.IntegerField()


class ModerationBacklogTrendsResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField()    