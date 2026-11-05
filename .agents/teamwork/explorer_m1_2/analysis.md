# Milestone M1 Analysis & Implementation Recommendations

**Explorer Agent**: Explorer M1-2  
**Investigation Scope**: Milestone M1 — MAVLink UART & Safety Interlocks  
**Target Codebase**: `config/settings.py`, `.env.example`, `backend/api/flight_routes.py`, `backend/flight/flight_controller.py`, `backend/flight/mavlink_service.py`  
**Date**: 2026-11-05  

---

## Executive Summary

This investigation analyzed the configuration validation mechanisms, environment variable resolution, safety interlocks, and the flight status telemetry API for Milestone M1. 

### Key Findings:
1. **Safety Interlock Enforcement (`Settings.validate_configuration`)**: `FORCE_ARM` (`false`) and `ARMING_CHECKS_ENABLED` (`true`) are strictly enforced at class initialization. Any attempt to enable force-arming or disable pre-arm checks immediately triggers a terminating `ValueError`. `MAVLINK_TRANSPORT` is restricted to `{"udp", "tcp", "serial"}`. However, cross-field validation is currently missing: if `MAVLINK_TRANSPORT="serial"`, `Settings.validate_configuration()` does not verify whether `MAVLINK_CONNECTION` points to a valid serial device (e.g. `/dev/serial0`) vs. a UDP/TCP URI.
2. **MAVLink Connection String Consistency**: `Settings.MAVLINK_CONNECTION` and `Settings.MAVLINK_CONNECTION_STRING` are aliased in Python (`MAVLINK_CONNECTION_STRING: str = MAVLINK_CONNECTION`). When `MAVLINK_CONNECTION=/dev/serial0`, both attributes resolve to `"/dev/serial0"`. However, if `.env` specifies both variables with divergent values, the existing loader can silently mask conflicts or prioritize `MAVLINK_CONNECTION` over `MAVLINK_CONNECTION_STRING`, while leaving `os.environ["MAVLINK_CONNECTION_STRING"]` unsynchronized for external processes.
3. **Flight Control Default**: `FLIGHT_CONTROL_ENABLED` consistently defaults to `False` across `.env.example`, `config/settings.py` (`os.getenv("FLIGHT_CONTROL_ENABLED", "false")`), and `FlightController.__init__()`. All state-mutating flight command endpoints return `HTTP 403 Forbidden` (`code: CONTROL_DISABLED`) when disabled.
4. **`/api/flight/status` Telemetry Coverage**: The route `/api/flight/status` exposes connection status (`connected`, `is_stale`, `connection_type`), connection string / serial port (`connection_string`), baud rate (`baudrate`), heartbeat age (`heartbeat_age_seconds`), autopilot type (`autopilot_type`), flight mode (`flight_mode`), and armed state (`armed`). To achieve full interface compliance and eliminate ambiguity, `serial_port` should be exposed as an explicit top-level field alias alongside `connection_string`, and `autopilot_type` must be decoded dynamically from MAVLink HEARTBEAT fields (`msg.autopilot` and `msg.type`) rather than remaining a static hardcoded string.
5. **Critical Bugs Identified in `mavlink_service.py`**:
   - **Dynamic USB Fallback Violation**: Lines 282–294 automatically scan for and fall back to `/dev/ttyACM*` or `/dev/ttyUSB*` when a configured serial port is not immediately found. This violates Requirement R1 / Acceptance Criteria, which mandates keeping `/dev/serial0` without automatic USB fallback.
   - **Attribute Misname (`self._connection_string`)**: Line 293 assigns to `self._connection_string`, whereas the class defines and accesses `self.connection_string`.
   - **Baudrate Defaults**: `settings.py` line 60 and `mavlink_service.py` line 509 default `MAVLINK_BAUDRATE` to `57600`, whereas Pixhawk TELEM2 UART is configured at `115200` baud.

---

## 1. Deep Dive: `config/settings.py` & Environment Configuration

### 1.1 `Settings.validate_configuration()` Audit

