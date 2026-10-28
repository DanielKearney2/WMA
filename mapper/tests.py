from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from mapper.models import CityBoundary, SafetyPin

DUBLIN_BBOX = (-6.3000, 53.3000, -6.2000, 53.4000)
PARIS_BBOX  = (2.25, 48.81, 2.42, 48.90)

DUBLIN_CENTER = (-6.2603, 53.3498)   # O'Connell St – inside Dublin bbox
PARIS_CENTER  = (2.3522, 48.8566)    # Notre-Dame   – inside Paris bbox


def make_poly(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return Polygon((
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
        (min_lon, min_lat),
    ), srid=4326)


class BaseAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.dublin = CityBoundary.objects.create(
            name="Dublin", geom=make_poly(DUBLIN_BBOX)
        )
        self.paris = CityBoundary.objects.create(
            name="Paris", geom=make_poly(PARIS_BBOX)
        )

        self.pin_dublin_peaceful = SafetyPin.objects.create(
            title="Dublin March",
            description="Peaceful rally",
            category=SafetyPin.CATEGORY_PEACEFUL,
            geom=Point(*DUBLIN_CENTER, srid=4326),
        )
        self.pin_dublin_violent = SafetyPin.objects.create(
            title="Dublin Riot",
            description="Violent incident",
            category=SafetyPin.CATEGORY_VIOLENT,
            geom=Point(-6.2610, 53.3500, srid=4326),
        )
        self.pin_paris = SafetyPin.objects.create(
            title="Paris Demo",
            description="Paris protest",
            category=SafetyPin.CATEGORY_PEACEFUL,
            geom=Point(*PARIS_CENTER, srid=4326),
        )

class PinListCreateTest(BaseAPITest):
    url = "/api/v1/pins/"

    def test_list_returns_geojson_feature_collection(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 3)

    def test_list_category_filter_peaceful(self):
        resp = self.client.get(self.url, {"category": "PEACEFUL"})
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        categories = [f["properties"]["category"] for f in features]
        self.assertTrue(all(c == "PEACEFUL" for c in categories))
        self.assertEqual(len(features), 2)

    def test_list_category_filter_violent(self):
        resp = self.client.get(self.url, {"category": "VIOLENT"})
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["properties"]["category"], "VIOLENT")

    def test_list_bbox_filter_dublin_only(self):
        bbox = f"{DUBLIN_BBOX[0]},{DUBLIN_BBOX[1]},{DUBLIN_BBOX[2]},{DUBLIN_BBOX[3]}"
        resp = self.client.get(self.url, {"bbox": bbox})
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertEqual(len(features), 2)

    def test_list_bbox_filter_paris_only(self):
        bbox = f"{PARIS_BBOX[0]},{PARIS_BBOX[1]},{PARIS_BBOX[2]},{PARIS_BBOX[3]}"
        resp = self.client.get(self.url, {"bbox": bbox})
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertEqual(len(features), 1)

    def test_list_bbox_filter_combined_with_category(self):
        bbox = f"{DUBLIN_BBOX[0]},{DUBLIN_BBOX[1]},{DUBLIN_BBOX[2]},{DUBLIN_BBOX[3]}"
        resp = self.client.get(self.url, {"bbox": bbox, "category": "VIOLENT"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["features"]), 1)

    def test_list_invalid_bbox_returns_400(self):
        resp = self.client.get(self.url, {"bbox": "bad,data"})
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_inside_city(self):
        payload = {
            "title": "Trinity College Pin",
            "description": "Near Trinity",
            "category": "PEACEFUL",
            "latitude": 53.3438,
            "longitude": -6.2546,
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["type"], "Feature")
        self.assertIsNotNone(data["properties"]["buffer_geom"])
        self.assertEqual(data["properties"]["category"], "PEACEFUL")

    def test_create_pin_outside_city_rejected(self):
        """Point in the middle of the Atlantic – outside all city boundaries."""
        payload = {
            "title": "Ocean Pin",
            "category": "VIOLENT",
            "latitude": 40.0,
            "longitude": -30.0,
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_invalid_lat_rejected(self):
        payload = {
            "title": "Bad coords",
            "category": "PEACEFUL",
            "latitude": 999,
            "longitude": -6.2603,
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_missing_fields_rejected(self):
        resp = self.client.post(self.url, {"title": "Incomplete"}, format="json")
        self.assertEqual(resp.status_code, 400)

class PinDetailTest(BaseAPITest):

    def _url(self, pk):
        return f"/api/v1/pins/{pk}/"

    def test_retrieve_existing_pin(self):
        resp = self.client.get(self._url(self.pin_dublin_peaceful.pk))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "Feature")
        self.assertEqual(data["properties"]["title"], "Dublin March")

    def test_retrieve_nonexistent_pin_returns_404(self):
        resp = self.client.get(self._url(99999))
        self.assertEqual(resp.status_code, 404)

    def test_delete_pin(self):
        pk = self.pin_paris.pk
        resp = self.client.delete(self._url(pk))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SafetyPin.objects.filter(pk=pk).exists())

    def test_delete_nonexistent_pin_returns_404(self):
        resp = self.client.delete(self._url(99999))
        self.assertEqual(resp.status_code, 404)

