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

    # -------------------------------------------------------------
    # Milestone M2: Frontend Cache-Busting Verification Tests
    # -------------------------------------------------------------
    def test_cache_control_headers_root_route(self):
        """Verify GET / returns strict no-cache headers for HTML shell."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_cache_control_headers_index_html(self):
        """Verify GET /index.html returns strict no-cache headers."""
        response = self.client.get("/index.html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_cache_control_headers_static_assets(self):
        """Verify /css/* and /js/* assets return no-cache, must-revalidate."""
        res_css = self.client.get("/css/dashboard.css")
        self.assertEqual(res_css.status_code, 200)
        self.assertEqual(
            res_css.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

        res_js = self.client.get("/js/dashboard.js")
        self.assertEqual(res_js.status_code, 200)
        self.assertEqual(
            res_js.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

    def test_cache_control_headers_with_version_query_params(self):
        """Verify version query string requests preserve revalidate cache headers."""
        res_css = self.client.get("/css/dashboard.css?v=20261105.1")
        self.assertEqual(res_css.status_code, 200)
        self.assertEqual(
            res_css.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

        res_js = self.client.get("/js/dashboard.js?v=20261105.1")
        self.assertEqual(res_js.status_code, 200)
        self.assertEqual(
            res_js.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

    def test_index_html_contains_cache_busting_version_tags(self):
        """Verify frontend/index.html includes ?v=20261105.1 in CSS and JS tags."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/css/dashboard.css?v=20261105.1", response.data)
        self.assertIn(b"/js/dashboard.js?v=20261105.1", response.data)

    def test_api_routes_unaffected_by_static_cache_headers(self):
        """Verify API endpoints do not receive frontend static cache-control headers."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )

    # -------------------------------------------------------------
    # Milestone M2: Geofence Coverage API Endpoint Tests
    # -------------------------------------------------------------
    def test_get_geofence_coverage_endpoint_schema_and_calculations(self):
        """Verify GET /api/geofence/coverage returns valid status, schema, and metrics."""
        response = self.client.get("/api/geofence/coverage")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")

        data = payload.get("data", payload)
        self.assertIn("boundary_type", data)
        self.assertIn("total_area_m2", data)
        self.assertIn("scanned_area_m2", data)
        self.assertIn("coverage_pct", data)
        self.assertIn("scanned_cells_count", data)
        self.assertIn("total_cells_count", data)
        self.assertIn("grid_resolution_m", data)
        self.assertIn("scanned_points", data)

        self.assertGreater(data["total_area_m2"], 0.0)
        self.assertGreaterEqual(data["scanned_area_m2"], 0.0)
        self.assertGreaterEqual(data["coverage_pct"], 0.0)
        self.assertLessEqual(data["coverage_pct"], 100.0)
        self.assertGreater(data["total_cells_count"], 0)
        self.assertGreaterEqual(data["scanned_cells_count"], 0)
        self.assertIsInstance(data["scanned_points"], list)

        grid_res = data["grid_resolution_m"]
        expected_scanned_area = round(data["scanned_cells_count"] * (grid_res ** 2), 1)
        self.assertAlmostEqual(data["scanned_area_m2"], expected_scanned_area, delta=0.5)

        expected_pct = round((data["scanned_cells_count"] / data["total_cells_count"]) * 100.0, 2)
        self.assertAlmostEqual(data["coverage_pct"], expected_pct, places=2)

    def test_post_geofence_coverage_reset_flow(self):
        """Verify POST /api/geofence/coverage/reset resets scanned cells to zero."""
        reset_res = self.client.post("/api/geofence/coverage/reset")
        self.assertEqual(reset_res.status_code, 200)
        reset_data = reset_res.get_json()
        self.assertEqual(reset_data["status"], "success")

        cov_res = self.client.get("/api/geofence/coverage")
        self.assertEqual(cov_res.status_code, 200)
        cov_data = cov_res.get_json()
        data = cov_data.get("data", cov_data)

        self.assertEqual(data["scanned_cells_count"], 0)
        self.assertEqual(data["scanned_area_m2"], 0.0)
        self.assertEqual(data["coverage_pct"], 0.0)
        self.assertEqual(len(data["scanned_points"]), 0)


if __name__ == "__main__":
    unittest.main()

