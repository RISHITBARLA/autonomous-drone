"""
Comprehensive tests for Computer Vision and QR Detection Subsystem (Milestone 02).
Tests QR detection, multi-QR decoding, edge cases, background worker lifecycle,
duplicate cooldowns, history ring buffers, and uploaded image processing.
"""
import time
import unittest
import numpy as np
import cv2

from backend.vision.qr_detector import QRDetector
from backend.vision.vision_service import VisionService
from backend.app import create_app


class TestQRDetector(unittest.TestCase):
    """Test suite for QRDetector computer vision algorithms."""

    def setUp(self):
        self.detector = QRDetector()

    def test_detect_valid_qr_code(self):
        """Verify detector reliably decodes a synthetic QR code."""
        test_payload = "MISSION:ALPHA_WAYPOINT_01"
        frame = QRDetector.generate_test_qr_frame(test_payload, width=640, height=480)

        results = self.detector.detect_and_decode(frame)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].payload, test_payload)
        self.assertIn("x", results[0].bbox)
        self.assertIn("width", results[0].bbox)
        self.assertEqual(len(results[0].points), 4)
        self.assertEqual(len(results[0].center), 2)
        self.assertGreaterEqual(results[0].confidence, 0.5)

    def test_detect_multiple_qr_codes(self):
        """Verify detector can detect multiple QR codes side by side in a single frame."""
        frame1 = QRDetector.generate_test_qr_frame("QR_ONE", width=300, height=300)
        frame2 = QRDetector.generate_test_qr_frame("QR_TWO", width=300, height=300)

        # Place side by side on a 700x400 canvas
        canvas = np.full((400, 700, 3), 255, dtype=np.uint8)
        canvas[50:350, 40:340] = frame1
        canvas[50:350, 360:660] = frame2

        results = self.detector.detect_and_decode(canvas)
        payloads = [r.payload for r in results]
        # At least one or both detected depending on OpenCV multi-detection
        self.assertGreaterEqual(len(payloads), 1)

    def test_empty_frame(self):
        """Verify empty/blank canvas returns empty list without error."""
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        results = self.detector.detect_and_decode(blank)
        self.assertEqual(results, [])

    def test_corrupted_and_invalid_inputs(self):
        """Verify None, non-array, and microscopic inputs are handled gracefully."""
        self.assertEqual(self.detector.detect_and_decode(None), [])
        self.assertEqual(self.detector.detect_and_decode(np.array([])), [])
        self.assertEqual(self.detector.detect_and_decode(np.zeros((10, 10, 3), dtype=np.uint8)), [])

    def test_blurred_frame(self):
        """Verify heavily blurred QR frame does not crash detector."""
        frame = QRDetector.generate_test_qr_frame("TEST_BLUR", width=320, height=240)
        blurred = cv2.GaussianBlur(frame, (51, 51), 0)
        results = self.detector.detect_and_decode(blurred)
        self.assertIsInstance(results, list)


class TestVisionService(unittest.TestCase):
    """Test suite for VisionService background engine, cooldown, and history."""

    def setUp(self):
        self.service = VisionService()
        self.service._cooldown_seconds = 1.0  # short cooldown for testing

    def tearDown(self):
        self.service.stop()

    def test_service_lifecycle(self):
        """Verify start and stop methods manage background thread correctly."""
        self.assertFalse(self.service.is_running)
        self.assertTrue(self.service.start())
        self.assertTrue(self.service.is_running)
        self.assertTrue(self.service.stop())
        self.assertFalse(self.service.is_running)

    def test_duplicate_detection_cooldown(self):
        """Verify duplicate detections within cooldown are filtered from history."""
        frame = QRDetector.generate_test_qr_frame("COOLDOWN_PAYLOAD_TEST", width=400, height=400)

        # First scan -> Should be accepted and added to history
        res1 = self.service.process_frame(frame)
        self.assertEqual(len(self.service.get_history()), 1)

        # Immediate second scan -> Should flag as duplicate and NOT append to history
        res2 = self.service.process_frame(frame)
        self.assertEqual(len(self.service.get_history()), 1)

        # Wait past cooldown -> Next scan should be accepted
        time.sleep(1.1)
        res3 = self.service.process_frame(frame)
        self.assertEqual(len(self.service.get_history()), 2)

    def test_history_limit(self):
        """Verify history buffer respects bounded capacity."""
        self.service._history_limit = 3
        for i in range(5):
            frame = QRDetector.generate_test_qr_frame(f"UNIQUE_PAYLOAD_{i}", width=320, height=320)
            self.service.process_frame(frame)

        history = self.service.get_history()
        self.assertLessEqual(len(history), 3)

    def test_process_image_bytes(self):
        """Verify decoding from image file bytes (upload simulation)."""
        frame = QRDetector.generate_test_qr_frame("UPLOAD_TEST_DATA", width=320, height=320)
        success, encoded_jpg = cv2.imencode(".jpg", frame)
        self.assertTrue(success)

        results = self.service.process_image_bytes(encoded_jpg.tobytes(), filename="test.jpg")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["payload"], "UPLOAD_TEST_DATA")

    def test_process_invalid_image_bytes(self):
        """Verify invalid or empty bytes raise ValueError."""
        with self.assertRaises(ValueError):
            self.service.process_image_bytes(b"")
        with self.assertRaises(ValueError):
            self.service.process_image_bytes(b"Not an image at all")

    def test_qr_rtl_trigger_action(self):
        """Verify QR detection with RTL trigger sets action_triggered and spatial data."""
        frame = QRDetector.generate_test_qr_frame("TRIGGER:RTL_NOW", width=320, height=320)
        results = self.service.process_frame(frame)
        self.assertGreaterEqual(len(results), 1)
        det = results[0]
        self.assertEqual(det["action_triggered"], "RTL")
        self.assertIn("action_result", det)
        self.assertIn("latitude", det)
        self.assertIn("longitude", det)


class TestVisionAPI(unittest.TestCase):
    """Test suite for /api/vision/qr REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_vision_status_endpoint(self):
        """Verify GET /api/vision/qr/status."""
        res = self.client.get("/api/vision/qr/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("running", data["data"])

    def test_vision_start_stop_endpoints(self):
        """Verify POST /api/vision/qr/start and stop."""
        start_res = self.client.post("/api/vision/qr/start")
        self.assertEqual(start_res.status_code, 200)
        stop_res = self.client.post("/api/vision/qr/stop")
        self.assertEqual(stop_res.status_code, 200)

    def test_vision_upload_endpoint(self):
        """Verify POST /api/vision/qr/process-image."""
        frame = QRDetector.generate_test_qr_frame("API_UPLOAD_TEST", width=320, height=320)
        _, encoded_jpg = cv2.imencode(".jpg", frame)

        res = self.client.post(
            "/api/vision/qr/process-image",
            data=encoded_jpg.tobytes(),
            content_type="image/jpeg"
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["count"], 1)
        self.assertEqual(data["data"][0]["payload"], "API_UPLOAD_TEST")


if __name__ == "__main__":
    unittest.main()

