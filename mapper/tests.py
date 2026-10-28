from django.test import TestCase
from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from mapper.models import CityBoundary, SafetyPin


class CityBoundaryModelTest(TestCase):
    def setUp(self):
        # Dublin boundary polygon sample
        self.dublin_poly = Polygon((
            (-6.2800, 53.3350),
            (-6.2400, 53.3350),
            (-6.2400, 53.3650),
            (-6.2800, 53.3650),
            (-6.2800, 53.3350),
        ), srid=4326)

        # Paris boundary polygon sample
        self.paris_poly = Polygon((
            (2.25, 48.81),
            (2.42, 48.81),
            (2.42, 48.90),
            (2.25, 48.90),
            (2.25, 48.81),
        ), srid=4326)

    def test_create_city_boundaries(self):
        dublin = CityBoundary.objects.create(name="Dublin", geom=self.dublin_poly)
        paris = CityBoundary.objects.create(name="Paris", geom=self.paris_poly)

        self.assertEqual(str(dublin), "Dublin")
        self.assertEqual(str(paris), "Paris")
        self.assertEqual(dublin.geom.geom_type, "Polygon")
        self.assertEqual(paris.geom.geom_type, "Polygon")
        self.assertEqual(dublin.geom.srid, 4326)
        self.assertEqual(paris.geom.srid, 4326)


class SafetyPinModelTest(TestCase):
    def setUp(self):
        # Dublin City Boundary
        self.dublin_boundary = CityBoundary.objects.create(
            name="Dublin",
            geom=Polygon((
                (-6.3000, 53.3000),
                (-6.2000, 53.3000),
                (-6.2000, 53.4000),
                (-6.3000, 53.4000),
                (-6.3000, 53.3000),
            ), srid=4326)
        )

    def test_buffer_automatically_generated_on_save(self):
        pin = SafetyPin(
            title="O'Connell Street Peaceful Gathering",
            description="Peaceful gathering near the Spire.",
            category=SafetyPin.CATEGORY_PEACEFUL,
            geom=Point(-6.2603, 53.3498, srid=4326),
        )
        self.assertIsNone(pin.buffer_geom)

        pin.save()

        self.assertIsNotNone(pin.buffer_geom)
        self.assertEqual(pin.buffer_geom.geom_type, "Polygon")
        self.assertEqual(pin.buffer_geom.srid, 4326)

        # Verify the buffer radius is ~100 meters in PostGIS
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ST_Distance(
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    ST_PointN(ST_ExteriorRing(%s::geometry), 1)::geography
                )
                """,
                [-6.2603, 53.3498, pin.buffer_geom.hexewkb.decode('ascii')]
            )
            dist_meters = cursor.fetchone()[0]
            # Buffer distance should be approximately 100m (within +/- 1m tolerance for polygon vertex approximation)
            self.assertAlmostEqual(dist_meters, 100.0, delta=1.5)

    def test_buffer_updated_when_geom_changes(self):
        pin = SafetyPin.objects.create(
            title="Initial Marker",
            category=SafetyPin.CATEGORY_VIOLENT,
            geom=Point(-6.2603, 53.3498, srid=4326),
        )
        initial_buffer = pin.buffer_geom

        # Move marker to Trinity College
        pin.geom = Point(-6.2546, 53.3438, srid=4326)
        pin.save()

        self.assertNotEqual(initial_buffer.wkt, pin.buffer_geom.wkt)

    def test_database_trigger_generates_buffer_on_raw_insert(self):
        """Verify the PostGIS database trigger fires on raw SQL insert when buffer_geom is NULL"""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO mapper_safetypin (title, description, category, geom, created_at, updated_at)
                VALUES ('Raw SQL Pin', 'Inserted directly', 'PEACEFUL', ST_SetSRID(ST_MakePoint(-6.25, 53.35), 4326), NOW(), NOW())
                RETURNING id;
                """
            )
            pin_id = cursor.fetchone()[0]

        pin = SafetyPin.objects.get(id=pin_id)
        self.assertIsNotNone(pin.buffer_geom)
        self.assertEqual(pin.buffer_geom.geom_type, "Polygon")

    def test_spec_spatial_queries(self):
        """Verify the 4 spatial queries required by SPEC#1.md"""
        pin1 = SafetyPin.objects.create(
            title="City Center Pin",
            category=SafetyPin.CATEGORY_PEACEFUL,
            geom=Point(-6.2600, 53.3490, srid=4326),
        )
        pin2 = SafetyPin.objects.create(
            title="Nearby Pin (50m away)",
            category=SafetyPin.CATEGORY_VIOLENT,
            geom=Point(-6.2605, 53.3493, srid=4326),
        )

        with connection.cursor() as cursor:
            # Q1 Nearest Safety Pins (KNN)
            cursor.execute(
                """
                SELECT id, title, category,
                       ST_Distance(geom::geography, p::geography) AS dist_m
                FROM mapping_safetypin,
                     (SELECT ST_SetSRID(ST_MakePoint(-6.2600, 53.3490), 4326) AS p) q
                ORDER BY geom <-> p
                LIMIT 1;
                """
            )
            q1_row = cursor.fetchone()
            self.assertEqual(q1_row[0], pin1.id)

            # Q2 Pins within radius (Proximity search)
            cursor.execute(
                """
                SELECT id, title, category 
                FROM mapping_safetypin
                WHERE ST_DWithin(geom::geography,
                                 ST_SetSRID(ST_MakePoint(-6.2600, 53.3490), 4326)::geography, 500);
                """
            )
            q2_rows = cursor.fetchall()
            self.assertGreaterEqual(len(q2_rows), 2)

            # Q3 Containment check (Ensure dropped pin is inside city boundary)
            cursor.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM mapping_cityboundary b
                  WHERE ST_Contains(b.geom, ST_SetSRID(ST_MakePoint(-6.2600, 53.3490), 4326))
                );
                """
            )
            inside = cursor.fetchone()[0]
            self.assertTrue(inside)

            # Q4 Intersecting buffer analysis (Overlapping buffers)
            cursor.execute(
                """
                SELECT a.id AS pin_a, b.id AS pin_b
                FROM mapping_safetypin a, mapping_safetypin b
                WHERE a.id <> b.id
                  AND ST_Intersects(a.buffer_geom, b.buffer_geom);
                """
            )
            overlaps = cursor.fetchall()
            self.assertGreaterEqual(len(overlaps), 2)
