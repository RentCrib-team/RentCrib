from django.urls import path

from .views import (
    AdminTenancyOverviewView,
)

urlpatterns = [
    path(
        "",
        AdminTenancyOverviewView.as_view(),
        name="admin-tenancy-overview",
    ),
]