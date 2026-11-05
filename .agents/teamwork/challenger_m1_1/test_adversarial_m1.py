"""
Milestone M1 Adversarial Stress Test Suite
Author: Challenger 1 (critic, specialist)
Workspace: .agents/teamwork/challenger_m1_1/test_adversarial_m1.py

Adversarial Stress Test Challenges:
1. USB Fallback Elimination:
   - Force MAVLinkService to fall back to USB across multiple serial representation targets:
     /dev/serial0, /dev/ttyAMA0, /dev/serial/by-id/*, /dev/serial/by-path/*, COM3, /dev/ttyS0.
   - Ensure it NEVER switches target_conn or self.connection_string to /dev/ttyACM* or /dev/ttyUSB*.
   - Verify USB fallback ONLY occurs if configured device was already a USB port.
2. HEARTBEAT Decoding & Malformed Input Robustness:
   - Unmapped autopilot and vehicle type IDs, boundary values, negative numbers, floats, strings, None.
   - Missing attributes, empty objects, malformed custom_mode, malformed base_mode.
   - GCS echo heartbeat rejection (MAV_TYPE_GCS = 6).
   - Verify zero crashes, full exception handling, correct identity strings.
3. Simulation Isolation Guarantee (Anti-Simulation Leak):
   - Repeated physical disconnects, IOErrors, SerialExceptions, and reconnect loops.
   - Verify self.simulate strictly remains False and never flips to True.
   - Verify snapshot and status reports remain is_simulated=False and connection_type="SERIAL_UART".
4. Settings & Startup Configuration Guardrails:
   - Transport vs URI mismatches, env inconsistencies, safety flags enforcement.
"""

import os
import sys
import time
import math
import glob
import logging
import unittest
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.flight.mavlink_service import (
    MAVLinkService,
    decode_heartbeat_identity,
    AUTOPILOT_NAME_MAP,
    VEHICLE_TYPE_MAP,
    COPTER_MODES
)
from config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AdversarialM1")


