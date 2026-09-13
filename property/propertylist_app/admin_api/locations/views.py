from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsLocationAdmin
from .selectors import get_admin_cities_queryset, get_admin_city
from .serializers import (
    AdminCityListResponseSerializer,
    AdminCityResponseSerializer,
    AdminCitySerializer,
)
from .services import create_city, update_city


class AdminCityListCreateView(APIView):
    permission_classes = [IsLocationAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        parameters=[
            OpenApiParameter(name="search", type=str, required=False),
            OpenApiParameter(name="is_active", type=bool, required=False),
            OpenApiParameter(name="is_featured", type=bool, required=False),
            OpenApiParameter(
                name="has_image",
                type=bool,
                required=False,
                description="Filter cities with or without an uploaded city image.",
            ),
        ],
        responses=AdminCityListResponseSerializer,
    )
    def get(self, request):
        cities = get_admin_cities_queryset(request.query_params)
        results = AdminCitySerializer(
            cities,
            many=True,
            context={"request": request},
        ).data

        return Response(
            {
                "ok": True,
                "message": "Admin cities fetched successfully",
                "data": {
                    "results": results,
                    "total_results": len(results),
                },
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=AdminCitySerializer,
        responses={201: AdminCityResponseSerializer},
    )
    def post(self, request):
        city = create_city(data=request.data)
        data = AdminCitySerializer(
            city,
            context={"request": request},
        ).data

        return Response(
            {
                "ok": True,
                "message": "City created successfully",
                "data": data,
            },
            status=status.HTTP_201_CREATED,
        )


class AdminCityDetailView(APIView):
    permission_classes = [IsLocationAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(responses=AdminCityResponseSerializer)
    def get(self, request, city_id):
        city = get_admin_city(city_id)
        data = AdminCitySerializer(
            city,
            context={"request": request},
        ).data

        return Response(
            {
                "ok": True,
                "message": "Admin city fetched successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=AdminCitySerializer,
        responses=AdminCityResponseSerializer,
    )
    def patch(self, request, city_id):
        city = update_city(city_id=city_id, data=request.data)
        data = AdminCitySerializer(
            city,
            context={"request": request},
        ).data

        return Response(
            {
                "ok": True,
                "message": "City updated successfully",
                "data": data,
            },
            status=status.HTTP_200_OK,
        )
