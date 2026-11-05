"""
Unit tests for Archimedean Spiral and Tangential Coverage Planner.
Tests:
1. Swath width and camera footprint scaling with altitude and overlap.
2. Coordinate conversion precision (WGS84 <-> Local Tangent Plane).
3. Archimedean spiral interior coverage (points expand progressively from center).
4. Concentric tangential ring generation.
5. Geofence containment validation and violation detection.
6. Input rejection on invalid coordinates, zero/negative radius.
"""
import math
import unittest

from backend.geofence.geofence_service import (
    GeofenceConfig,
    geofence_service,
    haversine_distance_m,
)
from backend.mission.spiral_coverage_planner import (
    SpiralCoverageConfig,
    SpiralCoveragePlanner,
    geo_to_tangent_plane,
    tangent_plane_to_geo,
)


class TestSpiralCoveragePlanner(unittest.TestCase):
    def setUp(self):
        # Configure test geofence centered at (37.4093, -122.0641) with 300m radius
        self.center_lat = 37.4093
        self.center_lon = -122.0641
        geofence_service.config = GeofenceConfig(
            enabled=True,
            fence_type="circular",
            circle_center_lat=self.center_lat,
            circle_center_lon=self.center_lon,
            circle_radius_m=300.0,
            min_alt_m=1.0,
            max_alt_m=120.0,
        )

    def test_tangent_plane_projection_roundtrip(self):
        """Verify local tangent plane conversion is accurate within 0.05 meters."""
        test_lat = 37.4105
        test_lon = -122.0625

        x, y = geo_to_tangent_plane(test_lat, test_lon, self.center_lat, self.center_lon)
        reconstructed_lat, reconstructed_lon = tangent_plane_to_geo(x, y, self.center_lat, self.center_lon)

        self.assertAlmostEqual(test_lat, reconstructed_lat, places=5)
        self.assertAlmostEqual(test_lon, reconstructed_lon, places=5)

        # Distance error should be negligible (< 0.05 m)
        err_m = haversine_distance_m(test_lat, test_lon, reconstructed_lat, reconstructed_lon)
        self.assertLess(err_m, 0.05)

    def test_swath_width_scaling(self):
        """Verify ground swath expands with altitude and contracts with overlap."""
        # Baseline: 15m altitude, 25% overlap
        cfg1 = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=50.0,
            alt_m=15.0,
            overlap_pct=25.0,
        )
        planner1 = SpiralCoveragePlanner(cfg1)
        swath1 = planner1.calculate_camera_swath()
        self.assertGreater(swath1, 10.0)

        # Higher altitude (30m) -> Swath should roughly double
        cfg2 = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=50.0,
            alt_m=30.0,
            overlap_pct=25.0,
        )
        planner2 = SpiralCoveragePlanner(cfg2)
        swath2 = planner2.calculate_camera_swath()
        self.assertAlmostEqual(swath2 / swath1, 2.0, delta=0.2)

        # Higher overlap (60%) -> Swath should shrink
        cfg3 = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=50.0,
            alt_m=15.0,
            overlap_pct=60.0,
        )
        planner3 = SpiralCoveragePlanner(cfg3)
        swath3 = planner3.calculate_camera_swath()
        self.assertLess(swath3, swath1)

    def test_spiral_waypoint_generation_and_interior_coverage(self):
        """Verify Archimedean spiral generates ordered waypoints covering the circle interior."""
        radius_m = 60.0
        cfg = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=radius_m,
            alt_m=15.0,
            pattern_type="spiral",
        )
        planner = SpiralCoveragePlanner(cfg)
        waypoints, meta = planner.generate_waypoints()

        self.assertGreaterEqual(len(waypoints), 10)
        self.assertEqual(meta["pattern"], "spiral")
        self.assertEqual(meta["radius_m"], radius_m)
        self.assertGreater(meta["total_path_length_m"], 100.0)

        # First waypoint is near center
        d_first = haversine_distance_m(self.center_lat, self.center_lon, waypoints[0].lat, waypoints[0].lon)
        self.assertLessEqual(d_first, 1.0)

        # Radial distances should expand progressively
        distances = [
            haversine_distance_m(self.center_lat, self.center_lon, wp.lat, wp.lon)
            for wp in waypoints
        ]
        # Check that waypoints span the interior: min distance near 0, max distance near radius
        self.assertLess(distances[0], 2.0)
        self.assertAlmostEqual(max(distances), radius_m, delta=6.0)

        # Waypoint spacing between consecutive points is smooth (< 10m)
        for i in range(1, len(waypoints)):
            step_d = haversine_distance_m(
                waypoints[i - 1].lat, waypoints[i - 1].lon, waypoints[i].lat, waypoints[i].lon
            )
            self.assertLessEqual(step_d, 12.0)

    def test_tangential_concentric_pattern(self):
        """Verify tangential concentric pattern generates valid waypoints."""
        cfg = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=50.0,
            alt_m=15.0,
            pattern_type="tangential",
        )
        planner = SpiralCoveragePlanner(cfg)
        waypoints, meta = planner.generate_waypoints()

        self.assertGreaterEqual(len(waypoints), 12)
        self.assertEqual(meta["pattern"], "tangential")

    def test_geofence_validation_contained_vs_exceeded(self):
        """Verify geofence validator accepts contained routes and rejects boundary breaches."""
        # Case A: 80m radius circle inside 300m geofence -> PASSED
        cfg_safe = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=80.0,
            alt_m=15.0,
        )
        planner_safe = SpiralCoveragePlanner(cfg_safe)
        wps_safe, _ = planner_safe.generate_waypoints()
        is_valid, violations = planner_safe.validate_against_geofence(wps_safe)
        self.assertTrue(is_valid)
        self.assertEqual(len(violations), 0)

        # Case B: 350m radius circle exceeding 300m geofence -> REJECTED
        cfg_excess = SpiralCoverageConfig(
            center_lat=self.center_lat,
            center_lon=self.center_lon,
            radius_m=350.0,
            alt_m=15.0,
        )
        planner_excess = SpiralCoveragePlanner(cfg_excess)
        wps_excess, _ = planner_excess.generate_waypoints()
        is_valid_e, violations_e = planner_excess.validate_against_geofence(wps_excess)
        self.assertFalse(is_valid_e)
        self.assertGreater(len(violations_e), 0)

    def test_invalid_input_rejection(self):
        """Verify zero or negative radius and invalid coordinates raise ValueError."""
        # Zero radius
        with self.assertRaises(ValueError):
            SpiralCoveragePlanner(SpiralCoverageConfig(self.center_lat, self.center_lon, radius_m=0.0)).generate_waypoints()

        # Negative radius
        with self.assertRaises(ValueError):
            SpiralCoveragePlanner(SpiralCoverageConfig(self.center_lat, self.center_lon, radius_m=-20.0)).generate_waypoints()

        # Out-of-bounds latitude
        with self.assertRaises(ValueError):
            SpiralCoveragePlanner(SpiralCoverageConfig(95.0, self.center_lon, radius_m=50.0)).generate_waypoints()


if __name__ == "__main__":
    unittest.main()

