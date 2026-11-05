# Milestone M1 Changes Summary: MAVLink UART & Safety Interlocks

**Worker Agent**: Worker M1 (`worker_m1`)  
**Timestamp**: 2026-11-05T11:35:00Z  
**Branch**: `main`  
**Working Directory**: `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\worker_m1\`  

---

## Overview of Modified & Created Files

| File | Type | Summary of Changes |
|---|---|---|
| `backend/flight/mavlink_service.py` | Modified | Eliminated USB dynamic fallback for serial UART ports; fixed line 293 attribute typo (`self._connection_string` -> `self.connection_string`); implemented dynamic `HEARTBEAT` decoding of `msg.autopilot` and `msg.type`; added `_handle_heartbeat()` method; enhanced connection error exception cleanup to reset `_mav_connection` handle and ensure `self.simulate` is never set to `True`. |
| `config/settings.py` | Modified | Updated default connection resolution to `/dev/serial0` and baud rate to `115200` when `MAVLINK_TRANSPORT="serial"`; added transport vs connection URI validation (blocking network URIs on serial transport and serial paths on network transport); added environment consistency verification between `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING`. |
| `.env.example` | Modified | Clarified physical Raspberry Pi TELEM2 GPIO UART pinout (Pins 8, 10, 6), device node (`/dev/serial0` symlinked to `/dev/ttyAMA0`), baud rate (`115200`), and mandatory safety configurations (`MAVLINK_SIMULATE=false`, `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, `FORCE_ARM=false`). |
| `tests/test_mavlink_uart_safety.py` | Created | Added 7 comprehensive unit test cases verifying: (1) no USB fallback on `/dev/serial0`, (2) no USB fallback on `/dev/ttyAMA0` and `/dev/serial/by-id/`, (3) USB fallback allowed only for configured USB devices and proper attribute update, (4) dynamic autopilot/vehicle decoding from `HEARTBEAT`, (5) GCS echo heartbeat filtering, (6) hardware mode preservation (`simulate=False`) on connection errors, and (7) exhaustive startup configuration validation. |

---

## Detailed Code Modifications

### 1. `backend/flight/mavlink_service.py`

#### A. Autopilot & Vehicle Type Enums and Decoding Function
- **Location**: Lines 42–117 (module level)
- **Changes**:
  - Defined `AUTOPILOT_NAME_MAP` mapping standardized MAVLink `MAV_AUTOPILOT` enums (e.g. 0: Generic, 3: ArduPilot, 12: PX4).
  - Defined `VEHICLE_TYPE_MAP` mapping standardized MAVLink `MAV_TYPE` enums (e.g. 1: Fixed Wing, 2: Quadrotor, 10: Ground Rover, 13: Hexarotor).
  - Implemented `decode_heartbeat_identity(autopilot_id, type_id)` returning `(autopilot_name, vehicle_type_name, composite_display_string)`:
    - ArduPilot copters: `"ArduPilot ArduCopter (Quadrotor)"`, `"ArduPilot ArduCopter (Hexarotor)"`
    - ArduPilot planes: `"ArduPilot ArduPlane (Fixed Wing)"`
    - PX4 copters: `"PX4 (Quadrotor)"`
    - Generic MAVLink nodes: `"Generic"`

#### B. Dedicated `_handle_heartbeat()` Method
- **Location**: Lines 345–385
- **Changes**:
  - Implemented `_handle_heartbeat(self, msg, timestamp=None)` to parse incoming HEARTBEAT packets.
  - Filters out GCS echo heartbeats (`raw_type == 6`, `MAV_TYPE_GCS`).
  - Dynamically updates `self._connected = True`, `self._last_heartbeat = now`, `self._flight_mode`, `self._armed`, `self._system_status`, and `self._autopilot_type = composite_identity`.
  - Safely verifies types (`isinstance(..., int)`) on `src_sys`, `src_comp`, `custom_mode`, and `base_mode` to prevent `TypeError` when processing mocked or malformed MAVLink packets.

#### C. Elimination of USB Dynamic Fallback for UART
- **Location**: Lines 395–430 (`_run_mavlink_stream`)
- **Changes**:
  - Evaluates `is_uart`:
    ```python
    is_uart = (
        str(target_conn) in ("/dev/serial0", "/dev/ttyAMA0")
        or str(target_conn).startswith(("/dev/serial", "/dev/ttyAMA"))
    )
    ```
  - When `is_uart` is `True`, bypasses `glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")` entirely.
  - Retries connection strictly against `self.connection_string` (`/dev/serial0`), logging a debug notice that USB fallback is disabled.
  - Only allows USB re-enumeration fallback if the configured device was already a USB port (`/dev/ttyACM*` or `/dev/ttyUSB*`).

#### D. Bug Fix at Line 293 (Attribute Typo)
- **Location**: Line 416
- **Changes**: Corrected `self._connection_string = target_conn` to `self.connection_string = target_conn` under `self._lock`.

