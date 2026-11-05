# Handoff Report: Codebase & MAVLink Survey

**Agent**: Explorer 1 (`explorer_survey_1`)  
**Recipient**: Orchestrator (`6a5cd16c-9678-4d2e-a31f-58d1e6ab6706`)  
**Timestamp**: 2026-11-05T11:10:00Z  
**Type**: Hard Handoff (Investigation Complete)  
**Report Artifact**: `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\explorer_survey_1\survey_report.md`

---

## 1. Observation

### 1.1 Git Status & Commit History
- Command `git status`:
  - Current Branch: `main`, up to date with `origin/main` (`https://github.com/laxminivas06/AUTONOMOUS-DRONE/`).
  - HEAD Commit: `0190890a9df7ed6a2c1142c88a0082a3ee4c4ef8` (`chore: format deployment scripts`).
  - Unstaged modified files:
    - `backend/api/flight_routes.py`
    - `backend/flight/flight_controller.py`
    - `data/missions.json`
    - `frontend/index.html`
    - `frontend/js/dashboard.js`
    - `tests/test_flight_control_activation.py`
  - Untracked files/directories:
    - `.agents/`
    - `backend/search/` (containing `coverage_planner.py` and `__pycache__`)
    - `backups/` (containing `arm_disarm_controls_20261105/`)
    - `bject FullName` (16.6 KB artifact containing manual pages from PowerShell command redirect)

### 1.2 MAVLink Configuration & Fallback Code
- In `config/settings.py` (lines 57–63):
  ```python
  MAVLINK_TRANSPORT: str = os.getenv("MAVLINK_TRANSPORT", "udp").lower()
  MAVLINK_CONNECTION: str = os.getenv("MAVLINK_CONNECTION", os.getenv("MAVLINK_CONNECTION_STRING", "udpin:0.0.0.0:14550"))
  MAVLINK_CONNECTION_STRING: str = MAVLINK_CONNECTION  # Retained for backward compatibility
  MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "57600"))
  MAVLINK_HEARTBEAT_TIMEOUT: float = float(os.getenv("MAVLINK_HEARTBEAT_TIMEOUT", "5.0"))
  MAVLINK_SIMULATE: bool = os.getenv("MAVLINK_SIMULATE", "true").lower() in ("true", "1", "yes")
  ```
- In `.env.example`:
  ```ini
  MAVLINK_TRANSPORT=udp
  MAVLINK_CONNECTION=udpin:0.0.0.0:14550
  MAVLINK_CONNECTION_STRING=udpin:0.0.0.0:14550
  MAVLINK_BAUDRATE=57600
  MAVLINK_SIMULATE=true
  FLIGHT_CONTROL_ENABLED=false
  ARMING_CHECKS_ENABLED=true
  FORCE_ARM=false
  ```
- In `backend/flight/mavlink_service.py` (lines 280–295):
  ```python
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
  ```
- Line 293 assigns to `self._connection_string`, whereas the attribute initialized at line 104 and read throughout the class is `self.connection_string`.
- In `mavlink_service.py` (lines 334–351), `HEARTBEAT` sets `self._autopilot_type = "ArduPilot ArduCopter"` statically rather than parsing `msg.autopilot` or `msg.type`.

### 1.3 Safety Interlocks
- In `config/settings.py` (lines 84–93):
  ```python
  if cls.FORCE_ARM:
      raise ValueError("CRITICAL SAFETY VIOLATION: FORCE_ARM must never be enabled...")
  if not cls.ARMING_CHECKS_ENABLED:
      raise ValueError("CRITICAL SAFETY VIOLATION: ARMING_CHECKS_ENABLED cannot be disabled...")
  ```
- In `backend/flight/flight_controller.py` (lines 102–106 and 153–158):
  - Blocks when `not self.enabled` with code `CONTROL_DISABLED` (HTTP 403 in `flight_routes.py`).
  - Sets `param2=0.0` in `MAV_CMD_COMPONENT_ARM_DISARM` (never the 21196 force-arm magic number).

### 1.4 Test Suite Execution
- Command `pytest`:
  ```
  platform win32 -- Python 3.10.11, pytest-9.0.2, pluggy-1.6.0
  collected 112 items
  tests\test_api.py ...........                                            [  9%]
  tests\test_camera_manager.py ...........                                 [ 19%]
  tests\test_e2e_integration.py ....                                       [ 23%]
  tests\test_flight_control_activation.py .....................            [ 41%]
  tests\test_flight_controller.py .......                                  [ 48%]
  tests\test_geofence_service.py .........                                 [ 56%]
  tests\test_hardware_info.py .....                                        [ 60%]
  tests\test_health_monitor.py ..........                                  [ 69%]
  tests\test_mavlink_telemetry.py ..........                               [ 78%]
  tests\test_mission_service.py ...........                                [ 88%]
  tests\test_qr_detector.py .............                                  [100%]
  ============================= 112 passed in 7.15s =============================
  ```

---

## 2. Logic Chain

1. **Safety Interlock Integrity**:
   - Observation 1.3 shows `Settings.validate_configuration()` immediately crashes the app if `ARMING_CHECKS_ENABLED=false` or `FORCE_ARM=true`.
   - Observation 1.3 shows `flight_controller.py` enforces `param2=0.0` and checks `self.enabled`.
   - Therefore, the codebase guarantees that physical arming commands cannot be force-armed and that disabled controls strictly prevent flight operations.

