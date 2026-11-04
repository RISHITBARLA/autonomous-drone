"""
Unit and Integration tests for Pixhawk MAVLink Telemetry Subsystem (Milestone 03).
Verifies read-only telemetry snapshots, stale heartbeat detection, simulated navigation,
reconnect lifecycle, and REST API telemetry routes.
"""
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.flight.mavlink_service import MAVLinkService, TelemetrySnapshot
from backend.app import create_app


class TestMAVLinkTelemetry(unittest.TestCase):
    """Test suite for MAVLinkService telemetry engine."""

    def setUp(self):
        self.service = MAVLinkService(
            connection_string="simulated",
            heartbeat_timeout=1.0,
            simulate=True
        )

    def tearDown(self):
        self.service.stop()

    def test_simulated_telemetry_snapshot(self):
        """Verify simulated telemetry yields valid GPS, battery, and attitude metrics."""
        self.service.start()
        time.sleep(0.2)  # Allow worker loop to execute a step

        snap = self.service.get_snapshot()
        self.assertTrue(snap.connected)
        self.assertTrue(snap.is_simulated)
        self.assertFalse(snap.is_stale)
        self.assertEqual(snap.flight_mode, "LOITER")
        self.assertTrue(snap.armed)

        # GPS values
        self.assertAlmostEqual(snap.latitude, 37.4093, delta=0.01)
        self.assertAlmostEqual(snap.longitude, -122.0641, delta=0.01)
        self.assertGreater(snap.altitude_relative_m, 10.0)
        self.assertEqual(snap.gps_fix_type, 3)
        self.assertGreater(snap.satellites_visible, 5)

        # Power & Dynamics
        self.assertGreater(snap.battery_voltage_v, 13.0)
        self.assertGreater(snap.battery_remaining_percent, 0)
        self.assertGreaterEqual(snap.heading_deg, 0.0)
        self.assertLessEqual(snap.heading_deg, 360.0)

    def test_stale_heartbeat_detection(self):
        """Verify heartbeat age exceeding timeout marks telemetry as stale and disconnected."""
        snap = self.service.get_snapshot()
        # Fresh initialization with no heartbeats
        self.assertTrue(snap.is_stale)
        self.assertFalse(snap.connected)
        self.assertEqual(snap.flight_mode, "DISCONNECTED")

        # Simulate a heartbeat 2 seconds ago with a 1.0s timeout
        with self.service._lock:
            self.service._connected = True
            self.service._last_heartbeat = time.time() - 2.5

        stale_snap = self.service.get_snapshot()
        self.assertTrue(stale_snap.is_stale)
        self.assertFalse(stale_snap.connected)

    def test_lifecycle_and_shutdown(self):
        """Verify start, stop, and clean resource release."""
        self.assertFalse(self.service.is_running)
        self.service.start()
        self.assertTrue(self.service.is_running)
        self.service.stop()
        self.assertFalse(self.service.is_running)

    def test_dynamic_reconnection_config(self):
        """Verify set_connection reconfigures settings and restarts worker."""
        self.service.start()
        self.service.set_connection(connection_string="udpin:127.0.0.1:14550", baudrate=115200, simulate=True)
        self.assertEqual(self.service.connection_string, "udpin:127.0.0.1:14550")
        self.assertEqual(self.service.baudrate, 115200)
        self.assertTrue(self.service.is_running)


class TestTelemetryAPI(unittest.TestCase):
    """Test suite for /api/telemetry REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_get_telemetry_status(self):
        """Verify GET /api/telemetry/status."""
        res = self.client.get("/api/telemetry/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("connected", data["data"])
        self.assertIn("flight_mode", data["data"])

    def test_get_telemetry_current(self):
        """Verify GET /api/telemetry/current."""
        res = self.client.get("/api/telemetry/current")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("latitude", data["data"])
        self.assertIn("battery_voltage_v", data["data"])

    def test_get_telemetry_gps(self):
        """Verify GET /api/telemetry/gps."""
        res = self.client.get("/api/telemetry/gps")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("fix_type", data["data"])
        self.assertIn("satellites", data["data"])

    def test_get_telemetry_battery(self):
        """Verify GET /api/telemetry/battery."""
        res = self.client.get("/api/telemetry/battery")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("voltage_v", data["data"])
        self.assertIn("remaining_percent", data["data"])

    def test_get_telemetry_attitude(self):
        """Verify GET /api/telemetry/attitude."""
        res = self.client.get("/api/telemetry/attitude")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("roll_deg", data["data"])
        self.assertIn("pitch_deg", data["data"])
        self.assertIn("yaw_deg", data["data"])

    def test_post_configure_connection(self):
        """Verify POST /api/telemetry/connection."""
        res = self.client.post("/api/telemetry/connection", json={
            "connection_string": "udpin:0.0.0.0:14550",
            "baudrate": 57600,
            "simulate": True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["baudrate"], 57600)


if __name__ == "__main__":
    unittest.main()

