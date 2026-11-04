"""
Isolated Flight Controller Subsystem for AUTONOMOUS-DRONE.
Provides explicit, controlled command interfaces to Pixhawk 2.4.8.

SAFETY & ISOLATION MANDATES:
1. Disabled by default in settings (`FLIGHT_CONTROL_ENABLED = False`).
2. Completely isolated: never triggered as a side effect of QR detection,
   telemetry polling, mission management, or page loading.
3. No automatic arming.
4. Does NOT bypass or override Pixhawk firmware safety checks or pre-arm failsafes.
5. Does NOT inject arbitrary application-level arming permission gates.
"""
import time
from datetime import datetime
import threading
from typing import Dict, Any, List, Optional

from config.settings import settings
from config.logging_config import setup_logging
from backend.flight.mavlink_service import mavlink_service

logger = setup_logging("flight_controller")

SUPPORTED_FLIGHT_MODES = [
    "STABILIZE",
    "ALT_HOLD",
    "LOITER",
    "GUIDED",
    "AUTO",
    "RTL",
    "LAND",
    "BRAKE",
    "POSHOLD"
]


class FlightController:
    """
    Explicit, isolated interface for flight mode changes, arming, takeoff, and RTL.
    Safe against unauthorized execution via disabled-by-default switch.
    """

    def __init__(self, enabled: Optional[bool] = None):
        self.enabled = enabled if enabled is not None else settings.FLIGHT_CONTROL_ENABLED
        self._lock = threading.Lock()
        self._command_history: List[Dict[str, Any]] = []

    def get_status(self) -> Dict[str, Any]:
        """Return operational state, safety lock status, and vehicle mode."""
        snap = mavlink_service.get_snapshot()
        with self._lock:
            return {
                "flight_control_enabled": self.enabled,
                "connected": snap.connected,
                "armed": snap.armed,
                "flight_mode": snap.flight_mode,
                "altitude_m": snap.altitude_relative_m,
                "battery_percent": snap.battery_remaining_percent,
                "supported_modes": SUPPORTED_FLIGHT_MODES,
                "command_count": len(self._command_history)
            }

    def _record_command(self, cmd_name: str, params: Dict[str, Any], success: bool, message: str) -> None:
        """Log command attempt and outcome into circular audit log."""
        entry = {
            "timestamp": time.time(),
            "iso_time": datetime.now().isoformat(),
            "command": cmd_name,
            "params": params,
            "success": success,
            "message": message
        }
        with self._lock:
            self._command_history.insert(0, entry)
            if len(self._command_history) > 100:
                self._command_history.pop()

    def request_arm(self, arm: bool = True) -> Dict[str, Any]:
        """
        Send arm or disarm request to Pixhawk flight controller.
        Firmware pre-arm safety checks are evaluated on the flight controller itself.
        """
        action = "ARM" if arm else "DISARM"
        params = {"arm": arm}

        if not self.enabled:
            msg = f"Flight control is disabled by default. Enable FLIGHT_CONTROL_ENABLED to allow {action} commands."
            logger.warning(msg)
            self._record_command(action, params, False, msg)
            return {"success": False, "code": "CONTROL_DISABLED", "message": msg}

        snap = mavlink_service.get_snapshot()
        if not snap.connected:
            msg = f"Cannot {action}: No active MAVLink telemetry heartbeat connection"
            logger.error(msg)
            self._record_command(action, params, False, msg)
            return {"success": False, "code": "NOT_CONNECTED", "message": msg}

        # Issue command through MAVLink
        if snap.is_simulated:
            with mavlink_service._lock:
                mavlink_service._armed = arm
                mavlink_service._system_status = "ACTIVE" if arm else "STANDBY"
            msg = f"Simulated Pixhawk successfully {action}ED"
            logger.info(msg)
            self._record_command(action, params, True, msg)
            return {"success": True, "message": msg}

        # Real hardware command
        try:
            from pymavlink import mavutil
            conn = mavlink_service._mav_connection
            if not conn:
                raise RuntimeError("MAVLink connection handle not available")

            # MAV_CMD_COMPONENT_ARM_DISARM: param1=1 to arm, 0 to disarm
            conn.mav.command_long_send(
                conn.target_system,
                conn.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                1.0 if arm else 0.0,
                0, 0, 0, 0, 0, 0
            )
            msg = f"Sent MAVLink {action} command to Pixhawk (target_system={conn.target_system})"
            logger.info(msg)
            self._record_command(action, params, True, msg)
            return {"success": True, "message": msg}
        except Exception as e:
            err = f"Failed sending MAVLink {action} command: {e}"
            logger.error(err)
            self._record_command(action, params, False, err)
            return {"success": False, "code": "COMMUNICATION_ERROR", "message": err}

    def request_mode(self, mode: str) -> Dict[str, Any]:
        """Request vehicle flight mode transition (e.g. GUIDED, LOITER, RTL)."""
        mode_upper = mode.strip().upper()
        params = {"mode": mode_upper}

        if not self.enabled:
            msg = f"Flight control is disabled. Cannot change mode to {mode_upper}."
            self._record_command("SET_MODE", params, False, msg)
            return {"success": False, "code": "CONTROL_DISABLED", "message": msg}

        if mode_upper not in SUPPORTED_FLIGHT_MODES:
            msg = f"Unsupported mode '{mode_upper}'. Allowed: {SUPPORTED_FLIGHT_MODES}"
            self._record_command("SET_MODE", params, False, msg)
            return {"success": False, "code": "INVALID_MODE", "message": msg}

        snap = mavlink_service.get_snapshot()
        if not snap.connected:
            msg = f"Cannot set mode to {mode_upper}: Flight controller not connected"
            self._record_command("SET_MODE", params, False, msg)
            return {"success": False, "code": "NOT_CONNECTED", "message": msg}

        if snap.is_simulated:
            with mavlink_service._lock:
                mavlink_service._flight_mode = mode_upper
            msg = f"Simulated mode switched to {mode_upper}"
            logger.info(msg)
            self._record_command("SET_MODE", params, True, msg)
            return {"success": True, "message": msg, "flight_mode": mode_upper}

        try:
            conn = mavlink_service._mav_connection
            mode_id = conn.mode_mapping().get(mode_upper)
            if mode_id is None:
                raise ValueError(f"Mode mapping not found for {mode_upper}")

            conn.set_mode(mode_id)
            msg = f"Requested Pixhawk flight mode {mode_upper} (ID: {mode_id})"
            logger.info(msg)
            self._record_command("SET_MODE", params, True, msg)
            return {"success": True, "message": msg, "flight_mode": mode_upper}
        except Exception as e:
            err = f"Failed setting flight mode to {mode_upper}: {e}"
            logger.error(err)
            self._record_command("SET_MODE", params, False, err)
            return {"success": False, "code": "MODE_CHANGE_FAILED", "message": err}

    def request_takeoff(self, altitude_m: float) -> Dict[str, Any]:
        """Request autonomous takeoff to a specified relative altitude."""
        params = {"altitude_m": altitude_m}

        if not self.enabled:
            msg = "Flight control is disabled. Cannot execute takeoff."
            self._record_command("TAKEOFF", params, False, msg)
            return {"success": False, "code": "CONTROL_DISABLED", "message": msg}

        if altitude_m < 1.0 or altitude_m > 100.0:
            msg = f"Takeoff altitude {altitude_m}m outside safe operating window (1.0m to 100.0m)"
            self._record_command("TAKEOFF", params, False, msg)
            return {"success": False, "code": "INVALID_ALTITUDE", "message": msg}

        snap = mavlink_service.get_snapshot()
        if not snap.connected:
            msg = "Cannot takeoff: Flight controller not connected"
            self._record_command("TAKEOFF", params, False, msg)
            return {"success": False, "code": "NOT_CONNECTED", "message": msg}

        if snap.is_simulated:
            with mavlink_service._lock:
                mavlink_service._armed = True
                mavlink_service._flight_mode = "GUIDED"
                mavlink_service._alt_rel = altitude_m
            msg = f"Simulated takeoff initiated to {altitude_m:.1f}m altitude"
            logger.info(msg)
            self._record_command("TAKEOFF", params, True, msg)
            return {"success": True, "message": msg}

        try:
            from pymavlink import mavutil
            conn = mavlink_service._mav_connection
            conn.mav.command_long_send(
                conn.target_system,
                conn.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0,
                0, 0, 0, 0, 0, 0,
                altitude_m
            )
            msg = f"Sent takeoff command to {altitude_m:.1f}m"
            logger.info(msg)
            self._record_command("TAKEOFF", params, True, msg)
            return {"success": True, "message": msg}
        except Exception as e:
            err = f"Failed issuing takeoff command: {e}"
            logger.error(err)
            self._record_command("TAKEOFF", params, False, err)
            return {"success": False, "code": "COMMAND_ERROR", "message": err}

    def request_rtl(self) -> Dict[str, Any]:
        """Request Return-to-Launch (RTL)."""
        return self.request_mode("RTL")

    def request_land(self) -> Dict[str, Any]:
        """Request vehicle auto land."""
        return self.request_mode("LAND")

    def get_command_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return history of issued flight commands."""
        with self._lock:
            return list(self._command_history[:limit])


# Global singleton instance (default disabled per safety requirements)
flight_controller = FlightController()

