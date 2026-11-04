"""
Raspberry Pi and Host CPU Temperature Monitoring Module.
Reads hardware thermal zones, vcgencmd metrics, and handles throttled states.
Provides graceful fallback for development and non-Linux hosts.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import psutil

from config.settings import settings
from config.logging_config import setup_logging

logger = setup_logging("temperature")


class TemperatureMonitor:
    """Monitors CPU and SoC thermal metrics, throttling warnings, and safety status."""

    THERMAL_ZONE_PATH = Path("/sys/class/thermal/thermal_zone0/temp")

    @classmethod
    def read_thermal_zone(cls) -> Optional[float]:
        """Read CPU temperature from Linux thermal_zone0 in Celsius."""
        if cls.THERMAL_ZONE_PATH.exists():
            try:
                raw_val = cls.THERMAL_ZONE_PATH.read_text().strip()
                milli_celsius = float(raw_val)
                return round(milli_celsius / 1000.0, 2)
            except Exception as e:
                logger.debug("Failed reading /sys/class/thermal/thermal_zone0/temp: %s", e)
        return None

    @classmethod
    def read_vcgencmd_temp(cls) -> Optional[float]:
        """Read temperature using Raspberry Pi vcgencmd utility."""
        try:
            res = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            if res.returncode == 0:
                # Output looks like: temp=48.2'C
                match = re.search(r"temp=([\d\.]+)", res.stdout)
                if match:
                    return round(float(match.group(1)), 2)
        except Exception:
            pass
        return None

    @classmethod
    def read_throttled_state(cls) -> Dict[str, Any]:
        """
        Query vcgencmd get_throttled to check for power brownout or thermal throttling.
        Decodes Raspberry Pi throttled bitmask.
        """
        throttled_info = {
            "available": False,
            "raw_hex": "0x0",
            "under_voltage_detected": False,
            "arm_frequency_capped": False,
            "currently_throttled": False,
            "soft_temp_limit_active": False,
            "under_voltage_occurred": False,
            "throttling_occurred": False
        }

        try:
            res = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False
            )
            if res.returncode == 0:
                # Output looks like: throttled=0x0
                match = re.search(r"throttled=(0x[0-9a-fA-F]+)", res.stdout)
                if match:
                    hex_val = match.group(1)
                    val = int(hex_val, 16)
                    throttled_info.update({
                        "available": True,
                        "raw_hex": hex_val,
                        "under_voltage_detected": bool(val & 0x1),
                        "arm_frequency_capped": bool(val & 0x2),
                        "currently_throttled": bool(val & 0x4),
                        "soft_temp_limit_active": bool(val & 0x8),
                        "under_voltage_occurred": bool(val & 0x10000),
                        "throttling_occurred": bool(val & 0x40000)
                    })
        except Exception:
            pass

        return throttled_info

    @classmethod
    def get_temperature(cls) -> Dict[str, Any]:
        """
        Get current CPU temperature, evaluates safety levels, and handles mock fallback.
        """
        temp_c: Optional[float] = None
        is_mocked = False

        # Attempt 1: Linux thermal zone (fastest, standard on Raspberry Pi OS)
        temp_c = cls.read_thermal_zone()

        # Attempt 2: vcgencmd utility
        if temp_c is None:
            temp_c = cls.read_vcgencmd_temp()

        # Attempt 3: psutil sensors (available on some Linux/BSD hosts)
        if temp_c is None and hasattr(psutil, "sensors_temperatures"):
            try:
                sensors = psutil.sensors_temperatures()
                if sensors:
                    for name, entries in sensors.items():
                        if entries:
                            temp_c = round(entries[0].current, 2)
                            break
            except Exception:
                pass

        # Fallback for Windows / test environments without thermal sensors
        if temp_c is None:
            is_mocked = True
            # Nominal operating temperature for simulated drone companion computer
            temp_c = 46.5

        # Compute status
        if temp_c >= settings.TEMP_CRITICAL_THRESHOLD:
            status = "CRITICAL"
        elif temp_c >= settings.TEMP_WARNING_THRESHOLD:
            status = "WARNING"
        else:
            status = "NORMAL"

        temp_f = round((temp_c * 9.0 / 5.0) + 32.0, 2)
        throttled = cls.read_throttled_state()

        return {
            "celsius": temp_c,
            "fahrenheit": temp_f,
            "status": status,
            "is_mocked": is_mocked,
            "thresholds": {
                "warning": settings.TEMP_WARNING_THRESHOLD,
                "critical": settings.TEMP_CRITICAL_THRESHOLD
            },
            "throttling": throttled
        }