#### E. Strict Reconnect and Error Cleanup
- **Location**: Lines 542–555
- **Changes**:
  - When connection or packet receive exceptions occur, `self.simulate` is NEVER set to `True`.
  - Sets `self._connected = False`.
  - Safely closes and resets `self._mav_connection = None` to ensure fresh connection handles on subsequent attempts.

---

### 2. `config/settings.py`

#### A. Serial Transport Defaults
- **Location**: Lines 57–61
- **Changes**:
  - `_DEFAULT_MAVLINK_CONN: str = "/dev/serial0" if MAVLINK_TRANSPORT == "serial" else "udpin:0.0.0.0:14550"`
  - `MAVLINK_CONNECTION: str = os.getenv("MAVLINK_CONNECTION", os.getenv("MAVLINK_CONNECTION_STRING", _DEFAULT_MAVLINK_CONN))`
  - `MAVLINK_CONNECTION_STRING: str = os.getenv("MAVLINK_CONNECTION_STRING", MAVLINK_CONNECTION)`
  - `MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "115200" if MAVLINK_TRANSPORT == "serial" else "57600"))`

#### B. Enhanced Startup Safety Validation (`Settings.validate_configuration`)
- **Location**: Lines 105–130
- **Changes**:
  - Added environment variable consistency check: if both `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING` are defined in the environment, verifies they are identical or raises `ValueError`.
  - Added cross-field transport validation:
    - If `MAVLINK_TRANSPORT == "serial"`, verifies `MAVLINK_CONNECTION` is not a network URI (`udp:`, `udpin:`, `udpout:`, `tcp:`, `tcpin:`, `tcpout:`).
    - If `MAVLINK_TRANSPORT in ("udp", "tcp")`, verifies `MAVLINK_CONNECTION` is not a serial device path (`/dev/`, `com`).

---

### 3. `.env.example`

- **Location**: Lines 35–60
- **Changes**:
  - Detailed physical connection pinout for Raspberry Pi 4 TELEM2 GPIO UART:
    - Pixhawk TELEM2 Pin 2 (TX) ↔ Raspberry Pi Pin 10 (GPIO 15 / RXD / `/dev/ttyAMA0`)
    - Pixhawk TELEM2 Pin 3 (RX) ↔ Raspberry Pi Pin 8 (GPIO 14 / TXD / `/dev/ttyAMA0`)
    - Pixhawk TELEM2 Pin 6 (GND) ↔ Raspberry Pi Pin 6 (GND)
  - Documented physical deployment parameters:
    - `MAVLINK_TRANSPORT=serial`
    - `MAVLINK_CONNECTION=/dev/serial0`
    - `MAVLINK_CONNECTION_STRING=/dev/serial0`
    - `MAVLINK_BAUDRATE=115200`
    - `MAVLINK_SIMULATE=false`
    - `FLIGHT_CONTROL_ENABLED=false`
    - `ARMING_CHECKS_ENABLED=true`
    - `FORCE_ARM=false`

---

### 4. `tests/test_mavlink_uart_safety.py`

- **New Suite**: Implemented 7 unit test methods:
  1. `test_no_usb_fallback_when_serial0_specified_and_missing`: Mocks missing `/dev/serial0` and present `/dev/ttyACM0`; verifies connection is attempted strictly on `/dev/serial0` without switching devices.
  2. `test_no_usb_fallback_for_ttyama0_and_serial_by_id`: Verifies `/dev/ttyAMA0` and `/dev/serial/by-id/` bypass USB fallback.
  3. `test_usb_fallback_allowed_when_configured_as_usb_device`: Verifies USB re-enumeration fallback operates when configured for USB and updates `self.connection_string`.
  4. `test_dynamic_autopilot_and_vehicle_decoding_from_heartbeat`: Verifies dynamic decoding for ArduPilot Copter (3, 2), PX4 (12, 2), Hexarotor (3, 13), Generic (0, 0), and handles malformed/None payloads gracefully.
  5. `test_gcs_heartbeat_ignored_in_decoding`: Verifies companion GCS echo heartbeats (`type=6`) do not overwrite vehicle telemetry identity.
  6. `test_mavlink_simulate_false_preserves_hardware_mode_on_connection_failure`: Verifies that connection exceptions retain `simulate=False`, `connection_type="SERIAL_UART"`, `connected=False`, `flight_mode="DISCONNECTED"`, and latitude/longitude 0.0.
  7. `test_settings_validate_configuration_safety_exceptions`: Exhaustively tests startup invariants (`FORCE_ARM`, `ARMING_CHECKS_ENABLED`, `MAVLINK_TRANSPORT`, `FLIGHT_MODE`, empty `MAVLINK_CONNECTION`, serial vs network URI cross-validation, environment conflict detection, and nominal passes).

---

## Verification Results

Full pytest execution across the entire test suite:
- **Command**: `& "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/ -v`
- **Result**: `119 passed in 17.24s (exit code 0)`
- **Regression Analysis**: Zero regressions against existing 112 tests; 7 new M1 tests passing 100%.
