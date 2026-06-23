from django.urls import path

from .views import (
    AdminLandlordVerificationActionView,
    AdminLandlordVerificationListView,
)

urlpatterns = [
    path(
        "landlord-verification-requests/",
        AdminLandlordVerificationListView.as_view(),
        name="admin-landlord-verification-list",
    ),
    path(
        "landlord-verification-requests/<int:request_id>/review/",
        AdminLandlordVerificationActionView.as_view(),
        name="admin-landlord-verification-review",
    ),
]