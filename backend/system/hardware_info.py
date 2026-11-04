"""
Hardware and Operating System Information Module.
Detects Raspberry Pi 4 hardware, CPU architecture, OS release details,
and provides hardware-independent fallback for development environments.
"""
import os
import platform
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import psutil

from config.logging_config import setup_logging

logger = setup_logging("hardware_info")


class HardwareInfo:
    """Detects and provides detailed hardware and OS specification for companion computers."""

    # Raspberry Pi revision codes mapping (SoC, Model, RAM)
    # References: Raspberry Pi hardware revision documentation
    RPI_REVISION_RAM_MAP = {
        0: "256MB",
        1: "512MB",
        2: "1GB",
        3: "2GB",
        4: "4GB",
        5: "8GB",
        6: "16GB"
    }

    @classmethod
    def is_raspberry_pi(cls) -> bool:
        """Check if the current host is a genuine Raspberry Pi device."""
        if platform.system() != "Linux":
            return False

        # Method 1: Check device tree model
        dt_model_path = Path("/sys/firmware/devicetree/base/model")
        if dt_model_path.exists():
            try:
                model_str = dt_model_path.read_text(encoding="utf-8", errors="ignore")
                if "Raspberry Pi" in model_str:
                    return True
            except Exception:
                pass

        # Method 2: Check /proc/cpuinfo
        cpuinfo_path = Path("/proc/cpuinfo")
        if cpuinfo_path.exists():
            try:
                content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
                if "Raspberry Pi" in content or "BCM2835" in content or "BCM2711" in content:
                    return True
            except Exception:
                pass

        return False

    @classmethod
    def get_rpi_model_from_devicetree(cls) -> Optional[str]:
        """Read device tree model string if available."""
        dt_path = Path("/sys/firmware/devicetree/base/model")
        if dt_path.exists():
            try:
                # Device tree strings can end with null byte
                return dt_path.read_text(encoding="utf-8", errors="ignore").strip().rstrip("\x00")
            except Exception as e:
                logger.debug("Could not read devicetree model: %s", e)
        return None

    @classmethod
    def parse_cpuinfo(cls) -> Dict[str, str]:
        """Parse Linux /proc/cpuinfo for Hardware, Revision, Serial, and Model."""
        info: Dict[str, str] = {}
        cpuinfo_path = Path("/proc/cpuinfo")
        if not cpuinfo_path.exists():
            return info

        try:
            with open(cpuinfo_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if ":" in line:
                        key, val = line.split(":", 1)
                        info[key.strip()] = val.strip()
        except Exception as e:
            logger.debug("Failed to read /proc/cpuinfo: %s", e)

        return info

    @classmethod
    def get_linux_distro_info(cls) -> Dict[str, str]:
        """Parse /etc/os-release to get Linux distribution details."""
        distro = {"name": "Linux", "version": platform.release(), "pretty_name": "Linux"}
        os_release = Path("/etc/os-release")
        if os_release.exists():
            try:
                with open(os_release, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            v = v.strip('"').strip("'")
                            if k == "NAME":
                                distro["name"] = v
                            elif k == "VERSION":
                                distro["version"] = v
                            elif k == "PRETTY_NAME":
                                distro["pretty_name"] = v
            except Exception as e:
                logger.debug("Could not read /etc/os-release: %s", e)
        return distro

    @classmethod
    def get_system_summary(cls, mock_if_not_rpi: bool = False) -> Dict[str, Any]:
        """
        Aggregate complete hardware, OS, and platform information.

        Args:
            mock_if_not_rpi: If True and running on non-Pi, reports simulated Pi 4 specs
                             for offline verification.
        """
        is_rpi = cls.is_raspberry_pi()
        cpuinfo = cls.parse_cpuinfo()
        dt_model = cls.get_rpi_model_from_devicetree()

        if is_rpi:
            hardware_model = dt_model or cpuinfo.get("Model") or "Raspberry Pi 4"
            soc = cpuinfo.get("Hardware", "BCM2711 (Raspberry Pi 4)")
            serial = cpuinfo.get("Serial", "Unknown")
            revision = cpuinfo.get("Revision", "Unknown")
        elif mock_if_not_rpi:
            hardware_model = "Raspberry Pi 4 Model B Rev 1.4 (Simulated)"
            soc = "BCM2711 (Quad-Core Cortex-A72 @ 1.5GHz)"
            serial = "10000000abcdef12"
            revision = "c03114"
        else:
            hardware_model = f"{platform.system()} Host ({platform.machine()})"
            soc = platform.processor() or "Generic Host Processor"
            serial = "N/A (Host System)"
            revision = "N/A"

        # Memory summary
        try:
            mem = psutil.virtual_memory()
            total_ram_gb = round(mem.total / (1024 ** 3), 2)
        except Exception:
            total_ram_gb = 0.0

        # Primary disk summary
        try:
            root_path = "/" if platform.system() != "Windows" else "C:\\"
            disk = psutil.disk_usage(root_path)
            total_disk_gb = round(disk.total / (1024 ** 3), 2)
        except Exception:
            total_disk_gb = 0.0

        os_distro = cls.get_linux_distro_info() if platform.system() == "Linux" else {
            "name": platform.system(),
            "version": platform.release(),
            "pretty_name": f"{platform.system()} {platform.release()}"
        }

        return {
            "is_raspberry_pi": is_rpi,
            "simulated": not is_rpi and mock_if_not_rpi,
            "device": {
                "model": hardware_model,
                "soc": soc,
                "revision": revision,
                "serial_number": serial,
                "hostname": platform.node(),
            },
            "cpu": {
                "architecture": platform.machine(),
                "physical_cores": psutil.cpu_count(logical=False) or 1,
                "logical_cores": psutil.cpu_count(logical=True) or 1,
            },
            "memory": {
                "total_ram_gb": total_ram_gb
            },
            "storage": {
                "total_disk_gb": total_disk_gb
            },
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "distribution": os_distro.get("pretty_name"),
            },
            "python": {
                "version": platform.python_version(),
                "executable": sys.executable,
            }
        }
