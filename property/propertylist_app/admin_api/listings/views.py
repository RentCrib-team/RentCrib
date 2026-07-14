from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from propertylist_app.admin_api.permissions import IsAdminUser

from .serializers import (
    AdminListingDetailResponseSerializer,
    ListingActionRequestSerializer,
    ListingActionResponseSerializer,
    ListingOverviewResponseSerializer,
)
from .services import (
    get_listing_detail_data,
    get_listing_overview_data,
    update_listing_action,
)


class ListingOverviewView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        parameters=[
            OpenApiParameter(name="search", type=str, required=False),
            OpenApiParameter(name="status", type=str, required=False),
            OpenApiParameter(name="category", type=str, required=False),
            OpenApiParameter(name="furnished", type=str, required=False),
            OpenApiParameter(name="bills", type=str, required=False),
            OpenApiParameter(name="parking", type=str, required=False),
            OpenApiParameter(name="availability", type=str, required=False),
            OpenApiParameter(name="sort_by", type=str, required=False),
            OpenApiParameter(name="page", type=int, required=False),
            OpenApiParameter(name="page_size", type=int, required=False),
        ],
        responses=ListingOverviewResponseSerializer,
    )
    def get(self, request):
        data = get_listing_overview_data(request.query_params)

        return Response(
            {
                "ok": True,
                "message": "Admin listing overview fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )


class ListingActionView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=ListingActionRequestSerializer,
        responses=ListingActionResponseSerializer,
    )
    def post(self, request, listing_id):
        serializer = ListingActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = update_listing_action(
                room_id=listing_id,
                action=serializer.validated_data["action"],
            )
        except ValidationError as exc:
            raise ValidationError({"detail": str(exc)})

        return Response(
            {
                "ok": True,
                "message": data["message"],
                "data": data,
            },
            status=status.HTTP_200_OK,
        )
        
        
        
class ListingDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=AdminListingDetailResponseSerializer,
    )
    def get(self, request, listing_id):
        try:
            data = get_listing_detail_data(
                room_id=listing_id,
                request=request,
            )
        except ValidationError as exc:
            raise ValidationError({"detail": str(exc)})

        return Response(
            {
                "ok": True,
                "message": "Admin listing detail fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )        