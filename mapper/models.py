from datetime import timedelta
from django.db import models
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.utils import timezone


class City(gis_models.Model):
    code = models.CharField(
        max_length=32,
        unique=True,
        help_text="City code identifier (e.g. 'paris')",
    )
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Name of the city (e.g. 'Paris')",
    )
    geom = gis_models.PolygonField(
        srid=4326,
        help_text="City boundary polygon in EPSG:4326 coordinates",
    )
    high_threshold = models.IntegerField(
        null=True,
        blank=True,
        help_text="Heatmap risk threshold",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "City"
        verbose_name_plural = "Cities"
        ordering = ["name"]
        indexes = [
            GistIndex(fields=["geom"], name="mapper_city_geom_gist"),
        ]

    @property
    def centroid(self):
        return self.geom.centroid if self.geom else None

    def __str__(self):
        return self.name


def default_pin_expiry():
    return timezone.now() + timedelta(minutes=90)


class HazardPin(gis_models.Model):
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Optional description of the incident",
    )
    geom = gis_models.PointField(
        srid=4326,
        help_text="Point geometry (Longitude, Latitude) in EPSG:4326",
    )
    buffer_geom = gis_models.PolygonField(
        srid=4326,
        null=True,
        blank=True,
        help_text="100-meter buffer polygon generated from geom by database trigger",
    )
    owner_token = models.UUIDField(
        help_text="Client-supplied ownership UUID token",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        default=default_pin_expiry,
        help_text="Timestamp when the pin expires (default now() + 90 min)",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hazard Pin"
        verbose_name_plural = "Hazard Pins"
        ordering = ["-created_at"]
        indexes = [
            GistIndex(fields=["geom"], name="mapper_hazardpin_geom_gist"),
            GistIndex(fields=["buffer_geom"], name="mapper_hazardpin_buf_gist"),
            models.Index(fields=["expires_at"], name="mapper_pin_expires_idx"),
            models.Index(fields=["owner_token"], name="mapper_pin_owner_idx"),
        ]

    def __str__(self):
        desc = (self.description[:30] + "...") if self.description and len(self.description) > 30 else (self.description or "Hazard Pin")
        return f"HazardPin #{self.pk}: {desc}"
