"""
Hardware Camera Detector for Sony IMX477 and Video Devices.
Detects CSI-2 connected IMX477 on Raspberry Pi 4, V4L2 devices, and available video backends.
"""
import glob
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from config.logging_config import setup_logging

logger = setup_logging("camera_detector")


class CameraDetector:
    """Discovers connected camera hardware and determines optimal camera backend."""

    IMX477_SENSOR_NAMES = ["imx477", "imx477r", "sony-imx477"]

    @classmethod
    def check_libcamera_available(cls) -> bool:
        """Check if libcamera / rpicam tools are installed on Linux host."""
        if platform.system() != "Linux":
            return False
        for cmd in ["rpicam-hello", "libcamera-hello"]:
            try:
                res = subprocess.run([cmd, "--version"], capture_output=True, timeout=2, check=False)
                if res.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    @classmethod
    def list_libcamera_devices(cls) -> List[Dict[str, Any]]:
        """Query rpicam-hello or libcamera-hello for connected CSI camera sensors."""
        devices = []
        if platform.system() != "Linux":
            return devices

        for cmd in ["rpicam-hello", "libcamera-hello"]:
            try:
                res = subprocess.run(
                    [cmd, "--list-cameras"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False
                )
                if res.returncode == 0:
                    output = res.stdout + "\n" + res.stderr
                    # Output format example:
                    # 0 : imx477 [4056x3040] (/base/soc/i2c0mux/i2c@1/imx477@1a)
                    #     Modes: 'SRGGB10_CSI2P' : 1332x990 ...
                    lines = output.splitlines()
                    for line in lines:
                        line_stripped = line.strip()
                        if ":" in line_stripped and any(sens in line_stripped.lower() for sens in ["imx", "ov", "camera"]):
                            is_imx477 = any(s in line_stripped.lower() for s in cls.IMX477_SENSOR_NAMES)
                            devices.append({
                                "raw_info": line_stripped,
                                "is_imx477": is_imx477,
                                "sensor": "Sony IMX477 (HQ Camera)" if is_imx477 else "Generic CSI Sensor",
                                "source": cmd
                            })
                    if devices:
                        break
            except Exception as e:
                logger.debug("Failed checking %s: %s", cmd, e)

        return devices

    @classmethod
    def list_v4l2_devices(cls) -> List[str]:
        """List /dev/video* devices on Linux."""
        if platform.system() != "Linux":
            return []
        return sorted(glob.glob("/dev/video*"))

    @classmethod
    def detect_camera_hardware(cls) -> Dict[str, Any]:
        """
        Comprehensive probe of connected camera hardware.
        Returns sensor type, connection state, and recommended backend.
        """
        is_linux = platform.system() == "Linux"
        libcamera_installed = cls.check_libcamera_available()
        libcamera_devs = cls.list_libcamera_devices()
        v4l2_devs = cls.list_v4l2_devices()

        has_imx477 = any(dev["is_imx477"] for dev in libcamera_devs)

        if has_imx477:
            status = "CONNECTED"
            model_name = "Sony IMX477 High Quality Camera"
            recommended_backend = "libcamera"
        elif libcamera_devs:
            status = "CONNECTED"
            model_name = libcamera_devs[0].get("sensor", "CSI Camera")
            recommended_backend = "libcamera"
        elif v4l2_devs:
            status = "CONNECTED"
            model_name = f"V4L2 Video Device ({v4l2_devs[0]})"
            recommended_backend = "opencv"
        else:
            # Check OpenCV device 0 availability on development host
            opencv_available = False
            try:
                import cv2
                cap = cv2.VideoCapture(0)
                if cap.isOpened():
                    opencv_available = True
                    cap.release()
            except Exception:
                pass

            if opencv_available:
                status = "CONNECTED"
                model_name = "Host Video Device (OpenCV)"
                recommended_backend = "opencv"
            else:
                status = "DISCONNECTED"
                model_name = "No physical camera detected (Mock Mode)"
                recommended_backend = "mock"

        return {
            "connected": status == "CONNECTED",
            "is_imx477": has_imx477,
            "camera_model": model_name,
            "recommended_backend": recommended_backend,
            "libcamera_available": libcamera_installed,
            "libcamera_devices": libcamera_devs,
            "v4l2_devices": v4l2_devs,
            "platform": platform.system()
        }
