# Milestone M1 Analysis: MAVLink UART & Safety Interlocks

## Executive Summary
This report provides a comprehensive architectural and code-level investigation into `backend/flight/mavlink_service.py` and `config/settings.py` for Milestone M1 (MAVLink UART & Safety Interlocks). It identifies root causes, exact file locations, and provides concrete implementation strategies to:
1. Eliminate automatic USB dynamic fallback when configured for Raspberry Pi GPIO serial UART (`/dev/serial0` / `/dev/ttyAMA0`).
2. Correct the dead-write attribute bug at line 293 (`self._connection_string` vs `self.connection_string`).
3. Replace hardcoded autopilot identification (`"ArduPilot ArduCopter"`) with dynamic MAVLink `HEARTBEAT` payload decoding (`msg.autopilot` and `msg.type`).
4. Enforce infinite non-switching retry of `/dev/serial0` when physical hardware is disconnected or unready, strictly preventing silent fallback into virtual simulation (`MAVLINK_SIMULATE=false`).

---

## 1. Dynamic USB Fallback Elimination (Lines 280–295)

### 1.1 Exact Code Observation
In `backend/flight/mavlink_service.py`, lines 280–295:
```python
280:                 if not self._mav_connection:
281:                     target_conn = self.connection_string
282:                     # Auto-fallback if /dev/ttyACM0 re-enumerated to /dev/ttyACM1 or similar
283:                     if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
284:                         import glob
285:                         dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
286:                         if dev_matches:
287:                             logger.info(
288:                                 "Port %s not found; dynamically falling back to active port %s",
289:                                 target_conn, dev_matches[0]
290:                             )
291:                             target_conn = dev_matches[0]
292:                             with self._lock:
293:                                 self._connection_string = target_conn
294: 
295:                     logger.info("Attempting physical MAVLink connection to %s", target_conn)
```

### 1.2 Defect & Hazard Analysis
1. **Flawed Prefix Match (`/dev/tty`)**:
   On Raspberry Pi 4, the primary PL011 UART is assigned device node `/dev/ttyAMA0`, and the standard alias is `/dev/serial0` (pointing to `/dev/ttyAMA0`).
   The condition `str(target_conn).startswith("/dev/tty")` matches `/dev/ttyAMA0`!
   If `target_conn` is `/dev/ttyAMA0` and the device node is temporarily unready (or in boot transition), `not os.path.exists(str(target_conn))` evaluates to `True`.
2. **Peripheral Hijacking Risk**:
   Lines 284–286 run `glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")`.
   If any USB peripheral is plugged into the Raspberry Pi (e.g. USB camera, cellular dongle, RTK GPS receiver, or USB-to-serial adapter), `dev_matches` is non-empty. Line 291 assigns `target_conn = dev_matches[0]`.
   The service then attempts to open that unrelated USB peripheral at 115200 baud, completely abandoning the Pixhawk TELEM2 UART connected to physical GPIO pins 8, 10, and 6.
3. **Requirement Mandate**:
   Per `PROJECT.md` Feature 2 and `ORIGINAL_REQUEST.md` R1:
   *"Remove automatic dynamic fallback to /dev/ttyACM* / /dev/ttyUSB* when serial UART is configured... prevent automatic USB fallback or silent switching into simulation when the physical port is unavailable."*

### 1.3 Recommended Fix Strategy
Dynamic USB fallback should **never** activate when the configured target is a hardware serial UART.
1. Define a helper check:
   ```python
   is_gpio_uart = str(target_conn) in ("/dev/serial0", "/dev/ttyAMA0") or str(target_conn).startswith(("/dev/serial", "/dev/ttyAMA"))
   ```
2. If `is_gpio_uart` is `True`, bypass all globbing and port switching. Log an explicit statement:
   ```python
   logger.debug("UART connection configured (%s); USB dynamic fallback is disabled.", target_conn)
   ```
3. Only consider USB re-enumeration if `target_conn` was explicitly configured as a USB device (i.e. starts with `/dev/ttyACM` or `/dev/ttyUSB`) AND is not a GPIO UART:
   ```python
   if not is_gpio_uart and str(target_conn).startswith(("/dev/ttyACM", "/dev/ttyUSB")) and not os.path.exists(str(target_conn)):
       dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
       if dev_matches:
           logger.info("USB device %s re-enumerated; adjusting to %s", target_conn, dev_matches[0])
           target_conn = dev_matches[0]
           with self._lock:
               self.connection_string = target_conn
   ```

