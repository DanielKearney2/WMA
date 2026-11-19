import uuid
from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.utils import timezone

from .models import City, HazardPin


class CityGeoSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = City
        geo_field = "geom"
        fields = ["id", "code", "name"]
        read_only_fields = ["id", "code", "name"]


class HazardPinGeoSerializer(GeoFeatureModelSerializer):
    distance = serializers.SerializerMethodField(required=False)

    class Meta:
        model = HazardPin
        geo_field = "geom"
        fields = [
            "id",
            "description",
            "buffer_geom",
            "created_at",
            "expires_at",
            "distance",
        ]
        read_only_fields = [
            "id",
            "buffer_geom",
            "created_at",
            "expires_at",
            "distance",
        ]

    def get_distance(self, obj):
        if hasattr(obj, "distance") and obj.distance is not None:
            if hasattr(obj.distance, "m"):
                return round(float(obj.distance.m), 1)
            try:
                return round(float(obj.distance), 1)
            except (TypeError, ValueError):
                pass
        return None


class HazardPinCreateSerializer(serializers.Serializer):
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        allow_null=True,
        default="",
    )
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    owner_token = serializers.UUIDField()

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
        point = Point(data["longitude"], data["latitude"], srid=4326)

        # Pin must be inside the Paris City boundary
        paris_qs = City.objects.filter(code="paris", geom__contains=point)
        city_qs = City.objects.filter(geom__contains=point)
        if not paris_qs.exists() and not city_qs.exists():
            raise serializers.ValidationError(
                "The pin location is outside the Paris boundary. "
                "Only pins inside Paris are accepted."
            )

        # No-stacking: no other active pin within 100 m
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM mapper_hazardpin
                WHERE expires_at > %s
                  AND ST_DWithin(
                      geom::geography,
                      ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                      100
                  )
                LIMIT 1
                """,
                [timezone.now(), data["longitude"], data["latitude"]],
            )
            if cursor.fetchone():
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            "Another active incident already exists within 100 m of this location."
                        ]
                    }
                )

        return data

    def create(self, validated_data):
        with transaction.atomic():
            # Lock the City row to prevent concurrent race condition on stacking check
            City.objects.select_for_update().filter(code="paris").first()

            point = Point(
                validated_data.pop("longitude"),
                validated_data.pop("latitude"),
                srid=4326,
            )
            pin = HazardPin.objects.create(geom=point, **validated_data)
            return pin


class ProximityQuerySerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    radius_m = serializers.FloatField(
        min_value=1, max_value=100_000, required=False, default=500
    )
    limit = serializers.IntegerField(
        min_value=1, max_value=100, required=False, default=10
    )

    def validate_lat(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("lat must be between -90 and 90.")
        return value

    def validate_lon(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("lon must be between -180 and 180.")
        return value


class BoundingBoxQuerySerializer(serializers.Serializer):
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
        return parts
