import gzip
import json
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError

from mapper.models import City


class Command(BaseCommand):
    help = "Seeds or updates the Paris city boundary from an ADMIN-EXPRESS-COG GeoJSON fixture (INSEE 75056)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default=None,
            help="Path to Paris GeoJSON file (plain or .gz). Defaults to mapper/fixtures/paris.geojson.gz",
        )

    def handle(self, *args, **options):
        source = options["source"]
        if not source:
            source = settings.BASE_DIR / "mapper" / "fixtures" / "paris.geojson.gz"
        else:
            source = Path(source)

        if not source.exists():
            raise CommandError(f"Fixture file not found at {source}")

        self.stdout.write(f"Reading Paris boundary from: {source}")

        if str(source).endswith(".gz"):
            with gzip.open(source, "rt", encoding="utf-8") as f:
                geojson_data = json.load(f)
        else:
            with open(source, "r", encoding="utf-8") as f:
                geojson_data = json.load(f)

        geom_json = None
        if geojson_data.get("type") == "FeatureCollection":
            features = geojson_data.get("features", [])
            for feat in features:
                props = feat.get("properties", {})
                if props.get("code") == "75056" or props.get("insee") == "75056" or props.get("nom") == "Paris":
                    geom_json = feat.get("geometry")
                    break
            if not geom_json and features:
                geom_json = features[0].get("geometry")
        elif geojson_data.get("type") == "Feature":
            geom_json = geojson_data.get("geometry")
        elif geojson_data.get("type") in ("Polygon", "MultiPolygon"):
            geom_json = geojson_data
        else:
            raise CommandError("Unrecognized GeoJSON format")

        if not geom_json:
            raise CommandError("Could not locate geometry in GeoJSON file")

        geos_geom = GEOSGeometry(json.dumps(geom_json), srid=4326)

        if isinstance(geos_geom, MultiPolygon):
            largest_poly = max(geos_geom, key=lambda p: p.area)
            geos_geom = Polygon(largest_poly.exterior_ring, srid=4326)
        elif not isinstance(geos_geom, Polygon):
            raise CommandError(f"Expected Polygon geometry, got {geos_geom.geom_type}")

        city, created = City.objects.update_or_create(
            code="paris",
            defaults={
                "name": "Paris",
                "geom": geos_geom,
            },
        )

        status_msg = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully {status_msg.lower()} City '{city.name}' (code: {city.code}, id: {city.id})"
            )
        )