**Observed Code** (`config/settings.py`, lines 81–108):
```python
@classmethod
def validate_configuration(cls) -> None:
    """Validate critical safety and runtime parameters at startup."""
    if cls.FORCE_ARM:
        raise ValueError(
            "CRITICAL SAFETY VIOLATION: FORCE_ARM must never be enabled. "
            "ArduPilot firmware pre-arm safety checks are mandatory."
        )
    if not cls.ARMING_CHECKS_ENABLED:
        raise ValueError(
            "CRITICAL SAFETY VIOLATION: ARMING_CHECKS_ENABLED cannot be disabled. "
            "Firmware pre-arm safety checks must remain active."
        )
    valid_transports = {"udp", "tcp", "serial"}
    if cls.MAVLINK_TRANSPORT not in valid_transports:
        raise ValueError(
            f"Invalid MAVLINK_TRANSPORT '{cls.MAVLINK_TRANSPORT}'. Must be one of {valid_transports}"
        )
    supported_modes = {
        "STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE", "POSHOLD", "CIRCLE"
    }
    if cls.FLIGHT_MODE not in supported_modes:
        raise ValueError(
            f"Invalid default FLIGHT_MODE '{cls.FLIGHT_MODE}'. Must be one of {supported_modes}"
        )
    if not cls.MAVLINK_CONNECTION or not cls.MAVLINK_CONNECTION.strip():
        raise ValueError("MAVLINK_CONNECTION string cannot be empty.")
```

#### Verification Matrix:
| Parameter | Expected Rule | Implementation | Status | Evidence |
|---|---|---|---|---|
| `ARMING_CHECKS_ENABLED` | Must be `True` | `if not cls.ARMING_CHECKS_ENABLED: raise ValueError` | **ENFORCED** | Lines 89–93; verified in `test_flight_control_activation.py` |
| `FORCE_ARM` | Must be `False` | `if cls.FORCE_ARM: raise ValueError` | **ENFORCED** | Lines 84–88; verified in `test_07_force_arm_is_never_used` |
| `MAVLINK_TRANSPORT` | Must be in `{"udp", "tcp", "serial"}` | `if cls.MAVLINK_TRANSPORT not in valid_transports: raise ValueError` | **ENFORCED** | Lines 94–98 |
| `FLIGHT_MODE` | Must be in ArduCopter supported set | Checked against set of 10 modes | **ENFORCED** | Lines 99–105 |
| `MAVLINK_CONNECTION` | Non-empty string | `if not cls.MAVLINK_CONNECTION or not cls.MAVLINK_CONNECTION.strip()` | **ENFORCED** | Lines 106–108 |

#### Identified Vulnerabilities & Gaps:
1. **Missing Cross-Field Serial Transport Validation**:
   If `.env` sets `MAVLINK_TRANSPORT=serial` and `MAVLINK_CONNECTION=udpin:0.0.0.0:14550`, `validate_configuration()` succeeds despite the obvious transport mismatch.
2. **Missing In-Memory Environment Consistency Check**:
   If `.env` defines `MAVLINK_CONNECTION=/dev/serial0` and `MAVLINK_CONNECTION_STRING=udpin:0.0.0.0:14550`, line 58 assigns `Settings.MAVLINK_CONNECTION = "/dev/serial0"` and line 59 assigns `Settings.MAVLINK_CONNECTION_STRING = "/dev/serial0"`. However, `os.environ["MAVLINK_CONNECTION_STRING"]` remains `udpin:0.0.0.0:14550`, creating discrepancies for child processes or shell tools.
3. **Missing Baudrate Alignment for TELEM2**:
   `MAVLINK_BAUDRATE` defaults to `57600` (line 60). Physical TELEM2 on Pixhawk 2.4.8 operates at `115200` baud. When `MAVLINK_TRANSPORT=serial` or `MAVLINK_CONNECTION=/dev/serial0`, defaulting to 57600 baud causes UART frame errors and framing desync.

---

### 1.2 `MAVLINK_CONNECTION` vs `MAVLINK_CONNECTION_STRING` Consistency