---

## 2. Attribute Typo Bug at Line 293 (`self._connection_string` vs `self.connection_string`)

### 2.1 Exact Code Observation
In `backend/flight/mavlink_service.py`:
- In `__init__` (line 104):
  ```python
  self.connection_string = connection_string or settings.MAVLINK_CONNECTION_STRING
  ```
- In `_run_mavlink_stream` (line 293):
  ```python
  with self._lock:
      self._connection_string = target_conn  # BUG: private attribute typo
  ```
- In `get_snapshot` (line 460):
  ```python
  conn_type = "SIMULATION" if self.simulate else (
      "UDP_WIFI" if "udp" in str(self.connection_string).lower() else "SERIAL_UART"
  )
  ```
- In `set_connection` (line 513):
  ```python
  self.connection_string = connection_string
  ```
- In `backend/flight/flight_controller.py` (line 60):
  ```python
  "connection_string": mavlink_service.connection_string,
  ```

### 2.2 Defect Analysis
1. Line 293 assigns to `self._connection_string` (with leading underscore).
2. `self._connection_string` is **never initialized** in `__init__`, never read by any method, and never exposed to REST APIs or the frontend dashboard.
3. Because `self.connection_string` was not updated, `flight_controller.get_status()` and `/api/flight/status` continue reporting the initial stale connection string, creating an inconsistent internal state where the active socket/serial connection differs from the reported connection string.
4. When dynamic USB fallback is eliminated for UART connections, `target_conn` is not modified for UART anyway. However, for any USB re-enumeration that does occur, the assignment must be to `self.connection_string`.

### 2.3 Recommended Fix Strategy
Replace line 293 with `self.connection_string = target_conn`:
```python
with self._lock:
    self.connection_string = target_conn
```
Furthermore, ensure `self.connection_string` is protected by `self._lock` whenever modified or accessed.

---

## 3. Dynamic Autopilot & Vehicle Type Decoding from HEARTBEAT (Lines 334–365)

### 3.1 Exact Code Observation
In `backend/flight/mavlink_service.py`, lines 334–351:
```python
334:                 if msg_type == "HEARTBEAT":
335:                     with self._lock:
336:                         self._connected = True
337:                         self._last_heartbeat = now
338:                         src_sys = msg.get_srcSystem()
339:                         src_comp = msg.get_srcComponent()
340:                         if src_sys > 0:
341:                             self._target_system = src_sys
342:                         if src_comp > 0:
343:                             self._target_component = src_comp
344:                         custom_mode = getattr(msg, "custom_mode", 0)
345:                         self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
346:                         # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
347:                         base_mode = getattr(msg, "base_mode", 0)
348:                         self._armed = bool(base_mode & 128)
349:                         self._system_status = "ACTIVE" if self._armed else "STANDBY"
350:                         self._autopilot_type = "ArduPilot ArduCopter"
```

### 3.2 Defect Analysis
1. Line 350 unconditionally hardcodes:
   `self._autopilot_type = "ArduPilot ArduCopter"`
   regardless of whether the connected device is running ArduPilot, PX4, or another flight stack, and regardless of vehicle geometry (Quadrotor, Hexarotor, Fixed Wing, Rover).
2. The incoming MAVLink `HEARTBEAT` payload carries two standardized enumeration fields:
   - `msg.autopilot`: MAVLink `MAV_AUTOPILOT` enum.
   - `msg.type`: MAVLink `MAV_TYPE` enum.
3. If an external heartbeat packet arrives (such as a GCS heartbeat reflection with `msg.type == MAV_TYPE_GCS` or component ID != autopilot), the system could incorrectly treat GCS as the autopilot if not properly filtered.

### 3.3 MAVLink Protocol Specification & Enumerations
From `pymavlink.mavutil.mavlink`:

