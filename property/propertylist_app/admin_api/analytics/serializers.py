from rest_framework import serializers


class ListingGrowthItemSerializer(serializers.Serializer):
    day = serializers.DateField()
    total = serializers.IntegerField()


class ListingGrowthResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = serializers.DictField()