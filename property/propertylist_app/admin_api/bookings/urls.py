from django.urls import path

from .views import (
    AdminBookingOverviewView,
    AdminBookingDetailView,
    AdminBookingActionView,
)

urlpatterns = [
    path(
        "",
        AdminBookingOverviewView.as_view(),
        name="admin-booking-overview",
    ),

    path(
        "<int:booking_id>/",
        AdminBookingDetailView.as_view(),
        name="admin-booking-detail",
    ),

    path(
        "<int:booking_id>/action/",
        AdminBookingActionView.as_view(),
        name="admin-booking-action",
    ),
]