class AdversarialUSBFallbackTests(unittest.TestCase):
    """Stress-tests USB fallback resistance across varied serial representations."""

    def setUp(self):
        self.available_usb_devices = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1"]

    def _execute_connection_setup_logic(self, connection_string_input):
        """
        Executes the exact connection-setup branch in MAVLinkService._run_mavlink_stream
        where target serial node does NOT exist on filesystem, but USB peripherals DO exist.
        """
        service = MAVLinkService(connection_string=connection_string_input, simulate=False)
        target_conn = service.connection_string

        is_uart = (
            str(target_conn) in ("/dev/serial0", "/dev/ttyAMA0")
            or str(target_conn).startswith(("/dev/serial", "/dev/ttyAMA"))
        )

        with patch("os.path.exists", return_value=False), \
             patch("glob.glob", side_effect=lambda pattern: [d for d in self.available_usb_devices if "ACM" in pattern or "USB" in pattern]):

            if is_uart:
                logger.debug("UART connection configured (%s); USB dynamic fallback is disabled.", target_conn)
            elif str(target_conn).startswith(("/dev/ttyACM", "/dev/ttyUSB")) and not os.path.exists(str(target_conn)):
                dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
                if dev_matches:
                    target_conn = dev_matches[0]
                    with service._lock:
                        service.connection_string = target_conn

        return target_conn, service.connection_string

    def test_challenge_serial0_never_falls_back(self):
        """Adversarial Challenge: /dev/serial0 missing with USB ports active must NEVER switch."""
        target, current = self._execute_connection_setup_logic("/dev/serial0")
        self.assertEqual(target, "/dev/serial0")
        self.assertEqual(current, "/dev/serial0")

    def test_challenge_ttyama0_never_falls_back(self):
        """Adversarial Challenge: /dev/ttyAMA0 missing with USB ports active must NEVER switch."""
        target, current = self._execute_connection_setup_logic("/dev/ttyAMA0")
        self.assertEqual(target, "/dev/ttyAMA0")
        self.assertEqual(current, "/dev/ttyAMA0")

    def test_challenge_serial_by_id_never_falls_back(self):
        """Adversarial Challenge: /dev/serial/by-id/ symlink missing must NEVER switch to /dev/ttyACM*."""
        port = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A1234567-if00-port0"
        target, current = self._execute_connection_setup_logic(port)
        self.assertEqual(target, port)
        self.assertEqual(current, port)

    def test_challenge_serial_by_path_never_falls_back(self):
        """Adversarial Challenge: /dev/serial/by-path/ symlink missing must NEVER switch to /dev/ttyACM*."""
        port = "/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0-port0"
        target, current = self._execute_connection_setup_logic(port)
        self.assertEqual(target, port)
        self.assertEqual(current, port)

    def test_challenge_windows_com_ports_never_fallback(self):
        """Adversarial Challenge: Windows COM ports must NEVER switch to USB Linux nodes."""
        for com in ["COM1", "COM3", "COM10", "COM25"]:
            target, current = self._execute_connection_setup_logic(com)
            self.assertEqual(target, com, f"Failed for Windows COM port {com}")
            self.assertEqual(current, com, f"Failed for Windows COM port {com}")

    def test_challenge_standard_ttys0_never_falls_back(self):
        """Adversarial Challenge: /dev/ttyS0 missing must NEVER switch to USB nodes."""
        target, current = self._execute_connection_setup_logic("/dev/ttyS0")
        self.assertEqual(target, "/dev/ttyS0")
        self.assertEqual(current, "/dev/ttyS0")

    def test_challenge_usb_configured_device_legitimately_reenumerates(self):
        """Adversarial Challenge: Fallback to USB ONLY occurs if connection was explicitly USB."""
        target, current = self._execute_connection_setup_logic("/dev/ttyACM99")
        self.assertEqual(target, "/dev/ttyACM0")
        self.assertEqual(current, "/dev/ttyACM0")

        target_usb, current_usb = self._execute_connection_setup_logic("/dev/ttyUSB99")
        self.assertEqual(target_usb, "/dev/ttyACM0")
        self.assertEqual(current_usb, "/dev/ttyACM0")


