"""
Adversarial Stress Test Harness 2: FlightController Command Rejection
Challenger 2 (Milestone M1)
Verifies that when FLIGHT_CONTROL_ENABLED is False, NO permutation of HTTP requests
or internal method calls can arm, spin motors, or execute flight commands.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.flight.flight_controller import FlightController, flight_controller, SUPPORTED_FLIGHT_MODES
from backend.flight.mavlink_service import mavlink_service
from backend.app import create_app


class StressTestFlightControllerRejection(unittest.TestCase):
    """Adversarial stress testing against flight command rejection when disabled."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Ensure disabled flight controller
        self.fc = FlightController(enabled=False)
        flight_controller.enabled = False

        # Reset mavlink_service state
        mavlink_service.simulate = True
        mavlink_service._armed = False
        mavlink_service._connected = True
        mavlink_service._flight_mode = "DISCONNECTED"

    def tearDown(self):
        flight_controller.enabled = False
        mavlink_service.stop()

    # --- 1. Exhaustive Internal Method Calls ---
    def test_direct_request_arm_all_permutations(self):
        """Test all permutations of request_arm with enabled=False."""
        permutations = [
            {"arm": True, "confirm": True, "operator": None},
            {"arm": True, "confirm": False, "operator": None},
            {"arm": False, "confirm": True, "operator": None},
            {"arm": False, "confirm": False, "operator": None},
            {"arm": True, "confirm": True, "operator": "adversary"},
            {"arm": True, "confirm": True, "operator": ""},
            {"arm": True, "confirm": True, "operator": "root"},
        ]

        with patch.object(mavlink_service, "send_command_long") as mock_send:
            for p in permutations:
                res = self.fc.request_arm(**p)
                self.assertFalse(res["success"], f"Failed to reject request_arm with {p}")
                self.assertEqual(res["code"], "CONTROL_DISABLED")
                self.assertFalse(mavlink_service._armed, f"Armed state changed with {p}!")
                mock_send.assert_not_called()

    def test_direct_request_mode_all_supported_and_unsupported(self):
        """Test request_mode with every supported mode and invalid modes."""
        modes_to_test = list(SUPPORTED_FLIGHT_MODES) + [
            "GUIDED", "ACRO", "AUTOTUNE", "; rm -rf /", "", "   ", "UNKNOWN"
        ]

        with patch.object(mavlink_service, "send_set_mode") as mock_set_mode:
            for mode in modes_to_test:
                res = self.fc.request_mode(mode)
                self.assertFalse(res["success"], f"Failed to reject request_mode for {mode}")
                self.assertEqual(res["code"], "CONTROL_DISABLED")
                self.assertNotEqual(mavlink_service._flight_mode, mode)
                mock_set_mode.assert_not_called()

    def test_direct_request_takeoff_all_altitudes(self):
        """Test request_takeoff with various altitude ranges when disabled."""
        altitudes = [-100.0, -1.0, 0.0, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 100.1, 1000.0]

        with patch.object(mavlink_service, "send_command_long") as mock_send:
            for alt in altitudes:
                res = self.fc.request_takeoff(alt)
                self.assertFalse(res["success"], f"Failed to reject takeoff for alt {alt}")
                self.assertEqual(res["code"], "CONTROL_DISABLED")
                self.assertFalse(mavlink_service._armed)
                mock_send.assert_not_called()

    def test_direct_request_rtl_and_land(self):
        """Test request_rtl and request_land when disabled."""
        with patch.object(mavlink_service, "send_set_mode") as mock_set_mode:
            rtl_res = self.fc.request_rtl()
            self.assertFalse(rtl_res["success"])
            self.assertEqual(rtl_res["code"], "CONTROL_DISABLED")

            land_res = self.fc.request_land()
            self.assertFalse(land_res["success"])
            self.assertEqual(land_res["code"], "CONTROL_DISABLED")

            mock_set_mode.assert_not_called()

    # --- 2. HTTP REST API Endpoints with enabled=False ---
    def test_http_arm_endpoint_permutations_return_403(self):
        payloads = [
            {"confirm": True},
            {"confirm": False},
            {},
            {"confirm": True, "operator": "attacker"},
            {"confirm": "true"},
            {"arm": True, "confirm": True},
        ]
        with patch.object(mavlink_service, "send_command_long") as mock_send:
            for payload in payloads:
                resp = self.client.post("/api/flight/arm", json=payload)
                self.assertEqual(resp.status_code, 403, f"Expected 403 for /api/flight/arm with {payload}, got {resp.status_code}")
                data = resp.get_json()
                self.assertEqual(data.get("code"), "CONTROL_DISABLED")
                self.assertFalse(mavlink_service._armed)
                mock_send.assert_not_called()

    def test_http_disarm_endpoint_permutations_return_403(self):
        payloads = [{"confirm": True}, {"confirm": False}, {}]
        for payload in payloads:
            resp = self.client.post("/api/flight/disarm", json=payload)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for /api/flight/disarm with {payload}")
            data = resp.get_json()
            self.assertEqual(data.get("code"), "CONTROL_DISABLED")

    def test_http_mode_endpoint_permutations_return_403(self):
        for mode in ("ALT_HOLD", "GUIDED", "LOITER", "RTL", "LAND", "AUTO"):
            resp = self.client.post("/api/flight/mode", json={"mode": mode})
            self.assertEqual(resp.status_code, 403, f"Expected 403 for mode {mode}")
            data = resp.get_json()
            self.assertEqual(data.get("code"), "CONTROL_DISABLED")

    def test_http_takeoff_endpoint_permutations_return_403(self):
        for alt in (1.0, 5.0, 10.0, 50.0):
            resp = self.client.post("/api/flight/takeoff", json={"altitude_m": alt})
            self.assertEqual(resp.status_code, 403, f"Expected 403 for takeoff {alt}")
            data = resp.get_json()
            self.assertEqual(data.get("code"), "CONTROL_DISABLED")

    def test_http_rtl_and_land_endpoints_return_403(self):
        resp_rtl = self.client.post("/api/flight/rtl")
        self.assertEqual(resp_rtl.status_code, 403)
        self.assertEqual(resp_rtl.get_json().get("code"), "CONTROL_DISABLED")

        resp_land = self.client.post("/api/flight/land")
        self.assertEqual(resp_land.status_code, 403)
        self.assertEqual(resp_land.get_json().get("code"), "CONTROL_DISABLED")

    # --- 3. Hardware mode (simulate=False) rejection ---
    def test_hardware_mode_rejection(self):
        """Verify that when simulate=False, disabled flight control still blocks everything."""
        mavlink_service.simulate = False
        with patch.object(mavlink_service, "send_command_long") as mock_send:
            res = self.fc.request_arm(arm=True, confirm=True)
            self.assertFalse(res["success"])
            self.assertEqual(res["code"], "CONTROL_DISABLED")
            mock_send.assert_not_called()

            resp = self.client.post("/api/flight/arm", json={"confirm": True})
            self.assertEqual(resp.status_code, 403)
            mock_send.assert_not_called()

    # --- 4. Investigation of bench testing /disable-arming-checks endpoint ---
    def test_disable_arming_checks_endpoint_behavior(self):
        """Observe whether /api/flight/disable-arming-checks interacts with armed state."""
        with patch.object(mavlink_service, "set_param") as mock_set_param:
            resp = self.client.post("/api/flight/disable-arming-checks")
            # Endpoint returns 200 and calls set_param
            self.assertEqual(resp.status_code, 200)
            # Crucially: vehicle MUST NOT be armed
            self.assertFalse(mavlink_service._armed)
            snap = mavlink_service.get_snapshot()
            self.assertFalse(snap.armed)
            print(f"[BENCH-ENDPOINT OBSERVED] /disable-arming-checks called set_param count: {mock_set_param.call_count}, armed remains: {snap.armed}")


if __name__ == "__main__":
    unittest.main()

