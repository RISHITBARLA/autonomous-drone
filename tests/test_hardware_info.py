"""
Unit tests for HardwareInfo module.
Tests detection logic, CPU info parsing, and mock fallback.
"""
import unittest
from unittest.mock import patch, mock_open
from backend.system.hardware_info import HardwareInfo


class TestHardwareInfo(unittest.TestCase):
    """Test suite for companion computer hardware identification."""

    def test_system_summary_structure(self):
        """Verify get_system_summary returns all required fields."""
        summary = HardwareInfo.get_system_summary(mock_if_not_rpi=True)

        self.assertIn("is_raspberry_pi", summary)
        self.assertIn("device", summary)
        self.assertIn("cpu", summary)
        self.assertIn("memory", summary)
        self.assertIn("storage", summary)
        self.assertIn("os", summary)
        self.assertIn("python", summary)

        # Device details
        device = summary["device"]
        self.assertIn("model", device)
        self.assertIn("soc", device)
        self.assertIn("hostname", device)

        # CPU details
        cpu = summary["cpu"]
        self.assertIn("architecture", cpu)
        self.assertGreaterEqual(cpu["physical_cores"], 1)
        self.assertGreaterEqual(cpu["logical_cores"], 1)

    def test_mock_simulation_mode(self):
        """Verify simulated Pi 4 parameters when requested on non-Pi hosts."""
        summary = HardwareInfo.get_system_summary(mock_if_not_rpi=True)
        if not summary["is_raspberry_pi"]:
            self.assertTrue(summary["simulated"])
            self.assertIn("Raspberry Pi 4", summary["device"]["model"])
            self.assertIn("BCM2711", summary["device"]["soc"])

    @patch("platform.system", return_value="Linux")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.read_text", return_value="Raspberry Pi 4 Model B Rev 1.4\x00")
    def test_is_raspberry_pi_detection(self, mock_read, mock_exists, mock_sys):
        """Verify device tree model detection on genuine Raspberry Pi."""
        self.assertTrue(HardwareInfo.is_raspberry_pi())

    @patch("pathlib.Path.exists", return_value=True)
    def test_parse_cpuinfo_mock(self, mock_exists):
        """Verify parsing Linux /proc/cpuinfo."""
        mock_cpuinfo_data = (
            "Hardware\t: BCM2711\n"
            "Revision\t: c03114\n"
            "Serial\t\t: 10000000a1b2c3d4\n"
            "Model\t\t: Raspberry Pi 4 Model B Rev 1.4\n"
        )
        with patch("builtins.open", mock_open(read_data=mock_cpuinfo_data)):
            parsed = HardwareInfo.parse_cpuinfo()
            self.assertEqual(parsed.get("Hardware"), "BCM2711")
            self.assertEqual(parsed.get("Revision"), "c03114")
            self.assertEqual(parsed.get("Serial"), "10000000a1b2c3d4")
            self.assertEqual(parsed.get("Model"), "Raspberry Pi 4 Model B Rev 1.4")

    @patch("pathlib.Path.exists", return_value=True)
    def test_get_linux_distro_info_mock(self, mock_exists):
        """Verify parsing /etc/os-release."""
        mock_os_release = (
            'NAME="Debian GNU/Linux"\n'
            'VERSION="12 (bookworm)"\n'
            'PRETTY_NAME="Raspberry Pi OS (64-bit)"\n'
        )
        with patch("builtins.open", mock_open(read_data=mock_os_release)):
            distro = HardwareInfo.get_linux_distro_info()
            self.assertEqual(distro["name"], "Debian GNU/Linux")
            self.assertEqual(distro["version"], "12 (bookworm)")
            self.assertEqual(distro["pretty_name"], "Raspberry Pi OS (64-bit)")


if __name__ == "__main__":
    unittest.main()