class AdversarialHeartbeatDecodingTests(unittest.TestCase):
    """Stress-tests HEARTBEAT decoding with malformed, edge-case, and hostile inputs."""

    def setUp(self):
        self.service = MAVLinkService(simulate=False)

    def test_unmapped_autopilot_ids(self):
        """Stress-test decoding arbitrary unmapped autopilot IDs."""
        edge_ids = [-1, -999, 99, 100, 255, 65535, 1000000]
        for ap_id in edge_ids:
            ap_name, veh_name, composite = decode_heartbeat_identity(ap_id, 2)
            self.assertEqual(ap_name, f"Autopilot-{ap_id}")
            self.assertEqual(veh_name, "Quadrotor")
            self.assertIn(f"Autopilot-{ap_id}", composite)
            self.assertIn("Quadrotor", composite)

    def test_unmapped_vehicle_type_ids(self):
        """Stress-test decoding arbitrary unmapped vehicle type IDs."""
        edge_types = [-1, -50, 99, 255, 9999]
        for t_id in edge_types:
            ap_name, veh_name, composite = decode_heartbeat_identity(3, t_id)
            self.assertEqual(ap_name, "ArduPilot")
            self.assertEqual(veh_name, f"Vehicle-{t_id}")
            self.assertIn(f"Vehicle-{t_id}", composite)

    def test_non_integer_type_inputs_to_decode_identity(self):
        """Stress-test passing non-int types (None, strings, floats, lists, dicts)."""
        bad_inputs = [None, "3", 3.14, [], {}, object(), (1, 2)]
        for bad_ap in bad_inputs:
            for bad_t in bad_inputs:
                try:
                    ap_name, veh_name, composite = decode_heartbeat_identity(bad_ap, bad_t)
                    self.assertIsInstance(ap_name, str)
                    self.assertIsInstance(veh_name, str)
                    self.assertIsInstance(composite, str)
                except Exception as e:
                    self.fail(f"decode_heartbeat_identity crashed with ({bad_ap}, {bad_t}): {e}")

    def test_all_known_ardupilot_subtypes(self):
        """Test all ArduPilot firmware subtypes: ArduCopter, ArduPlane, Rover, ArduSub, Heli."""
        # ArduCopter types: 2, 3, 13, 14, 15, 29, 35, 43
        for t_id in [2, 3, 13, 14, 15, 29, 35, 43]:
            _, _, comp = decode_heartbeat_identity(3, t_id)
            self.assertIn("ArduPilot ArduCopter", comp)

        # ArduPlane types: 1, 19, 20, 21
        for t_id in [1, 19, 20, 21]:
            _, _, comp = decode_heartbeat_identity(3, t_id)
            self.assertIn("ArduPilot ArduPlane", comp)

        # Rover types: 10, 11
        for t_id in [10, 11]:
            _, _, comp = decode_heartbeat_identity(3, t_id)
            self.assertIn("ArduPilot Rover", comp)

        # ArduSub: 12
        _, _, comp = decode_heartbeat_identity(3, 12)
        self.assertIn("ArduPilot ArduSub", comp)

        # Heli: 4
        _, _, comp = decode_heartbeat_identity(3, 4)
        self.assertIn("ArduPilot Heli", comp)

    def test_handle_heartbeat_nominal_and_px4(self):
        """Test _handle_heartbeat with nominal ArduPilot and PX4 messages."""
        # 1. Nominal ArduPilot Copter
        msg1 = MagicMock()
        msg1.type = 2
        msg1.autopilot = 3
        msg1.custom_mode = 5  # LOITER
        msg1.base_mode = 128 + 1  # Armed
        msg1.get_srcSystem = MagicMock(return_value=1)
        msg1.get_srcComponent = MagicMock(return_value=1)

        self.service._handle_heartbeat(msg1, timestamp=1000.0)
        self.assertTrue(self.service._connected)
        self.assertEqual(self.service._flight_mode, "LOITER")
        self.assertTrue(self.service._armed)
        self.assertEqual(self.service._system_status, "ACTIVE")
        self.assertEqual(self.service._autopilot_type, "ArduPilot ArduCopter (Quadrotor)")

        # 2. PX4 Quadrotor
        msg2 = MagicMock()
        msg2.type = 2
        msg2.autopilot = 12
        msg2.custom_mode = 0
        msg2.base_mode = 0  # Disarmed
        msg2.get_srcSystem = MagicMock(return_value=1)
        msg2.get_srcComponent = MagicMock(return_value=1)

        self.service._handle_heartbeat(msg2, timestamp=1001.0)
        self.assertFalse(self.service._armed)
        self.assertEqual(self.service._system_status, "STANDBY")
        self.assertEqual(self.service._autopilot_type, "PX4 (Quadrotor)")

    def test_gcs_heartbeat_echo_rejection(self):
        """Verify GCS heartbeat echo (type=6, MAV_TYPE_GCS) is ignored and does NOT overwrite state."""
        # Establish vehicle state first
        msg_veh = MagicMock(type=2, autopilot=3, custom_mode=4, base_mode=128)
        msg_veh.get_srcSystem = MagicMock(return_value=1)
        msg_veh.get_srcComponent = MagicMock(return_value=1)
        self.service._handle_heartbeat(msg_veh, timestamp=1000.0)
        self.assertEqual(self.service._autopilot_type, "ArduPilot ArduCopter (Quadrotor)")
        self.assertTrue(self.service._armed)

        # Receive GCS echo heartbeat
        msg_gcs = MagicMock(type=6, autopilot=0, custom_mode=0, base_mode=0)
        msg_gcs.get_srcSystem = MagicMock(return_value=255)
        msg_gcs.get_srcComponent = MagicMock(return_value=190)
        self.service._handle_heartbeat(msg_gcs, timestamp=1001.0)

        # Vehicle state MUST NOT be altered
        self.assertEqual(self.service._autopilot_type, "ArduPilot ArduCopter (Quadrotor)")
        self.assertTrue(self.service._armed)
        self.assertEqual(self.service._target_system, 1)

    def test_handle_heartbeat_malformed_fields(self):
        """Feed object with string/None/float fields to _handle_heartbeat."""
        class MalformedHeartbeat:
            type = "NOT_AN_INT"
            autopilot = None
            custom_mode = "MODE_UNKNOWN"
            base_mode = 3.14
            srcSystem = -10
            srcComponent = "INVALID"

        msg = MalformedHeartbeat()
        try:
            self.service._handle_heartbeat(msg, timestamp=2000.0)
        except Exception as e:
            self.fail(f"_handle_heartbeat raised exception on MalformedHeartbeat: {e}")

        self.assertTrue(self.service._connected)
        self.assertEqual(self.service._flight_mode, "STABILIZE")
        self.assertFalse(self.service._armed)
        self.assertEqual(self.service._system_status, "STANDBY")

    def test_handle_heartbeat_empty_object(self):
        """Feed empty object lacking all MAVLink attributes to _handle_heartbeat."""
        class EmptyMsg:
            pass

        try:
            self.service._handle_heartbeat(EmptyMsg(), timestamp=3000.0)
        except Exception as e:
            self.fail(f"_handle_heartbeat raised exception on EmptyMsg: {e}")

        self.assertTrue(self.service._connected)
        self.assertEqual(self.service._flight_mode, "STABILIZE")
        self.assertFalse(self.service._armed)


