from django.urls import path

from .views import ListingActionView, ListingDetailView, ListingOverviewView


urlpatterns = [
    path(
        "overview/",
        ListingOverviewView.as_view(),
        name="admin-listing-overview",
    ),
    path(
        "<int:listing_id>/action/",
        ListingActionView.as_view(),
        name="admin-listing-action",
    ),
    
    path(
    "<int:listing_id>/",
    ListingDetailView.as_view(),
    name="admin-listing-detail",
    ),
]