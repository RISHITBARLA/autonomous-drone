"""
Unit and Integration tests for Geofence Boundary and Navigation Planning Subsystem (Milestone 05).
Tests Haversine distance, ray-casting point-in-polygon, boundary violations,
mission safety auditing, and REST API routes.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.geofence.geofence_service import (
    GeofenceService,
    GeofenceConfig,
    haversine_distance_m,
    point_in_polygon
)
from backend.mission.mission_model import Mission, Waypoint
from backend.app import create_app


class TestGeofenceAlgorithms(unittest.TestCase):
    """Test suite for mathematical and geometric geofence algorithms."""

    def test_haversine_distance(self):
        """Verify Haversine distance between two known GPS coordinates."""
        # San Francisco (37.7749, -122.4194) to Oakland (37.8044, -122.2711) ~ 13.4 km
        dist = haversine_distance_m(37.7749, -122.4194, 37.8044, -122.2711)
        self.assertAlmostEqual(dist, 13450.0, delta=200.0)

        # Same point -> 0 meters
        self.assertAlmostEqual(haversine_distance_m(37.0, -122.0, 37.0, -122.0), 0.0, delta=0.01)

    def test_point_in_polygon(self):
        """Verify ray-casting accurately identifies inside and outside points."""
        square = [
            {"lat": 10.0, "lon": 10.0},
            {"lat": 10.0, "lon": 20.0},
            {"lat": 20.0, "lon": 20.0},
            {"lat": 20.0, "lon": 10.0}
        ]
        # Inside center
        self.assertTrue(point_in_polygon(15.0, 15.0, square))

        # Outside
        self.assertFalse(point_in_polygon(5.0, 15.0, square))
        self.assertFalse(point_in_polygon(25.0, 15.0, square))
        self.assertFalse(point_in_polygon(15.0, 25.0, square))


class TestGeofenceService(unittest.TestCase):
    """Test suite for GeofenceService operations and boundary evaluations."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage_file = self.temp_dir / "test_geofence.json"
        self.service = GeofenceService(storage_path=self.storage_file)

        # Configure circular fence centered at (37.4093, -122.0641) with 200m radius
        self.service.update_config({
            "enabled": True,
            "fence_type": "circular",
            "circle_center_lat": 37.4093,
            "circle_center_lon": -122.0641,
            "circle_radius_m": 200.0,
            "min_alt_m": 2.0,
            "max_alt_m": 100.0
        })

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_circular_fence_inside(self):
        """Verify point within radius and altitude is marked inside."""
        res = self.service.check_coordinate(37.4093, -122.0641, alt_m=15.0)
        self.assertTrue(res["inside"])
        self.assertTrue(res["horizontal_ok"])
        self.assertTrue(res["vertical_ok"])
        self.assertEqual(len(res["violations"]), 0)

    def test_circular_fence_radius_breach(self):
        """Verify point outside radius flags violation."""
        # 0.01 deg latitude is ~1110 meters away (> 200m)
        res = self.service.check_coordinate(37.4193, -122.0641, alt_m=15.0)
        self.assertFalse(res["inside"])
        self.assertFalse(res["horizontal_ok"])
        self.assertGreaterEqual(len(res["violations"]), 1)

    def test_altitude_breaches(self):
        """Verify altitude below floor or above ceiling flags violation."""
        floor_breach = self.service.check_coordinate(37.4093, -122.0641, alt_m=0.5)  # min is 2.0m
        self.assertFalse(floor_breach["inside"])
        self.assertFalse(floor_breach["vertical_ok"])

        ceiling_breach = self.service.check_coordinate(37.4093, -122.0641, alt_m=150.0)  # max is 100.0m
        self.assertFalse(ceiling_breach["inside"])
        self.assertFalse(ceiling_breach["vertical_ok"])

    def test_validate_mission_waypoints(self):
        """Verify mission validation flags breaches accurately."""
        valid_mission = Mission(
            id="m_valid",
            name="Valid",
            waypoints=[
                Waypoint(seq=1, lat=37.4093, lon=-122.0641, alt_m=10.0),
                Waypoint(seq=2, lat=37.4094, lon=-122.0640, alt_m=15.0)
            ]
        )
        report_valid = self.service.validate_mission(valid_mission)
        self.assertTrue(report_valid["valid"])
        self.assertEqual(len(report_valid["violations"]), 0)

        invalid_mission = Mission(
            id="m_invalid",
            name="Invalid",
            waypoints=[
                Waypoint(seq=1, lat=37.4093, lon=-122.0641, alt_m=10.0),
                Waypoint(seq=2, lat=37.4999, lon=-122.0640, alt_m=200.0)  # out of bounds
            ]
        )
        report_invalid = self.service.validate_mission(invalid_mission)
        self.assertFalse(report_invalid["valid"])
        self.assertGreater(len(report_invalid["violations"]), 0)


class TestGeofenceAPI(unittest.TestCase):
    """Test suite for /api/geofence REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_get_and_post_geofence(self):
        """Verify GET and POST /api/geofence."""
        get_res = self.client.get("/api/geofence")
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("circle_radius_m", data["data"])

        post_res = self.client.post("/api/geofence", json={"circle_radius_m": 300.0})
        self.assertEqual(post_res.status_code, 200)
        data_post = post_res.get_json()
        self.assertEqual(data_post["data"]["circle_radius_m"], 300.0)

    def test_check_point_endpoint(self):
        """Verify POST /api/geofence/check-point."""
        res = self.client.post("/api/geofence/check-point", json={"lat": 37.4093, "lon": -122.0641, "alt_m": 15.0})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("inside", data["data"])

    def test_plan_preview_endpoint(self):
        """Verify POST /api/geofence/plan-preview."""
        payload = {
            "waypoints": [
                {"lat": 37.4093, "lon": -122.0641, "alt_m": 10.0, "speed_m_s": 5.0},
                {"lat": 37.4095, "lon": -122.0638, "alt_m": 15.0, "speed_m_s": 5.0}
            ]
        }
        res = self.client.post("/api/geofence/plan-preview", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("metrics", data["data"])
        self.assertGreater(data["data"]["metrics"]["total_distance_m"], 0.0)


if __name__ == "__main__":
    unittest.main()