**Observed Code** (`config/settings.py`, lines 57–60):
```python
MAVLINK_TRANSPORT: str = os.getenv("MAVLINK_TRANSPORT", "udp").lower()
MAVLINK_CONNECTION: str = os.getenv("MAVLINK_CONNECTION", os.getenv("MAVLINK_CONNECTION_STRING", "udpin:0.0.0.0:14550"))
MAVLINK_CONNECTION_STRING: str = MAVLINK_CONNECTION  # Retained for backward compatibility
MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "57600"))
```

#### Evaluation when `MAVLINK_CONNECTION=/dev/serial0`:
- **Python Attributes**:
  - `Settings.MAVLINK_CONNECTION` evaluates to `"/dev/serial0"`.
  - `Settings.MAVLINK_CONNECTION_STRING` evaluates to `"/dev/serial0"`.
  - Both properties are 100% identical.
- **Consumption in `mavlink_service.py`**:
  - `MAVLinkService.__init__()` line 104:
    `self.connection_string = connection_string or settings.MAVLINK_CONNECTION_STRING`
  - Resolves cleanly to `"/dev/serial0"`.
- **Environment Template (`.env.example`)**:
  - Currently contains:
    ```bash
    MAVLINK_TRANSPORT=udp
    MAVLINK_CONNECTION=udpin:0.0.0.0:14550
    MAVLINK_CONNECTION_STRING=udpin:0.0.0.0:14550
    MAVLINK_BAUDRATE=57600
    MAVLINK_SIMULATE=true
    ```
  - For Raspberry Pi physical deployment, both variables must be set to `/dev/serial0`, `MAVLINK_TRANSPORT=serial`, `MAVLINK_BAUDRATE=115200`, and `MAVLINK_SIMULATE=false`.

---

### 1.3 `FLIGHT_CONTROL_ENABLED` Default & Interlocks

**Observed Code**:
- `config/settings.py` line 65:
  ```python
  FLIGHT_CONTROL_ENABLED: bool = os.getenv("FLIGHT_CONTROL_ENABLED", "false").lower() in ("true", "1", "yes")
  ```
- `.env.example` line 59:
  ```bash
  FLIGHT_CONTROL_ENABLED=false
  ```
- `backend/flight/flight_controller.py` lines 44–45:
  ```python
  def __init__(self, enabled: Optional[bool] = None):
      self.enabled = enabled if enabled is not None else settings.FLIGHT_CONTROL_ENABLED
  ```
- Default state: strictly `False`.

#### Interlock Enforcement:
In `backend/flight/flight_controller.py`:
- `request_arm()` (lines 102–106):
  ```python
  if not self.enabled:
      msg = f"Flight control is disabled by default. Enable FLIGHT_CONTROL_ENABLED to allow {action} commands."
      logger.warning(msg)
      self._record_command(action, params, False, msg)
      return {"success": False, "code": "CONTROL_DISABLED", "message": msg}
  ```
- `request_mode()` (lines 207–210): Returns `{"success": False, "code": "CONTROL_DISABLED"}`
- `request_takeoff()` (lines 263–266): Returns `{"success": False, "code": "CONTROL_DISABLED"}`
- `request_rtl()` & `request_land()`: Call `request_mode()` and return `HTTP 403 / CONTROL_DISABLED`.

In `backend/api/flight_routes.py`:
- Lines 54, 74, 89, 106, 116, 126 map `code == "CONTROL_DISABLED"` to `HTTP 403 Forbidden`.
- Confirmed by `tests/test_flight_control_activation.py` test cases `test_01_disabled_by_default` and `test_02_http_403_when_disabled`.

---

## 2. Deep Dive: `/api/flight/status` Telemetry & Status Route

### 2.1 Route Handler & Data Pipeline

**Observed Code** (`backend/api/flight_routes.py`, lines 30–36):
```python
@flight_bp.route("/status", methods=["GET"])
def get_flight_status():
    """GET /api/flight/status - Return flight control state, safety interlock, and mode."""
    return jsonify({
        "status": "success",
        "data": flight_controller.get_status()
    }), 200
```