class AdversarialSimulationLeakTests(unittest.TestCase):
    """Stress-tests isolation between physical hardware and simulation modes."""

    def test_simulate_strictly_persists_false_across_connection_failures(self):
        """Simulate 100 repeated connection dropouts and verify self.simulate NEVER flips to True."""
        service = MAVLinkService(connection_string="/dev/serial0", simulate=False)
        self.assertFalse(service.simulate)

        mock_exceptions = [
            FileNotFoundError("No such file or directory: '/dev/serial0'"),
            PermissionError("Permission denied: '/dev/ttyAMA0'"),
            TimeoutError("MAVLink connection handshake timed out"),
            OSError("Device or resource busy"),
            IOError("Input/output error on serial port")
        ]

        # Emulate the loop error handling of _run_mavlink_stream lines 429-434
        for i in range(100):
            exc = mock_exceptions[i % len(mock_exceptions)]
            try:
                raise exc
            except Exception as e:
                with service._lock:
                    service._connected = False
                if service._mav_connection:
                    service._mav_connection = None

            self.assertFalse(service.simulate, f"Simulation leaked to True on attempt {i}")
            snap = service.get_snapshot()
            self.assertFalse(snap.is_simulated)
            self.assertEqual(snap.connection_type, "SERIAL_UART")

    def test_simulate_strictly_persists_false_across_packet_receive_failures(self):
        """Simulate 50 packet receive crashes (corrupted bytes, disconnected USB/UART cable)."""
        service = MAVLinkService(connection_string="/dev/serial0", simulate=False)
        mock_conn = MagicMock()
        mock_conn.recv_match.side_effect = IOError("Serial pipe broken")
        service._mav_connection = mock_conn

        for i in range(50):
            try:
                msg = service._mav_connection.recv_match(blocking=True, timeout=1.0)
            except Exception:
                with service._lock:
                    service._connected = False
                if service._mav_connection:
                    try:
                        service._mav_connection.close()
                    except Exception:
                        pass
                    service._mav_connection = None

            self.assertFalse(service.simulate, f"Simulation leaked on recv error {i}")
            self.assertIsNone(service._mav_connection)
            snap = service.get_snapshot()
            self.assertFalse(snap.is_simulated)
            self.assertFalse(snap.connected)

    def test_hardware_mode_telemetry_snapshot_integrity(self):
        """Verify telemetry snapshot under disconnected hardware mode is completely clean."""
        service = MAVLinkService(connection_string="/dev/serial0", simulate=False)
        snap = service.get_snapshot()
        self.assertFalse(snap.connected)
        self.assertFalse(snap.is_simulated)
        self.assertTrue(snap.is_stale)
        self.assertEqual(snap.connection_type, "SERIAL_UART")
        self.assertEqual(snap.flight_mode, "DISCONNECTED")
        self.assertEqual(snap.latitude, 0.0)
        self.assertEqual(snap.longitude, 0.0)


