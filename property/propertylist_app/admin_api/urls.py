from django.urls import path, include

urlpatterns = [
    path("dashboard/", include("propertylist_app.admin_api.dashboard.urls")),
    path("analytics/", include("propertylist_app.admin_api.analytics.urls")),
    path("common/", include("propertylist_app.admin_api.common.urls")),
]