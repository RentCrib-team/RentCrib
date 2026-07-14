from rest_framework import serializers

from propertylist_app.models import LandlordVerificationRequest


class AdminLandlordVerificationRequestSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = LandlordVerificationRequest
        fields = (
            "id",
            "user_id",
            "username",
            "email",
            "status",
            "document",
            "notes",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        )


class AdminLandlordVerificationActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)