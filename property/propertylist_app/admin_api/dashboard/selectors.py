from django.contrib.auth.models import User

from propertylist_app.models import Room


def get_total_users():
    return User.objects.count()


def get_active_listings_count():
    return Room.objects.filter(is_deleted=False).count()