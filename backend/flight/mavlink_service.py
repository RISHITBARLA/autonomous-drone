"""
MAVLink Telemetry Bridge for Pixhawk 2.4.8 and S500 Quadcopter.
Provides read-only telemetry acquisition, heartbeat monitoring, stale-data detection,
and dual-mode execution (physical serial/UDP MAVLink or high-fidelity simulated telemetry).

SAFETY CONSTRAINT:
This module is strictly read-only. No flight control, arming, or movement commands are
issued by this subsystem.
"""
import math
import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from config.settings import settings
from config.logging_config import setup_logging

logger = setup_logging("mavlink_service")


# Mapping of ArduPilot / PX4 custom mode numbers to human-readable strings
COPTER_MODES = {
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


@dataclass
class TelemetrySnapshot:
    """Thread-safe immutable representation of current vehicle telemetry state."""
    timestamp: float
    iso_time: str
    connected: bool
    is_simulated: bool
    is_stale: bool
    heartbeat_age_seconds: float
    flight_mode: str
    armed: bool
    system_status: str

    # GPS & Navigation
    latitude: float
    longitude: float
    altitude_relative_m: float
    altitude_msl_m: float
    gps_fix_type: int  # 0=No GPS, 1=No Fix, 2=2D, 3=3D, 4=DGPS, 5=RTK Float, 6=RTK Fixed
    gps_fix_name: str
    satellites_visible: int
    hdop: float

    # Flight Dynamics & HUD
    heading_deg: float
    groundspeed_m_s: float
    airspeed_m_s: float
    climb_rate_m_s: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float

    # Power & Battery
    battery_voltage_v: float
    battery_current_a: float
    battery_remaining_percent: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MAVLinkService:
    """
    Manages telemetry communication with Pixhawk flight controller via MAVLink.
    Thread-safe, handles connection drops, and reports stale indicators.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        baudrate: Optional[int] = None,
        heartbeat_timeout: Optional[float] = None,
        simulate: Optional[bool] = None
    ):
        self.connection_string = connection_string or settings.MAVLINK_CONNECTION_STRING
        self.baudrate = baudrate or settings.MAVLINK_BAUDRATE
        self.heartbeat_timeout = heartbeat_timeout or settings.MAVLINK_HEARTBEAT_TIMEOUT
        self.simulate = simulate if simulate is not None else settings.MAVLINK_SIMULATE

        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._mav_connection: Any = None

        # Telemetry State variables
        self._connected = False
        self._last_heartbeat = 0.0
        self._flight_mode = "DISCONNECTED"
        self._armed = False
        self._system_status = "STANDBY"

        self._lat = 0.0
        self._lon = 0.0
        self._alt_rel = 0.0
        self._alt_msl = 0.0
        self._gps_fix = 0
        self._satellites = 0
        self._hdop = 99.9

        self._heading = 0.0
        self._groundspeed = 0.0
        self._airspeed = 0.0
        self._climb_rate = 0.0
        self._roll = 0.0
        self._pitch = 0.0
        self._yaw = 0.0

        self._battery_voltage = 0.0
        self._battery_current = 0.0
        self._battery_percent = 0

        # Simulation step counter
        self._sim_step = 0

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> bool:
        """Start background telemetry collection thread."""
        with self._lock:
            if self._running:
                return True
            self._running = True
            if self.simulate:
                self._connected = True
                self._last_heartbeat = time.time()
                self._flight_mode = "LOITER"
                self._armed = True
                self._system_status = "ACTIVE"
                self._lat = 37.4093
                self._lon = -122.0641
                self._alt_rel = 18.5
                self._gps_fix = 3
                self._satellites = 14
                self._battery_voltage = 15.4
                self._battery_percent = 95

            self._worker_thread = threading.Thread(
                target=self._telemetry_worker,
                name="MAVLinkTelemetryWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("MAVLink telemetry service started (simulate=%s, connection=%s)", self.simulate, self.connection_string)
            return True

    def stop(self) -> bool:
        """Stop background telemetry thread safely."""
        with self._lock:
            if not self._running:
                return True
            self._running = False

        if self._mav_connection:
            try:
                self._mav_connection.close()
            except Exception:
                pass
            self._mav_connection = None

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        with self._lock:
            self._connected = False

        try:
            logger.info("MAVLink telemetry service stopped")
        except Exception:
            pass
        return True

    def _telemetry_worker(self) -> None:
        """Main worker loop: selects simulated telemetry or physical MAVLink stream."""
        if self.simulate:
            self._run_simulated_stream()
        else:
            self._run_mavlink_stream()

    def _run_simulated_stream(self) -> None:
        """Generate high-fidelity, physics-consistent quadcopter telemetry for offline testing."""
        # Baseline starting coordinate: S500 drone test field (San Francisco Bay / Moffett Field coordinates)
        base_lat = 37.4093
        base_lon = -122.0641
        base_alt = 18.5

        logger.info("Running simulated MAVLink telemetry engine")
        while self.is_running:
            self._sim_step += 1
            t = self._sim_step * 0.1

            with self._lock:
                self._connected = True
                self._last_heartbeat = time.time()
                if self._flight_mode in ("DISCONNECTED", "OFFLINE"):
                    self._flight_mode = "LOITER"
                self._system_status = "ACTIVE" if self._armed else "STANDBY"

                # Orbital waypoint drift pattern
                radius = 0.0004
                self._lat = base_lat + radius * math.cos(t * 0.1)
                self._lon = base_lon + radius * math.sin(t * 0.1)
                if abs(self._alt_rel - base_alt) <= 2.0 or self._alt_rel == 0.0:
                    self._alt_rel = round(base_alt + 1.2 * math.sin(t * 0.2), 2)
                self._alt_msl = round(self._alt_rel + 12.0, 2)
                self._gps_fix = 3  # 3D Fix
                self._satellites = 14
                self._hdop = 0.85

                self._heading = round((t * 5.7) % 360.0, 1)
                self._groundspeed = round(2.8 + 0.5 * math.sin(t * 0.3), 2)
                self._airspeed = self._groundspeed
                self._climb_rate = round(0.2 * math.cos(t * 0.2), 2)
                self._roll = round(2.5 * math.sin(t * 0.4), 1)
                self._pitch = round(1.8 * math.cos(t * 0.3), 1)
                self._yaw = self._heading

                # Gradual nominal 4S LiPo discharge
                self._battery_voltage = round(15.4 - (self._sim_step * 0.0002), 2)
                self._battery_current = round(12.5 + 2.0 * math.sin(t), 1)
                self._battery_percent = max(10, int(round((self._battery_voltage - 14.0) / (16.8 - 14.0) * 100)))

            time.sleep(0.1)  # 10 Hz telemetry rate

    def _run_mavlink_stream(self) -> None:
        """Physical MAVLink connection receiver with automatic reconnect on failure."""
        while self.is_running:
            try:
                # 1. Establish connection if not already open
                if not self._mav_connection:
                    logger.info("Attempting MAVLink connection to %s (baud: %d)", self.connection_string, self.baudrate)
                    try:
                        from pymavlink import mavutil
                        self._mav_connection = mavutil.mavlink_connection(
                            self.connection_string,
                            baud=self.baudrate,
                            autoreconnect=True,
                            timeout=2.0
                        )
                    except Exception as e:
                        logger.warning("MAVLink connection attempt failed: %s; falling back to simulated stream", e)
                        self.simulate = True
                        self._run_simulated_stream()
                        return

                # 2. Wait for messages
                msg = self._mav_connection.recv_match(blocking=True, timeout=1.0)
                if msg is None:
                    continue

                msg_type = msg.get_type()
                now = time.time()

                if msg_type == "HEARTBEAT":
                    with self._lock:
                        self._connected = True
                        self._last_heartbeat = now
                        custom_mode = getattr(msg, "custom_mode", 0)
                        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
                        # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
                        base_mode = getattr(msg, "base_mode", 0)
                        self._armed = bool(base_mode & 128)
                        self._system_status = "ACTIVE" if self._armed else "STANDBY"

                elif msg_type == "GLOBAL_POSITION_INT":
                    with self._lock:
                        self._lat = msg.lat / 1e7
                        self._lon = msg.lon / 1e7
                        self._alt_rel = round(msg.relative_alt / 1000.0, 2)
                        self._alt_msl = round(msg.alt / 1000.0, 2)
                        self._heading = round(msg.hdg / 100.0, 1)

                elif msg_type == "GPS_RAW_INT":
                    with self._lock:
                        self._gps_fix = getattr(msg, "fix_type", 0)
                        self._satellites = getattr(msg, "satellites_visible", 0)
                        self._hdop = round(getattr(msg, "eph", 9999) / 100.0, 2)

                elif msg_type == "VFR_HUD":
                    with self._lock:
                        self._airspeed = round(getattr(msg, "airspeed", 0.0), 2)
                        self._groundspeed = round(getattr(msg, "groundspeed", 0.0), 2)
                        self._climb_rate = round(getattr(msg, "climb", 0.0), 2)

                elif msg_type == "ATTITUDE":
                    with self._lock:
                        self._roll = round(math.degrees(getattr(msg, "roll", 0.0)), 1)
                        self._pitch = round(math.degrees(getattr(msg, "pitch", 0.0)), 1)
                        self._yaw = round(math.degrees(getattr(msg, "yaw", 0.0)), 1)

                elif msg_type == "SYS_STATUS":
                    with self._lock:
                        voltage = getattr(msg, "voltage_battery", 0) / 1000.0
                        current = getattr(msg, "current_battery", 0) / 100.0
                        percent = getattr(msg, "battery_remaining", -1)
                        if voltage > 0:
                            self._battery_voltage = round(voltage, 2)
                            self._battery_current = round(current, 2)
                            self._battery_percent = max(0, min(100, percent))

            except Exception as e:
                logger.error("Error receiving MAVLink packet: %s", e)
                with self._lock:
                    self._connected = False
                time.sleep(1.0)

    def get_snapshot(self) -> TelemetrySnapshot:
        """Generate a thread-safe telemetry snapshot."""
        now = time.time()
        with self._lock:
            hb_age = round(now - self._last_heartbeat, 2) if self._last_heartbeat > 0 else 999.0
            is_stale = hb_age > self.heartbeat_timeout
            is_connected = self._connected and not is_stale

            fix_names = {
                0: "No GPS",
                1: "No Fix",
                2: "2D Fix",
                3: "3D Fix",
                4: "DGPS",
                5: "RTK Float",
                6: "RTK Fixed"
            }
            fix_name = fix_names.get(self._gps_fix, "Unknown")

            return TelemetrySnapshot(
                timestamp=now,
                iso_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                connected=is_connected,
                is_simulated=self.simulate,
                is_stale=is_stale,
                heartbeat_age_seconds=hb_age,
                flight_mode=self._flight_mode if is_connected else "DISCONNECTED",
                armed=self._armed if is_connected else False,
                system_status=self._system_status if is_connected else "OFFLINE",
                latitude=self._lat,
                longitude=self._lon,
                altitude_relative_m=self._alt_rel,
                altitude_msl_m=self._alt_msl,
                gps_fix_type=self._gps_fix,
                gps_fix_name=fix_name,
                satellites_visible=self._satellites,
                hdop=self._hdop,
                heading_deg=self._heading,
                groundspeed_m_s=self._groundspeed,
                airspeed_m_s=self._airspeed,
                climb_rate_m_s=self._climb_rate,
                roll_deg=self._roll,
                pitch_deg=self._pitch,
                yaw_deg=self._yaw,
                battery_voltage_v=self._battery_voltage,
                battery_current_a=self._battery_current,
                battery_remaining_percent=self._battery_percent
            )

    def set_connection(self, connection_string: str, baudrate: int = 57600, simulate: bool = False) -> None:
        """Dynamically update connection parameters and trigger reconnect."""
        self.stop()
        with self._lock:
            self.connection_string = connection_string
            self.baudrate = baudrate
            self.simulate = simulate
            self._last_heartbeat = 0.0
            self._connected = False
        self.start()


# Global singleton instance
mavlink_service = MAVLinkService()
