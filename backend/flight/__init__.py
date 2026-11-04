"""
Flight and Telemetry Subsystem for AUTONOMOUS-DRONE.
Includes MAVLink telemetry bridge and isolated flight controller.
"""
from .mavlink_service import MAVLinkService, mavlink_service

__all__ = ["MAVLinkService", "mavlink_service"]

