"""
Serializers for the mapper app.

Three tiers per SPEC#1.md §5:
  - SafetyPinCreateSerializer  – validates lat/lon/category POST body, builds Point geometry
  - SafetyPinGeoSerializer     – GeoJSON FeatureCollection output (GeoFeatureModelSerializer)
  - CityBoundaryGeoSerializer  – GeoJSON output for city boundary polygons

Input format (POST /api/v1/pins/):
  { "title": "...", "description": "...", "category": "PEACEFUL",
    "latitude": 48.8566, "longitude": 2.3522 }

Output: GeoJSON Feature with geometry + properties including buffer_geom.
"""

from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from django.contrib.gis.geos import Point

from .models import CityBoundary, SafetyPin


# ---------------------------------------------------------------------------
# SafetyPin serializers
# ---------------------------------------------------------------------------

class SafetyPinGeoSerializer(GeoFeatureModelSerializer):
    """
    GeoJSON FeatureCollection serializer for SafetyPin.
    Exposes the point geometry as the primary geo_field and includes
    buffer_geom in properties for Leaflet polygon rendering.
    """

    class Meta:
        model = SafetyPin
        geo_field = "geom"
        fields = [
            "id",
            "title",
            "description",
            "category",
            "buffer_geom",
            "created_at",
        ]
        read_only_fields = ["id", "buffer_geom", "created_at"]


class SafetyPinCreateSerializer(serializers.Serializer):
    """
    Write-only serializer for creating a SafetyPin from flat lat/lon input.

    Validates:
      - latitude  in [-90,  90]
      - longitude in [-180, 180]
      - category  in {PEACEFUL, VIOLENT}
      - (optional) title, description

    Performs a city-boundary containment check and delegates save to the
    model (which computes the 100 m PostGIS buffer).
    """

    title = serializers.CharField(max_length=200)
    description = serializers.CharField(
        allow_blank=True, required=False, default=""
    )
    category = serializers.ChoiceField(
        choices=SafetyPin.CATEGORY_CHOICES,
        default=SafetyPin.CATEGORY_PEACEFUL,
    )
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()

    def validate_latitude(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError(
                "Latitude must be between -90 and 90."
            )
        return value

    def validate_longitude(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError(
                "Longitude must be between -180 and 180."
            )
        return value

    def validate(self, data):
        """
        Cross-field validation: ensure the point lies inside at least one
        registered CityBoundary (SPEC#1 Q3 containment check).
        """
        point = Point(data["longitude"], data["latitude"], srid=4326)
        if not CityBoundary.objects.filter(geom__contains=point).exists():
            raise serializers.ValidationError(
                "The pin location is outside all registered city boundaries. "
                "Only pins inside a tracked city are accepted."
            )
        return data

    def create(self, validated_data):
        point = Point(
            validated_data.pop("longitude"),
            validated_data.pop("latitude"),
            srid=4326,
        )
        pin = SafetyPin(geom=point, **validated_data)
        pin.save()  # triggers calculate_buffer() in model.save()
        return pin


# ---------------------------------------------------------------------------
# CityBoundary serializers
# ---------------------------------------------------------------------------

class CityBoundaryGeoSerializer(GeoFeatureModelSerializer):
    """GeoJSON serializer for CityBoundary polygons."""

    class Meta:
        model = CityBoundary
        geo_field = "geom"
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


# ---------------------------------------------------------------------------
# Utility / parameter serializers (used by spatial filter views)
# ---------------------------------------------------------------------------

class ProximityQuerySerializer(serializers.Serializer):
    """Validates ?lat=&lon=&radius_m=&limit= query parameters (SPEC Q1, Q2)."""

    lat = serializers.FloatField()
    lon = serializers.FloatField()
    radius_m = serializers.FloatField(
        min_value=1, max_value=100_000, required=False, default=500
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, required=False, default=10)

    def validate_lat(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("lat must be between -90 and 90.")
        return value

    def validate_lon(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("lon must be between -180 and 180.")
        return value


class BoundingBoxQuerySerializer(serializers.Serializer):
    """Validates ?bbox=min_lon,min_lat,max_lon,max_lat query parameter."""

    bbox = serializers.CharField(
        help_text="Comma-separated: min_lon,min_lat,max_lon,max_lat"
    )

    def validate_bbox(self, value):
        try:
            parts = [float(p.strip()) for p in value.split(",")]
        except ValueError:
            raise serializers.ValidationError(
                "bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat"
            )
        if len(parts) != 4:
            raise serializers.ValidationError(
                "bbox requires exactly four values: min_lon,min_lat,max_lon,max_lat"
            )
        min_lon, min_lat, max_lon, max_lat = parts
        if min_lon >= max_lon:
            raise serializers.ValidationError("min_lon must be less than max_lon.")
        if min_lat >= max_lat:
            raise serializers.ValidationError("min_lat must be less than max_lat.")
        return parts  # return as list for easy unpacking in the view
