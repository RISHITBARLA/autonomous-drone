"""
Unit tests for HealthMonitor and TemperatureMonitor.
Verifies telemetry metric structures, safety threshold alerts, and uptime formatting.
"""
import unittest
from unittest.mock import patch
from backend.system.health_monitor import HealthMonitor
from backend.system.temperature import TemperatureMonitor


class TestHealthMonitor(unittest.TestCase):
    """Test suite for system health, temperature, and metrics collection."""

    def test_cpu_metrics(self):
        """Verify CPU metrics structure and non-negative values."""
        cpu = HealthMonitor.get_cpu_metrics()
        self.assertIn("usage_percent", cpu)
        self.assertIn("per_core_percent", cpu)
        self.assertIn("physical_cores", cpu)
        self.assertIn("logical_cores", cpu)
        self.assertGreaterEqual(cpu["usage_percent"], 0.0)
        self.assertIsInstance(cpu["per_core_percent"], list)

    def test_memory_metrics(self):
        """Verify RAM metrics values."""
        mem = HealthMonitor.get_memory_metrics()
        self.assertIn("total_bytes", mem)
        self.assertIn("used_bytes", mem)
        self.assertIn("usage_percent", mem)
        self.assertIn("total_gb", mem)
        self.assertGreater(mem["total_gb"], 0.0)
        self.assertGreaterEqual(mem["usage_percent"], 0.0)
        self.assertLessEqual(mem["usage_percent"], 100.0)

    def test_disk_metrics(self):
        """Verify disk storage metrics."""
        disk = HealthMonitor.get_disk_metrics()
        self.assertIn("total_gb", disk)
        self.assertIn("used_gb", disk)
        self.assertIn("free_gb", disk)
        self.assertIn("usage_percent", disk)
        self.assertGreater(disk["total_gb"], 0.0)

    def test_uptime_metrics(self):
        """Verify uptime formatting and seconds."""
        uptime = HealthMonitor.get_uptime_metrics()
        self.assertIn("uptime_seconds", uptime)
        self.assertIn("formatted", uptime)
        self.assertGreater(uptime["uptime_seconds"], 0)
        self.assertTrue(len(uptime["formatted"]) > 0)

    def test_temperature_monitor(self):
        """Verify temperature monitor returns valid celsius and status."""
        temp = TemperatureMonitor.get_temperature()
        self.assertIn("celsius", temp)
        self.assertIn("fahrenheit", temp)
        self.assertIn("status", temp)
        self.assertIn("thresholds", temp)
        self.assertIn(temp["status"], ["NORMAL", "WARNING", "CRITICAL"])
        self.assertGreater(temp["celsius"], 0.0)

    def test_status_evaluation_critical_threshold(self):
        """Verify status evaluation marks critical when temperature exceeds critical limit."""
        mock_cpu = {"usage_percent": 10.0}
        mock_mem = {"usage_percent": 30.0}
        mock_disk = {"usage_percent": 40.0}
        mock_temp = {"celsius": 88.0, "status": "CRITICAL", "throttling": {}}

        status = HealthMonitor.evaluate_system_status(mock_cpu, mock_mem, mock_disk, mock_temp)
        self.assertEqual(status["status"], "CRITICAL")
        self.assertFalse(status["healthy"])
        self.assertGreater(status["warning_count"], 0)

    def test_status_evaluation_healthy(self):
        """Verify status evaluation reports HEALTHY under nominal conditions."""
        mock_cpu = {"usage_percent": 15.0}
        mock_mem = {"usage_percent": 40.0}
        mock_disk = {"usage_percent": 45.0}
        mock_temp = {"celsius": 45.0, "status": "NORMAL", "throttling": {}}

        status = HealthMonitor.evaluate_system_status(mock_cpu, mock_mem, mock_disk, mock_temp)
        self.assertEqual(status["status"], "HEALTHY")
        self.assertTrue(status["healthy"])
        self.assertEqual(status["warning_count"], 0)

    def test_status_evaluation_warning_thresholds(self):
        """Verify WARNING status when thresholds are reached."""
        mock_cpu = {"usage_percent": 20.0}
        mock_mem = {"usage_percent": 88.0}  # Over 85%
        mock_disk = {"usage_percent": 92.0} # Over 90%
        mock_temp = {"celsius": 76.5, "status": "WARNING", "throttling": {"currently_throttled": True}}

        status = HealthMonitor.evaluate_system_status(mock_cpu, mock_mem, mock_disk, mock_temp)
        self.assertEqual(status["status"], "WARNING")
        self.assertFalse(status["healthy"])
        self.assertGreaterEqual(status["warning_count"], 3)

    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.read_text", return_value="48500\n")
    def test_thermal_zone_reading(self, mock_read, mock_exists):
        """Verify reading Linux thermal zone."""
        temp = TemperatureMonitor.read_thermal_zone()
        self.assertEqual(temp, 48.5)

    @patch("subprocess.run")
    def test_throttled_state_decoding(self, mock_run):
        """Verify decoding Raspberry Pi vcgencmd throttled bitmask."""
        # 0x50005 = 0x1 (under-voltage detected) | 0x4 (currently throttled) | 0x10000 (under-voltage occurred) | 0x40000 (throttling occurred)
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "throttled=0x50005\n"

        throttled = TemperatureMonitor.read_throttled_state()
        self.assertTrue(throttled["available"])
        self.assertTrue(throttled["under_voltage_detected"])
        self.assertTrue(throttled["currently_throttled"])
        self.assertTrue(throttled["under_voltage_occurred"])
        self.assertTrue(throttled["throttling_occurred"])


if __name__ == "__main__":
    unittest.main()
