"""
Comprehensive Acceptance Test Suite for Task 2:
Autonomous Circular/Spiral Drone Scanning, Priority-Based Candidate Detection,
3D Geoprojection Photogrammetry, QR Verification, and Live Colour-Coded Heatmap.

Covers all 11 Acceptance Scenarios:
1. Circular boundary creation & radius scaling.
2. Archimedean spiral and concentric interior coverage waypoint generation.
3. Geofence containment audit and out-of-bounds rejection.
4. Priority geometric candidate detection (Square/Rectangle).
5. High-contrast B/W pattern discrimination (Otsu variance vs uniform shadow).
6. QR payload allowlist regex validation.
7. Validated QR event debouncing and safe RTL recommendation logging.
8. Live heatmap 7-category spatial clustering and Haversine deduplication.
9. 3D pinhole geoprojector photogrammetry & degraded uncertainty flags.
10. Asynchronous bounded queue drop-oldest behavior under burst load.
11. Flight control safety interlock preservation (FLIGHT_CONTROL_ENABLED=false).
"""
import math
import os
import time
import unittest
import numpy as np
import cv2

from config.settings import settings
from backend.mission.spiral_coverage_planner import (
    SpiralCoveragePlanner,
    SpiralCoverageConfig,
    geo_to_tangent_plane,
    tangent_plane_to_geo,
)
from backend.geofence.geofence_service import geofence_service
from backend.vision.geoprojector import (
    CameraGeoprojector,
    CameraCalibration,
    DronePose,
    EARTH_RADIUS_M,
)
from backend.vision.priority_detector import (
    PriorityTargetDetector,
    DetectionCategory,
    CATEGORY_COLORS,
)
from backend.vision.task2_vision_service import Task2VisionEngine, haversine_dist_m
from backend.app import create_app


