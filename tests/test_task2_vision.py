#!/usr/bin/env python3
"""
Automated QA Verification Suite for Task 2 (Visual Object Search & Geospatial Heatmap).
Tests:
1. Low-light darkness and uniform shadow rejection (Noise/Shadow Gate).
2. Nadir camera-to-ground 3D GPS projection accuracy against synthetic ground coordinates.
3. Coordinate integrity: Never invent coordinates when GPS fix is invalid or alt <= 0.
4. Haversine spatial deduplication: Repeated observations of stationary target grouped into 1 cluster.
5. ADDC 2026 2+2 digit intelligence code logic: Airborne QR (2 digits) + Ground puzzle (2 digits).
6. Non-blocking Flask extension endpoints (/api/v2/vision/heatmap, /api/v2/vision/config, /api/v2/vision/qr_puzzle_digits).
"""
import time
import unittest
import numpy as np
from flask import Flask

from backend.vision.task2_vision_master import (
    DronePoseSnapshot,
    NonBlockingVisionPipeline,
    RawObjectDetection,
    TargetPriorityLevel,
    VisionHeatmapConfig,
    create_task2_vision_blueprint,
)


class TestTask2VisionAndHeatmap(unittest.TestCase):
    def setUp(self):
        self.cfg = VisionHeatmapConfig(
            frame_sample_every_n=1,
            image_width=1920,
            image_height=1080,
            mount_pitch_deg=-90.0,  # Nadir downward-facing camera
            dedup_cluster_radius_m=5.0,
            image_save_dir="captures/test_task2_targets"
        )

    def test_1_darkness_and_uniform_shadow_rejection(self):
        pipeline = NonBlockingVisionPipeline(self.cfg)
        dark_frame = np.zeros((480, 640, 3), dtype=np.uint8)  # Pitch black frame
        passed, reason = pipeline.preprocessor.passes_evidence_gate(dark_frame, (100, 100, 220, 220))
        self.assertFalse(passed)
        self.assertEqual(reason, "REJECTED_DARKNESS")

        shadow_frame = np.full((480, 640, 3), 40, dtype=np.uint8)  # Flat uniform shadow
        passed_s, reason_s = pipeline.preprocessor.passes_evidence_gate(shadow_frame, (100, 100, 220, 220))
        self.assertFalse(passed_s)
        self.assertEqual(reason_s, "REJECTED_UNIFORM_SHADOW")

    def test_2_nadir_camera_to_ground_gps_projection_accuracy(self):
        pipeline = NonBlockingVisionPipeline(self.cfg)
        pose = DronePoseSnapshot(
            timestamp=time.time(),
            lat=17.3850000,
            lon=78.4867000,
            alt_agl_m=30.0,
            roll_deg=0.0,
            pitch_deg=0.0,
            yaw_deg=0.0,
            gps_fix_valid=True,
        )
        # Principal point (center pixel 960, 540) on level nadir drone must project directly to drone lat/lon
        est_lat, est_lon, unc_m, valid, approx = pipeline.projector.project_bbox_to_gps(
            (910, 490, 1010, 590), pose
        )
        self.assertTrue(valid)
        self.assertFalse(approx)
        self.assertAlmostEqual(est_lat, 17.3850000, places=5)
        self.assertAlmostEqual(est_lon, 78.4867000, places=5)
        self.assertGreater(unc_m, 0.0)

    def test_3_never_invent_coordinates_when_gps_invalid(self):
        pipeline = NonBlockingVisionPipeline(self.cfg)
        no_gps_pose = DronePoseSnapshot(
            timestamp=time.time(), lat=None, lon=None, alt_agl_m=20.0, gps_fix_valid=False
        )
        est_lat, est_lon, _, valid, approx = pipeline.projector.project_bbox_to_gps(
            (500, 500, 600, 600), no_gps_pose
        )
        self.assertIsNone(est_lat)
        self.assertIsNone(est_lon)
        self.assertFalse(valid)
        self.assertTrue(approx)

    def test_4_repeated_observations_grouped_into_single_object(self):
        # Create textured synthetic frame so evidence gate passes
        textured_frame = np.random.randint(60, 220, (1080, 1920, 3), dtype=np.uint8)
        det_fn = lambda frame: [
            RawObjectDetection(
                bbox_xyxy=(920, 500, 1000, 580),
                category="payload_box",
                confidence=0.75,
                timestamp=time.time(),
            )
        ]
        pipeline = NonBlockingVisionPipeline(self.cfg, detector_fn=det_fn)
        pose = DronePoseSnapshot(
            timestamp=time.time(), lat=17.3850, lon=78.4867, alt_agl_m=25.0, gps_fix_valid=True
        )

        # Simulate 5 consecutive camera frames observing the exact same stationary ground target
        for _ in range(5):
            pipeline.process_single_frame_sync(textured_frame, pose)

        payload = pipeline.heatmap_engine.generate_heatmap_payload()
        self.assertEqual(payload["total_unique_objects"], 1)
        self.assertEqual(payload["markers"][0]["observation_count"], 5)
        self.assertEqual(payload["markers"][0]["priority_level"], TargetPriorityLevel.HIGH_PRIORITY.value)

    def test_5_addc_2026_qr_two_digit_partial_rule(self):
        pipeline = NonBlockingVisionPipeline(self.cfg)
        status_after_qr = pipeline.heatmap_engine.record_qr_verification("ADDC-QR: 42", None, None)
        self.assertEqual(status_after_qr["drone_qr_2_digits"], "42")
        # Decoding QR alone must NOT mark the 4-digit intelligence code complete
        self.assertFalse(status_after_qr["intelligence_code_complete"])
        self.assertIsNone(status_after_qr["combined_4_digit_access_code"])

        # Supplying the ground operative's 2 puzzle digits completes the 4-digit intelligence code
        status_complete = pipeline.heatmap_engine.set_ground_operative_puzzle_digits("89")
        self.assertTrue(status_complete["intelligence_code_complete"])
        self.assertEqual(status_complete["combined_4_digit_access_code"], "4289")

    def test_6_flask_blueprint_integration(self):
        pipeline = NonBlockingVisionPipeline(self.cfg)
        app = Flask(__name__)
        app.register_blueprint(create_task2_vision_blueprint(pipeline))

        client = app.test_client()
        res = client.get("/api/v2/vision/heatmap")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["heatmap_type"], "VISUAL_DETECTION_HEATMAP")
        self.assertIn("markers", data)
        self.assertIn("addc_intelligence", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)

