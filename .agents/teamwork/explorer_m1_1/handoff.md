# Handoff Report: Explorer M1-1 (Milestone M1 — MAVLink UART & Safety Interlocks)

## 1. Observation
- **File**: `backend/flight/mavlink_service.py`
  - **Lines 281–295**:
    ```python
    281: target_conn = self.connection_string
    282: # Auto-fallback if /dev/ttyACM0 re-enumerated to /dev/ttyACM1 or similar
    283: if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
    284:     import glob
    285:     dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    286:     if dev_matches:
    287:         logger.info(
    288:             "Port %s not found; dynamically falling back to active port %s",
    289:             target_conn, dev_matches[0]
    290:         )
    291:         target_conn = dev_matches[0]
    292:         with self._lock:
    293:             self._connection_string = target_conn
    ```
  - **Line 293**: `self._connection_string = target_conn`. Searching the repository reveals `self._connection_string` appears nowhere else. The public attribute initialized in `__init__` (line 104) is `self.connection_string`.
  - **Lines 334–351**:
    ```python
    334: if msg_type == "HEARTBEAT":
    335:     with self._lock:
    ...
    350:         self._autopilot_type = "ArduPilot ArduCopter"
    ```
    The string `"ArduPilot ArduCopter"` is statically assigned, ignoring `msg.autopilot` and `msg.type`.
  - **Lines 298–310 & 434–439**:
    Physical port failures are caught by `except Exception as e:` (lines 305–310), logging a warning, setting `self._connected = False`, sleeping for 2.0s, and continuing the loop. At no point in `_run_mavlink_stream` is `self.simulate` altered.
- **File**: `config/settings.py`
  - Lines 57–62: `MAVLINK_TRANSPORT` defaults to `"udp"`, `MAVLINK_CONNECTION` defaults to `"udpin:0.0.0.0:14550"`, and `MAVLINK_SIMULATE` is loaded from `os.getenv("MAVLINK_SIMULATE", "true")`.
  - Lines 84–93: Startup validation prohibits `FORCE_ARM=true` and requires `ARMING_CHECKS_ENABLED=true`.
- **File**: `systemd/autonomous-drone.service`
  - Line 9: `SupplementaryGroups=dialout video` confirms group membership for serial device access (`/dev/ttyAMA0`).

## 2. Logic Chain
1. *Observation 1* shows that `str(target_conn).startswith("/dev/tty")` matches `/dev/ttyAMA0` (the Raspberry Pi PL011 UART). If this device node or its symlink `/dev/serial0` is temporarily missing or unready, lines 285–291 scan for `/dev/ttyACM*` and switch `target_conn` to an arbitrary USB peripheral. Because the Pixhawk is physically wired via GPIO UART (Pins 8, 10, 6) rather than USB, switching to a USB device disconnects flight telemetry or communicates with the wrong hardware.
2. *Observation 2* reveals line 293 assigns to `self._connection_string` instead of `self.connection_string`. Any caller reading `mavlink_service.connection_string` (such as `flight_controller.get_status()` or `/api/flight/status`) receives stale data. Furthermore, under UART operation, fallback must be completely suppressed so `target_conn` remains `/dev/serial0`.
3. *Observation 3* reveals `self._autopilot_type = "ArduPilot ArduCopter"` is hardcoded. MAVLink specifications define `msg.autopilot` (e.g. `MAV_AUTOPILOT_ARDUPILOTMEGA=3`, `MAV_AUTOPILOT_PX4=12`) and `msg.type` (e.g. `MAV_TYPE_QUADROTOR=2`, `MAV_TYPE_HEXAROTOR=13`, `MAV_TYPE_FIXED_WING=1`, `MAV_TYPE_GROUND_ROVER=10`). Inspecting `pymavlink.mavutil.mavlink.enums` confirms these values are standardized. Decoding them produces an exact string (e.g. `"ArduPilot ArduCopter"` or `"PX4 Quadrotor"`), fulfilling requirement R1.
4. *Observation 4* demonstrates that when `/dev/serial0` fails to open or is disconnected, `_run_mavlink_stream` catches the exception, sleeps 2.0s, and retries. Because `self.simulate` is never set to `True` during physical streaming, the service never silently enters simulation mode when `MAVLINK_SIMULATE=false`. Telemetry remains safely flagged as `connected=False`, `is_stale=True`, `is_simulated=False`, and flight commands are rejected with `CONTROL_DISABLED`, `NOT_CONNECTED`, or `HEARTBEAT_STALE`.

## 3. Caveats
- Testing on Windows simulates serial failure via mock ports, as `/dev/serial0` is a Linux/Raspberry Pi specific device node.
- Pixhawk TELEM2 baud rate is configured at 115200 in firmware (`SERIAL2_BAUD=115`); if Pixhawk parameters were altered externally, communication will fail until matched in `.env`.
- No modifications have been made to source code during this explorer turn, adhering strictly to read-only constraints.

## 4. Conclusion
1. Dynamic USB fallback in `backend/flight/mavlink_service.py` (lines 280–295) must be disabled whenever `target_conn in ("/dev/serial0", "/dev/ttyAMA0")` or starts with `("/dev/serial", "/dev/ttyAMA")`.
2. Line 293 dead-write attribute typo must be changed to `self.connection_string = target_conn` under `self._lock`.
3. Line 350 hardcoded `"ArduPilot ArduCopter"` must be replaced with dynamic decoding of `msg.autopilot` and `msg.type` using dictionary lookups for `AUTOPILOT_NAME_MAP` and `VEHICLE_TYPE_MAP`.
4. The physical reconnection loop retries `/dev/serial0` every 2.0s and never enables simulation mode (`self.simulate` remains `False`), ensuring full compliance with safety requirement R2.
5. All detailed diffs and architecture proposals are documented in `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\explorer_m1_1\analysis.md`.

## 5. Verification Method
1. **Automated Unit Tests**:
   Execute pytest on Windows to verify telemetry and flight control baselines:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/test_mavlink_telemetry.py tests/test_flight_controller.py tests/test_flight_control_activation.py -v
   ```
2. **Dynamic HEARTBEAT Decoding Verification**:
   Inspect `decode_heartbeat_identity(3, 2)` -> returns `("ArduPilot", "Quadrotor", "ArduPilot ArduCopter")`.
   Inspect `decode_heartbeat_identity(12, 2)` -> returns `("PX4", "Quadrotor", "PX4 Quadrotor")`.
3. **USB Fallback Bypass Verification**:
   With `connection_string="/dev/serial0"`, verify `dev_matches` search is skipped and `svc.connection_string` remains `"/dev/serial0"`.
4. **Invalidation Condition**:
   If dynamic fallback still triggers when `connection_string="/dev/serial0"`, or if `snap.autopilot_type` remains hardcoded when receiving a PX4 heartbeat, this handoff is invalidated.
