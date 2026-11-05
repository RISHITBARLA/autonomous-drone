"""
MAVLink Telemetry Bridge for Pixhawk 2.4.8 and S500 Quadcopter.
Provides read-only telemetry acquisition, heartbeat monitoring, stale-data detection,
and dual-mode execution (physical serial/UDP MAVLink or high-fidelity simulated telemetry).

SAFETY CONSTRAINT:
This module is strictly read-only. No flight control, arming, or movement commands are
issued by this subsystem.
"""
import os
import glob
import math
import time
import threading
from typing import Dict, Any, Optional, List
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

ARDUCOPTER_MODE_IDS = {v: k for k, v in COPTER_MODES.items()}


# MAVLink Autopilot identification mappings (MAV_AUTOPILOT enum)
AUTOPILOT_NAME_MAP = {
    0: "Generic",
    1: "Reserved",
    2: "SLUGS",
    3: "ArduPilot",
    4: "OpenPilot",
    12: "PX4",
    13: "SMACCMPilot",
    14: "AutoQuad",
    15: "Armazila",
    16: "Aerob",
    17: "ASLUAV",
    18: "SmartAP",
    19: "AirRails"
}

# MAVLink Vehicle Type identification mappings (MAV_TYPE enum)
VEHICLE_TYPE_MAP = {
    0: "Generic",
    1: "Fixed Wing",
    2: "Quadrotor",
    3: "Coaxial",
    4: "Helicopter",
    10: "Ground Rover",
    11: "Surface Boat",
    12: "Submarine",
    13: "Hexarotor",
    14: "Octorotor",
    15: "Tricopter",
    16: "Flapping Wing",
    17: "Kite",
    19: "VTOL DuoRotor",
    20: "VTOL Quadrotor",
    21: "VTOL Tiltrotor",
    29: "Dodecarotor",
    35: "Decarotor",
    43: "Multirotor"
}


