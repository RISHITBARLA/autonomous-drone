"""
Adversarial Stress Test Harness 1: Settings.validate_configuration() Fail-Closed Invariants
Challenger 2 (Milestone M1)
"""
import os
import sys
import unittest
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import Settings


class StressTestSettingsValidation(unittest.TestCase):
    """Stress tests Settings.validate_configuration against adversarial/malicious configurations."""

    def setUp(self):
        # Save original env and settings attributes
        self._orig_env = dict(os.environ)
        self._orig_attrs = {
            "FORCE_ARM": Settings.FORCE_ARM,
            "ARMING_CHECKS_ENABLED": Settings.ARMING_CHECKS_ENABLED,
            "MAVLINK_TRANSPORT": Settings.MAVLINK_TRANSPORT,
            "MAVLINK_CONNECTION": Settings.MAVLINK_CONNECTION,
            "MAVLINK_CONNECTION_STRING": Settings.MAVLINK_CONNECTION_STRING,
            "FLIGHT_MODE": Settings.FLIGHT_MODE,
        }

    def tearDown(self):
        # Restore environment
        os.environ.clear()
        os.environ.update(self._orig_env)
        for k, v in self._orig_attrs.items():
            setattr(Settings, k, v)

    def set_nominal(self):
        """Set nominal valid settings."""
        Settings.FORCE_ARM = False
        Settings.ARMING_CHECKS_ENABLED = True
        Settings.MAVLINK_TRANSPORT = "serial"
        Settings.MAVLINK_CONNECTION = "/dev/serial0"
        Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"
        Settings.FLIGHT_MODE = "ALT_HOLD"
        os.environ["MAVLINK_CONNECTION"] = "/dev/serial0"
        os.environ["MAVLINK_CONNECTION_STRING"] = "/dev/serial0"
        os.environ["FORCE_ARM"] = "false"
        os.environ["ARMING_CHECKS_ENABLED"] = "true"

    # --- 1. FORCE_ARM variations ---
    def test_force_arm_true_fails_closed(self):
        self.set_nominal()
        Settings.FORCE_ARM = True
        with self.assertRaises(ValueError) as ctx:
            Settings.validate_configuration()
        self.assertIn("CRITICAL SAFETY VIOLATION", str(ctx.exception))
        self.assertIn("FORCE_ARM", str(ctx.exception))

    def test_force_arm_truthy_truth_table(self):
        """Test truthy values parsed from environment into Settings."""
        for truthy in ("true", "TRUE", "True", "1", "yes", "YES", "Yes"):
            self.set_nominal()
            os.environ["FORCE_ARM"] = truthy
            val = os.getenv("FORCE_ARM", "false").lower() in ("true", "1", "yes")
            Settings.FORCE_ARM = val
            with self.assertRaises(ValueError, msg=f"Failed to reject FORCE_ARM={truthy}"):
                Settings.validate_configuration()

    # --- 2. ARMING_CHECKS_ENABLED variations ---
    def test_arming_checks_disabled_fails_closed(self):
        self.set_nominal()
        Settings.ARMING_CHECKS_ENABLED = False
        with self.assertRaises(ValueError) as ctx:
            Settings.validate_configuration()
        self.assertIn("CRITICAL SAFETY VIOLATION", str(ctx.exception))
        self.assertIn("ARMING_CHECKS_ENABLED", str(ctx.exception))

    def test_arming_checks_falsy_truth_table(self):
        for falsy in ("false", "FALSE", "False", "0", "no", "NO", "off", ""):
            self.set_nominal()
            os.environ["ARMING_CHECKS_ENABLED"] = falsy
            val = os.getenv("ARMING_CHECKS_ENABLED", "true").lower() in ("true", "1", "yes")
            Settings.ARMING_CHECKS_ENABLED = val
            with self.assertRaises(ValueError, msg=f"Failed to reject ARMING_CHECKS_ENABLED={falsy}"):
                Settings.validate_configuration()

    # --- 3. Empty or whitespace connection strings ---
    def test_empty_connection_strings_fail_closed(self):
        bad_conns = ["", "   ", "\t", "\n", None]
        for conn in bad_conns:
            self.set_nominal()
            Settings.MAVLINK_CONNECTION = conn
            with self.assertRaises(ValueError, msg=f"Failed to reject MAVLINK_CONNECTION={repr(conn)}"):
                Settings.validate_configuration()

    # --- 4. Transport vs Connection Mismatches ---
    def test_serial_transport_with_network_uris_fail_closed(self):
        network_uris = [
            "udpin:0.0.0.0:14550",
            "udp:192.168.1.100:14550",
            "udpout:127.0.0.1:14550",
            "tcp:10.0.0.1:5760",
            "tcpin:0.0.0.0:5760",
            "tcpout:192.168.1.50:5760",
            "UDPIN:0.0.0.0:14550",
            "TCP:127.0.0.1:5760",
        ]
        for uri in network_uris:
            self.set_nominal()
            Settings.MAVLINK_TRANSPORT = "serial"
            Settings.MAVLINK_CONNECTION = uri
            Settings.MAVLINK_CONNECTION_STRING = uri
            os.environ["MAVLINK_CONNECTION"] = uri
            os.environ["MAVLINK_CONNECTION_STRING"] = uri
            with self.assertRaises(ValueError, msg=f"Failed to reject serial with network URI {uri}"):
                Settings.validate_configuration()

    def test_udp_transport_with_serial_devices_fail_closed(self):
        serial_paths = [
            "/dev/serial0",
            "/dev/ttyAMA0",
            "/dev/ttyUSB0",
            "/dev/ttyACM0",
            "/dev/serial/by-id/usb-ArduPilot-xxx",
            "COM3",
            "com1",
            "COM12",
        ]
        for s_path in serial_paths:
            self.set_nominal()
            Settings.MAVLINK_TRANSPORT = "udp"
            Settings.MAVLINK_CONNECTION = s_path
            Settings.MAVLINK_CONNECTION_STRING = s_path
            os.environ["MAVLINK_CONNECTION"] = s_path
            os.environ["MAVLINK_CONNECTION_STRING"] = s_path
            with self.assertRaises(ValueError, msg=f"Failed to reject udp with serial path {s_path}"):
                Settings.validate_configuration()

    def test_tcp_transport_with_serial_devices_fail_closed(self):
        serial_paths = [
            "/dev/serial0",
            "/dev/ttyAMA0",
            "/dev/ttyUSB0",
            "COM4",
        ]
        for s_path in serial_paths:
            self.set_nominal()
            Settings.MAVLINK_TRANSPORT = "tcp"
            Settings.MAVLINK_CONNECTION = s_path
            Settings.MAVLINK_CONNECTION_STRING = s_path
            os.environ["MAVLINK_CONNECTION"] = s_path
            os.environ["MAVLINK_CONNECTION_STRING"] = s_path
            with self.assertRaises(ValueError, msg=f"Failed to reject tcp with serial path {s_path}"):
                Settings.validate_configuration()

    # --- 5. Contradictory connection env vars ---
    def test_contradictory_connection_env_vars_fail_closed(self):
        contradictions = [
            ("/dev/serial0", "/dev/ttyAMA0"),
            ("udpin:0.0.0.0:14550", "udpout:127.0.0.1:14550"),
            ("/dev/serial0", "udpin:0.0.0.0:14550"),
            ("/dev/serial0", "/dev/ttyUSB0"),
        ]
        for c1, c2 in contradictions:
            self.set_nominal()
            os.environ["MAVLINK_CONNECTION"] = c1
            os.environ["MAVLINK_CONNECTION_STRING"] = c2
            with self.assertRaises(ValueError, msg=f"Failed to reject contradictory env vars {c1} != {c2}"):
                Settings.validate_configuration()

    # --- 6. Invalid Transport and Modes ---
    def test_invalid_transports_fail_closed(self):
        bad_transports = ["bluetooth", "spi", "i2c", "wifi", "can", "unknown", ""]
        for t in bad_transports:
            self.set_nominal()
            Settings.MAVLINK_TRANSPORT = t
            with self.assertRaises(ValueError, msg=f"Failed to reject transport {t}"):
                Settings.validate_configuration()

    def test_invalid_modes_fail_closed(self):
        bad_modes = ["ACRO", "SPORT", "DRIFT", "FLIP", "AUTOTUNE", "CRASH", "UNKNOWN", ""]
        for m in bad_modes:
            self.set_nominal()
            Settings.FLIGHT_MODE = m
            with self.assertRaises(ValueError, msg=f"Failed to reject flight mode {m}"):
                Settings.validate_configuration()

    # --- 7. Edge Cases ---
    def test_network_bare_ip_port_edge_case(self):
        """Check behavior when MAVLINK_TRANSPORT is serial but connection is bare IP:port."""
        self.set_nominal()
        Settings.MAVLINK_TRANSPORT = "serial"
        # Bare IP:port without udp: prefix
        bare_ip = "192.168.10.235:14550"
        Settings.MAVLINK_CONNECTION = bare_ip
        Settings.MAVLINK_CONNECTION_STRING = bare_ip
        os.environ["MAVLINK_CONNECTION"] = bare_ip
        os.environ["MAVLINK_CONNECTION_STRING"] = bare_ip
        # In current implementation, does validate_configuration catch bare IP or let it pass?
        # Let's observe!
        try:
            Settings.validate_configuration()
            caught = False
        except ValueError:
            caught = True
        print(f"[EDGE-CASE OBSERVED] serial transport with bare IP '{bare_ip}' caught by validate_configuration? {caught}")

    # --- 8. Nominal Valid Configurations Must Pass ---
    def test_nominal_serial_passes(self):
        self.set_nominal()
        # Should not raise
        Settings.validate_configuration()

    def test_nominal_udp_passes(self):
        self.set_nominal()
        Settings.MAVLINK_TRANSPORT = "udp"
        Settings.MAVLINK_CONNECTION = "udpin:0.0.0.0:14550"
        Settings.MAVLINK_CONNECTION_STRING = "udpin:0.0.0.0:14550"
        os.environ["MAVLINK_CONNECTION"] = "udpin:0.0.0.0:14550"
        os.environ["MAVLINK_CONNECTION_STRING"] = "udpin:0.0.0.0:14550"
        Settings.validate_configuration()

    def test_nominal_tcp_passes(self):
        self.set_nominal()
        Settings.MAVLINK_TRANSPORT = "tcp"
        Settings.MAVLINK_CONNECTION = "tcp:127.0.0.1:5760"
        Settings.MAVLINK_CONNECTION_STRING = "tcp:127.0.0.1:5760"
        os.environ["MAVLINK_CONNECTION"] = "tcp:127.0.0.1:5760"
        os.environ["MAVLINK_CONNECTION_STRING"] = "tcp:127.0.0.1:5760"
        Settings.validate_configuration()


if __name__ == "__main__":
    unittest.main()

