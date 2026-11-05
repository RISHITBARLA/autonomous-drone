# Milestone M1 Hard Handoff Report: MAVLink UART & Safety Interlocks

**Agent**: Worker M1 (`worker_m1`)  
**Role**: Implementer, QA, Specialist  
**Working Directory**: `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\worker_m1\`  
**Timestamp**: 2026-11-05T11:36:00Z  
**Type**: Hard Handoff (Milestone Implementation & Verification Complete)  

---

## 1. Observation

### 1.1 Baseline Defect Observations
1. In `backend/flight/mavlink_service.py` (lines 282–294 prior to edit):
   ```python
   if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
       import glob
       dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
       if dev_matches:
           logger.info("Port %s not found; dynamically falling back to active port %s", target_conn, dev_matches[0])
           target_conn = dev_matches[0]
           with self._lock:
               self._connection_string = target_conn
   ```
   - When `target_conn` was configured as `/dev/serial0` (pointing to `/dev/ttyAMA0`), `str(target_conn).startswith("/dev/tty")` evaluated to `True` for `/dev/ttyAMA0`.
   - If missing, it dynamically switched `target_conn` to any detected USB device (`/dev/ttyACM*`, `/dev/ttyUSB*`).
   - Line 293 wrote to `self._connection_string`, an unreferenced private attribute, leaving `self.connection_string` un-synchronized.
2. In `backend/flight/mavlink_service.py` (line 350 prior to edit):
   ```python
   self._autopilot_type = "ArduPilot ArduCopter"
   ```
   - `_autopilot_type` unconditionally hardcoded `"ArduPilot ArduCopter"`, ignoring `msg.autopilot` (e.g. 3=ArduPilot, 12=PX4) and `msg.type` (e.g. 2=Quadrotor, 13=Hexarotor) from MAVLink HEARTBEAT payloads.
3. In `config/settings.py` (lines 57–60 & 82–108 prior to edit):
   - `MAVLINK_BAUDRATE` defaulted to `57600`, whereas Pixhawk TELEM2 operates at `115200` baud.
   - `Settings.validate_configuration()` lacked validation to prevent pairing `MAVLINK_TRANSPORT="serial"` with network addresses (e.g. `udpin:0.0.0.0:14550`), and lacked environment conflict detection between `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING`.
4. In `.env.example`:
   - Lacked explicit documentation of Raspberry Pi TELEM2 GPIO UART pinout (Pins 8, 10, 6), device `/dev/serial0`, and 115200 baud setting.

### 1.2 Implemented Fix Observations
1. In `backend/flight/mavlink_service.py`:
   - Lines 42–117: Added `AUTOPILOT_NAME_MAP`, `VEHICLE_TYPE_MAP`, and `decode_heartbeat_identity()`.
   - Lines 345–385: Implemented `_handle_heartbeat()` method filtering GCS heartbeats (`type=6`) and safely decoding `msg.autopilot` and `msg.type`.
   - Lines 395–430: Added `is_uart` check. When `is_uart` is True (`/dev/serial0`, `/dev/ttyAMA0`, `/dev/serial*`, `/dev/ttyAMA*`), USB glob fallback is completely bypassed. Line 416 assigns `self.connection_string = target_conn` under `self._lock` for valid USB device re-enumeration.
   - Lines 542–555: Reset `_mav_connection = None` on packet receive error, keeping `self.simulate` strictly `False`.
2. In `config/settings.py`:
   - Lines 57–61: `_DEFAULT_MAVLINK_CONN: str = "/dev/serial0" if MAVLINK_TRANSPORT == "serial" else "udpin:0.0.0.0:14550"`, and `MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "115200" if MAVLINK_TRANSPORT == "serial" else "57600"))`.
   - Lines 105–130: In `Settings.validate_configuration()`, added environment consistency check and cross-field validation blocking network URIs when `MAVLINK_TRANSPORT == "serial"` and blocking serial paths when `MAVLINK_TRANSPORT in ("udp", "tcp")`.
3. In `.env.example`:
   - Updated lines 35–60 with explicit Raspberry Pi TELEM2 GPIO UART pinout (Pins 8, 10, 6), device node `/dev/serial0`, baud rate 115200, and required safety flags (`MAVLINK_SIMULATE=false`, `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, `FORCE_ARM=false`).
4. In `tests/test_mavlink_uart_safety.py`:
   - Created comprehensive unit test suite with 7 test methods testing all 4 required behaviors.
5. Automated test execution:
   - Command: `& "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/ -v`
   - Output: `119 passed in 17.24s (exit code 0)`
   - Compilation: `& "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile backend/flight/mavlink_service.py config/settings.py tests/test_mavlink_uart_safety.py` passed with exit code 0.

---

## 2. Logic Chain

1. **Hardware UART Isolation**:
   From Observation 1.1.1, the previous logic scanned `/dev/ttyACM*` and `/dev/ttyUSB*` whenever a device starting with `/dev/tty` did not exist. Because `/dev/ttyAMA0` begins with `/dev/tty`, any missing or unready PL011 UART node triggered a switch to an arbitrary USB peripheral. From Observation 1.2.1, checking `is_uart` directly disables globbing for `/dev/serial0`, `/dev/ttyAMA0`, and all serial device symlinks. Therefore, the connection loop retries `/dev/serial0` indefinitely without diverting flight traffic to USB peripherals.
