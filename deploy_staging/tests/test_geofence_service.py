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


# =====================================================================
# Milestone M2: Coverage Planner Unit & MAVLink Integration Test Suite
# =====================================================================
from backend.search.coverage_planner import (
    GeofenceCoveragePlanner,
    CameraFootprint,
    geo_to_local_meters,
    local_meters_to_geo,
    coverage_planner
)
from backend.flight.mavlink_service import MAVLinkService


class TestCoveragePlannerModel(unittest.TestCase):
    """Unit test suite for GeofenceCoveragePlanner mathematical algorithms."""

    def setUp(self):
        # Configure a standard circular geofence centered at Moffett Field
        self.planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0,
            grid_resolution_m=2.0,
            search_altitude_m=10.0
        )

    def test_initial_grid_and_area(self):
        """Verify circular grid discretization area matches analytical geometry."""
        # Theoretical area: pi * r^2 = pi * 100^2 ~ 31415.9 m^2
        self.assertAlmostEqual(self.planner.total_area_m2, 31415.0, delta=1500.0)
        self.assertGreater(len(self.planner.total_cells), 0)
        self.assertEqual(len(self.planner.scanned_cells), 0)
        self.assertEqual(self.planner.get_coverage_percentage(), 0.0)

    def test_camera_footprint_scaling(self):
        """Verify camera footprint dimensions scale linearly with flight altitude."""
        fp10 = CameraFootprint.calculate(altitude_m=10.0)
        fp20 = CameraFootprint.calculate(altitude_m=20.0)
        self.assertAlmostEqual(fp20.width_m, fp10.width_m * 2.0, delta=0.2)
        self.assertAlmostEqual(fp20.height_m, fp10.height_m * 2.0, delta=0.2)

    def test_gps_position_update_accumulates_scanned_cells(self):
        """Verify GPS updates inside geofence accumulate scanned cells and coverage."""
        # 1. Update at center
        pct1 = self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        self.assertGreater(pct1, 0.0)
        scanned_count_1 = len(self.planner.scanned_cells)
        self.assertGreater(scanned_count_1, 0)

        # 2. Update at adjacent location (+15m North ~ +0.000135 lat)
        pct2 = self.planner.update_drone_position(37.409435, -122.0641, altitude_m=10.0)
        self.assertGreaterEqual(pct2, pct1)
        self.assertGreater(len(self.planner.scanned_cells), scanned_count_1)

    def test_gps_position_outside_geofence_does_not_expand_coverage(self):
        """Verify GPS updates outside geofence boundary do not add invalid cells."""
        # Initial scan at center
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        valid_scanned = len(self.planner.scanned_cells)

        # Update 10 km away (out of bounds)
        pct = self.planner.update_drone_position(37.5000, -122.0641, altitude_m=10.0)
        self.assertEqual(len(self.planner.scanned_cells), valid_scanned)

    def test_reset_coverage_clears_scanned_cells(self):
        """Verify reset_coverage() clears scanned cells and resets percentage to zero."""
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        self.assertGreater(len(self.planner.scanned_cells), 0)

        # Reset
        self.planner.reset_coverage()
        self.assertEqual(len(self.planner.scanned_cells), 0)
        self.assertEqual(self.planner.get_coverage_percentage(), 0.0)

    def test_coverage_snapshot_structure(self):
        """Verify get_coverage_snapshot() serializes all required fields."""
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        snap = self.planner.get_coverage_snapshot()
        self.assertEqual(snap["boundary_type"], "circular")
        self.assertGreater(snap["total_area_m2"], 0.0)
        self.assertGreater(snap["scanned_area_m2"], 0.0)
        self.assertGreater(snap["coverage_pct"], 0.0)
        self.assertGreater(snap["scanned_cells_count"], 0)
        self.assertGreater(snap["total_cells_count"], 0)
        self.assertEqual(snap["grid_resolution_m"], 2.0)
        self.assertEqual(snap["search_altitude_m"], 10.0)
        self.assertIsInstance(snap["scanned_points"], list)
        self.assertGreater(len(snap["scanned_points"]), 0)

    def test_reconfigure_boundary_geometry(self):
        """Verify reconfigure() dynamically recalculates grid cells and resets coverage."""
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        self.assertGreater(len(self.planner.scanned_cells), 0)

        # Reconfigure to smaller radius 50m
        self.planner.reconfigure({
            "fence_type": "circular",
            "circle_center_lat": 37.4093,
            "circle_center_lon": -122.0641,
            "circle_radius_m": 50.0
        })
        self.assertEqual(len(self.planner.scanned_cells), 0)
        self.assertEqual(self.planner.circle_radius_m, 50.0)
        # 50m circle ~ 7853 m^2
        self.assertAlmostEqual(self.planner.total_area_m2, 7850.0, delta=500.0)


class TestMAVLinkCoverageIntegration(unittest.TestCase):
    """Integration test suite verifying MAVLink GPS stream feeds CoveragePlanner."""

    def setUp(self):
        coverage_planner.reset_coverage()

    def tearDown(self):
        coverage_planner.reset_coverage()

    def test_simulated_mavlink_stream_updates_coverage_planner(self):
        """Verify simulated MAVLink telemetry thread feeds GPS updates to coverage_planner."""
        initial_scanned = len(coverage_planner.scanned_cells)
        service = MAVLinkService(
            connection_string="simulated",
            heartbeat_timeout=1.0,
            simulate=True
        )
        try:
            service.start()
            import time
            time.sleep(0.35)  # Allow worker thread to run a few simulated orbital steps
            # Drone orbits around base coordinate (37.4093, -122.0641) inside geofence
            self.assertGreater(len(coverage_planner.scanned_cells), initial_scanned)
            self.assertGreater(coverage_planner.get_coverage_percentage(), 0.0)
        finally:
            service.stop()

    def test_direct_mavlink_gps_update_handling(self):
        """Verify _update_coverage_telemetry safely filters invalid/null coordinates."""
        service = MAVLinkService(connection_string="simulated", simulate=True)
        initial_cells = len(coverage_planner.scanned_cells)

        # 1. Null Island coordinate (0, 0) should be dropped
        service._update_coverage_telemetry(0.0, 0.0, 15.0)
        self.assertEqual(len(coverage_planner.scanned_cells), initial_cells)

        # 2. Out of range coordinates should be dropped
        service._update_coverage_telemetry(999.0, -122.0641, 15.0)
        self.assertEqual(len(coverage_planner.scanned_cells), initial_cells)

        # 3. Valid coordinate should update
        service._update_coverage_telemetry(37.4093, -122.0641, 15.0)
        self.assertGreater(len(coverage_planner.scanned_cells), initial_cells)


if __name__ == "__main__":
    unittest.main()