#### Autopilot Enums (`MAV_AUTOPILOT`):
| Enum Value | Identifier | Display Name |
|---|---|---|
| 0 | `MAV_AUTOPILOT_GENERIC` | Generic Autopilot |
| 3 | `MAV_AUTOPILOT_ARDUPILOTMEGA` | ArduPilot |
| 4 | `MAV_AUTOPILOT_OPENPILOT` | OpenPilot |
| 12 | `MAV_AUTOPILOT_PX4` | PX4 |
| 13 | `MAV_AUTOPILOT_SMACCMPILOT` | SMACCMPilot |
| 14 | `MAV_AUTOPILOT_AUTOQUAD` | AutoQuad |
| 15 | `MAV_AUTOPILOT_ARMAZILA` | Armazila |
| 16 | `MAV_AUTOPILOT_AEROB` | Aerob |
| 17 | `MAV_AUTOPILOT_ASLUAV` | ASLUAV |
| 18 | `MAV_AUTOPILOT_SMARTAP` | SmartAP |
| 19 | `MAV_AUTOPILOT_AIRRAILS` | AirRails |

#### Vehicle Type Enums (`MAV_TYPE`):
| Enum Value | Identifier | Display Name | ArduPilot Firmware Name |
|---|---|---|---|
| 1 | `MAV_TYPE_FIXED_WING` | Fixed Wing | ArduPlane |
| 2 | `MAV_TYPE_QUADROTOR` | Quadrotor | ArduCopter |
| 3 | `MAV_TYPE_COAXIAL` | Coaxial | ArduCopter |
| 4 | `MAV_TYPE_HELICOPTER` | Helicopter | Heli |
| 10 | `MAV_TYPE_GROUND_ROVER` | Ground Rover | Rover |
| 11 | `MAV_TYPE_SURFACE_BOAT` | Surface Boat | Rover |
| 12 | `MAV_TYPE_SUBMARINE` | Submarine | ArduSub |
| 13 | `MAV_TYPE_HEXAROTOR` | Hexarotor | ArduCopter |
| 14 | `MAV_TYPE_OCTOROTOR` | Octorotor | ArduCopter |
| 15 | `MAV_TYPE_TRICOPTER` | Tricopter | ArduCopter |
| 20 | `MAV_TYPE_VTOL_QUADROTOR` | VTOL Quadrotor | QuadPlane |
| 21 | `MAV_TYPE_VTOL_TILTROTOR` | VTOL Tiltrotor | QuadPlane |
| 29 | `MAV_TYPE_DODECAROTOR` | Dodecarotor | ArduCopter |
| 35 | `MAV_TYPE_DECAROTOR` | Decarotor | ArduCopter |
| 43 | `MAV_TYPE_GENERIC_MULTIROTOR`| Multirotor | ArduCopter |

### 3.4 Dynamic Decoding Implementation Strategy
Define standard dictionary mappings and a decoding function at module scope in `mavlink_service.py`:

```python
AUTOPILOT_NAME_MAP = {
    0: "Generic Autopilot",
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

VEHICLE_TYPE_MAP = {
    0: "Generic Vehicle",
    1: "Fixed Wing",
    2: "Quadrotor",
    3: "Coaxial",
    4: "Helicopter",
    10: "Rover",
    11: "Boat",
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

def decode_heartbeat_identity(autopilot_id: int, type_id: int) -> Tuple[str, str, str]:
    """
    Decodes MAVLink HEARTBEAT autopilot and type IDs into human-readable strings.
    Returns: (autopilot_name, vehicle_type_name, composite_display_string)
    """
    autopilot_name = AUTOPILOT_NAME_MAP.get(autopilot_id, f"Autopilot-{autopilot_id}")
    vehicle_type_name = VEHICLE_TYPE_MAP.get(type_id, f"Vehicle-{type_id}")

    # ArduPilot specific firmware designations
    if autopilot_id == 3:  # ArduPilot
        if type_id in (2, 3, 13, 14, 15, 29, 35, 43):
            firmware_sub = "ArduCopter"
        elif type_id in (1, 19, 20, 21):
            firmware_sub = "ArduPlane"
        elif type_id in (10, 11):
            firmware_sub = "Rover"
        elif type_id == 12:
            firmware_sub = "ArduSub"
        elif type_id == 4:
            firmware_sub = "Heli"
        else:
            firmware_sub = vehicle_type_name
        composite = f"ArduPilot {firmware_sub}"
    elif autopilot_id == 12:  # PX4
        composite = f"PX4 {vehicle_type_name}"
    else:
        composite = f"{autopilot_name} {vehicle_type_name}"

    return autopilot_name, vehicle_type_name, composite
```

