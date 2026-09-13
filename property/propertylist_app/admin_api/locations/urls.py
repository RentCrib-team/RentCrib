from django.urls import path

from .views import AdminCityDetailView, AdminCityListCreateView


urlpatterns = [
    path(
        "cities/",
        AdminCityListCreateView.as_view(),
        name="admin-city-list-create",
    ),
    path(
        "cities/<int:city_id>/",
        AdminCityDetailView.as_view(),
        name="admin-city-detail",
    ),
]