class PinNearestTest(BaseAPITest):

    url = "/api/v1/pins/nearest/"

    def test_nearest_returns_closest_first(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0], "limit": 2
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("features", data)
        self.assertLessEqual(len(data["features"]), 2)
        # First result should be the Dublin peaceful pin (same point)
        self.assertEqual(
            data["features"][0]["properties"]["title"], "Dublin March"
        )

    def test_nearest_with_category_filter(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0],
            "limit": 3, "category": "VIOLENT"
        })
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertTrue(all(
            f["properties"]["category"] == "VIOLENT" for f in features
        ))

    def test_nearest_missing_params_returns_400(self):
        resp = self.client.get(self.url, {"lat": 53.35})
        self.assertEqual(resp.status_code, 400)

    def test_nearest_invalid_lat_returns_400(self):
        resp = self.client.get(self.url, {"lat": 999, "lon": -6.26})
        self.assertEqual(resp.status_code, 400)

class PinWithinTest(BaseAPITest):

    url = "/api/v1/pins/within/"

    def test_within_large_radius_returns_both_dublin_pins(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0], "radius_m": 1000
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)

    def test_within_tiny_radius_returns_only_exact_pin(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0], "radius_m": 5
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)

    def test_within_with_category_filter(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0],
            "radius_m": 1000, "category": "PEACEFUL"
        })
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertTrue(all(
            f["properties"]["category"] == "PEACEFUL" for f in features
        ))

    def test_within_excludes_paris_from_dublin_search(self):
        resp = self.client.get(self.url, {
            "lat": DUBLIN_CENTER[1], "lon": DUBLIN_CENTER[0], "radius_m": 5000
        })
        self.assertEqual(resp.status_code, 200)
        titles = [f["properties"]["title"] for f in resp.json()["features"]]
        self.assertNotIn("Paris Demo", titles)

    def test_within_missing_params_returns_400(self):
        resp = self.client.get(self.url, {"lat": 53.35})
        self.assertEqual(resp.status_code, 400)

    def test_within_radius_too_large_returns_400(self):
        resp = self.client.get(self.url, {
            "lat": 53.35, "lon": -6.26, "radius_m": 999_999
        })
        self.assertEqual(resp.status_code, 400)

class BoundaryListTest(BaseAPITest):

    url = "/api/v1/boundaries/"

    def test_list_returns_geojson_feature_collection(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 2)

    def test_boundary_features_contain_name(self):
        resp = self.client.get(self.url)
        names = {f["properties"]["name"] for f in resp.json()["features"]}
        self.assertIn("Dublin", names)
        self.assertIn("Paris", names)
