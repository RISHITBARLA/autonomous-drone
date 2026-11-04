"""
Integration tests for Flask REST APIs.
Tests health routes, hardware routes, camera status, capture endpoints, and image serving.
"""
import unittest
from backend.app import create_app


class TestAPIEndpoints(unittest.TestCase):
    """Test suite for companion computer REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_frontend_index_route(self):
        """Verify root route returns 200 and dashboard HTML."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AUTONOMOUS-DRONE", response.data)

    def test_api_health_endpoint(self):
        """Verify GET /api/health returns comprehensive telemetry."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("cpu", data["data"])
        self.assertIn("memory", data["data"])
        self.assertIn("disk", data["data"])
        self.assertIn("temperature", data["data"])
        self.assertIn("uptime", data["data"])

    def test_api_health_summary_endpoint(self):
        """Verify GET /api/health/summary returns fast telemetry fields."""
        response = self.client.get("/api/health/summary")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("overall_status", data["data"])
        self.assertIn("cpu_percent", data["data"])
        self.assertIn("ram_percent", data["data"])

    def test_api_temperature_endpoint(self):
        """Verify GET /api/health/temperature returns thermal readings."""
        response = self.client.get("/api/health/temperature")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("celsius", data["data"])
        self.assertIn("status", data["data"])

    def test_api_hardware_endpoint(self):
        """Verify GET /api/health/hardware returns platform information."""
        response = self.client.get("/api/health/hardware")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("device", data["data"])
        self.assertIn("cpu", data["data"])
        self.assertIn("os", data["data"])

    def test_api_camera_status_endpoint(self):
        """Verify GET /api/camera/status returns backend connection data."""
        response = self.client.get("/api/camera/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("connected", data["data"])
        self.assertIn("active_backend", data["data"])

    def test_api_camera_capture_and_retrieve_flow(self):
        """Verify POST /api/camera/capture saves image and GET /api/camera/latest retrieves it."""
        # Step 1: Capture
        post_res = self.client.post("/api/camera/capture")
        self.assertEqual(post_res.status_code, 201)
        post_data = post_res.get_json()
        self.assertEqual(post_data["status"], "success")
        filename = post_data["data"]["filename"]
        self.assertTrue(filename.startswith("capture_"))

        # Step 2: Latest
        get_latest = self.client.get("/api/camera/latest")
        self.assertEqual(get_latest.status_code, 200)
        latest_data = get_latest.get_json()
        self.assertEqual(latest_data["data"]["filename"], filename)

        # Step 3: Serve image file
        img_res = self.client.get(f"/api/camera/image/{filename}")
        self.assertEqual(img_res.status_code, 200)
        self.assertEqual(img_res.mimetype, "image/jpeg")

    def test_camera_list_endpoint(self):
        """Verify GET /api/camera/list returns captured images list."""
        response = self.client.get("/api/camera/list?limit=5")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("count", data)
        self.assertIn("data", data)
        self.assertIsInstance(data["data"], list)

    def test_camera_config_update_api(self):
        """Verify POST /api/camera/config updates runtime settings."""
        response = self.client.post("/api/camera/config", json={"width": 1280, "height": 720, "framerate": 20})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["width"], 1280)
        self.assertEqual(data["data"]["height"], 720)

    def test_camera_image_not_found(self):
        """Verify non-existent image returns 404."""
        response = self.client.get("/api/camera/image/non_existent_file.jpg")
        self.assertEqual(response.status_code, 404)

    def test_404_error_handler(self):
        """Verify non-existent API routes return 404 JSON response."""
        response = self.client.get("/api/nonexistent/route")
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data["status"], "error")


if __name__ == "__main__":
    unittest.main()
