from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from propertylist_app.models import Tenancy
from propertylist_app.api.views.common import ok_response

from .serializers import (
    AdminTenancyOverviewResponseSerializer,
    AdminTenancyDetailResponseSerializer,
    
)

from .services import (
    get_admin_tenancy_overview_data,
   
)

from .selectors import (
    get_admin_tenancy_detail,
)

class AdminTenancyOverviewView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
    operation_id="admin_tenancies_overview",
    responses=AdminTenancyOverviewResponseSerializer,
    )
    def get(self, request):
        data = get_admin_tenancy_overview_data(request.query_params)

        return ok_response(
            data=data,
            message="Admin tenancy overview fetched successfully.",
        )
        
        
class AdminTenancyDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        operation_id="admin_tenancy_detail",
        responses=AdminTenancyDetailResponseSerializer,
    )
    def get(self, request, tenancy_id):
        data = get_admin_tenancy_detail(tenancy_id)

        return ok_response(
            data=data,
            message="Admin tenancy detail fetched successfully.",
        )
        
        