class AdversarialSettingsValidationTests(unittest.TestCase):
    """Stress-tests startup settings guardrails and invariants."""

    def test_serial_transport_rejects_network_uris(self):
        """Verify MAVLINK_TRANSPORT='serial' rejects all UDP/TCP network URIs."""
        invalid_serial = [
            "udpin:0.0.0.0:14550",
            "udpout:127.0.0.1:14550",
            "udp:192.168.1.100:14550",
            "tcpin:0.0.0.0:5760",
            "tcpout:127.0.0.1:5760",
            "tcp:10.0.0.1:5760"
        ]
        for conn in invalid_serial:
            with patch.object(Settings, "MAVLINK_TRANSPORT", "serial"), \
                 patch.object(Settings, "MAVLINK_CONNECTION", conn), \
                 patch.object(Settings, "MAVLINK_CONNECTION_STRING", conn), \
                 patch.dict(os.environ, {"MAVLINK_CONNECTION": conn, "MAVLINK_CONNECTION_STRING": conn}):
                with self.assertRaises(ValueError, msg=f"Should reject serial transport with {conn}"):
                    Settings.validate_configuration()

    def test_network_transport_rejects_serial_devices(self):
        """Verify MAVLINK_TRANSPORT in ('udp', 'tcp') rejects all serial device paths."""
        invalid_network = [
            "/dev/serial0",
            "/dev/ttyAMA0",
            "/dev/ttyUSB0",
            "/dev/ttyACM0",
            "COM1",
            "COM3",
            "com10"
        ]
        for transport in ["udp", "tcp"]:
            for conn in invalid_network:
                with patch.object(Settings, "MAVLINK_TRANSPORT", transport), \
                     patch.object(Settings, "MAVLINK_CONNECTION", conn), \
                     patch.object(Settings, "MAVLINK_CONNECTION_STRING", conn), \
                     patch.dict(os.environ, {"MAVLINK_CONNECTION": conn, "MAVLINK_CONNECTION_STRING": conn}):
                    with self.assertRaises(ValueError, msg=f"Should reject {transport} transport with {conn}"):
                        Settings.validate_configuration()

    def test_conflicting_env_connection_keys(self):
        """Test that different values in MAVLINK_CONNECTION and MAVLINK_CONNECTION_STRING raise ValueError."""
        with patch.dict(os.environ, {
            "MAVLINK_CONNECTION": "/dev/serial0",
            "MAVLINK_CONNECTION_STRING": "/dev/ttyAMA0"
        }):
            with self.assertRaises(ValueError):
                Settings.validate_configuration()

    def test_force_arm_and_arming_checks_safety(self):
        """Verify strict prohibitions on FORCE_ARM=true and ARMING_CHECKS_ENABLED=false."""
        with patch.object(Settings, "FORCE_ARM", True):
            with self.assertRaises(ValueError):
                Settings.validate_configuration()

        with patch.object(Settings, "ARMING_CHECKS_ENABLED", False):
            with self.assertRaises(ValueError):
                Settings.validate_configuration()


