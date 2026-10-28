from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from django.contrib.gis.geos import Point

from .models import CityBoundary, SafetyPin

class SafetyPinGeoSerializer(GeoFeatureModelSerializer):
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

class CityBoundaryGeoSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = CityBoundary
        geo_field = "geom"
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]

class ProximityQuerySerializer(serializers.Serializer):
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