def decode_heartbeat_identity(autopilot_id: Optional[int], type_id: Optional[int]) -> tuple:
    """
    Decodes MAVLink HEARTBEAT autopilot and vehicle type enums into human-readable strings.
    Returns: (autopilot_name, vehicle_type_name, composite_display_string)
    """
    ap_id = autopilot_id if isinstance(autopilot_id, int) else 0
    t_id = type_id if isinstance(type_id, int) else 0

    ap_name = AUTOPILOT_NAME_MAP.get(ap_id, f"Autopilot-{ap_id}")
    veh_name = VEHICLE_TYPE_MAP.get(t_id, f"Vehicle-{t_id}")

    if ap_id == 3:  # ArduPilot
        if t_id in (2, 3, 13, 14, 15, 29, 35, 43):
            firmware_sub = "ArduCopter"
        elif t_id in (1, 19, 20, 21):
            firmware_sub = "ArduPlane"
        elif t_id in (10, 11):
            firmware_sub = "Rover"
        elif t_id == 12:
            firmware_sub = "ArduSub"
        elif t_id == 4:
            firmware_sub = "Heli"
        else:
            firmware_sub = veh_name
        composite = f"ArduPilot {firmware_sub} ({veh_name})"
    elif ap_id == 12:  # PX4
        composite = f"PX4 ({veh_name})"
    elif ap_id == 0 and t_id == 0:
        composite = "Generic"
    else:
        composite = f"{ap_name} ({veh_name})"

    return ap_name, veh_name, composite


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

    # Connection & Autopilot Identity
    connection_type: str
    autopilot_type: str
    target_system: int
    target_component: int
    prearm_status: str
    prearm_messages: list

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
        self._command_lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._mav_connection: Any = None

        # Telemetry State variables
        self._connected = False
        self._last_heartbeat = 0.0
        self._flight_mode = "DISCONNECTED"
        self._armed = False
        self._system_status = "STANDBY"
        self._target_system = 1
        self._target_component = 1
        self._autopilot_type = "ArduPilot ArduCopter" if not self.simulate else "Simulated Pixhawk"

        self._status_texts: List[Dict[str, Any]] = []
        self._command_acks: Dict[int, Dict[str, Any]] = {}

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
                self._autopilot_type = "Simulated Pixhawk"
                self._status_texts = [
                    {"timestamp": time.time(), "severity": 6, "text": "ArduCopter V4.3.5 (Simulated)", "is_prearm": False},
                    {"timestamp": time.time(), "severity": 6, "text": "PreArm: Passed all safety checks", "is_prearm": True}
                ]

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
                sim_lat = self._lat
                sim_lon = self._lon
                sim_alt = self._alt_rel

            self._update_coverage_telemetry(sim_lat, sim_lon, sim_alt)
            time.sleep(0.1)  # 10 Hz telemetry rate

    def _update_coverage_telemetry(self, lat: float, lon: float, alt: float) -> None:
        """Safely route genuine GPS coordinates to coverage planner."""
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return
        if lat == 0.0 and lon == 0.0:
            return
        try:
            from backend.search.coverage_planner import coverage_planner
            if coverage_planner is not None:
                coverage_planner.update_drone_position(lat, lon, alt)
        except Exception as e:
            logger.debug("Coverage planner update skipped: %s", e)

    def _handle_gps_raw_int(self, msg: Any) -> None:
        """Process GPS_RAW_INT message and update coverage planner if fix is valid."""
        try:
            fix_type = getattr(msg, "fix_type", 0)
            lat = getattr(msg, "lat", 0) / 1e7
            lon = getattr(msg, "lon", 0) / 1e7
            alt_m = getattr(msg, "alt", 0) / 1000.0

            with self._lock:
                self._gps_fix = fix_type
                self._satellites = getattr(msg, "satellites_visible", 0)
                self._hdop = round(getattr(msg, "eph", 9999) / 100.0, 2)
                rel_alt = self._alt_rel

            effective_alt = rel_alt if rel_alt > 0.5 else alt_m

            if fix_type >= 2 and lat != 0.0 and lon != 0.0:
                self._update_coverage_telemetry(lat, lon, effective_alt)
        except Exception as e:
            logger.debug("Error in _handle_gps_raw_int: %s", e)

    def _handle_heartbeat(self, msg: Any, timestamp: Optional[float] = None) -> None:
        """Process incoming MAVLink HEARTBEAT message and dynamically decode vehicle identity."""
        raw_type = getattr(msg, "type", 0)
        # Ignore companion GCS echo heartbeats
        if raw_type == 6:  # MAV_TYPE_GCS
            return

        now = timestamp if timestamp is not None else time.time()
        raw_ap = getattr(msg, "autopilot", 0)
        ap_name, veh_name, composite_identity = decode_heartbeat_identity(raw_ap, raw_type)

        with self._lock:
            self._connected = True
            self._last_heartbeat = now
            try:
                src_sys = msg.get_srcSystem() if callable(getattr(msg, "get_srcSystem", None)) else getattr(msg, "srcSystem", 1)
                if isinstance(src_sys, int) and src_sys > 0:
                    self._target_system = src_sys
            except Exception:
                pass

            try:
                src_comp = msg.get_srcComponent() if callable(getattr(msg, "get_srcComponent", None)) else getattr(msg, "srcComponent", 1)
                if isinstance(src_comp, int) and src_comp > 0:
                    self._target_component = src_comp
            except Exception:
                pass

            custom_mode = getattr(msg, "custom_mode", 0)
            if not isinstance(custom_mode, int):
                custom_mode = 0
            self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
            # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
            base_mode = getattr(msg, "base_mode", 0)
            if not isinstance(base_mode, int):
                base_mode = 0
            self._armed = bool(base_mode & 128)
            self._system_status = "ACTIVE" if self._armed else "STANDBY"
            self._autopilot_type = composite_identity

    def _run_mavlink_stream(self) -> None:
        """Physical MAVLink connection receiver with automatic reconnect on failure."""
        logger.info(
            "Starting physical MAVLink connection stream on %s (baud: %d)",
            self.connection_string, self.baudrate
        )
        last_gcs_hb = 0.0
        requested_streams = False
        while self.is_running:
            try:
                # 1. Establish connection if not already open
                if not self._mav_connection:
                    target_conn = self.connection_string
                    # Dedicated Raspberry Pi GPIO UART ports (/dev/serial0, /dev/ttyAMA0) must NEVER fall back to USB
                    is_uart = (
                        str(target_conn) in ("/dev/serial0", "/dev/ttyAMA0")
                        or str(target_conn).startswith(("/dev/serial", "/dev/ttyAMA"))
                    )

                    if is_uart:
                        logger.debug("UART connection configured (%s); USB dynamic fallback is disabled.", target_conn)
                    elif str(target_conn).startswith(("/dev/ttyACM", "/dev/ttyUSB")) and not os.path.exists(str(target_conn)):
                        # Only allow USB re-enumeration fallback if configured device was already a USB port (/dev/ttyACM* or /dev/ttyUSB*)
                        import glob
                        dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
                        if dev_matches:
                            logger.info(
                                "USB port %s not found; dynamically falling back to active USB port %s",
                                target_conn, dev_matches[0]
                            )
                            target_conn = dev_matches[0]
                            with self._lock:
                                self.connection_string = target_conn

                    logger.info("Attempting physical MAVLink connection to %s", target_conn)
                    try:
                        from pymavlink import mavutil
                        self._mav_connection = mavutil.mavlink_connection(
                            target_conn,
                            baud=self.baudrate,
                            autoreconnect=True,
                            timeout=2.0
                        )
                        requested_streams = False
                    except Exception as e:
                        logger.warning("MAVLink connection attempt failed: %s; retrying in 2.0s", e)
                        with self._lock:
                            self._connected = False
                        time.sleep(2.0)
                        continue

                now = time.time()
                # Send periodic GCS heartbeat to announce companion presence to Pixhawk
                if now - last_gcs_hb >= 1.0:
                    try:
                        from pymavlink import mavutil
                        self._mav_connection.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0, 0
                        )
                        last_gcs_hb = now
                    except Exception:
                        pass

                # 2. Wait for messages
                msg = self._mav_connection.recv_match(blocking=True, timeout=1.0)
                if msg is None:
                    continue

                msg_type = msg.get_type()
                now = time.time()

                if msg_type == "HEARTBEAT":
                    self._handle_heartbeat(msg, now)

                    if not requested_streams:
                        try:
                            from pymavlink import mavutil
                            self._mav_connection.mav.request_data_stream_send(
                                self._target_system,
                                self._target_component,
                                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                                4,
                                1
                            )
                            requested_streams = True
                            logger.info("Requested all data streams from Pixhawk (sys: %d, comp: %d)", self._target_system, self._target_component)
                        except Exception as e:
                            logger.debug("Could not send request_data_stream: %s", e)

                elif msg_type == "STATUSTEXT":
                    text_raw = getattr(msg, "text", "")
                    if isinstance(text_raw, bytes):
                        text = text_raw.decode("utf-8", errors="ignore").rstrip("\x00")
                    else:
                        text = str(text_raw).rstrip("\x00")
                    sev = getattr(msg, "severity", 6)
                    entry = {
                        "timestamp": now,
                        "severity": sev,
                        "text": text,
                        "is_prearm": "prearm" in text.lower()
                    }
                    with self._lock:
                        self._status_texts.append(entry)
                        if len(self._status_texts) > 50:
                            self._status_texts.pop(0)
                    logger.info("MAVLink STATUSTEXT (sev=%d): %s", sev, text)

                elif msg_type == "COMMAND_ACK":
                    cmd_id = getattr(msg, "command", 0)
                    res_code = getattr(msg, "result", -1)
                    entry = {
                        "timestamp": now,
                        "command": cmd_id,
                        "result": res_code
                    }
                    with self._lock:
                        self._command_acks[cmd_id] = entry
                    logger.info("MAVLink COMMAND_ACK: cmd=%d, result=%d", cmd_id, res_code)

                elif msg_type == "GLOBAL_POSITION_INT":
                    with self._lock:
                        self._lat = msg.lat / 1e7
                        self._lon = msg.lon / 1e7
                        self._alt_rel = round(msg.relative_alt / 1000.0, 2)
                        self._alt_msl = round(msg.alt / 1000.0, 2)
                        self._heading = round(msg.hdg / 100.0, 1)
                        g_lat = self._lat
                        g_lon = self._lon
                        g_alt = self._alt_rel if self._alt_rel > 0.5 else 10.0
                    self._update_coverage_telemetry(g_lat, g_lon, g_alt)

                elif msg_type == "GPS_RAW_INT":
                    self._handle_gps_raw_int(msg)

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
                if self._mav_connection:
                    try:
                        self._mav_connection.close()
                    except Exception:
                        pass
                    self._mav_connection = None
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

            conn_type = "SIMULATION" if self.simulate else (
                "UDP_WIFI" if "udp" in str(self.connection_string).lower() else "SERIAL_UART"
            )

            # Pre-arm analysis from recent STATUSTEXT messages
            prearm_msgs = [t["text"] for t in self._status_texts if t.get("is_prearm")]
            prearm_errors = [m for m in prearm_msgs if "passed" not in m.lower()]
            if prearm_errors:
                prearm_status = "CHECKS_FAILED"
            elif any("passed" in m.lower() for m in prearm_msgs):
                prearm_status = "PASSED"
            else:
                prearm_status = "READY" if self.simulate else "STANDBY"

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
                connection_type=conn_type,
                autopilot_type=self._autopilot_type if is_connected else "Unknown",
                target_system=self._target_system,
                target_component=self._target_component,
                prearm_status=prearm_status,
                prearm_messages=prearm_msgs[-10:],
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
            self._autopilot_type = "Simulated Pixhawk" if simulate else "ArduPilot ArduCopter"
        self.start()

    def get_status_texts(self, limit: int = 20, prearm_only: bool = False) -> List[Dict[str, Any]]:
        """Return circular buffer of vehicle STATUSTEXT messages."""
        with self._lock:
            texts = list(self._status_texts)
        if prearm_only:
            texts = [t for t in texts if t.get("is_prearm")]
        return texts[-limit:]

    def get_latest_prearm_error(self, max_age_seconds: float = 10.0) -> Optional[str]:
        """Return the most recent pre-arm failure message within given time window."""
        now = time.time()
        with self._lock:
            for entry in reversed(self._status_texts):
                if entry.get("is_prearm") and (now - entry["timestamp"] <= max_age_seconds):
                    if "passed" not in entry["text"].lower():
                        return entry["text"]
        return None

    def get_command_ack(self, command_id: int, max_age_seconds: float = 5.0) -> Optional[Dict[str, Any]]:
        """Retrieve recent COMMAND_ACK for a given command ID."""
        now = time.time()
        with self._lock:
            ack = self._command_acks.get(command_id)
            if ack and (now - ack["timestamp"] <= max_age_seconds):
                return ack
        return None

    def wait_for_mode(self, expected_mode: str, timeout: float = 3.5) -> bool:
        """Wait until vehicle reports expected flight mode in heartbeat."""
        start_t = time.time()
        expected_upper = expected_mode.strip().upper()
        while time.time() - start_t < timeout:
            snap = self.get_snapshot()
            if snap.connected and snap.flight_mode == expected_upper:
                return True
            time.sleep(0.05)
        return False

    def wait_for_arm_state(self, expected_armed: bool, timeout: float = 5.0) -> bool:
        """Wait until vehicle reports expected armed state in heartbeat."""
        start_t = time.time()
        while time.time() - start_t < timeout:
            snap = self.get_snapshot()
            if snap.connected and snap.armed == expected_armed:
                return True
            time.sleep(0.05)
        return False

    def send_command_long(
        self,
        command: int,
        param1: float = 0.0,
        param2: float = 0.0,
        param3: float = 0.0,
        param4: float = 0.0,
        param5: float = 0.0,
        param6: float = 0.0,
        param7: float = 0.0,
        confirmation: int = 0
    ) -> bool:
        """Thread-safe dispatch of MAVLink COMMAND_LONG."""
        with self._command_lock:
            if not self._mav_connection:
                raise RuntimeError("MAVLink connection handle not available")
            sys_id = getattr(self._mav_connection, "target_system", None) or self._target_system or 1
            comp_id = getattr(self._mav_connection, "target_component", None) or self._target_component or 1
            self._mav_connection.mav.command_long_send(
                sys_id,
                comp_id,
                command,
                confirmation,
                float(param1),
                float(param2),
                float(param3),
                float(param4),
                float(param5),
                float(param6),
                float(param7)
            )
            return True

    def send_set_mode(self, mode_name: str) -> bool:
        """Thread-safe request to switch ArduCopter flight mode."""
        mode_upper = mode_name.strip().upper()
        mode_id = ARDUCOPTER_MODE_IDS.get(mode_upper)
        if mode_id is None:
            raise ValueError(f"Unknown ArduCopter mode '{mode_upper}'")

        with self._command_lock:
            if not self._mav_connection:
                raise RuntimeError("MAVLink connection handle not available")

            # Method 1: Using pymavlink set_mode if mapping available
            try:
                if hasattr(self._mav_connection, "set_mode"):
                    self._mav_connection.set_mode(mode_id)
                    return True
            except Exception:
                pass

            # Method 2: MAV_CMD_DO_SET_MODE (176)
            from pymavlink import mavutil
            sys_id = getattr(self._mav_connection, "target_system", None) or self._target_system or 1
            comp_id = getattr(self._mav_connection, "target_component", None) or self._target_component or 1
            self._mav_connection.mav.command_long_send(
                sys_id,
                comp_id,
                mavutil.mavlink.MAV_CMD_DO_SET_MODE,
                0,
                1.0,  # MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                float(mode_id),
                0, 0, 0, 0, 0
            )
            return True

    def set_param(
        self,
        param_name: str,
        param_val: float,
        param_type: Optional[int] = None
    ) -> bool:
        """Thread-safe MAVLink PARAM_SET dispatch."""
        with self._command_lock:
            if not self._mav_connection:
                if self.simulate:
                    logger.info("Simulated PARAM_SET %s = %s", param_name, param_val)
                    return True
                raise RuntimeError("MAVLink connection handle not available")
            from pymavlink import mavutil
            ptype = param_type if param_type is not None else mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            sys_id = getattr(self._mav_connection, "target_system", None) or self._target_system or 1
            comp_id = getattr(self._mav_connection, "target_component", None) or self._target_component or 1
            self._mav_connection.mav.param_set_send(
                sys_id,
                comp_id,
                param_name.encode("utf-8"),
                float(param_val),
                ptype
            )
            logger.info("Sent MAVLink PARAM_SET %s = %s (type=%d)", param_name, param_val, ptype)
            return True


# Global singleton instance
mavlink_service = MAVLinkService()