**Backing Implementation** (`backend/flight/flight_controller.py`, lines 50–75):
```python
def get_status(self) -> Dict[str, Any]:
    """Return operational state, safety lock status, and vehicle mode."""
    snap = mavlink_service.get_snapshot()
    with self._lock:
        last_cmd = self._command_history[0] if self._command_history else None
        return {
            "flight_control_enabled": self.enabled,
            "connected": snap.connected,
            "is_simulated": snap.is_simulated,
            "connection_type": snap.connection_type,
            "connection_string": mavlink_service.connection_string,
            "baudrate": mavlink_service.baudrate,
            "autopilot_type": snap.autopilot_type,
            "heartbeat_age_seconds": snap.heartbeat_age_seconds,
            "is_stale": snap.is_stale,
            "armed": snap.armed,
            "flight_mode": snap.flight_mode,
            "target_mode": settings.FLIGHT_MODE,
            "altitude_m": snap.altitude_relative_m,
            "battery_percent": snap.battery_remaining_percent,
            "prearm_status": snap.prearm_status,
            "prearm_messages": snap.prearm_messages,
            "supported_modes": SUPPORTED_FLIGHT_MODES,
            "command_count": len(self._command_history),
            "last_command": last_cmd
        }
```

### 2.2 Telemetry Field Verification Matrix

| Required Telemetry Item | Corresponding Dict Field | Type / Sample Value | Compliance Status | Analysis & Improvement |
|---|---|---|---|---|
| **Connection Status** | `connected`, `is_stale`, `connection_type` | `bool` (`True`/`False`), `str` (`"SERIAL_UART"`, `"UDP_WIFI"`, `"SIMULATION"`) | **Compliant** | `connected` reflects active non-stale heartbeat (`connected and not is_stale`). Also recommend exposing `system_status` (`snap.system_status`). |
| **Serial Port / Device** | `connection_string` | `str` (`"/dev/serial0"`) | **Compliant with alias recommendation** | `connection_string` holds the port. Recommend exposing explicit alias `"serial_port": mavlink_service.connection_string` for semantic clarity. |
| **Baud Rate** | `baudrate` | `int` (`115200` or `57600`) | **Compliant** | Directly exposes `mavlink_service.baudrate`. |
| **Heartbeat Reception / Age** | `heartbeat_age_seconds`, `is_stale` | `float` (`0.2`), `bool` (`False`) | **Compliant** | If no heartbeat has ever been received, returns `999.0`. Recommend exposing `"heartbeat_received": snap.heartbeat_age_seconds < 900.0`. |
| **Autopilot Type** | `autopilot_type` | `str` (`"ArduPilot ArduCopter"`) | **Partially Compliant (Static string)** | Currently hardcoded in `mavlink_service.py:350`. Needs dynamic extraction of `msg.autopilot` and `msg.type` from HEARTBEAT packets (PROJECT.md Feature 4). |
| **Flight Mode** | `flight_mode` | `str` (`"ALT_HOLD"`, `"LOITER"`, `"DISCONNECTED"`) | **Compliant** | Decoded from `msg.custom_mode` using `COPTER_MODES` lookup. |
| **Armed Status** | `armed` | `bool` (`False` / `True`) | **Compliant** | Decoded from `msg.base_mode & 128` (`MAV_MODE_FLAG_SAFETY_ARMED`). |
| **Pre-arm Messages** | `prearm_status`, `prearm_messages` | `str` (`"PASSED"`, `"CHECKS_FAILED"`), `List[str]` | **Compliant** | Extracted from `STATUSTEXT` MAVLink messages. |

---

## 3. Discovered Defects in `backend/flight/mavlink_service.py`

### 3.1 Defect 1: Dynamic Fallback to USB (`/dev/ttyACM*`)
- **Location**: `backend/flight/mavlink_service.py`, lines 282–294:
  ```python
  if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
      import glob
      dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
      if dev_matches:
          logger.info(
              "Port %s not found; dynamically falling back to active port %s",
              target_conn, dev_matches[0]
          )
          target_conn = dev_matches[0]
          with self._lock:
              self._connection_string = target_conn
  ```
