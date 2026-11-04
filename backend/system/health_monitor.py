"""
Comprehensive System Health Monitor for Raspberry Pi 4 Companion Computer.
Aggregates CPU, RAM, Disk, Temperature, Uptime, and overall health status.
"""
import os
import platform
import time
from typing import Dict, Any, List
import psutil

from config.settings import settings
from config.logging_config import setup_logging
from .temperature import TemperatureMonitor
from .hardware_info import HardwareInfo

logger = setup_logging("health_monitor")


class HealthMonitor:
    """Collects real-time telemetry on CPU, memory, storage, temperature, and system uptime."""

    def __init__(self):
        # Warm up psutil cpu_percent calculation
        psutil.cpu_percent(interval=None)

    @classmethod
    def get_cpu_metrics(cls) -> Dict[str, Any]:
        """Collect overall and per-core CPU usage, core counts, and frequencies."""
        overall_percent = psutil.cpu_percent(interval=None)
        per_core_percent = psutil.cpu_percent(interval=None, percpu=True)

        freq = psutil.cpu_freq()
        freq_info = {
            "current_mhz": round(freq.current, 1) if freq else None,
            "min_mhz": round(freq.min, 1) if freq and freq.min else None,
            "max_mhz": round(freq.max, 1) if freq and freq.max else None
        }

        # System load average (Linux/Unix only)
        load_avg = None
        if hasattr(os, "getloadavg"):
            try:
                loads = os.getloadavg()
                load_avg = {
                    "1min": round(loads[0], 2),
                    "5min": round(loads[1], 2),
                    "15min": round(loads[2], 2)
                }
            except Exception:
                pass

        return {
            "usage_percent": overall_percent,
            "per_core_percent": per_core_percent,
            "physical_cores": psutil.cpu_count(logical=False) or 1,
            "logical_cores": psutil.cpu_count(logical=True) or 1,
            "frequency": freq_info,
            "load_average": load_avg
        }

    @classmethod
    def get_memory_metrics(cls) -> Dict[str, Any]:
        """Collect RAM and Swap metrics."""
        vmem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            "total_bytes": vmem.total,
            "available_bytes": vmem.available,
            "used_bytes": vmem.used,
            "usage_percent": vmem.percent,
            "total_gb": round(vmem.total / (1024 ** 3), 2),
            "available_gb": round(vmem.available / (1024 ** 3), 2),
            "used_gb": round(vmem.used / (1024 ** 3), 2),
            "swap": {
                "total_gb": round(swap.total / (1024 ** 3), 2),
                "used_gb": round(swap.used / (1024 ** 3), 2),
                "percent": swap.percent
            }
        }

    @classmethod
    def get_disk_metrics(cls) -> Dict[str, Any]:
        """Collect root filesystem disk space metrics."""
        mount_path = "/" if platform.system() != "Windows" else "C:\\"
        try:
            disk = psutil.disk_usage(mount_path)
            total_gb = round(disk.total / (1024 ** 3), 2)
            used_gb = round(disk.used / (1024 ** 3), 2)
            free_gb = round(disk.free / (1024 ** 3), 2)
            percent = disk.percent
        except Exception as e:
            logger.error("Failed to read disk usage: %s", e)
            total_gb = used_gb = free_gb = percent = 0.0

        return {
            "mount_path": mount_path,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "usage_percent": percent
        }

    @classmethod
    def get_uptime_metrics(cls) -> Dict[str, Any]:
        """Calculate system uptime and boot time."""
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)

        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        if days > 0:
            formatted = f"{days}d {hours}h {minutes}m {seconds}s"
        elif hours > 0:
            formatted = f"{hours}h {minutes}m {seconds}s"
        else:
            formatted = f"{minutes}m {seconds}s"

        return {
            "uptime_seconds": uptime_seconds,
            "boot_timestamp": int(boot_time),
            "formatted": formatted
        }

    @classmethod
    def evaluate_system_status(cls, cpu: Dict, mem: Dict, disk: Dict, temp: Dict) -> Dict[str, Any]:
        """Determine overall system health grade and flag potential warnings."""
        warnings: List[str] = []
        is_critical = False

        # Temperature checks
        if temp["status"] == "CRITICAL":
            warnings.append(f"Critical CPU temperature: {temp['celsius']}°C")
            is_critical = True
        elif temp["status"] == "WARNING":
            warnings.append(f"High CPU temperature: {temp['celsius']}°C")

        # Under-voltage or throttling
        throttling = temp.get("throttling", {})
        if throttling.get("under_voltage_detected"):
            warnings.append("Under-voltage power brownout detected on Raspberry Pi")
            is_critical = True
        if throttling.get("currently_throttled"):
            warnings.append("Companion computer is actively throttling")

        # Memory checks
        if mem["usage_percent"] >= settings.RAM_WARNING_THRESHOLD:
            warnings.append(f"High RAM usage: {mem['usage_percent']}%")

        # Disk checks
        if disk["usage_percent"] >= settings.DISK_WARNING_THRESHOLD:
            warnings.append(f"Low disk storage remaining: {disk['usage_percent']}% used")

        if is_critical:
            overall_status = "CRITICAL"
        elif warnings:
            overall_status = "WARNING"
        else:
            overall_status = "HEALTHY"

        return {
            "status": overall_status,
            "healthy": overall_status == "HEALTHY",
            "warnings": warnings,
            "warning_count": len(warnings)
        }

    @classmethod
    def get_full_health(cls, mock_hardware: bool = False) -> Dict[str, Any]:
        """
        Aggregate complete real-time system health telemetry for the companion computer.
        """
        cpu = cls.get_cpu_metrics()
        mem = cls.get_memory_metrics()
        disk = cls.get_disk_metrics()
        temp = TemperatureMonitor.get_temperature()
        uptime = cls.get_uptime_metrics()
        status_eval = cls.evaluate_system_status(cpu, mem, disk, temp)
        hw_summary = HardwareInfo.get_system_summary(mock_if_not_rpi=mock_hardware)

        return {
            "timestamp": time.time(),
            "overall_status": status_eval["status"],
            "healthy": status_eval["healthy"],
            "warnings": status_eval["warnings"],
            "cpu": cpu,
            "memory": mem,
            "disk": disk,
            "temperature": temp,
            "uptime": uptime,
            "hardware": hw_summary
        }
