"""
Unit and Integration tests for Flight Controller Subsystem (Milestone 07).
Verifies default disabled safety lock, explicit command interfaces,
parameter validation, and REST API error routing.
"""
import unittest
from backend.flight.flight_controller import FlightController
from backend.flight.mavlink_service import mavlink_service
from backend.app import create_app


class TestFlightController(unittest.TestCase):
    """Test suite for FlightController explicit command engine."""

    def setUp(self):
        # Default: disabled for safety
        self.fc_disabled = FlightController(enabled=False)
        self.fc_enabled = FlightController(enabled=True)

        # Start simulated telemetry so vehicle is considered connected
        mavlink_service.simulate = True
        mavlink_service.start()

    def tearDown(self):
        mavlink_service.stop()

    def test_disabled_by_default_blocks_all_commands(self):
        """Verify that when disabled, arm, mode, and takeoff commands are blocked."""
        arm_res = self.fc_disabled.request_arm(True)
        self.assertFalse(arm_res["success"])
        self.assertEqual(arm_res["code"], "CONTROL_DISABLED")

        mode_res = self.fc_disabled.request_mode("GUIDED")
        self.assertFalse(mode_res["success"])
        self.assertEqual(mode_res["code"], "CONTROL_DISABLED")

        takeoff_res = self.fc_disabled.request_takeoff(10.0)
        self.assertFalse(takeoff_res["success"])
        self.assertEqual(takeoff_res["code"], "CONTROL_DISABLED")

    def test_enabled_arm_and_disarm(self):
        """Verify arm and disarm execute properly when enabled."""
        arm_res = self.fc_enabled.request_arm(True)
        self.assertTrue(arm_res["success"])

        snap = mavlink_service.get_snapshot()
        self.assertTrue(snap.armed)

        disarm_res = self.fc_enabled.request_arm(False)
        self.assertTrue(disarm_res["success"])

        snap = mavlink_service.get_snapshot()
        self.assertFalse(snap.armed)

    def test_enabled_mode_switch(self):
        """Verify mode transition to supported modes."""
        res = self.fc_enabled.request_mode("GUIDED")
        self.assertTrue(res["success"])
        self.assertEqual(res["flight_mode"], "GUIDED")

        # Invalid mode
        bad_mode = self.fc_enabled.request_mode("SUPERSONIC_INVALID")
        self.assertFalse(bad_mode["success"])
        self.assertEqual(bad_mode["code"], "INVALID_MODE")

    def test_enabled_takeoff(self):
        """Verify takeoff validates altitude and sets guided mode."""
        res = self.fc_enabled.request_takeoff(12.5)
        self.assertTrue(res["success"])

        snap = mavlink_service.get_snapshot()
        self.assertEqual(snap.flight_mode, "GUIDED")
        self.assertAlmostEqual(snap.altitude_relative_m, 12.5, delta=0.1)

        # Out of bounds altitudes
        too_low = self.fc_enabled.request_takeoff(0.2)
        self.assertFalse(too_low["success"])
        self.assertEqual(too_low["code"], "INVALID_ALTITUDE")

        too_high = self.fc_enabled.request_takeoff(500.0)
        self.assertFalse(too_high["success"])
        self.assertEqual(too_high["code"], "INVALID_ALTITUDE")

    def test_command_audit_log(self):
        """Verify commands are logged to command history."""
        self.fc_enabled.request_mode("RTL")
        log = self.fc_enabled.get_command_log()
        self.assertGreaterEqual(len(log), 1)
        self.assertEqual(log[0]["command"], "SET_MODE")
        self.assertEqual(log[0]["params"]["mode"], "RTL")


class TestFlightAPI(unittest.TestCase):
    """Test suite for /api/flight REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_get_flight_status(self):
        """Verify GET /api/flight/status."""
        res = self.client.get("/api/flight/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("flight_control_enabled", data["data"])

    def test_commands_return_403_when_disabled(self):
        """Verify POST endpoints return 403 Forbidden while flight control is disabled."""
        from backend.flight.flight_controller import flight_controller
        original_state = flight_controller.enabled
        flight_controller.enabled = False

        try:
            arm_res = self.client.post("/api/flight/arm")
            self.assertEqual(arm_res.status_code, 403)

            mode_res = self.client.post("/api/flight/mode", json={"mode": "GUIDED"})
            self.assertEqual(mode_res.status_code, 403)

            takeoff_res = self.client.post("/api/flight/takeoff", json={"altitude_m": 10.0})
            self.assertEqual(takeoff_res.status_code, 403)
        finally:
            flight_controller.enabled = original_state


if __name__ == "__main__":
    unittest.main()

