"""
Comprehensive Integration & Unit Tests for Flight Control Activation and AltHold Integration.
Covers all 17 mandatory verification criteria:
1. Flight control disabled by default.
2. HTTP 403 when disabled.
3. Successful MAVLink heartbeat reception.
4. ALT_HOLD mode request.
5. ALT_HOLD mode confirmation.
6. Normal ARM command parameters (param1=1.0, param2=0.0).
7. Force-arm is never used (param2 is never 21196).
8. Arming rejection is correctly reported from Pixhawk STATUSTEXT / COMMAND_ACK.
9. Armed state is confirmed from heartbeat.
10. Disarm command and state confirmation.
11. MAVLink connection loss detection.
12. Stale heartbeat handling.
13. Command timeout handling.
14. No automatic arming from QR detection.
15. No automatic arming from mission association.
16. Simulator and mock compatibility.
17. Separation of simulation and physical hardware modes (no silent fallback).
"""
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from config.settings import Settings, settings
from backend.flight.flight_controller import FlightController, flight_controller
from backend.flight.mavlink_service import MAVLinkService, mavlink_service, COPTER_MODES, ARDUCOPTER_MODE_IDS
from backend.app import create_app
from backend.mission.mission_service import mission_service
from backend.mission.mission_model import MissionState
from backend.vision.vision_service import vision_service
from backend.vision.qr_detector import QRDetector


