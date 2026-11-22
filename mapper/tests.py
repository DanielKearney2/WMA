from datetime import timedelta
import uuid

from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from mapper.models import City, HazardPin

PARIS_BBOX = (2.25, 48.81, 2.42, 48.91)
PARIS_CENTER = (2.3522, 48.8566)
OUTSIDE_POINT = (-30.0, 40.0)


def make_poly(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return Polygon(
        (
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ),
        srid=4326,
    )


class BaseAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.paris = City.objects.create(
            code="paris",
            name="Paris",
            geom=make_poly(PARIS_BBOX),
        )

        self.owner_token = uuid.uuid4()
        self.other_token = uuid.uuid4()

        self.pin_paris = HazardPin.objects.create(
            description="Incident near Notre-Dame",
            geom=Point(*PARIS_CENTER, srid=4326),
            owner_token=self.owner_token,
        )


class PinListCreateTest(BaseAPITest):
    url = "/api/v1/pins/"

    def test_list_returns_geojson_feature_collection(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 1)

    def test_list_rejects_category_filter_with_400(self):
        resp = self.client.get(self.url, {"category": "VIOLENT"})
        self.assertEqual(resp.status_code, 400)

    def test_list_bbox_filter_paris(self):
        bbox = f"{PARIS_BBOX[0]},{PARIS_BBOX[1]},{PARIS_BBOX[2]},{PARIS_BBOX[3]}"
        resp = self.client.get(self.url, {"bbox": bbox})
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        self.assertEqual(len(features), 1)

    def test_list_invalid_bbox_returns_400(self):
        resp = self.client.get(self.url, {"bbox": "bad,data"})
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_inside_city(self):
        token = uuid.uuid4()
        payload = {
            "description": "Hazard on Boulevard Saint-Germain",
            "latitude": 48.8530,
            "longitude": 2.3400,
            "owner_token": str(token),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["type"], "Feature")
        self.assertIn("buffer_geom", data["properties"])
        self.assertEqual(
            data["properties"]["description"], "Hazard on Boulevard Saint-Germain"
        )
        self.assertIn("expires_at", data["properties"])

    def test_create_pin_outside_city_rejected(self):
        payload = {
            "description": "Ocean Hazard",
            "latitude": OUTSIDE_POINT[1],
            "longitude": OUTSIDE_POINT[0],
            "owner_token": str(uuid.uuid4()),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_missing_owner_token_rejected(self):
        payload = {
            "description": "Missing token",
            "latitude": 48.8530,
            "longitude": 2.3400,
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_with_non_uuid_owner_token_rejected(self):
        payload = {
            "description": "Bad token",
            "latitude": 48.8530,
            "longitude": 2.3400,
            "owner_token": "not-a-valid-uuid",
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_pin_stacked_within_100m_rejected(self):
        # 50m north of PARIS_CENTER (~0.00045 deg lat) is <100m away
        payload = {
            "description": "Stacked pin",
            "latitude": PARIS_CENTER[1] + 0.00045,
            "longitude": PARIS_CENTER[0],
            "owner_token": str(uuid.uuid4()),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertIn("non_field_errors", data)
        self.assertIn("within 100 m", data["non_field_errors"][0])

    def test_create_pin_150m_apart_allowed(self):
        # 150m north of PARIS_CENTER (~0.00135 deg lat) is >100m away
        payload = {
            "description": "Pin 150m away",
            "latitude": PARIS_CENTER[1] + 0.00135,
            "longitude": PARIS_CENTER[0],
            "owner_token": str(uuid.uuid4()),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 201)

    def test_create_pin_rejects_outside_paris_when_second_city_exists(self):
        City.objects.create(
            code="test",
            name="Test City",
            geom=make_poly((-31.0, 39.0, -29.0, 41.0)),
        )
        payload = {
            "description": "Hazard in second city",
            "latitude": OUTSIDE_POINT[1],
            "longitude": OUTSIDE_POINT[0],
            "owner_token": str(uuid.uuid4()),
        }
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Paris", str(resp.json()))

    def test_owner_token_never_serialised(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        feature = data["features"][0]
        self.assertNotIn("owner_token", feature["properties"])
        self.assertNotIn("owner_token", feature)


class PinDetailTest(BaseAPITest):

    def _url(self, pk):
        return f"/api/v1/pins/{pk}/"

    def test_retrieve_existing_pin(self):
        resp = self.client.get(self._url(self.pin_paris.pk))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "Feature")
        self.assertEqual(data["properties"]["description"], "Incident near Notre-Dame")
        self.assertNotIn("owner_token", data["properties"])

    def test_retrieve_nonexistent_pin_returns_404(self):
        resp = self.client.get(self._url(99999))
        self.assertEqual(resp.status_code, 404)

    def test_delete_pin_without_token_403(self):
        resp = self.client.delete(self._url(self.pin_paris.pk))
        self.assertEqual(resp.status_code, 403)

    def test_delete_pin_with_wrong_token_403(self):
        resp = self.client.delete(
            self._url(self.pin_paris.pk),
            HTTP_X_OWNER_TOKEN=str(self.other_token),
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_pin_with_matching_token_204(self):
        pk = self.pin_paris.pk
        resp = self.client.delete(
            self._url(pk),
            HTTP_X_OWNER_TOKEN=str(self.owner_token),
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(HazardPin.objects.filter(pk=pk).exists())

    def test_patch_description_with_token_200(self):
        pk = self.pin_paris.pk
        resp = self.client.patch(
            self._url(pk),
            {"description": "Updated incident description"},
            format="json",
            HTTP_X_OWNER_TOKEN=str(self.owner_token),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(
            data["properties"]["description"], "Updated incident description"
        )
        self.pin_paris.refresh_from_db()
        self.assertEqual(self.pin_paris.description, "Updated incident description")

    def test_patch_other_field_with_token_400(self):
        pk = self.pin_paris.pk
        resp = self.client.patch(
            self._url(pk),
            {"latitude": 48.8600},
            format="json",
            HTTP_X_OWNER_TOKEN=str(self.owner_token),
        )
        self.assertEqual(resp.status_code, 400)


class PinExpiryTest(BaseAPITest):

    def test_expired_pin_not_returned_by_list(self):
        HazardPin.objects.create(
            description="Old expired hazard",
            geom=Point(2.3600, 48.8600, srid=4326),
            owner_token=uuid.uuid4(),
            expires_at=timezone.now() - timedelta(minutes=10),
        )
        resp = self.client.get("/api/v1/pins/")
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        descriptions = [f["properties"]["description"] for f in features]
        self.assertNotIn("Old expired hazard", descriptions)
        self.assertEqual(len(features), 1)

    def test_expired_pin_returns_404_on_detail(self):
        expired_pin = HazardPin.objects.create(
            description="Expired detail hazard",
            geom=Point(2.3600, 48.8600, srid=4326),
            owner_token=uuid.uuid4(),
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        resp = self.client.get(f"/api/v1/pins/{expired_pin.pk}/")
        self.assertEqual(resp.status_code, 404)


class PinNearestTest(BaseAPITest):
    url = "/api/v1/pins/nearest/"

    def test_nearest_returns_closest_first(self):
        resp = self.client.get(
            self.url,
            {"lat": PARIS_CENTER[1], "lon": PARIS_CENTER[0], "limit": 2},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("features", data)
        self.assertLessEqual(len(data["features"]), 2)
        self.assertEqual(
            data["features"][0]["properties"]["description"],
            "Incident near Notre-Dame",
        )
        self.assertIn("distance", data["features"][0]["properties"])
        self.assertEqual(data["features"][0]["properties"]["distance"], 0.0)

    def test_nearest_distance_reported_in_metres(self):
        HazardPin.objects.create(
            description="East pin",
            geom=Point(2.36, 48.8566, srid=4326),
            owner_token=self.owner_token,
        )
        resp = self.client.get(
            self.url,
            {"lat": PARIS_CENTER[1], "lon": PARIS_CENTER[0], "limit": 2},
        )
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        seeded = next(
            f for f in features if f["properties"]["description"] == "East pin"
        )
        distance = seeded["properties"]["distance"]
        self.assertTrue(400 < distance < 600)

    def test_nearest_category_parameter_rejected_with_400(self):
        resp = self.client.get(
            self.url,
            {
                "lat": PARIS_CENTER[1],
                "lon": PARIS_CENTER[0],
                "limit": 3,
                "category": "VIOLENT",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_nearest_missing_params_returns_400(self):
        resp = self.client.get(self.url, {"lat": 48.8566})
        self.assertEqual(resp.status_code, 400)

    def test_nearest_invalid_lat_returns_400(self):
        resp = self.client.get(self.url, {"lat": 999, "lon": 2.35})
        self.assertEqual(resp.status_code, 400)


class PinWithinTest(BaseAPITest):
    url = "/api/v1/pins/within/"

    def test_within_radius_returns_pins(self):
        resp = self.client.get(
            self.url,
            {"lat": PARIS_CENTER[1], "lon": PARIS_CENTER[0], "radius_m": 1000},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("distance", data["features"][0]["properties"])

    def test_within_distance_reported_in_metres(self):
        HazardPin.objects.create(
            description="East pin",
            geom=Point(2.36, 48.8566, srid=4326),
            owner_token=self.owner_token,
        )
        resp = self.client.get(
            self.url,
            {"lat": PARIS_CENTER[1], "lon": PARIS_CENTER[0], "radius_m": 1000},
        )
        self.assertEqual(resp.status_code, 200)
        features = resp.json()["features"]
        seeded = next(
            f for f in features if f["properties"]["description"] == "East pin"
        )
        distance = seeded["properties"]["distance"]
        self.assertTrue(400 < distance < 600)

    def test_within_tiny_radius_returns_exact_pin(self):
        resp = self.client.get(
            self.url,
            {"lat": PARIS_CENTER[1], "lon": PARIS_CENTER[0], "radius_m": 5},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)

    def test_within_category_parameter_rejected_with_400(self):
        resp = self.client.get(
            self.url,
            {
                "lat": PARIS_CENTER[1],
                "lon": PARIS_CENTER[0],
                "radius_m": 1000,
                "category": "PEACEFUL",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_within_missing_params_returns_400(self):
        resp = self.client.get(self.url, {"lat": 48.8566})
        self.assertEqual(resp.status_code, 400)

    def test_within_radius_too_large_returns_400(self):
        resp = self.client.get(
            self.url,
            {"lat": 48.8566, "lon": 2.35, "radius_m": 999_999},
        )
        self.assertEqual(resp.status_code, 400)


class CityListTest(BaseAPITest):
    url = "/api/v1/cities/"

    def test_list_returns_geojson_feature_collection(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 1)

    def test_city_features_contain_code_and_name(self):
        resp = self.client.get(self.url)
        features = resp.json()["features"]
        feature = features[0]
        self.assertEqual(feature["properties"]["code"], "paris")
        self.assertEqual(feature["properties"]["name"], "Paris")
