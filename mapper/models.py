from django.db import models, connection
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry


class CityBoundary(gis_models.Model):
    """
    City administrative boundary model (e.g. Paris or Dublin).
    Stored as an SRID 4326 Polygon geometry.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Name of the city (e.g. Paris, Dublin)",
    )
    geom = gis_models.PolygonField(
        srid=4326,
        help_text="City boundary polygon in EPSG:4326 coordinates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "City Boundary"
        verbose_name_plural = "City Boundaries"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SafetyPin(gis_models.Model):
    """
    User-dropped incident or protest pin with an automatic 100-meter impact buffer polygon.
    Categories:
      - PEACEFUL: Peaceful Protest / Safe Zone
      - VIOLENT: Violent Incident / Danger Zone
    """
    CATEGORY_PEACEFUL = "PEACEFUL"
    CATEGORY_VIOLENT = "VIOLENT"

    CATEGORY_CHOICES = [
        (CATEGORY_PEACEFUL, "Peaceful Protest / Safe Zone"),
        (CATEGORY_VIOLENT, "Violent Incident / Danger Zone"),
    ]

    title = models.CharField(
        max_length=200,
        help_text="Title or brief label for the pin",
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the incident or protest",
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_PEACEFUL,
        help_text="Incident category",
    )
    geom = gis_models.PointField(
        srid=4326,
        help_text="Point geometry (Longitude, Latitude) in EPSG:4326",
    )
    buffer_geom = gis_models.PolygonField(
        srid=4326,
        null=True,
        blank=True,
        help_text="100-meter PostGIS buffer polygon generated from geom",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Safety Pin"
        verbose_name_plural = "Safety Pins"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["category", "-created_at"], name="mapper_pin_cat_created_idx"),
        ]

    def calculate_buffer(self):
        """
        Calculates a 100-meter PostGIS buffer polygon from the point geometry.
        Casting to geography (geom::geography) ensures the buffer distance is
        measured in true meters on the WGS84 spheroid before casting back to geometry.
        """
        if not self.geom:
            return None

        # Execute PostGIS ST_Buffer on geography type for an accurate 100-meter radius
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ST_Buffer(ST_GeomFromText(%s, 4326)::geography, 100)::geometry",
                [self.geom.wkt],
            )
            row = cursor.fetchone()
            if row and row[0]:
                return GEOSGeometry(row[0])
        return None

    def save(self, *args, **kwargs):
        """
        Ensures a 100-meter PostGIS buffer polygon is generated whenever a pin is created
        or its point geometry is updated.
        """
        if self.geom:
            if not self.buffer_geom:
                self.buffer_geom = self.calculate_buffer()
            elif self.pk:
                orig_geom = (
                    SafetyPin.objects.filter(pk=self.pk)
                    .values_list("geom", flat=True)
                    .first()
                )
                if orig_geom != self.geom:
                    self.buffer_geom = self.calculate_buffer()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"
