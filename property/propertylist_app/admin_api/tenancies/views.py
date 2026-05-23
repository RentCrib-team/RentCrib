from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from propertylist_app.api.views.common import ok_response

from .serializers import AdminTenancyOverviewResponseSerializer
from .services import get_admin_tenancy_overview_data


class AdminTenancyOverviewView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminTenancyOverviewResponseSerializer,
    )
    def get(self, request):
        data = get_admin_tenancy_overview_data(request.query_params)

        return ok_response(
            data=data,
            message="Admin tenancy overview fetched successfully.",
        )