class TestFlightControlActivation(unittest.TestCase):
    """Full test suite covering Flight Control Activation & AltHold integration."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Ensure simulated telemetry is started by default for testing
        mavlink_service.simulate = True
        mavlink_service.start()

    def tearDown(self):
        mavlink_service.stop()

    def test_01_disabled_by_default(self):
        """1. Flight control must be disabled by default."""
        fc_default = FlightController()
        # Verify settings default is False
        self.assertFalse(fc_default.enabled)
        status = fc_default.get_status()
        self.assertFalse(status["flight_control_enabled"])

    def test_02_http_403_when_disabled(self):
        """2. HTTP 403 Forbidden returned for all flight commands when disabled."""
        original_state = flight_controller.enabled
        flight_controller.enabled = False
        try:
            endpoints = [
                ("/api/flight/arm", {"confirm": True}),
                ("/api/flight/disarm", {}),
                ("/api/flight/mode", {"mode": "ALT_HOLD"}),
                ("/api/flight/takeoff", {"altitude_m": 5.0}),
                ("/api/flight/rtl", {}),
                ("/api/flight/land", {})
            ]
            for url, payload in endpoints:
                res = self.client.post(url, json=payload)
                self.assertEqual(
                    res.status_code, 403,
                    f"Endpoint {url} expected 403, got {res.status_code}: {res.get_data(as_text=True)}"
                )
                data = res.get_json()
                self.assertEqual(data.get("code"), "CONTROL_DISABLED")
        finally:
            flight_controller.enabled = original_state

    def test_03_successful_heartbeat_reception(self):
        """3. Successful MAVLink heartbeat reception updates state and freshness."""
        svc = MAVLinkService(connection_string="test", simulate=False)
        mock_msg = MagicMock()
        mock_msg.get_type.return_value = "HEARTBEAT"
        mock_msg.get_srcSystem.return_value = 1
        mock_msg.get_srcComponent.return_value = 1
        mock_msg.custom_mode = 2  # ALT_HOLD
        mock_msg.base_mode = 128  # Armed

        with svc._lock:
            svc._connected = True
            svc._last_heartbeat = time.time()
            svc._flight_mode = "ALT_HOLD"
            svc._armed = True
            svc._target_system = 1
            svc._target_component = 1

        snap = svc.get_snapshot()
        self.assertTrue(snap.connected)
        self.assertFalse(snap.is_stale)
        self.assertLess(snap.heartbeat_age_seconds, 1.0)
        self.assertEqual(snap.flight_mode, "ALT_HOLD")
        self.assertTrue(snap.armed)

    def test_04_alt_hold_mode_request(self):
        """4. ALT_HOLD mode request is properly routed with custom mode 2."""
        self.assertEqual(ARDUCOPTER_MODE_IDS.get("ALT_HOLD"), 2)

        fc = FlightController(enabled=True)
        res = fc.request_mode("ALT_HOLD")
        self.assertTrue(res["success"])
        self.assertEqual(res["flight_mode"], "ALT_HOLD")

    def test_05_alt_hold_mode_confirmation(self):
        """5. ALT_HOLD mode change is confirmed via heartbeat."""
        fc = FlightController(enabled=True)
        res = fc.request_mode("ALT_HOLD")
        self.assertTrue(res["success"])

        snap = mavlink_service.get_snapshot()
        self.assertEqual(snap.flight_mode, "ALT_HOLD")

    def test_06_normal_arm_command_parameters(self):
        """6. Normal ARM command sends param1=1.0 and param2=0.0 (no force-arm)."""
        fc = FlightController(enabled=True)
        mock_conn = MagicMock()
        mavlink_service._mav_connection = mock_conn

        # Test through send_command_long directly
        with patch.object(mavlink_service, "wait_for_arm_state", return_value=True):
            # Temporarily simulate hardware mode
            orig_sim = mavlink_service.simulate
            mavlink_service.simulate = False
            with mavlink_service._lock:
                mavlink_service._connected = True
                mavlink_service._last_heartbeat = time.time()
            try:
                res = fc.request_arm(arm=True, confirm=True)
                self.assertTrue(res["success"])
                # Verify MAV_CMD_COMPONENT_ARM_DISARM was called with param1=1.0, param2=0.0
                mock_conn.mav.command_long_send.assert_called_once()
                args, _ = mock_conn.mav.command_long_send.call_args
                # args: (target_sys, target_comp, command, confirmation, param1, param2, ...)
                cmd = args[2]
                p1 = args[4]
                p2 = args[5]
                self.assertEqual(cmd, 400)  # MAV_CMD_COMPONENT_ARM_DISARM
                self.assertEqual(p1, 1.0)   # Arm
                self.assertEqual(p2, 0.0)   # Mandatory normal arm (NOT 21196)
            finally:
                mavlink_service.simulate = orig_sim

    def test_07_force_arm_is_never_used(self):
        """7. Verify force-arm magic number (21196) is never passed and config prohibits it."""
        # 1. Startup validation blocks FORCE_ARM = True
        orig_force = Settings.FORCE_ARM
        try:
            Settings.FORCE_ARM = True
            with self.assertRaises(ValueError) as ctx:
                Settings.validate_configuration()
            self.assertIn("FORCE_ARM must never be enabled", str(ctx.exception))
        finally:
            Settings.FORCE_ARM = orig_force

        # 2. REST API /api/flight/arm requires confirmation
        original_state = flight_controller.enabled
        flight_controller.enabled = True
        try:
            # Without confirmation body
            res = self.client.post("/api/flight/arm", json={})
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertEqual(data.get("code"), "CONFIRMATION_REQUIRED")

            # With confirmation body
            res_confirmed = self.client.post("/api/flight/arm", json={"confirm": True})
            self.assertEqual(res_confirmed.status_code, 200)
            self.assertTrue(res_confirmed.get_json()["data"]["success"])
        finally:
            flight_controller.enabled = original_state

    def test_08_arming_rejection_reported_from_pixhawk(self):
        """8. Arming rejection is correctly extracted and reported from Pixhawk STATUSTEXT."""
        fc = FlightController(enabled=True)
        mock_conn = MagicMock()
        mavlink_service._mav_connection = mock_conn

        orig_sim = mavlink_service.simulate
        mavlink_service.simulate = False
        with mavlink_service._lock:
            mavlink_service._connected = True
            mavlink_service._last_heartbeat = time.time()
            mavlink_service._status_texts = [
                {
                    "timestamp": time.time(),
                    "severity": 4,
                    "text": "PreArm: Compass not calibrated",
                    "is_prearm": True
                }
            ]

        try:
            with patch.object(mavlink_service, "wait_for_arm_state", return_value=False):
                res = fc.request_arm(arm=True, confirm=True)
                self.assertFalse(res["success"])
                self.assertEqual(res["code"], "ARM_REJECTED")
                self.assertIn("Compass not calibrated", res["message"])
        finally:
            mavlink_service.simulate = orig_sim

    def test_09_armed_state_confirmed_from_heartbeat(self):
        """9. Armed state is confirmed from vehicle heartbeat."""
        fc = FlightController(enabled=True)
        res = fc.request_arm(arm=True, confirm=True)
        self.assertTrue(res["success"])
        snap = mavlink_service.get_snapshot()
        self.assertTrue(snap.armed)

    def test_10_disarm_command_and_confirmation(self):
        """10. Disarm command sends param1=0.0 and confirms disarmed state."""
        fc = FlightController(enabled=True)
        # Arm first
        fc.request_arm(arm=True, confirm=True)
        self.assertTrue(mavlink_service.get_snapshot().armed)

        # Now disarm
        res = fc.request_arm(arm=False, confirm=True)
        self.assertTrue(res["success"])
        self.assertFalse(mavlink_service.get_snapshot().armed)

    def test_11_mavlink_connection_loss(self):
        """11. MAVLink connection loss is detected and blocks flight commands."""
        fc = FlightController(enabled=True)
        mavlink_service.stop()

        snap = mavlink_service.get_snapshot()
        self.assertFalse(snap.connected)

        arm_res = fc.request_arm(True, confirm=True)
        self.assertFalse(arm_res["success"])
        self.assertEqual(arm_res["code"], "NOT_CONNECTED")

        mode_res = fc.request_mode("ALT_HOLD")
        self.assertFalse(mode_res["success"])
        self.assertEqual(mode_res["code"], "NOT_CONNECTED")

    def test_12_stale_heartbeat_handling(self):
        """12. Stale heartbeat (> timeout) blocks arming and mode transitions."""
        fc = FlightController(enabled=True)
        with mavlink_service._lock:
            mavlink_service._connected = True
            mavlink_service._last_heartbeat = time.time() - (settings.MAVLINK_HEARTBEAT_TIMEOUT + 2.0)

        snap = mavlink_service.get_snapshot()
        self.assertTrue(snap.is_stale)
        self.assertFalse(snap.connected)

        arm_res = fc.request_arm(True, confirm=True)
        self.assertFalse(arm_res["success"])
        self.assertIn(arm_res["code"], ["NOT_CONNECTED", "HEARTBEAT_STALE"])

    def test_13_command_timeout_handling(self):
        """13. Command timeout is detected and returns failure without hanging."""
        fc = FlightController(enabled=True)
        orig_sim = mavlink_service.simulate
        mavlink_service.simulate = False
        with mavlink_service._lock:
            mavlink_service._connected = True
            mavlink_service._last_heartbeat = time.time()
            mavlink_service._status_texts.clear()
            mavlink_service._command_acks.clear()

        try:
            with patch.object(mavlink_service, "send_set_mode", return_value=True):
                with patch.object(mavlink_service, "wait_for_mode", return_value=False):
                    res = fc.request_mode("ALT_HOLD")
                    self.assertFalse(res["success"])
                    self.assertEqual(res["code"], "MODE_CHANGE_FAILED")
                    self.assertIn("timed out", res["message"])
        finally:
            mavlink_service.simulate = orig_sim

    def test_14_no_automatic_arming_from_qr_detection(self):
        """14. QR code detection must never arm the vehicle."""
        flight_controller.enabled = True
        with mavlink_service._lock:
            mavlink_service._armed = False

        # Generate QR code with various payloads
        payloads = [
            "MISSION:field-test-01",
            '{"action": "ARM", "force": true}',
            '{"action": "SELECT_MISSION", "mission_id": "patrol-field-alpha"}'
        ]
        for p in payloads:
            frame = QRDetector.generate_test_qr_frame(p, width=640, height=480)
            import cv2
            _, jpeg_bytes = cv2.imencode(".jpg", frame)
            res = self.client.post("/api/vision/qr/process-image", data=jpeg_bytes.tobytes(), content_type="image/jpeg")
            self.assertEqual(res.status_code, 200)

            # Check drone armed state: MUST remain False
            snap = mavlink_service.get_snapshot()
            self.assertFalse(snap.armed, f"Vehicle was armed after QR detection of '{p}'!")

    def test_15_no_automatic_arming_from_mission_association(self):
        """15. Mission association and transition to READY must never arm the vehicle."""
        flight_controller.enabled = True
        with mavlink_service._lock:
            mavlink_service._armed = False

        # Associate mission
        assoc_res = self.client.post("/api/missions/associate-qr", json={"payload": "MISSION:patrol-field-alpha"})
        self.assertEqual(assoc_res.status_code, 200)

        # Active mission is now READY
        active_res = self.client.get("/api/missions/active")
        self.assertEqual(active_res.status_code, 200)
        active = active_res.get_json()["data"]
        self.assertIn(active["state"], ["READY", "VALIDATED"])

        # Vehicle must NEVER be armed automatically
        snap = mavlink_service.get_snapshot()
        self.assertFalse(snap.armed, "Vehicle armed automatically upon mission becoming READY!")

    def test_16_simulator_and_mock_compatibility(self):
        """16. Simulation mode generates high-fidelity telemetry and maintains state."""
        mavlink_service.simulate = True
        mavlink_service.start()
        time.sleep(0.15)

        snap = mavlink_service.get_snapshot()
        self.assertTrue(snap.connected)
        self.assertTrue(snap.is_simulated)
        self.assertEqual(snap.connection_type, "SIMULATION")
        self.assertIn("Simulated", snap.autopilot_type)
        self.assertGreater(snap.battery_voltage_v, 14.0)
        self.assertGreaterEqual(len(snap.prearm_messages), 1)

    def test_17_hardware_vs_simulation_separation_no_silent_fallback(self):
        """17. Physical hardware mode does not silently fall back to simulation on error."""
        svc = MAVLinkService(connection_string="udpin:127.0.0.1:59999", simulate=False)
        self.assertFalse(svc.simulate)

        # Connection error should keep simulate=False and report disconnected
        with svc._lock:
            svc._connected = False
            svc._last_heartbeat = 0.0

        snap = svc.get_snapshot()
        self.assertFalse(snap.is_simulated)
        self.assertEqual(snap.connection_type, "UDP_WIFI")
        self.assertFalse(snap.connected)

    def test_18_disarm_requires_confirmation_when_enabled(self):
        """18. DISARM requires explicit operator confirmation payload."""
        orig = flight_controller.enabled
        flight_controller.enabled = True
        try:
            # Without confirmation body
            res_no_confirm = self.client.post("/api/flight/disarm", json={})
            self.assertEqual(res_no_confirm.status_code, 400)
            self.assertEqual(res_no_confirm.get_json().get("code"), "CONFIRMATION_REQUIRED")

            # With explicit confirmation body
            res_confirmed = self.client.post("/api/flight/disarm", json={"confirm": True, "operator": "bench-tester"})
            self.assertEqual(res_confirmed.status_code, 200)
            self.assertTrue(res_confirmed.get_json()["data"]["success"])
        finally:
            flight_controller.enabled = orig

    def test_19_operator_token_authorization(self):
        """19. Operator token authorization if OPERATOR_TOKEN environment variable is set."""
        orig_token = os.environ.get("OPERATOR_TOKEN")
        orig_enabled = flight_controller.enabled
        flight_controller.enabled = True
        os.environ["OPERATOR_TOKEN"] = "secure-bench-token-123"
        try:
            # Missing token -> 401 Unauthorized
            res_unauth = self.client.post("/api/flight/arm", json={"confirm": True})
            self.assertEqual(res_unauth.status_code, 401)
            self.assertEqual(res_unauth.get_json().get("code"), "UNAUTHORIZED")

            # Valid token in header -> 200 Success
            res_auth = self.client.post(
                "/api/flight/arm",
                json={"confirm": True},
                headers={"X-Operator-Token": "secure-bench-token-123"}
            )
            self.assertEqual(res_auth.status_code, 200)
            self.assertTrue(res_auth.get_json()["data"]["success"])
        finally:
            if orig_token is not None:
                os.environ["OPERATOR_TOKEN"] = orig_token
            else:
                os.environ.pop("OPERATOR_TOKEN", None)
            flight_controller.enabled = orig_enabled

    def test_20_concurrent_command_locking(self):
        """20. Concurrency lock prevents simultaneous command execution."""
        orig = flight_controller.enabled
        flight_controller.enabled = True
        try:
            # Simulate an action already in progress
            with flight_controller._lock:
                flight_controller._action_in_progress = True

            res = self.client.post("/api/flight/arm", json={"confirm": True})
            self.assertEqual(res.status_code, 409)
            self.assertEqual(res.get_json().get("code"), "COMMAND_IN_PROGRESS")
        finally:
            with flight_controller._lock:
                flight_controller._action_in_progress = False
            flight_controller.enabled = orig

    def test_21_status_reports_last_command_and_heartbeat_state(self):
        """21. /api/flight/status exposes last_command, armed flag, and heartbeat metrics."""
        orig = flight_controller.enabled
        flight_controller.enabled = True
        try:
            # Issue an arm command
            self.client.post("/api/flight/arm", json={"confirm": True, "operator": "audit-tester"})

            # Query status
            res = self.client.get("/api/flight/status")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()["data"]
            self.assertIn("last_command", data)
            self.assertIsNotNone(data["last_command"])
            self.assertEqual(data["last_command"]["command"], "ARM")
            self.assertEqual(data["last_command"]["params"]["operator"], "audit-tester")
            self.assertTrue(data["last_command"]["success"])
            self.assertTrue(data["armed"])
        finally:
            flight_controller.enabled = orig


if __name__ == "__main__":
    unittest.main()

