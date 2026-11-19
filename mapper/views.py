import uuid
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.db.models.functions import Distance, GeometryDistance
from django.db import connection as db_connection
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import City, HazardPin
from .serializers import (
    BoundingBoxQuerySerializer,
    CityGeoSerializer,
    HazardPinCreateSerializer,
    HazardPinGeoSerializer,
    ProximityQuerySerializer,
)


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


def _extract_owner_token(request):
    token_str = request.headers.get("X-Owner-Token") or request.query_params.get("owner_token")
    if not token_str:
        return None
    try:
        return uuid.UUID(str(token_str).strip())
    except (ValueError, AttributeError):
        return None


class HazardPinListCreateView(APIView):
    def get(self, request):
        if "category" in request.query_params:
            return Response(
                {"error": "Category parameter is no longer supported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = HazardPin.objects.filter(expires_at__gt=timezone.now()).order_by("-created_at")

        qs, err = _apply_bbox_filter(qs, request)
        if err:
            return err

        serializer = HazardPinGeoSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = HazardPinCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        pin = serializer.save()
        out = HazardPinGeoSerializer(pin)
        return Response(out.data, status=status.HTTP_201_CREATED)


class HazardPinDetailView(APIView):
    def _get_pin(self, pk):
        try:
            pin = HazardPin.objects.get(pk=pk)
            if pin.expires_at <= timezone.now():
                return None
            return pin
        except HazardPin.DoesNotExist:
            return None

    def get(self, request, pk):
        pin = self._get_pin(pk)
        if pin is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(HazardPinGeoSerializer(pin).data)

    def patch(self, request, pk):
        pin = self._get_pin(pk)
        if pin is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        token = _extract_owner_token(request)
        if token is None or pin.owner_token != token:
            return Response(
                {"detail": "You do not have permission to modify this pin."},
                status=status.HTTP_403_FORBIDDEN,
            )

        allowed_fields = {"description"}
        extra_fields = set(request.data.keys()) - allowed_fields
        if extra_fields:
            return Response(
                {"detail": f"Only 'description' may be updated. Disallowed fields: {list(extra_fields)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if "description" in request.data:
            pin.description = request.data["description"]
            pin.save(update_fields=["description", "updated_at"])

        return Response(HazardPinGeoSerializer(pin).data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        pin = self._get_pin(pk)
        if pin is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        token = _extract_owner_token(request)
        if token is None or pin.owner_token != token:
            return Response(
                {"detail": "You do not have permission to delete this pin."},
                status=status.HTTP_403_FORBIDDEN,
            )

        pin.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def pins_nearest(request):
    if "category" in request.query_params:
        return Response(
            {"error": "Category parameter is no longer supported."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    params = ProximityQuerySerializer(data=request.query_params)
    if not params.is_valid():
        return Response(params.errors, status=status.HTTP_400_BAD_REQUEST)

    data = params.validated_data
    center = Point(data["lon"], data["lat"], srid=4326)

    qs = HazardPin.objects.filter(expires_at__gt=timezone.now())
    qs = (
        qs.annotate(distance=Distance("geom", center))
        .order_by(GeometryDistance("geom", center))[: data["limit"]]
    )

    out = HazardPinGeoSerializer(qs, many=True)
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
    if "category" in request.query_params:
        return Response(
            {"error": "Category parameter is no longer supported."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    params = ProximityQuerySerializer(data=request.query_params)
    if not params.is_valid():
        return Response(params.errors, status=status.HTTP_400_BAD_REQUEST)

    data = params.validated_data
    center = Point(data["lon"], data["lat"], srid=4326)

    # Cast to geography for accurate spherical distance in true meters on EPSG:4326
    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM mapper_hazardpin
            WHERE expires_at > %s
              AND ST_DWithin(
                  geom::geography,
                  ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                  %s
              )
            """,
            [timezone.now(), data["lon"], data["lat"], data["radius_m"]],
        )
        pin_ids = [row[0] for row in cursor.fetchall()]

    qs = (
        HazardPin.objects.filter(pk__in=pin_ids, expires_at__gt=timezone.now())
        .annotate(distance=Distance("geom", center))
        .order_by("distance")
    )

    out = HazardPinGeoSerializer(qs, many=True)
    return Response(
        {
            "center": {"latitude": data["lat"], "longitude": data["lon"]},
            "radius_m": data["radius_m"],
            "count": qs.count(),
            "features": out.data.get("features", []),
        }
    )


class CityListView(APIView):
    def get(self, request):
        qs = City.objects.all()
        serializer = CityGeoSerializer(qs, many=True)
        return Response(serializer.data)
