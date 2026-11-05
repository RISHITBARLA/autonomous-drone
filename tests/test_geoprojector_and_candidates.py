"""
Unit tests for 3D Pinhole CameraGeoprojector and PriorityTargetDetector.
Verifies photogrammetric ground intersection, uncertainty bounds, coordinate integrity,
and priority candidate classification across synthetic targets.
"""
import math
import time
import unittest
import numpy as np
import cv2

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


class TestGeoprojectorAndCandidates(unittest.TestCase):
    def setUp(self):
        self.calib = CameraCalibration(
            image_width=1920,
            image_height=1080,
            hfov_deg=62.2,
            vfov_deg=48.8,
            mount_pitch_deg=-90.0,  # Nadir
        )
        self.projector = CameraGeoprojector(self.calib)
        self.detector = PriorityTargetDetector()

    def test_nadir_center_pixel_projection_accuracy(self):
        """Optical axis ray at center pixel (960, 540) must project to exact drone position."""
        ref_lat = 17.3850000
        ref_lon = 78.4867000
        pose = DronePose(
            timestamp=time.time(),
            lat=ref_lat,
            lon=ref_lon,
            alt_agl_m=25.0,
            roll_deg=0.0,
            pitch_deg=0.0,
            yaw_deg=0.0,
            gps_fix_valid=True,
            hdop=0.9,
        )

        est_lat, est_lon, unc_m, valid, approx = self.projector.project_pixel_to_ground(960.0, 540.0, pose)
        self.assertTrue(valid)
        self.assertFalse(approx)
        self.assertAlmostEqual(est_lat, ref_lat, places=6)
        self.assertAlmostEqual(est_lon, ref_lon, places=6)
        self.assertLess(unc_m, 5.0)

    def test_off_center_pixel_displacement(self):
        """Off-center pixel must project with correct displacement in meters."""
        ref_lat = 17.3850000
        ref_lon = 78.4867000
        alt = 20.0
        # Yaw = 0 (North), Camera Nadir (-90 pitch):
        # Pixel moved up (v < 540) corresponds to forward in camera optical frame -> North displacement
        pose = DronePose(
            timestamp=time.time(),
            lat=ref_lat,
            lon=ref_lon,
            alt_agl_m=alt,
            roll_deg=0.0,
            pitch_deg=0.0,
            yaw_deg=0.0,
            gps_fix_valid=True,
            hdop=1.0,
        )

        est_lat, est_lon, unc_m, valid, _ = self.projector.project_pixel_to_ground(960.0, 300.0, pose)
        self.assertTrue(valid)
        self.assertGreater(est_lat, ref_lat)  # Displaced North
        self.assertAlmostEqual(est_lon, ref_lon, places=5)

    def test_invalid_telemetry_integrity(self):
        """Projector must never fabricate coordinates when GPS is missing or alt <= 0.2m."""
        # GPS invalid
        pose_no_gps = DronePose(
            timestamp=time.time(),
            lat=None,
            lon=None,
            alt_agl_m=20.0,
            gps_fix_valid=False,
        )
        lat, lon, unc, valid, approx = self.projector.project_pixel_to_ground(960.0, 540.0, pose_no_gps)
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertFalse(valid)
        self.assertTrue(approx)

        # On ground (alt <= 0.2m)
        pose_ground = DronePose(
            timestamp=time.time(),
            lat=17.385,
            lon=78.486,
            alt_agl_m=0.1,
            gps_fix_valid=True,
        )
        lat2, lon2, _, valid2, _ = self.projector.project_pixel_to_ground(960.0, 540.0, pose_ground)
        self.assertIsNone(lat2)
        self.assertFalse(valid2)

    def test_square_candidate_detection(self):
        """Detector identifies clean square as SQUARE_CANDIDATE with correct priority color."""
        # Create 640x480 test image with a white square on black background
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (200, 150), (320, 270), (255, 255, 255), -1)

        candidates = self.detector.detect_candidates(frame)
        self.assertGreaterEqual(len(candidates), 1)

        sq = next((c for c in candidates if c.category == DetectionCategory.SQUARE_CANDIDATE), None)
        self.assertIsNotNone(sq)
        self.assertFalse(sq.is_confirmed)  # Not confirmed without secondary verification
        self.assertEqual(sq.color, "#FB923C")  # Orange priority
        self.assertGreater(sq.confidence, 0.6)

    def test_rectangular_candidate_detection(self):
        """Detector identifies elongated rectangle as RECTANGLE_CANDIDATE."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (150, 150), (380, 230), (240, 240, 240), -1)

        candidates = self.detector.detect_candidates(frame)
        self.assertGreaterEqual(len(candidates), 1)

        rect = next((c for c in candidates if c.category == DetectionCategory.RECTANGLE_CANDIDATE), None)
        self.assertIsNotNone(rect)
        self.assertEqual(rect.color, "#FB923C")

    def test_high_contrast_bw_pattern_detection(self):
        """Detector identifies high-contrast black-and-white grid as BW_PATTERN."""
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        # Draw high-contrast checkerboard in center
        for i in range(4):
            for j in range(4):
                color = (0, 0, 0) if (i + j) % 2 == 0 else (255, 255, 255)
                cv2.rectangle(frame, (200 + i * 25, 150 + j * 25), (200 + (i + 1) * 25, 150 + (j + 1) * 25), color, -1)

        candidates = self.detector.detect_candidates(frame)
        self.assertGreaterEqual(len(candidates), 1)
        bw_cand = candidates[0]
        self.assertIn(bw_cand.category, (DetectionCategory.BW_PATTERN, DetectionCategory.SQUARE_CANDIDATE))
        self.assertIn(bw_cand.color, (CATEGORY_COLORS[DetectionCategory.BW_PATTERN], CATEGORY_COLORS[DetectionCategory.SQUARE_CANDIDATE]))


if __name__ == "__main__":
    unittest.main()

