from django.urls import path
from .views import (
    AdminNotificationDropdownView,
    AdminProfileDropdownView,
)


urlpatterns = [
    path(
        "notifications/dropdown/",
        AdminNotificationDropdownView.as_view(),
        name="admin-notification-dropdown",
    ),
    
    path(
    "profile/dropdown/",
    AdminProfileDropdownView.as_view(),
    name="admin-profile-dropdown",
    ),
]