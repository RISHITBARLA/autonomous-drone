"""
Unit tests for CameraManager, CameraConfig, and CameraDetector.
Verifies frame acquisition, capture persistence, metadata extraction, and mock fallback.
"""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.camera.camera_config import CameraConfig
from backend.camera.camera_manager import CameraManager
from backend.camera.camera_detector import CameraDetector


class TestCameraManager(unittest.TestCase):
    """Test suite for camera subsystem."""

    def setUp(self):
        self.config = CameraConfig(
            width=640,
            height=480,
            preview_width=320,
            preview_height=240,
            backend="mock"
        )
        self.camera = CameraManager(config=self.config)

    def tearDown(self):
        self.camera.release()

    def test_camera_initialization(self):
        """Verify camera initializes in mock mode successfully."""
        status = self.camera.get_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["active_backend"], "mock")
        self.assertTrue(status["is_mock"])

    def test_frame_generation(self):
        """Verify get_frame generates numpy frame with matching resolution."""
        frame = self.camera.get_frame(preview=False)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[0], 480)
        self.assertEqual(frame.shape[1], 640)
        self.assertEqual(frame.shape[2], 3)

    def test_preview_frame_generation(self):
        """Verify preview frame has lower resolution for streaming."""
        frame = self.camera.get_frame(preview=True)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[0], 240)
        self.assertEqual(frame.shape[1], 320)

    def test_jpeg_frame_bytes(self):
        """Verify JPEG encoding returns non-empty byte buffer."""
        jpeg_bytes = self.camera.get_jpeg_frame(preview=True)
        self.assertIsInstance(jpeg_bytes, bytes)
        self.assertGreater(len(jpeg_bytes), 100)
        # JPEG Magic number check: FF D8
        self.assertEqual(jpeg_bytes[:2], b"\xff\xd8")

    def test_capture_image_persists_file(self):
        """Verify capture_image writes JPEG file to disk with proper metadata."""
        metadata = self.camera.capture_image()
        self.assertIn("filename", metadata)
        self.assertIn("filepath", metadata)
        self.assertIn("size_bytes", metadata)
        self.assertIn("relative_url", metadata)
        self.assertEqual(metadata["width"], 640)
        self.assertEqual(metadata["height"], 480)

        saved_path = Path(metadata["filepath"])
        self.assertTrue(saved_path.exists())
        self.assertGreater(saved_path.stat().st_size, 0)

        # Verify get_latest_capture matches
        latest = self.camera.get_latest_capture()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["filename"], metadata["filename"])

    def test_config_update(self):
        """Verify dynamic camera config updates."""
        self.camera.config.update({"width": 1280, "height": 720, "framerate": 25})
        self.assertEqual(self.camera.config.width, 1280)
        self.assertEqual(self.camera.config.height, 720)
        self.assertEqual(self.camera.config.framerate, 25)

    def test_rotation_handling(self):
        """Verify rotation alters frame orientation dimensions."""
        self.camera.config.update({"rotation": 90})
        frame_90 = self.camera.get_frame(preview=False)
        # 640x480 rotated 90 deg becomes height 640, width 480
        self.assertEqual(frame_90.shape[0], 640)
        self.assertEqual(frame_90.shape[1], 480)

        self.camera.config.update({"rotation": 180})
        frame_180 = self.camera.get_frame(preview=False)
        self.assertEqual(frame_180.shape[0], 480)
        self.assertEqual(frame_180.shape[1], 640)

    def test_concurrent_capture_prevention(self):
        """Verify second capture attempt while lock held raises RuntimeError."""
        self.camera._capture_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                self.camera.capture_image()
        finally:
            self.camera._capture_lock.release()

    def test_record_error_and_status(self):
        """Verify error recording and status reporting."""
        initial_error_count = len(self.camera._error_log)
        self.camera.record_error("Test mock error condition")
        status = self.camera.get_status()
        self.assertEqual(status["error_count"], initial_error_count + 1)
        self.assertIn("Test mock error condition", status["recent_errors"][-1]["error"])

    @patch("platform.system", return_value="Linux")
    @patch("backend.camera.camera_detector.CameraDetector.check_libcamera_available", return_value=True)
    @patch("backend.camera.camera_detector.CameraDetector.list_libcamera_devices", return_value=[{
        "raw_info": "0 : imx477 [4056x3040]",
        "is_imx477": True,
        "sensor": "Sony IMX477 (HQ Camera)",
        "source": "rpicam-hello"
    }])
    def test_detector_detects_imx477(self, mock_list, mock_check, mock_sys):
        """Verify CameraDetector correctly identifies Sony IMX477 and recommends libcamera."""
        res = CameraDetector.detect_camera_hardware()
        self.assertTrue(res["connected"])
        self.assertTrue(res["is_imx477"])
        self.assertEqual(res["recommended_backend"], "libcamera")
        self.assertEqual(res["camera_model"], "Sony IMX477 High Quality Camera")

    @patch("platform.system", return_value="Linux")
    @patch("backend.camera.camera_detector.CameraDetector.check_libcamera_available", return_value=False)
    @patch("backend.camera.camera_detector.CameraDetector.list_libcamera_devices", return_value=[])
    @patch("backend.camera.camera_detector.CameraDetector.list_v4l2_devices", return_value=["/dev/video0"])
    def test_detector_v4l2_fallback(self, mock_v4l2, mock_list, mock_check, mock_sys):
        """Verify CameraDetector falls back to opencv for V4L2 device."""
        res = CameraDetector.detect_camera_hardware()
        self.assertTrue(res["connected"])
        self.assertFalse(res["is_imx477"])
        self.assertEqual(res["recommended_backend"], "opencv")


if __name__ == "__main__":
    unittest.main()