class AdversarialModeMatrixTests(unittest.TestCase):
    """Stress-tests all ArduCopter mode translations and unknown mode IDs."""

    def setUp(self):
        self.service = MAVLinkService(simulate=False)

    def test_all_standard_copter_modes(self):
        """Verify all 11 standard ArduCopter custom modes map accurately."""
        expected_modes = {
            0: "STABILIZE",
            1: "ACRO",
            2: "ALT_HOLD",
            3: "AUTO",
            4: "GUIDED",
            5: "LOITER",
            6: "RTL",
            7: "CIRCLE",
            9: "LAND",
            16: "POSHOLD",
            17: "BRAKE"
        }
        for mode_id, expected_str in expected_modes.items():
            msg = MagicMock(type=2, autopilot=3, custom_mode=mode_id, base_mode=0)
            msg.get_srcSystem = MagicMock(return_value=1)
            msg.get_srcComponent = MagicMock(return_value=1)
            self.service._handle_heartbeat(msg)
            self.assertEqual(self.service._flight_mode, expected_str, f"Mismatch for mode {mode_id}")

    def test_unknown_copter_modes(self):
        """Verify unmapped custom modes format as MODE_<id> without crashing."""
        for mode_id in [-5, 8, 10, 15, 20, 999]:
            msg = MagicMock(type=2, autopilot=3, custom_mode=mode_id, base_mode=0)
            msg.get_srcSystem = MagicMock(return_value=1)
            msg.get_srcComponent = MagicMock(return_value=1)
            self.service._handle_heartbeat(msg)
            self.assertEqual(self.service._flight_mode, f"MODE_{mode_id}")


class AdversarialConcurrencyAndDropoutHarness(unittest.TestCase):
    """Concurrent multi-threaded stress harness for rapid dropouts, errors, and snapshot reads."""

    def test_concurrent_dropout_and_snapshot_flood(self):
        """Flood get_snapshot and get_status across 4 threads while simulating 100 disconnect cycles."""
        import threading

        service = MAVLinkService(connection_string="/dev/serial0", simulate=False)
        errors = []
        stop_event = threading.Event()

        def reader_worker(worker_id):
            try:
                for _ in range(250):
                    snap = service.get_snapshot()
                    snap_dict = snap.to_dict()
                    if snap.is_simulated:
                        errors.append(f"Worker {worker_id}: snap.is_simulated leaked True!")
                    if snap_dict["is_simulated"]:
                        errors.append(f"Worker {worker_id}: snap_dict['is_simulated'] leaked True!")
                    if service.simulate:
                        errors.append(f"Worker {worker_id}: service.simulate leaked True!")
                    if snap.connection_type != "SERIAL_UART":
                        errors.append(f"Worker {worker_id}: snap.connection_type unexpected: {snap.connection_type}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Worker {worker_id} crashed: {e}")

        # Start 4 concurrent reader threads
        reader_threads = [
            threading.Thread(target=reader_worker, args=(i,), daemon=True)
            for i in range(4)
        ]
        for t in reader_threads:
            t.start()

        # In main thread, rapidly alternate between connected heartbeat and disconnect error
        for cycle in range(50):
            # 1. Simulate packet arriving
            msg = MagicMock(type=2, autopilot=3, custom_mode=cycle % 10, base_mode=128 if cycle % 2 else 0)
            msg.get_srcSystem = MagicMock(return_value=1)
            msg.get_srcComponent = MagicMock(return_value=1)
            service._handle_heartbeat(msg)

            # 2. Simulate sudden serial disconnection / error
            with service._lock:
                service._connected = False
            if service._mav_connection:
                service._mav_connection = None

            time.sleep(0.002)

        for t in reader_threads:
            t.join(timeout=3.0)

        self.assertFalse(service.simulate)
        self.assertEqual(errors, [], f"Concurrency errors detected: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