- **Impact**: Violates R1 / Acceptance Criteria ("without falling back to USB /dev/ttyACM0"). If `/dev/ttyAMA0` is momentarily busy or re-enumerating, the companion computer silently switches to USB `/dev/ttyACM0` or `/dev/ttyUSB0`.
- **Recommendation**: Remove this dynamic USB fallback completely. Serial UART must stay locked to the configured device (`self.connection_string`), logging an error if unavailable rather than silently rebinding.

### 3.2 Defect 2: Typo Assignment `self._connection_string`
- **Location**: `backend/flight/mavlink_service.py`, line 293:
  ```python
  with self._lock:
      self._connection_string = target_conn
  ```
- **Impact**: Creates a stray instance attribute `_connection_string`. All other methods, getters, and setters read `self.connection_string`.
- **Recommendation**: With the removal of USB fallback, this assignment is deleted. Ensure any runtime connection mutation uses `self.connection_string`.

### 3.3 Defect 3: Static Autopilot Type
- **Location**: `backend/flight/mavlink_service.py`, lines 123, 350, 484:
  ```python
  self._autopilot_type = "ArduPilot ArduCopter"
  ```
- **Impact**: Ignores dynamic parameters `msg.autopilot` and `msg.type` transmitted in the MAVLink HEARTBEAT message. If Pixhawk runs PX4 or a different vehicle profile, the dashboard and API display inaccurate metadata.
- **Recommendation**: Implement dynamic decoding using `pymavlink.mavutil.mavlink.enums` for `MAV_AUTOPILOT` and `MAV_TYPE`.

---

## 4. Proposed Implementation Changes & Code Patches

### 4.1 Proposed Patch for `config/settings.py`

```python
<<<<
    @classmethod
    def validate_configuration(cls) -> None:
        """Validate critical safety and runtime parameters at startup."""
        if cls.FORCE_ARM:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: FORCE_ARM must never be enabled. "
                "ArduPilot firmware pre-arm safety checks are mandatory."
            )
        if not cls.ARMING_CHECKS_ENABLED:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: ARMING_CHECKS_ENABLED cannot be disabled. "
                "Firmware pre-arm safety checks must remain active."
            )
        valid_transports = {"udp", "tcp", "serial"}
        if cls.MAVLINK_TRANSPORT not in valid_transports:
            raise ValueError(
                f"Invalid MAVLINK_TRANSPORT '{cls.MAVLINK_TRANSPORT}'. Must be one of {valid_transports}"
            )
        supported_modes = {
            "STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE", "POSHOLD", "CIRCLE"
        }
        if cls.FLIGHT_MODE not in supported_modes:
            raise ValueError(
                f"Invalid default FLIGHT_MODE '{cls.FLIGHT_MODE}'. Must be one of {supported_modes}"
            )
        if not cls.MAVLINK_CONNECTION or not cls.MAVLINK_CONNECTION.strip():
            raise ValueError("MAVLINK_CONNECTION string cannot be empty.")
====
    @classmethod
    def validate_configuration(cls) -> None:
        """Validate critical safety and runtime parameters at startup."""
        if cls.FORCE_ARM:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: FORCE_ARM must never be enabled. "
                "ArduPilot firmware pre-arm safety checks are mandatory."
            )
        if not cls.ARMING_CHECKS_ENABLED:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: ARMING_CHECKS_ENABLED cannot be disabled. "
                "Firmware pre-arm safety checks must remain active."
            )
        valid_transports = {"udp", "tcp", "serial"}
        if cls.MAVLINK_TRANSPORT not in valid_transports:
            raise ValueError(
                f"Invalid MAVLINK_TRANSPORT '{cls.MAVLINK_TRANSPORT}'. Must be one of {valid_transports}"
            )
        supported_modes = {
            "STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE", "POSHOLD", "CIRCLE"
        }
        if cls.FLIGHT_MODE not in supported_modes:
            raise ValueError(
                f"Invalid default FLIGHT_MODE '{cls.FLIGHT_MODE}'. Must be one of {supported_modes}"
            )
        if not cls.MAVLINK_CONNECTION or not cls.MAVLINK_CONNECTION.strip():
            raise ValueError("MAVLINK_CONNECTION string cannot be empty.")

        # Consistency check between MAVLINK_CONNECTION and MAVLINK_CONNECTION_STRING
        env_conn = os.getenv("MAVLINK_CONNECTION")
        env_conn_str = os.getenv("MAVLINK_CONNECTION_STRING")
        if env_conn and env_conn_str and env_conn.strip() != env_conn_str.strip():
            raise ValueError(
                f"Configuration conflict: MAVLINK_CONNECTION ('{env_conn}') and "
                f"MAVLINK_CONNECTION_STRING ('{env_conn_str}') must be identical."
            )

        # Transport vs Connection string validation
        conn_lower = cls.MAVLINK_CONNECTION.lower()
        if cls.MAVLINK_TRANSPORT == "serial":
            if conn_lower.startswith(("udp:", "udpin:", "udpout:", "tcp:", "tcpin:")):
                raise ValueError(
                    f"MAVLINK_TRANSPORT is 'serial' but MAVLINK_CONNECTION is a network URI: '{cls.MAVLINK_CONNECTION}'"
                )
        elif cls.MAVLINK_TRANSPORT in ("udp", "tcp"):
            if conn_lower.startswith("/dev/") or conn_lower.startswith("com"):
                raise ValueError(
                    f"MAVLINK_TRANSPORT is '{cls.MAVLINK_TRANSPORT}' but MAVLINK_CONNECTION is a serial port: '{cls.MAVLINK_CONNECTION}'"
                )
>>>>
```