### 3.5 Updating State in `_run_mavlink_stream`
In `_run_mavlink_stream`:
```python
if msg_type == "HEARTBEAT":
    raw_type = getattr(msg, "type", 0)
    # Ignore companion GCS echo heartbeats
    if raw_type == 6:  # MAV_TYPE_GCS
        continue

    raw_ap = getattr(msg, "autopilot", 0)
    ap_name, veh_name, composite_identity = decode_heartbeat_identity(raw_ap, raw_type)

    with self._lock:
        self._connected = True
        self._last_heartbeat = now
        src_sys = msg.get_srcSystem()
        src_comp = msg.get_srcComponent()
        if src_sys > 0:
            self._target_system = src_sys
        if src_comp > 0:
            self._target_component = src_comp
        custom_mode = getattr(msg, "custom_mode", 0)
        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
        base_mode = getattr(msg, "base_mode", 0)
        self._armed = bool(base_mode & 128)
        self._system_status = "ACTIVE" if self._armed else "STANDBY"
        self._autopilot_type = composite_identity
        self._vehicle_type = veh_name
```

### 3.6 Exposing Vehicle Type in `TelemetrySnapshot`
In `TelemetrySnapshot` (dataclass):
```python
    autopilot_type: str
    vehicle_type: str = "Unknown"
```
In `get_snapshot()`:
```python
    return TelemetrySnapshot(
        ...
        autopilot_type=self._autopilot_type if is_connected else "Unknown",
        vehicle_type=getattr(self, "_vehicle_type", "Unknown") if is_connected else "Unknown",
        ...
    )
```
In `flight_controller.get_status()`:
```python
    "autopilot_type": snap.autopilot_type,
    "vehicle_type": getattr(snap, "vehicle_type", "Unknown"),
```
In `frontend/js/dashboard.js`:
Dashboard displays `d.autopilot_type || 'ArduPilot ArduCopter'`, seamlessly rendering `"ArduPilot ArduCopter"`, `"ArduPilot Quadrotor"`, or `"PX4 Quadrotor"`.
In simulation mode: `self._autopilot_type` remains `"Simulated Pixhawk"`, preserving 100% compliance with `tests/test_flight_control_activation.py` (`self.assertIn("Simulated", snap.autopilot_type)`).

---

## 4. Physical Port Retry & Anti-Simulation Interlock Verification

### 4.1 Reconnection Loop Behavior on `/dev/serial0`
When `MAVLINK_TRANSPORT=serial` and `MAVLINK_CONNECTION=/dev/serial0`:
1. `_run_mavlink_stream()` initiates with `self.connection_string = "/dev/serial0"`.
2. When the physical UART port is unavailable (e.g. cable disconnected, Pixhawk powered off, or udev symlink unready):
   ```python
   try:
       from pymavlink import mavutil
       self._mav_connection = mavutil.mavlink_connection(
           target_conn,
           baud=self.baudrate,
           autoreconnect=True,
           timeout=2.0
       )
   except Exception as e:
       logger.warning("MAVLink connection attempt failed: %s; retrying in 2.0s", e)
       with self._lock:
           self._connected = False
       time.sleep(2.0)
       continue
   ```
3. Because dynamic fallback is eliminated for UART:
   - `target_conn` is never replaced with `/dev/ttyACM*`.
   - `self.connection_string` remains `/dev/serial0`.
   - The loop sleeps for 2.0 seconds and retries `/dev/serial0` indefinitely.
4. If an existing connection handle fails or raises an unhandled serial read exception, it must be cleanly closed and set to `None` so the reconnection loop retries cleanly:
   ```python
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
       time.sleep(2.0)
   ```

### 4.2 Strict Prevention of Silent Simulation Fallback
1. **Zero Simulation Promotion**:
   `self.simulate` is initialized strictly from `settings.MAVLINK_SIMULATE` in `__init__`.
   In `mavlink_service.py`, `self.simulate` is NEVER modified during connection failures or packet errors.
   When `MAVLINK_SIMULATE=false`, `self.simulate` remains `False` permanently.
2. **Telemetry State during Port Disconnection**:
   During port unavailability or when heartbeats stop:
   - `snap.connected` = `False`
   - `snap.is_stale` = `True`
   - `snap.is_simulated` = `False`
   - `snap.flight_mode` = `"DISCONNECTED"`
   - `snap.system_status` = `"OFFLINE"`
   - `snap.connection_type` = `"SERIAL_UART"`
   - `snap.autopilot_type` = `"Unknown"`
