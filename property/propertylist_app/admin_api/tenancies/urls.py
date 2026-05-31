from django.urls import path

from .views import (
    AdminTenancyOverviewView,
    AdminTenancyDetailView,
)

urlpatterns = [
    path(
        "",
        AdminTenancyOverviewView.as_view(),
        name="admin-tenancy-overview",
    ),

    path(
        "<int:tenancy_id>/",
        AdminTenancyDetailView.as_view(),
        name="admin-tenancy-detail",
    ),
]