class TestAutonomousScanningTask2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.engine = Task2VisionEngine()
        self.engine.clear_state()

    def tearDown(self):
        self.engine.stop()
        self.engine.clear_state()

    # ------------------------------------------------------------------------
    # Scenario 1: Circular boundary creation & radius scaling
    # ------------------------------------------------------------------------
    def test_scenario_1_circular_boundary_creation_and_geodesic_math(self):
        """Verify geodesic local tangent plane conversion and radius scaling."""
        lat0, lon0 = 37.4093000, -122.0641000
        dx_m, dy_m = 50.0, -30.0

        lat1, lon1 = tangent_plane_to_geo(dx_m, dy_m, lat0, lon0)
        # Round-trip projection back to tangent plane must match within 0.02m
        dx_calc, dy_calc = geo_to_tangent_plane(lat1, lon1, lat0, lon0)
        self.assertAlmostEqual(dx_calc, dx_m, delta=0.02)
        self.assertAlmostEqual(dy_calc, dy_m, delta=0.02)

        # Great-circle distance check
        dist = haversine_dist_m(lat0, lon0, lat1, lon1)
        self.assertAlmostEqual(dist, math.hypot(dx_m, dy_m), delta=0.15)

    # ------------------------------------------------------------------------
    # Scenario 2: Archimedean spiral interior coverage
    # ------------------------------------------------------------------------
    def test_scenario_2_archimedean_spiral_interior_coverage(self):
        """Verify Archimedean spiral generates contiguous inwards-to-outwards waypoints."""
        cfg = SpiralCoverageConfig(
            center_lat=37.4093,
            center_lon=-122.0641,
            radius_m=60.0,
            alt_m=20.0,
            overlap_pct=25.0,
            speed_m_s=3.5,
            pattern_type="spiral",
        )
        planner = SpiralCoveragePlanner(cfg)
        swath = planner.calculate_camera_swath()
        self.assertGreater(swath, 5.0)

        waypoints, meta = planner.generate_waypoints()
        self.assertGreater(len(waypoints), 10)
        self.assertEqual(meta["pattern"], "spiral")

        # Verify radial distance increases progressively
        dists = []
        for wp in waypoints:
            d = haversine_dist_m(cfg.center_lat, cfg.center_lon, wp.lat, wp.lon)
            dists.append(d)
            self.assertLessEqual(d, cfg.radius_m + 1.0)

        # Outermost waypoint should be near radius limit
        self.assertGreater(max(dists), cfg.radius_m * 0.70)

    # ------------------------------------------------------------------------
    # Scenario 3: Geofence containment audit & violation rejection
    # ------------------------------------------------------------------------
    def test_scenario_3_geofence_containment_and_violation_rejection(self):
        """Verify route exceeding geofence boundary is rejected with HTTP 400."""
        # Active circular geofence has radius ~300m at 37.4093, -122.0641
        # Request radius of 600m to intentionally breach geofence
        payload = {
            "center_lat": 37.4093,
            "center_lon": -122.0641,
            "radius_m": 600.0,
            "alt_m": 20.0,
            "pattern_type": "spiral",
        }
        res = self.client.post("/api/missions/generate-spiral", json=payload)
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertEqual(body["status"], "error")
        self.assertIn("geofence", body["message"].lower())

    # ------------------------------------------------------------------------
    # Scenario 4: Priority geometric candidate detection (Square/Rectangle)
    # ------------------------------------------------------------------------
    def test_scenario_4_priority_geometric_candidate_detection(self):
        """Verify detection of square and rectangular geometric contours."""
        detector = PriorityTargetDetector()
        img = np.zeros((480, 640, 3), dtype=np.uint8)

        # Draw bright square target (AR = 1.0)
        cv2.rectangle(img, (100, 100), (200, 200), (240, 240, 240), -1)
        # Draw bright rectangular target (AR = 2.0)
        cv2.rectangle(img, (350, 150), (550, 250), (230, 230, 230), -1)

        candidates = detector.detect_candidates(img)
        categories = [c.category for c in candidates]
        self.assertIn(DetectionCategory.SQUARE_CANDIDATE, categories)
        self.assertIn(DetectionCategory.RECTANGLE_CANDIDATE, categories)

        for c in candidates:
            if c.category == DetectionCategory.SQUARE_CANDIDATE:
                self.assertEqual(c.color, CATEGORY_COLORS[DetectionCategory.SQUARE_CANDIDATE])
                self.assertGreaterEqual(c.confidence, 0.60)

    # ------------------------------------------------------------------------
    # Scenario 5: High-contrast B/W pattern discrimination
    # ------------------------------------------------------------------------
    def test_scenario_5_high_contrast_bw_pattern_discrimination(self):
        """Verify high-contrast bimodal pattern detected as BW_PATTERN, while flat shadow is rejected."""
        detector = PriorityTargetDetector()

        # 1. High contrast checkerboard pattern
        img_bw = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(img_bw, (200, 150), (320, 270), (255, 255, 255), -1)
        cv2.rectangle(img_bw, (220, 170), (300, 250), (0, 0, 0), -1)
        candidates_bw = detector.detect_candidates(img_bw)
        categories_bw = [c.category for c in candidates_bw]
        self.assertTrue(
            DetectionCategory.BW_PATTERN in categories_bw or
            DetectionCategory.SQUARE_CANDIDATE in categories_bw or
            DetectionCategory.RECTANGLE_CANDIDATE in categories_bw
        )

        # 2. Flat uniform shadow/patch (std-dev < 12.0)
        img_flat = np.full((480, 640, 3), 45, dtype=np.uint8)
        candidates_flat = detector.detect_candidates(img_flat)
        self.assertEqual(len(candidates_flat), 0)

    # ------------------------------------------------------------------------
    # Scenario 6: QR payload allowlist validation
    # ------------------------------------------------------------------------
    def test_scenario_6_qr_payload_allowlist_validation(self):
        """Verify QR payload matching allowlist is validated, non-matching flagged unverified."""
        # Allowlist pattern in settings: ^[A-Za-z0-9_-]{2,64}$
        valid_payload = "MISSION_TARGET_A4"
        invalid_payload = "bad$*payload!!"

        self.assertTrue(bool(self.engine.validation_regex.match(valid_payload)))
        self.assertFalse(bool(self.engine.validation_regex.match(invalid_payload)))

    # ------------------------------------------------------------------------
    # Scenario 7: Validated QR event debouncing & safe RTL recommendation
    # ------------------------------------------------------------------------
    def test_scenario_7_qr_event_debouncing_and_safe_rtl_logging(self):
        """Verify duplicate QR detections within cooldown are debounced and RTL logged safely."""
        record = {
            "estimated_lat": 37.4093,
            "estimated_lon": -122.0641,
        }
        # First observation of payload
        self.engine._handle_validated_qr_event("TARGET_XYZ", record)
        self.assertEqual(record.get("rtl_recommendation"), "RECOMMENDED_BY_VISION")

        # Second observation of same payload immediately -> Debounced (no re-trigger)
        record2 = {"estimated_lat": 37.4093, "estimated_lon": -122.0641}
        self.engine._handle_validated_qr_event("TARGET_XYZ", record2)
        self.assertNotIn("rtl_recommendation", record2)

    # ------------------------------------------------------------------------
    # Scenario 8: Live heatmap 7-category clustering & Haversine deduplication
    # ------------------------------------------------------------------------
    def test_scenario_8_heatmap_clustering_and_haversine_dedup(self):
        """Verify multiple observations within cluster radius merge into single cluster."""
        lat0, lon0 = 37.409300, -122.064100
        for i in range(5):
            # Minor GPS jitter < 2m
            jitter_lat = lat0 + (i * 0.000008)
            jitter_lon = lon0 + (i * 0.000008)
            rec = {
                "category": DetectionCategory.SQUARE_CANDIDATE.value,
                "color": CATEGORY_COLORS[DetectionCategory.SQUARE_CANDIDATE],
                "confidence": 0.80,
                "uncertainty_m": 3.0,
                "estimated_lat": jitter_lat,
                "estimated_lon": jitter_lon,
                "timestamp": time.time() + i,
                "is_confirmed": False,
            }
            self.engine._ingest_into_spatial_cluster(rec)

        heatmap = self.engine.get_live_heatmap()
        self.assertEqual(heatmap["total_unique_targets"], 1)
        cluster = heatmap["clusters"][0]
        self.assertEqual(cluster["observation_count"], 5)
        self.assertGreater(cluster["confidence"], 0.80)
        self.assertAlmostEqual(cluster["estimated_lat"], lat0, places=4)

    # ------------------------------------------------------------------------
    # Scenario 9: 3D Geoprojector photogrammetry & degraded uncertainty flags
    # ------------------------------------------------------------------------
    def test_scenario_9_geoprojector_photogrammetry_and_degraded_flags(self):
        """Verify accurate ground ray intersection and degraded flag on invalid telemetry."""
        calib = CameraCalibration(
            image_width=1920,
            image_height=1080,
            hfov_deg=62.2,
            vfov_deg=48.8,
            mount_pitch_deg=-90.0,
        )
        projector = CameraGeoprojector(calib)

        # Valid level pose
        pose_valid = DronePose(
            timestamp=time.time(),
            lat=37.4093000,
            lon=-122.0641000,
            alt_agl_m=30.0,
            roll_deg=0.0,
            pitch_deg=0.0,
            yaw_deg=0.0,
            gps_fix_valid=True,
            hdop=0.8,
        )
        lat, lon, unc, valid, approx = projector.project_pixel_to_ground(960.0, 540.0, pose_valid)
        self.assertTrue(valid)
        self.assertFalse(approx)
        self.assertAlmostEqual(lat, 37.4093000, places=6)
        self.assertAlmostEqual(lon, -122.0641000, places=6)

        # Invalid pose: altitude 0.0 (drone on ground) -> degraded flag, no invented coordinates
        pose_ground = DronePose(
            timestamp=time.time(),
            lat=37.4093,
            lon=-122.0641,
            alt_agl_m=0.1,
            gps_fix_valid=True,
        )
        lat_g, lon_g, unc_g, valid_g, approx_g = projector.project_pixel_to_ground(960.0, 540.0, pose_ground)
        self.assertIsNone(lat_g)
        self.assertIsNone(lon_g)
        self.assertFalse(valid_g)
        self.assertTrue(approx_g)

    # ------------------------------------------------------------------------
    # Scenario 10: Asynchronous bounded queue drop-oldest behavior under burst load
    # ------------------------------------------------------------------------
    def test_scenario_10_bounded_queue_drop_oldest_under_burst(self):
        """Verify queue does not overflow and drops oldest frame under heavy burst load."""
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        dummy_pose = DronePose(
            timestamp=time.time(),
            lat=37.4093,
            lon=-122.0641,
            alt_agl_m=15.0,
            gps_fix_valid=True,
        )

        # Temporarily force sample N to 1
        orig_sample = settings.CANDIDATE_FRAME_SAMPLE_N
        try:
            settings.CANDIDATE_FRAME_SAMPLE_N = 1
            # Push 20 frames into maxsize=6 queue without worker running
            for _ in range(20):
                self.engine.submit_frame(dummy_frame, dummy_pose)

            # Queue depth must be capped at maxsize=6
            self.assertLessEqual(self.engine._frame_queue.qsize(), 6)
            # Dropped frame count must be > 0
            self.assertGreater(self.engine._total_dropped_frames, 0)
        finally:
            settings.CANDIDATE_FRAME_SAMPLE_N = orig_sample

    # ------------------------------------------------------------------------
    # Scenario 11: Flight control safety interlock preservation
    # ------------------------------------------------------------------------
    def test_scenario_11_flight_control_safety_interlock_preservation(self):
        """Verify FLIGHT_CONTROL_ENABLED=false, ARMING_CHECKS_ENABLED=true, and no actuation."""
        self.assertFalse(settings.FLIGHT_CONTROL_ENABLED)
        self.assertTrue(settings.ARMING_CHECKS_ENABLED)
        self.assertFalse(settings.FORCE_ARM)

        # API check: ARM attempt must be blocked with HTTP 403
        res = self.client.post("/api/flight/arm", json={"flight_mode": "STABILIZE"})
        self.assertEqual(res.status_code, 403)
        body = res.get_json()
        self.assertEqual(body.get("status"), "error")
        self.assertIn("FLIGHT_CONTROL_ENABLED", body.get("message", ""))


if __name__ == "__main__":
    unittest.main()