2. **State Consistency & Line 293 Attribute Fix**:
   From Observation 1.1.1, the assignment `self._connection_string = target_conn` failed to update the public `self.connection_string` attribute queried by `FlightController.get_status()` and `/api/flight/status`. From Observation 1.2.1, updating `self.connection_string = target_conn` under `self._lock` ensures complete synchronization between driver socket/serial handles and the telemetry snapshot.
3. **Dynamic Autopilot & Vehicle Identification**:
   From Observation 1.1.2, static hardcoding of `"ArduPilot ArduCopter"` misrepresented any vehicle running PX4, Hexarotor, Plane, or Rover firmware. From Observation 1.2.1, `decode_heartbeat_identity()` dynamically translates `msg.autopilot` (e.g. 3, 12) and `msg.type` (e.g. 2, 13, 1) into descriptive strings (e.g. `"ArduPilot ArduCopter (Quadrotor)"`, `"PX4 (Quadrotor)"`), while filtering GCS echo heartbeats (`type=6`). In simulation mode, `self._autopilot_type` remains `"Simulated Pixhawk"`, ensuring 100% backward compatibility with existing tests.
4. **Anti-Simulation Interlock Enforcement**:
   From Observation 1.1.1 and 1.2.1, when `MAVLINK_SIMULATE=false`, connection exceptions in `_run_mavlink_stream` log warnings, set `self._connected = False`, reset `self._mav_connection = None`, and sleep 2.0s before retrying. At no point is `self.simulate` modified. Telemetry snapshots retain `is_simulated=False`, `connection_type="SERIAL_UART"`, and `flight_mode="DISCONNECTED"`, preventing simulated telemetry leakage or unauthorized flight commands.
5. **Configuration & Startup Safety Validation**:
   From Observation 1.1.3 and 1.2.2, `Settings.validate_configuration()` now validates that if `MAVLINK_TRANSPORT == "serial"`, `MAVLINK_CONNECTION` cannot be a network URI (e.g. `udpin:0.0.0.0:14550`), and vice versa. It also validates that `.env` cannot contain conflicting values for `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING`.
6. **Zero Regression Guarantee**:
   From Observation 1.2.5, running the full pytest suite executes all 112 baseline tests plus the 7 new M1 tests (total 119 tests), with 100% passing and zero regressions.

---

## 3. Caveats

- **Physical Raspberry Pi Environment Deployment**:
  The tests performed in this workspace run on the Windows development environment with mock serial drivers and simulated MAVLink packets. Live physical serial byte communication at 115200 baud over GPIO pins 8 and 10 will occur upon deployment to the live Raspberry Pi 4 environment (`192.168.10.235`) in Milestone M3.
- **Dialout Permissions on Pi**:
  User `drone` must belong to group `dialout` on the target Raspberry Pi to access `/dev/ttyAMA0` without permission errors. This is pre-configured via `SupplementaryGroups=dialout video` in `systemd/autonomous-drone.service`.

---

## 4. Conclusion

1. Milestone M1 requirements are fully implemented, verified, and passing:
   - `/dev/serial0` resolution is enforced across `.env.example`, `config/settings.py`, and `backend/flight/mavlink_service.py`.
   - Dynamic USB fallback is eliminated for all serial UART devices (`/dev/serial0`, `/dev/ttyAMA0`, `/dev/serial*`).
   - Line 293 attribute typo is fixed to `self.connection_string`.
   - HEARTBEAT messages dynamically decode `msg.autopilot` and `msg.type`.
   - `MAVLINK_SIMULATE=false` strictly prevents switching to simulation on connection failure.
   - `Settings.validate_configuration()` rejects transport/connection mismatches, force-arming, and disabled arming checks.
2. All 119 automated tests pass cleanly with exit code 0.
3. The codebase is fully ready for Milestone M2 (Visualizations & Coverage Planner).

---

## 5. Verification Method

To independently verify this milestone:

1. **Run full automated pytest test suite**:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/ -v
   ```
   *Expected result*: 119 passed in ~17s with exit code 0.

2. **Run dedicated Milestone M1 unit test suite**:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m pytest tests/test_mavlink_uart_safety.py -v
   ```
   *Expected result*: 7 passed in ~10s with exit code 0.

3. **Verify compilation**:
   ```powershell
   & "C:\Users\IDEAL\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile backend/flight/mavlink_service.py config/settings.py tests/test_mavlink_uart_safety.py
   ```
   *Expected result*: Exit code 0 with no syntax or compilation errors.

4. **Inspect artifacts**:
   - `backend/flight/mavlink_service.py`: Inspect lines 42–117 (`decode_heartbeat_identity`), lines 345–385 (`_handle_heartbeat`), and lines 395–430 (`is_uart` check).
   - `config/settings.py`: Inspect lines 57–61 and 105–130 (`validate_configuration`).
   - `.env.example`: Inspect lines 35–60.
   - `tests/test_mavlink_uart_safety.py`: Inspect test cases 1 through 7.

5. **Invalidation Conditions**:
   - If `MAVLinkService(connection_string="/dev/serial0")` switches to `/dev/ttyACM*` when `/dev/serial0` is absent, this handoff is invalidated.
   - If an incoming HEARTBEAT with `autopilot=12, type=2` reports anything other than `"PX4"` and `"Quadrotor"`, this handoff is invalidated.
   - If `Settings.validate_configuration()` fails to raise `ValueError` when `MAVLINK_TRANSPORT="serial"` and `MAVLINK_CONNECTION="udpin:0.0.0.0:14550"`, this handoff is invalidated.
   - If any test in `pytest tests/` fails, this handoff is invalidated.