3. **Safety Interlocks in `flight_controller.py`**:
   - `FLIGHT_CONTROL_ENABLED=false` (enforced by R2; all arming and mode commands return HTTP 403 `CONTROL_DISABLED`).
   - Even if flight control were forcefully enabled in memory:
     - `if not snap.connected:` returns `NOT_CONNECTED`
     - `if snap.is_stale:` returns `HEARTBEAT_STALE`
   - Physical motors cannot spin and arming cannot occur without an active, non-stale heartbeat from physical hardware.

### 4.3 Settings & Environment Consistency
In `config/settings.py`:
```python
MAVLINK_TRANSPORT: str = os.getenv("MAVLINK_TRANSPORT", "udp").lower()
MAVLINK_CONNECTION: str = os.getenv(
    "MAVLINK_CONNECTION",
    os.getenv("MAVLINK_CONNECTION_STRING", "/dev/serial0" if MAVLINK_TRANSPORT == "serial" else "udpin:0.0.0.0:14550")
)
MAVLINK_CONNECTION_STRING: str = MAVLINK_CONNECTION
```
In `.env` on Raspberry Pi 4:
```ini
MAVLINK_TRANSPORT=serial
MAVLINK_CONNECTION=/dev/serial0
MAVLINK_CONNECTION_STRING=/dev/serial0
MAVLINK_BAUDRATE=115200
MAVLINK_HEARTBEAT_TIMEOUT=5.0
MAVLINK_SIMULATE=false
FLIGHT_CONTROL_ENABLED=false
ARMING_CHECKS_ENABLED=true
FORCE_ARM=false
```
User permissions: User `drone` belongs to `dialout` (configured via `SupplementaryGroups=dialout video` in `systemd/autonomous-drone.service`), which grants direct read/write access to `/dev/ttyAMA0` (`crw-rw---- root dialout`).

---

## 5. Concrete Implementation Changes (Proposed)

### 5.1 Proposed Code Patch for `backend/flight/mavlink_service.py`

#### A. Autopilot & Vehicle Type Enums (Insert before line 42)
```python
AUTOPILOT_NAME_MAP = {
    0: "Generic Autopilot",
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

VEHICLE_TYPE_MAP = {
    0: "Generic Vehicle",
    1: "Fixed Wing",
    2: "Quadrotor",
    3: "Coaxial",
    4: "Helicopter",
    10: "Rover",
    11: "Boat",
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

def decode_heartbeat_identity(autopilot_id: int, type_id: int) -> tuple[str, str, str]:
    """Decodes MAVLink HEARTBEAT autopilot and type into (autopilot, vehicle, composite)."""
    ap_name = AUTOPILOT_NAME_MAP.get(autopilot_id, f"Autopilot-{autopilot_id}")
    veh_name = VEHICLE_TYPE_MAP.get(type_id, f"Vehicle-{type_id}")
    if autopilot_id == 3:  # ArduPilot
        if type_id in (2, 3, 13, 14, 15, 29, 35, 43):
            firmware_sub = "ArduCopter"
        elif type_id in (1, 19, 20, 21):
            firmware_sub = "ArduPlane"
        elif type_id in (10, 11):
            firmware_sub = "Rover"
        elif type_id == 12:
            firmware_sub = "ArduSub"
        elif type_id == 4:
            firmware_sub = "Heli"
        else:
            firmware_sub = veh_name
        composite = f"ArduPilot {firmware_sub}"
    elif autopilot_id == 12:  # PX4
        composite = f"PX4 {veh_name}"
    else:
        composite = f"{ap_name} {veh_name}"
    return ap_name, veh_name, composite
```

#### B. Eliminating USB Dynamic Fallback and Fixing Line 293 (Lines 280–295)
```python
<<<< BEFORE:
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

==== AFTER:
                if not self._mav_connection:
                    target_conn = self.connection_string
                    # Dedicated Raspberry Pi GPIO UART ports (/dev/serial0, /dev/ttyAMA0) must NEVER fall back to USB
                    is_uart = str(target_conn) in ("/dev/serial0", "/dev/ttyAMA0") or str(target_conn).startswith(("/dev/serial", "/dev/ttyAMA"))

                    if not is_uart and str(target_conn).startswith(("/dev/ttyACM", "/dev/ttyUSB")) and not os.path.exists(str(target_conn)):
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
>>>>
```