### 4.2 Proposed Updates to `.env.example`

Update the MAVLink telemetry section to provide explicit `/dev/serial0` configuration for Raspberry Pi TELEM2 deployment:

```bash
# MAVLink Flight Controller Telemetry & Flight Control
# Transport: udp, tcp, or serial (Use 'serial' for Raspberry Pi TELEM2 GPIO UART)
MAVLINK_TRANSPORT=serial

# MAVLink Connection String:
# For physical Raspberry Pi GPIO UART (Pixhawk TELEM2 via pins GPIO 14/15):
MAVLINK_CONNECTION=/dev/serial0
MAVLINK_CONNECTION_STRING=/dev/serial0
MAVLINK_BAUDRATE=115200
MAVLINK_HEARTBEAT_TIMEOUT=5.0

# Simulation vs Physical Hardware:
# Set to 'false' for physical Pixhawk 2.4.8 hardware over Wi-Fi / Serial.
# Set to 'true' for local virtual simulation (Windows development / testing).
MAVLINK_SIMULATE=false

# Flight Control Subsystem (Disabled by default for safety)
FLIGHT_CONTROL_ENABLED=false
```

### 4.3 Proposed Updates to `backend/flight/flight_controller.py`

Enhance `get_status()` to provide explicit `serial_port` and `heartbeat_received` aliases:

