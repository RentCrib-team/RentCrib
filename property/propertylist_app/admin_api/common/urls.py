from django.urls import path

from .views import AdminNotificationDropdownView


urlpatterns = [
    path(
        "notifications/dropdown/",
        AdminNotificationDropdownView.as_view(),
        name="admin-notification-dropdown",
    ),
]