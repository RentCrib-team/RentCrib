from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.text import slugify
from rest_framework import serializers

from propertylist_app.models import City
from propertylist_app.services.city_images import (
    city_has_uploaded_image,
    city_image_url,
    prepare_city_image,
)


class AdminCitySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    has_image = serializers.SerializerMethodField()
    room_count = serializers.SerializerMethodField()

    class Meta:
        model = City
        fields = (
            "id",
            "name",
            "slug",
            "image",
            "image_url",
            "has_image",
            "image_alt",
            "is_active",
            "is_featured",
            "display_order",
            "room_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "image_url",
            "has_image",
            "room_count",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {
            "slug": {"required": False, "allow_blank": True},
            "image": {"required": False, "allow_null": True},
            "image_alt": {"required": False, "allow_blank": True},
            "is_active": {"required": False},
            "is_featured": {"required": False},
            "display_order": {"required": False},
        }

    def get_image_url(self, obj):
        return city_image_url(
            obj,
            request=self.context.get("request"),
        )

    def get_has_image(self, obj):
        return city_has_uploaded_image(obj)

    def get_room_count(self, obj):
        annotated_count = getattr(obj, "room_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.rooms.count()

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("City name is required.")

        qs = City.objects.filter(name__iexact=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A city with this name already exists.")
        return name

    def validate_slug(self, value):
        raw = (value or "").strip()
        if not raw:
            return ""

        value = slugify(raw)
        if not value:
            raise serializers.ValidationError("Enter a valid city slug.")

        qs = City.objects.filter(slug=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A city with this slug already exists.")
        return value

    def validate_image(self, value):
        if value is None:
            return None

        try:
            return prepare_city_image(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class AdminCityListDataSerializer(serializers.Serializer):
    results = AdminCitySerializer(many=True)
    total_results = serializers.IntegerField()


class AdminCityListResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminCityListDataSerializer()


class AdminCityResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminCitySerializer()