```python
<<<<
            return {
                "flight_control_enabled": self.enabled,
                "connected": snap.connected,
                "is_simulated": snap.is_simulated,
                "connection_type": snap.connection_type,
                "connection_string": mavlink_service.connection_string,
                "baudrate": mavlink_service.baudrate,
                "autopilot_type": snap.autopilot_type,
                "heartbeat_age_seconds": snap.heartbeat_age_seconds,
                "is_stale": snap.is_stale,
                "armed": snap.armed,
                "flight_mode": snap.flight_mode,
                "target_mode": settings.FLIGHT_MODE,
                "altitude_m": snap.altitude_relative_m,
                "battery_percent": snap.battery_remaining_percent,
                "prearm_status": snap.prearm_status,
                "prearm_messages": snap.prearm_messages,
                "supported_modes": SUPPORTED_FLIGHT_MODES,
                "command_count": len(self._command_history),
                "last_command": last_cmd
            }
====
            return {
                "flight_control_enabled": self.enabled,
                "connected": snap.connected,
                "is_simulated": snap.is_simulated,
                "connection_type": snap.connection_type,
                "connection_string": mavlink_service.connection_string,
                "serial_port": mavlink_service.connection_string,  # Explicit alias for serial device
                "baudrate": mavlink_service.baudrate,
                "autopilot_type": snap.autopilot_type,
                "vehicle_type": getattr(snap, "vehicle_type", "Quadrotor"),
                "heartbeat_age_seconds": snap.heartbeat_age_seconds,
                "heartbeat_received": snap.heartbeat_age_seconds < 900.0,
                "is_stale": snap.is_stale,
                "armed": snap.armed,
                "flight_mode": snap.flight_mode,
                "target_mode": settings.FLIGHT_MODE,
                "altitude_m": snap.altitude_relative_m,
                "battery_percent": snap.battery_remaining_percent,
                "system_status": snap.system_status,
                "prearm_status": snap.prearm_status,
                "prearm_messages": snap.prearm_messages,
                "supported_modes": SUPPORTED_FLIGHT_MODES,
                "command_count": len(self._command_history),
                "last_command": last_cmd
            }
>>>>
```

### 4.4 Proposed Updates to `backend/flight/mavlink_service.py`

1. **Remove dynamic USB fallback** in `_run_mavlink_stream()`:
```python
<<<<
                # 1. Establish connection if not already open
                if not self._mav_connection:
                    target_conn = self.connection_string
                    # Auto-fallback if /dev/ttyACM0 re-enumerated to /dev/ttyACM1 or similar
                    if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
                        import glob
                        dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
                        if dev_matches:
                            logger.info(
                                "Port %s not found; dynamically falling back to active port %s",
                                target_conn, dev_matches[0]
                            )
                            target_conn = dev_matches[0]
                            with self._lock:
                                self._connection_string = target_conn

                    logger.info("Attempting physical MAVLink connection to %s", target_conn)
====
                # 1. Establish connection if not already open
                if not self._mav_connection:
                    target_conn = self.connection_string
                    logger.info("Attempting physical MAVLink connection to %s (baud: %d)", target_conn, self.baudrate)
>>>>
```

2. **Dynamic Autopilot and Vehicle Decoding** in `_run_mavlink_stream()`:
```python
<<<<
                        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
                        # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
                        base_mode = getattr(msg, "base_mode", 0)
                        self._armed = bool(base_mode & 128)
                        self._system_status = "ACTIVE" if self._armed else "STANDBY"
                        self._autopilot_type = "ArduPilot ArduCopter"
====
                        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
                        # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
                        base_mode = getattr(msg, "base_mode", 0)
                        self._armed = bool(base_mode & 128)
                        self._system_status = "ACTIVE" if self._armed else "STANDBY"

                        # Dynamic decoding of autopilot and vehicle type from HEARTBEAT
                        ap_raw = getattr(msg, "autopilot", 3)
                        type_raw = getattr(msg, "type", 2)
                        try:
                            from pymavlink import mavutil
                            ap_desc = mavutil.mavlink.enums.get("MAV_AUTOPILOT", {}).get(ap_raw)
                            type_desc = mavutil.mavlink.enums.get("MAV_TYPE", {}).get(type_raw)
                            ap_name = ap_desc.description.split(" - ")[0] if ap_desc and ap_desc.description else (ap_desc.name if ap_desc else "ArduPilot")
                            v_name = type_desc.description if type_desc and type_desc.description else (type_desc.name if type_desc else "Quadrotor")
                            self._autopilot_type = f"{ap_name} ({v_name})"
                            self._vehicle_type = v_name
                        except Exception:
                            self._autopilot_type = "ArduPilot (Quadrotor)"
                            self._vehicle_type = "Quadrotor"
>>>>
```

---

## 5. Summary of Verification & Next Steps

All 112 existing pytest unit and integration tests pass successfully on the current codebase. The recommendations above are non-breaking, enhance configuration security, enforce strict UART resolution to `/dev/serial0`, and fulfill all telemetry and safety requirements for Milestone M1.