#### C. Dynamic Autopilot Decoding in HEARTBEAT (Lines 334–351)
```python
<<<< BEFORE:
                if msg_type == "HEARTBEAT":
                    with self._lock:
                        self._connected = True
                        self._last_heartbeat = now
                        src_sys = msg.get_srcSystem()
                        src_comp = msg.get_srcComponent()
                        if src_sys > 0:
                            self._target_system = src_sys
                        if src_comp > 0:
                            self._target_component = src_comp
                        custom_mode = getattr(msg, "custom_mode", 0)
                        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
                        # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
                        base_mode = getattr(msg, "base_mode", 0)
                        self._armed = bool(base_mode & 128)
                        self._system_status = "ACTIVE" if self._armed else "STANDBY"
                        self._autopilot_type = "ArduPilot ArduCopter"

==== AFTER:
                if msg_type == "HEARTBEAT":
                    raw_type = getattr(msg, "type", 0)
                    # Ignore companion GCS echo heartbeats
                    if raw_type == 6:  # MAV_TYPE_GCS
                        continue

                    raw_ap = getattr(msg, "autopilot", 0)
                    _, veh_name, composite_identity = decode_heartbeat_identity(raw_ap, raw_type)

                    with self._lock:
                        self._connected = True
                        self._last_heartbeat = now
                        src_sys = msg.get_srcSystem()
                        src_comp = msg.get_srcComponent()
                        if src_sys > 0:
                            self._target_system = src_sys
                        if src_comp > 0:
                            self._target_component = src_comp
                        custom_mode = getattr(msg, "custom_mode", 0)
                        self._flight_mode = COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")
                        # Check base_mode armed bit (128 = MAV_MODE_FLAG_SAFETY_ARMED)
                        base_mode = getattr(msg, "base_mode", 0)
                        self._armed = bool(base_mode & 128)
                        self._system_status = "ACTIVE" if self._armed else "STANDBY"
                        self._autopilot_type = composite_identity
                        self._vehicle_type = veh_name
>>>>
```

#### D. Stream Exception Reset Handling (Lines 434–439)
```python
<<<< BEFORE:
            except Exception as e:
                logger.error("Error receiving MAVLink packet: %s", e)
                with self._lock:
                    self._connected = False
                time.sleep(1.0)

==== AFTER:
            except Exception as e:
                logger.error("Error receiving MAVLink packet: %s; closing connection handle for retry", e)
                with self._lock:
                    self._connected = False
                if self._mav_connection:
                    try:
                        self._mav_connection.close()
                    except Exception:
                        pass
                    self._mav_connection = None
                time.sleep(2.0)
>>>>
```

---

## 6. Verification and Test Strategy

### 6.1 Windows Unit & Integration Testing
1. Execute existing telemetry tests:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/test_mavlink_telemetry.py -v
   ```
2. Execute flight control activation tests:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/test_flight_control_activation.py -v
   ```
3. New test case for dynamic heartbeat decoding:
   Construct a mock HEARTBEAT message with `msg.autopilot = 12` (`MAV_AUTOPILOT_PX4`) and `msg.type = 2` (`MAV_TYPE_QUADROTOR`), verify `snap.autopilot_type == "PX4 Quadrotor"`.
   Construct a mock HEARTBEAT message with `msg.autopilot = 3` (`MAV_AUTOPILOT_ARDUPILOTMEGA`) and `msg.type = 2` (`MAV_TYPE_QUADROTOR`), verify `snap.autopilot_type == "ArduPilot ArduCopter"`.
4. New test case for UART non-fallback:
   Initialize `MAVLinkService(connection_string="/dev/serial0", simulate=False)`. Mock `glob.glob` to return `["/dev/ttyACM0"]`. Confirm that `svc.connection_string` remains `"/dev/serial0"` and does not switch to `/dev/ttyACM0`.

### 6.2 Raspberry Pi Live Deployment Verification
1. Verify symlink and permissions:
   `ls -la /dev/serial0` -> verifies pointing to `/dev/ttyAMA0`.
   `groups drone` -> verifies user is in `dialout` and `video`.
2. Verify journal output on service restart:
   `journalctl -u autonomous-drone -n 50` -> verifies `"Attempting physical MAVLink connection to /dev/serial0"`.
3. Query API endpoint:
   `curl -s http://127.0.0.1:5000/api/flight/status | jq` -> verifies `connection_string: "/dev/serial0"`, `baudrate: 115200`, `autopilot_type`, `heartbeat_age_seconds`, and safety flags.
