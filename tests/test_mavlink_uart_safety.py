"""
Milestone M1 Automated Test Suite: MAVLink UART & Safety Interlocks.
Covers:
1. No USB fallback (/dev/ttyACM*, /dev/ttyUSB*) when /dev/serial0 (or configured UART device) is specified.
2. Dynamic autopilot and vehicle decoding from HEARTBEAT messages (ArduPilot, PX4, Quadrotor, Hexarotor).
3. Strict MAVLINK_SIMULATE=false enforcement on connection errors without silent fallback.
4. Settings.validate_configuration() safety exceptions and cross-field validation.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from config.settings import Settings, settings
from backend.flight.mavlink_service import (
    MAVLinkService,
    decode_heartbeat_identity,
    AUTOPILOT_NAME_MAP,
    VEHICLE_TYPE_MAP
)
from backend.app import create_app


class TestMAVLinkUARTSafety(unittest.TestCase):
    """Milestone M1 MAVLink UART and Safety Verification Suite."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        pass

    @patch("os.path.exists")
    @patch("glob.glob")
    @patch("pymavlink.mavutil.mavlink_connection")
    def test_no_usb_fallback_when_serial0_specified_and_missing(self, mock_mavconn, mock_glob, mock_exists):
        """
        Behavior A: Verify that when connection_string is /dev/serial0 and the port does not exist,
        the service NEVER falls back to /dev/ttyACM* or /dev/ttyUSB* devices.
        """
        mock_exists.return_value = False
        mock_glob.side_effect = lambda pat: ["/dev/ttyACM0"] if "ACM" in pat else (["/dev/ttyUSB0"] if "USB" in pat else [])
        
        # Stop the worker thread inside the first connection attempt
        svc = MAVLinkService(
            connection_string="/dev/serial0",
            baudrate=115200,
            simulate=False
        )

        def stop_on_connect(*args, **kwargs):
            svc._running = False
            raise Exception("Simulated serial port open failure")

        mock_mavconn.side_effect = stop_on_connect

        # Run single connection attempt cycle
        svc._running = True
        svc._run_mavlink_stream()

        # Verification: Connection was attempted strictly on /dev/serial0
        self.assertEqual(svc.connection_string, "/dev/serial0")
        self.assertTrue(mock_mavconn.called)
        call_args, call_kwargs = mock_mavconn.call_args
        self.assertEqual(call_args[0], "/dev/serial0")
        self.assertNotIn("/dev/ttyACM0", call_args[0])
        self.assertNotIn("/dev/ttyUSB0", call_args[0])
        self.assertFalse(svc.simulate)

    @patch("os.path.exists")
    @patch("glob.glob")
    @patch("pymavlink.mavutil.mavlink_connection")
    def test_no_usb_fallback_for_ttyama0_and_serial_by_id(self, mock_mavconn, mock_glob, mock_exists):
        """
        Verify that /dev/ttyAMA0 and /dev/serial paths also strictly bypass USB globbing.
        """
        mock_exists.return_value = False
        mock_glob.return_value = ["/dev/ttyACM0"]

        for uart_port in ["/dev/ttyAMA0", "/dev/serial/by-id/usb-pixhawk"]:
            svc = MAVLinkService(connection_string=uart_port, baudrate=115200, simulate=False)
            
            def stop_on_connect(*args, **kwargs):
                svc._running = False
                raise Exception("Port unavailable")

            mock_mavconn.side_effect = stop_on_connect
            svc._running = True
            svc._run_mavlink_stream()

            self.assertEqual(svc.connection_string, uart_port)
            self.assertEqual(mock_mavconn.call_args[0][0], uart_port)

    @patch("os.path.exists")
    @patch("glob.glob")
    @patch("pymavlink.mavutil.mavlink_connection")
    def test_usb_fallback_allowed_when_configured_as_usb_device(self, mock_mavconn, mock_glob, mock_exists):
        """
        Verify that when configured as a USB device (e.g. /dev/ttyACM0) and missing,
        USB re-enumeration fallback is allowed and updates self.connection_string.
        """
        mock_exists.return_value = False
        mock_glob.side_effect = lambda pat: ["/dev/ttyACM1"] if "ACM" in pat else []

        svc = MAVLinkService(
            connection_string="/dev/ttyACM0",
            baudrate=115200,
            simulate=False
        )

        def stop_on_connect(*args, **kwargs):
            svc._running = False
            raise Exception("Port test abort")

        mock_mavconn.side_effect = stop_on_connect
        svc._running = True
        svc._run_mavlink_stream()

        # Must have fallen back to /dev/ttyACM1 and updated self.connection_string
        self.assertEqual(svc.connection_string, "/dev/ttyACM1")
        self.assertEqual(mock_mavconn.call_args[0][0], "/dev/ttyACM1")

    def test_dynamic_autopilot_and_vehicle_decoding_from_heartbeat(self):
        """
        Behavior B: Verify dynamic decoding of msg.autopilot and msg.type from HEARTBEAT messages.
        """
        svc = MAVLinkService(connection_string="/dev/serial0", simulate=False)

        test_cases = [
            {"autopilot": 3, "type": 2, "expected_contains": ["ArduPilot", "Quadrotor"]},
            {"autopilot": 12, "type": 2, "expected_contains": ["PX4", "Quadrotor"]},
            {"autopilot": 3, "type": 13, "expected_contains": ["ArduPilot", "Hexarotor"]},
            {"autopilot": 0, "type": 0, "expected_contains": ["Generic"]},
        ]

        for tc in test_cases:
            mock_msg = MagicMock()
            mock_msg.get_type.return_value = "HEARTBEAT"
            mock_msg.get_srcSystem.return_value = 1
            mock_msg.get_srcComponent.return_value = 1
            mock_msg.custom_mode = 2  # ALT_HOLD
            mock_msg.base_mode = 128  # Armed
            mock_msg.autopilot = tc["autopilot"]
            mock_msg.type = tc["type"]

            svc._handle_heartbeat(mock_msg)
            snap = svc.get_snapshot()

            for exp in tc["expected_contains"]:
                self.assertIn(
                    exp.lower(),
                    snap.autopilot_type.lower(),
                    f"Expected '{exp}' in decoded autopilot_type '{snap.autopilot_type}' for test case {tc}"
                )

        # Robustness against missing or None attributes
        malformed_msg = MagicMock()
        malformed_msg.get_type.return_value = "HEARTBEAT"
        malformed_msg.autopilot = None
        malformed_msg.type = None
        malformed_msg.get_srcSystem.return_value = 1
        malformed_msg.get_srcComponent.return_value = 1
        malformed_msg.custom_mode = 0
        malformed_msg.base_mode = 0

        # Must not raise an exception
        try:
            svc._handle_heartbeat(malformed_msg)
            snap = svc.get_snapshot()
            self.assertIn("generic", snap.autopilot_type.lower())
        except Exception as e:
            self.fail(f"Heartbeat handling crashed on missing/None attributes: {e}")

    def test_gcs_heartbeat_ignored_in_decoding(self):
        """
        Verify that GCS echo heartbeat (type=6) is ignored and does not overwrite vehicle identity.
        """
        svc = MAVLinkService(connection_string="/dev/serial0", simulate=False)
        # Seed with valid vehicle heartbeat
        valid_msg = MagicMock()
        valid_msg.get_type.return_value = "HEARTBEAT"
        valid_msg.autopilot = 3
        valid_msg.type = 2
        valid_msg.custom_mode = 2
        valid_msg.base_mode = 128
        svc._handle_heartbeat(valid_msg)

        snap_before = svc.get_snapshot()
        self.assertIn("ardupilot", snap_before.autopilot_type.lower())

        # Now send GCS heartbeat (type=6)
        gcs_msg = MagicMock()
        gcs_msg.get_type.return_value = "HEARTBEAT"
        gcs_msg.autopilot = 0
        gcs_msg.type = 6
        svc._handle_heartbeat(gcs_msg)

        snap_after = svc.get_snapshot()
        self.assertEqual(snap_before.autopilot_type, snap_after.autopilot_type)

    @patch("pymavlink.mavutil.mavlink_connection")
    def test_mavlink_simulate_false_preserves_hardware_mode_on_connection_failure(self, mock_mavconn):
        """
        Behavior C: Verify that physical hardware connection errors keep simulate=False,
        report disconnected status, and never activate synthetic telemetry coordinates.
        """
        svc = MAVLinkService(
            connection_string="/dev/serial0",
            baudrate=115200,
            simulate=False
        )
        self.assertFalse(svc.simulate)

        def fail_and_stop(*args, **kwargs):
            svc._running = False
            raise Exception("Cannot open /dev/serial0: Port not found")

        mock_mavconn.side_effect = fail_and_stop

        svc._running = True
        svc._run_mavlink_stream()

        # Strict safety assertions
        self.assertFalse(svc.simulate, "Service silently switched simulate=True on error!")
        snap = svc.get_snapshot()
        self.assertFalse(snap.connected)
        self.assertFalse(snap.is_simulated)
        self.assertEqual(snap.connection_type, "SERIAL_UART")
        self.assertEqual(snap.flight_mode, "DISCONNECTED")
        self.assertEqual(snap.latitude, 0.0)
        self.assertEqual(snap.longitude, 0.0)
        self.assertEqual(snap.altitude_relative_m, 0.0)

    def test_settings_validate_configuration_safety_exceptions(self):
        """
        Behavior D: Exhaustively verify Settings.validate_configuration() safety exceptions.
        """
        orig_force_arm = Settings.FORCE_ARM
        orig_arming_checks = Settings.ARMING_CHECKS_ENABLED
        orig_transport = Settings.MAVLINK_TRANSPORT
        orig_flight_mode = Settings.FLIGHT_MODE
        orig_conn = Settings.MAVLINK_CONNECTION
        orig_conn_str = Settings.MAVLINK_CONNECTION_STRING

        try:
            # 1. FORCE_ARM = True must raise ValueError
            Settings.FORCE_ARM = True
            with self.assertRaises(ValueError) as ctx:
                Settings.validate_configuration()
            self.assertIn("FORCE_ARM must never be enabled", str(ctx.exception))
            Settings.FORCE_ARM = False

            # 2. ARMING_CHECKS_ENABLED = False must raise ValueError
            Settings.ARMING_CHECKS_ENABLED = False
            with self.assertRaises(ValueError) as ctx:
                Settings.validate_configuration()
            self.assertIn("ARMING_CHECKS_ENABLED cannot be disabled", str(ctx.exception))
            Settings.ARMING_CHECKS_ENABLED = True

            # 3. Invalid MAVLINK_TRANSPORT must raise ValueError
            for bad_transport in ["bluetooth", "can", "spi", ""]:
                Settings.MAVLINK_TRANSPORT = bad_transport
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("Invalid MAVLINK_TRANSPORT", str(ctx.exception))
            Settings.MAVLINK_TRANSPORT = "serial"
            Settings.MAVLINK_CONNECTION = "/dev/serial0"
            Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"

            # 4. Invalid FLIGHT_MODE must raise ValueError
            for bad_mode in ["ACRO_UNKNOWN", "SPORT", "DRIFT", "INVALID_MODE"]:
                Settings.FLIGHT_MODE = bad_mode
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("Invalid default FLIGHT_MODE", str(ctx.exception))
            Settings.FLIGHT_MODE = "ALT_HOLD"

            # 5. Empty or whitespace MAVLINK_CONNECTION must raise ValueError
            for empty_conn in ["", "   ", "\t\n", None]:
                Settings.MAVLINK_CONNECTION = empty_conn
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("cannot be empty", str(ctx.exception))
            Settings.MAVLINK_CONNECTION = "/dev/serial0"
            Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"

            # 6. Transport serial with network URI must raise ValueError
            Settings.MAVLINK_TRANSPORT = "serial"
            for net_uri in ["udpin:0.0.0.0:14550", "udp:192.168.1.1:14550", "tcp:127.0.0.1:5760"]:
                Settings.MAVLINK_CONNECTION = net_uri
                Settings.MAVLINK_CONNECTION_STRING = net_uri
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("network URI", str(ctx.exception))
            Settings.MAVLINK_CONNECTION = "/dev/serial0"
            Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"

            # 7. Transport udp/tcp with serial port must raise ValueError
            Settings.MAVLINK_TRANSPORT = "udp"
            for ser_dev in ["/dev/serial0", "/dev/ttyAMA0", "COM3"]:
                Settings.MAVLINK_CONNECTION = ser_dev
                Settings.MAVLINK_CONNECTION_STRING = ser_dev
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("serial port", str(ctx.exception))
            Settings.MAVLINK_CONNECTION = "udpin:0.0.0.0:14550"
            Settings.MAVLINK_CONNECTION_STRING = "udpin:0.0.0.0:14550"

            # 8. Mismatched environment variables must raise ValueError
            with patch.dict(os.environ, {"MAVLINK_CONNECTION": "/dev/serial0", "MAVLINK_CONNECTION_STRING": "udpin:0.0.0.0:14550"}):
                with self.assertRaises(ValueError) as ctx:
                    Settings.validate_configuration()
                self.assertIn("Configuration conflict", str(ctx.exception))

            # 9. Nominal serial configuration must pass cleanly
            Settings.MAVLINK_TRANSPORT = "serial"
            Settings.MAVLINK_CONNECTION = "/dev/serial0"
            Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"
            try:
                Settings.validate_configuration()
            except ValueError as e:
                self.fail(f"Nominal serial configuration raised unexpected ValueError: {e}")

            # 10. Nominal UDP configuration must pass cleanly
            Settings.MAVLINK_TRANSPORT = "udp"
            Settings.MAVLINK_CONNECTION = "udpin:0.0.0.0:14550"
            Settings.MAVLINK_CONNECTION_STRING = "udpin:0.0.0.0:14550"
            try:
                Settings.validate_configuration()
            except ValueError as e:
                self.fail(f"Nominal UDP configuration raised unexpected ValueError: {e}")

        finally:
            Settings.FORCE_ARM = orig_force_arm
            Settings.ARMING_CHECKS_ENABLED = orig_arming_checks
            Settings.MAVLINK_TRANSPORT = orig_transport
            Settings.FLIGHT_MODE = orig_flight_mode
            Settings.MAVLINK_CONNECTION = orig_conn
            Settings.MAVLINK_CONNECTION_STRING = orig_conn_str


if __name__ == "__main__":
    unittest.main()
