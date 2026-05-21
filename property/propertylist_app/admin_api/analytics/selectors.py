from django.db.models import Count
from django.db.models.functions import TruncDate
from propertylist_app.models import (
    Room,
    Booking,
    Payment,
    RoomImage,
)



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
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )

    return list(queryset)  
  
  
  
def get_payment_status_mix_data():
    queryset = (
        Payment.objects.values("status")
        .annotate(total=Count("id"))
        .order_by("status")
    )

    return list(queryset)  


def get_moderation_backlog_trends_data():
    queryset = (
        RoomImage.objects.filter(status="pending")
        .annotate(day=TruncDate("uploaded_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )

    return list(queryset)