from .selectors import get_admin_city
from .serializers import AdminCitySerializer


def create_city(*, data):
    serializer = AdminCitySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    city = serializer.save()
    return get_admin_city(city.pk)


def update_city(*, city_id, data):
    city = get_admin_city(city_id)
    serializer = AdminCitySerializer(city, data=data, partial=True)
    serializer.is_valid(raise_exception=True)
    city = serializer.save()
    return get_admin_city(city.pk)
