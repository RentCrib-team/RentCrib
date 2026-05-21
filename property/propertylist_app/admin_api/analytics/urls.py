from django.urls import path



from .views import (
    ListingGrowthAnalyticsView,
    BookingTrendsAnalyticsView,
    PaymentStatusMixAnalyticsView,
    ModerationBacklogTrendsAnalyticsView,
)


urlpatterns = [
    path(
        "listing-growth/",
        ListingGrowthAnalyticsView.as_view(),
        name="admin-listing-growth-analytics",
    ),
    
    path(
    "booking-trends/",
    BookingTrendsAnalyticsView.as_view(),
    name="admin-booking-trends-analytics",
    ),
    
    path(
    "payment-status-mix/",
    PaymentStatusMixAnalyticsView.as_view(),
    name="admin-payment-status-mix-analytics",
    ),
    
    path(
    "moderation-backlog-trends/",
    ModerationBacklogTrendsAnalyticsView.as_view(),
    name="admin-moderation-backlog-trends-analytics",
    ),
]