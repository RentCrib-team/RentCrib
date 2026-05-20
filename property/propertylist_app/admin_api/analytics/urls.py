from django.urls import path

from .views import ListingGrowthAnalyticsView


urlpatterns = [
    path(
        "listing-growth/",
        ListingGrowthAnalyticsView.as_view(),
        name="admin-listing-growth-analytics",
    ),
]