2. **GPIO UART vs USB Fallback**:
   - Observation 1.2 shows that `mavlink_service.py` currently inspects `dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))` and reassigns `target_conn`.
   - Requirement R1 explicitly demands: *"prevent automatic USB fallback or silent switching into simulation when the physical port is unavailable"*.
   - Therefore, this USB fallback block must be conditionally disabled or guarded when UART serial communication (`/dev/serial0`) is requested, ensuring the driver retries `/dev/serial0` without switching ports.

3. **Serial Resolution & Settings Configuration**:
   - Observation 1.2 shows default `MAVLINK_TRANSPORT="udp"`, `MAVLINK_CONNECTION="udpin:0.0.0.0:14550"`, and `MAVLINK_BAUDRATE=57600`.
   - On the Raspberry Pi, TELEM2 GPIO UART operates at 115200 baud over `/dev/serial0`.
   - `config/settings.py` correctly aliases `MAVLINK_CONNECTION_STRING = MAVLINK_CONNECTION`.
   - Therefore, setting `MAVLINK_TRANSPORT=serial`, `MAVLINK_CONNECTION=/dev/serial0`, `MAVLINK_CONNECTION_STRING=/dev/serial0`, and `MAVLINK_BAUDRATE=115200` in `.env` on the Raspberry Pi will cause `settings.MAVLINK_CONNECTION` to resolve cleanly without configuration drift.

4. **Preservation of Unstaged Modifications**:
   - Observation 1.1 reveals uncommitted changes in `flight_routes.py`, `flight_controller.py`, `dashboard.js`, `index.html`, and `test_flight_control_activation.py`.
   - Observation 1.4 confirms all 112 tests pass with these changes active.
   - Inspecting the diff shows they implement mandatory safety features: confirmation for disarming, operator audit tracking, concurrency locks, and real heartbeat state verification.
   - Requirement R3 forbids destructive git commands (`git reset --hard`).
   - Therefore, these uncommitted changes are valid, safe, and must be preserved during deployment synchronization.

5. **Map & Heatmap Restoration Pathway**:
   - Observation 1.1 shows `backend/search/coverage_planner.py` exists as an untracked file.
   - It provides `GeofenceCoveragePlanner` with full Boustrophedon sweep and `get_coverage_snapshot()`.
   - The frontend already has `#geofenceCanvas` in `frontend/index.html` rendering 2D boundaries and waypoints.
   - Therefore, connecting `GeofenceCoveragePlanner` to a REST endpoint and adding a mode toggle on `#geofenceCanvas` completely fulfills Requirement R4 without fabricating data or introducing third-party map dependencies.

---

## 3. Caveats

1. **Hardware Telemetry on Windows vs Raspberry Pi**:
   - Testing on Windows runs with `MAVLINK_SIMULATE=true` because no physical Pixhawk or `/dev/serial0` hardware port is attached.
   - Final validation of real Pixhawk 2.4.8 TELEM2 UART communication, 115200 baud compatibility, and `dialout` group permissions must be verified on the Raspberry Pi (`192.168.10.235`).
2. **Firmware Parameter Accessibility**:
   - As noted in R1, TELEM2 baud rate is expected to be 115200 (SERIAL2_BAUD = 115). If the Pixhawk firmware parameters cannot be safely read over MAVLink due to companion permissions, the limitation should be reported rather than guessing.

---

## 4. Conclusion

1. **Environment State**: Windows environment is fully operational with 112/112 tests passing. All safety checks and interlocks are functioning as designed.
2. **MAVLink UART Readiness**:
   - Deployment to Raspberry Pi requires configuring `.env` with `MAVLINK_TRANSPORT=serial`, `MAVLINK_CONNECTION=/dev/serial0`, `MAVLINK_CONNECTION_STRING=/dev/serial0`, `MAVLINK_BAUDRATE=115200`, `MAVLINK_SIMULATE=false`, `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`.
   - `mavlink_service.py` requires removing the automatic USB fallback so `/dev/serial0` failure retries the serial device instead of jumping to `/dev/ttyACM0`.
   - Typo in `mavlink_service.py:293` (`self._connection_string`) should be fixed.
3. **Map Restoration**: `backend/search/coverage_planner.py` provides the exact coverage engine needed for R4.

---

## 5. Verification Method

1. **Automated Test Suite**:
   ```powershell
   pytest
   ```
   *Expected outcome*: 112 passed in ~7s.
2. **MAVLink Connection & Safety Verification**:
   Inspect `config/settings.py` and `backend/flight/mavlink_service.py` to confirm:
   - `MAVLINK_CONNECTION_STRING` resolves to `MAVLINK_CONNECTION`.
   - `ARMING_CHECKS_ENABLED=False` or `FORCE_ARM=True` raises `ValueError` in `Settings.validate_configuration()`.
   - `_run_mavlink_stream()` does not switch to USB when `target_conn == "/dev/serial0"`.
3. **Report Verification**:
   Review detailed report at `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\explorer_survey_1\survey_report.md`.
