from django.db.models import Count
from django.db.models.functions import TruncDate
from propertylist_app.models import Room, Booking



def get_listing_growth_data():
    queryset = (
        Room.objects.filter(is_deleted=False)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )

    return list(queryset)
  
  
def get_booking_trends_data():
    queryset = (
        Booking.objects.filter(is_deleted=False)
        .annotate(day=TruncDate("created_at"))
        .values("day", "status")
        .annotate(total=Count("id"))
        .order_by("day", "status")
    )

    return list(queryset)  