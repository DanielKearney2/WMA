from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.db.models.functions import Distance
from django.db import connection as db_connection

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CityBoundary, SafetyPin
from .serializers import (
    BoundingBoxQuerySerializer,
    CityBoundaryGeoSerializer,
    ProximityQuerySerializer,
    SafetyPinCreateSerializer,
    SafetyPinGeoSerializer,
)

def _apply_category_filter(queryset, request):
    category = request.query_params.get("category", "").upper()
    if category in (SafetyPin.CATEGORY_PEACEFUL, SafetyPin.CATEGORY_VIOLENT):
        queryset = queryset.filter(category=category)
    return queryset


def _apply_bbox_filter(queryset, request):
    bbox_raw = request.query_params.get("bbox")
    if not bbox_raw:
        return queryset, None

    serializer = BoundingBoxQuerySerializer(data={"bbox": bbox_raw})
    if not serializer.is_valid():
        return queryset, Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    min_lon, min_lat, max_lon, max_lat = serializer.validated_data["bbox"]
    bbox_poly = Polygon.from_bbox((min_lon, min_lat, max_lon, max_lat))
    bbox_poly.srid = 4326
    queryset = queryset.filter(geom__within=bbox_poly)
    return queryset, None

class SafetyPinListCreateView(APIView):
    def get(self, request):
        qs = SafetyPin.objects.all()

        # Category filter
        qs = _apply_category_filter(qs, request)

        # Bounding-box filter
        qs, err = _apply_bbox_filter(qs, request)
        if err:
            return err

        serializer = SafetyPinGeoSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SafetyPinCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        pin = serializer.save()
        out = SafetyPinGeoSerializer(pin)
        return Response(out.data, status=status.HTTP_201_CREATED)

class SafetyPinDetailView(APIView):
    def _get_pin(self, pk):
        try:
            return SafetyPin.objects.get(pk=pk)
        except SafetyPin.DoesNotExist:
            return None

    def get(self, request, pk):
        pin = self._get_pin(pk)
        if pin is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SafetyPinGeoSerializer(pin).data)

    def delete(self, request, pk):
        pin = self._get_pin(pk)
        if pin is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        pin.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(["GET"])
def pins_nearest(request):
    params = ProximityQuerySerializer(data=request.query_params)
    if not params.is_valid():
        return Response(params.errors, status=status.HTTP_400_BAD_REQUEST)

    data = params.validated_data
    center = Point(data["lon"], data["lat"], srid=4326)

    qs = SafetyPin.objects.all()
    qs = _apply_category_filter(qs, request)
    qs = (
        qs.annotate(distance=Distance("geom", center))
        .order_by("distance")[: data["limit"]]
    )

    out = SafetyPinGeoSerializer(qs, many=True)
    return Response(
        {
            "center": {"latitude": data["lat"], "longitude": data["lon"]},
            "limit": data["limit"],
            "count": len(out.data.get("features", [])),
            "features": out.data.get("features", []),
        }
    )

@api_view(["GET"])
def pins_within(request):
    params = ProximityQuerySerializer(data=request.query_params)
    if not params.is_valid():
        return Response(params.errors, status=status.HTTP_400_BAD_REQUEST)

    data = params.validated_data
    center = Point(data["lon"], data["lat"], srid=4326)

    qs = SafetyPin.objects.all()
    qs = _apply_category_filter(qs, request)

    # geom__dwithin on SRID 4326 PointField expects degrees, not metres.
    # Use a raw ST_DWithin(geom::geography, ..., radius_m) for accurate metre lookup
    # then filter the ORM queryset by the returned PKs.
    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM mapper_safetypin
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s
            )
            """,
            [data["lon"], data["lat"], data["radius_m"]],
        )
        pin_ids = [row[0] for row in cursor.fetchall()]

    qs = qs.filter(pk__in=pin_ids)

    out = SafetyPinGeoSerializer(qs, many=True)
    return Response(
        {
            "center": {"latitude": data["lat"], "longitude": data["lon"]},
            "radius_m": data["radius_m"],
            "count": qs.count(),
            "features": out.data.get("features", []),
        }
    )

class CityBoundaryListView(APIView):
    """
    GET /api/v1/boundaries/
    Returns a GeoJSON FeatureCollection of all registered city boundaries.
    """

    def get(self, request):
        qs = CityBoundary.objects.all()
        serializer = CityBoundaryGeoSerializer(qs, many=True)
        return Response(serializer.data)
