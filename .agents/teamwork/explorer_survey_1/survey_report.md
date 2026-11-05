# Codebase & MAVLink Survey Report

**Explorer**: Explorer 1 (Codebase & MAVLink Surveyor)  
**Date**: 2026-11-05  
**Working Directory**: `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\explorer_survey_1\`  
**Target Environment**: Windows Development Environment (`C:\Users\IDEAL\AUTONOMOUS-DRONE`) & Raspberry Pi Live Deployment Target (`192.168.10.235`)

---

## Executive Summary

A comprehensive investigation of the Windows development environment and codebase was conducted. The repository is on branch `main` at commit `0190890a9df7ed6a2c1142c88a0082a3ee4c4ef8`. The working directory contains unstaged, high-value safety improvements in `backend/api/flight_routes.py`, `backend/flight/flight_controller.py`, `frontend/index.html`, `frontend/js/dashboard.js`, and `tests/test_flight_control_activation.py`, all of which pass 100% of the 112 automated unit and integration tests. 

Key architectural observations include:
1. **MAVLink Transport & Serial Resolution**: Currently, `config/settings.py` and `.env.example` default to `MAVLINK_TRANSPORT=udp` and `udpin:0.0.0.0:14550`. For Raspberry Pi TELEM2 GPIO UART operation, `MAVLINK_TRANSPORT=serial`, `MAVLINK_CONNECTION=/dev/serial0`, `MAVLINK_CONNECTION_STRING=/dev/serial0`, and `MAVLINK_BAUDRATE=115200` must be consistently set.
2. **MAVLink Fallback Logic**: `backend/flight/mavlink_service.py` currently contains dynamic USB fallback logic (`glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")`) which contradicts Requirement R1 (*"prevent automatic USB fallback or silent switching into simulation when the physical port is unavailable"*). Furthermore, a variable naming bug was discovered at line 293 (`self._connection_string = target_conn` instead of `self.connection_string = target_conn`).
3. **Heartbeat & Telemetry Exposure**: Heartbeat reception updates armed status and flight mode, but autopilot type is hardcoded to `"ArduPilot ArduCopter"` rather than parsed from MAVLink `HEARTBEAT.autopilot` and `HEARTBEAT.type`. All required fields are present in `/api/flight/status`.
4. **Safety Interlocks**: `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, and `FORCE_ARM=false` are verified across the codebase. Startup checks in `config/settings.py` enforce `ARMING_CHECKS_ENABLED=true` and prevent `FORCE_ARM`.
5. **Map & Heatmap Foundations**: Untracked module `backend/search/coverage_planner.py` contains a complete `GeofenceCoveragePlanner` that generates real coverage metrics and scanned grid points, ready for restoration on the frontend dashboard.
6. **Test Suite**: Pytest executes 112 tests across 11 test modules in 7.15 seconds with zero failures.

---

## 1. Git Repository State Analysis

### 1.1 Branch and Commit Information
- **Current Branch**: `main`
- **Tracking Branch**: `origin/main` (`https://github.com/laxminivas06/AUTONOMOUS-DRONE/`)
- **HEAD Commit Hash**: `0190890a9df7ed6a2c1142c88a0082a3ee4c4ef8`
- **HEAD Commit Message**: `chore: format deployment scripts`

### 1.2 Recent Commit History (Last 10 Commits)
| Commit Hash | Author Date / Message |
|-------------|-----------------------|
| `0190890` | `chore: format deployment scripts` |
| `cb6ec2d` | `feat: add 1-command deployment script, CIRCLE mode, and persistent udev rules` |
| `5ccdd79` | `feat: add enable-arming-checks script and API route for safe outdoor flight` |
| `ae995b8` | `feat: add 1-click UI button and API endpoint to disable pre-arm and safety switch checks for bench testing` |
| `72f71f0` | `fix: add missing import os and glob in mavlink_service.py` |
| `95e0319` | `fix: dynamic fallback between /dev/ttyACM0 and /dev/ttyACM1 if port re-enumerates` |
| `e019365` | `fix: auto-detect pixhawk serial port in disable_arming_checks script` |
| `0d3b33c` | `feat: add indoor bench-testing script to disable ARMING_CHECK and FENCE_ENABLE` |
| `2c8e72a` | `fix: start mavlink and vision services in app.py; add GCS heartbeat and stream request` |
| `5a5761c` | `fix: bind endpoint display and default UI connection to /dev/ttyACM0` |

### 1.3 Changes Not Staged for Commit (Uncommitted Modifications)
The working tree contains carefully crafted, uncommitted safety enhancements:

1. **`backend/api/flight_routes.py`**:
   - Added `_check_operator_auth(req)` supporting `OPERATOR_TOKEN` via `X-Operator-Token` header.
   - Enforced confirmation and audit parameter `operator` on `/api/flight/disarm`.
   - Handled `COMMAND_IN_PROGRESS` returning HTTP 409 Conflict.
2. **`backend/flight/flight_controller.py`**:
   - Added concurrency locking via `self._action_in_progress` to prevent simultaneous command races.
   - Enhanced `request_arm()` to support disarm confirmation and operator parameter tracking.
   - Exposed `last_command` in `get_status()`.
3. **`data/missions.json`**:
   - Mission persistence storage updates.
4. **`frontend/index.html`**:
   - Added MAVLink connection status badge (`fcMavlinkConnBadge`) and active mode badge (`fcCurrentModeBadge`).
   - Added Safety Mandate Banner emphasizing propeller removal and safety check preservation.
   - Removed the bench-test 1-click button that disabled arming checks (`btnDisableArmingChecks`).
   - Added dedicated Motor Disarming Confirmation Modal (`disarmConfirmModal`) with mandatory checkbox.
   - Added `fcLastCommandBox` for immediate audit feedback.
5. **`frontend/js/dashboard.js`**:
   - Integrated confirmation modals for both ARM and DISARM.
   - Added heartbeat state verification polling (up to 8 attempts over 4 seconds) to ensure physical Pixhawk heartbeat confirmation before displaying success.
   - Added command pending flags preventing duplicate requests.
6. **`tests/test_flight_control_activation.py`**:
   - Added tests 18-21:
     - `test_18_disarm_requires_confirmation_when_enabled`
     - `test_19_operator_token_authorization`
     - `test_20_concurrent_command_locking`
     - `test_21_status_reports_last_command_and_heartbeat_state`

### 1.4 Untracked Files and Directories
- `.agents/`: Agent metadata and task documentation.
- `backend/search/coverage_planner.py`: Complete Boustrophedon sweep coverage planner and metric grid heatmap generator.
- `backups/arm_disarm_controls_20261105/`: Pre-modification backups of `dashboard.js`, `flight_controller.py`, `flight_routes.py`, `index.html`.
- `bject FullName`: Stray 16.6 KB artifact from PowerShell pipeline redirect (`less` command manual). Safe to clean up.

---

## 2. MAVLink Configuration & Safety Architecture

### 2.1 Configuration Mapping
| Parameter | Default in `config/settings.py` | Template `.env.example` | Target Pi Deployment (`.env`) |
|-----------|----------------------------------|-------------------------|-------------------------------|
| `MAVLINK_TRANSPORT` | `"udp"` | `udp` | `serial` |
| `MAVLINK_CONNECTION` | `"udpin:0.0.0.0:14550"` | `udpin:0.0.0.0:14550` | `/dev/serial0` |
| `MAVLINK_CONNECTION_STRING`| Alias to `MAVLINK_CONNECTION` | `udpin:0.0.0.0:14550` | `/dev/serial0` |
| `MAVLINK_BAUDRATE` | `57600` | `57600` | `115200` |
| `MAVLINK_HEARTBEAT_TIMEOUT` | `5.0` | `5.0` | `5.0` |
| `MAVLINK_SIMULATE` | `true` | `true` | `false` |
| `FLIGHT_CONTROL_ENABLED` | `false` | `false` | `false` |
| `ARMING_CHECKS_ENABLED` | `true` | `true` | `true` |
| `FORCE_ARM` | `false` | `false` | `false` |

### 2.2 GPIO UART Device Resolution on Raspberry Pi
- **Physical Pins**: Pin 8 (GPIO 14 / TXD), Pin 10 (GPIO 15 / RXD), Pin 6 (GND).
- **Device Symlink**: On Raspberry Pi OS with primary UART enabled (`enable_uart=1` in `/boot/config.txt`), `/dev/serial0` is a symlink pointing directly to `/dev/ttyAMA0` (PL011 hardware UART) or `/dev/ttyS0` (mini UART).
- **Group Permissions**: User `drone` must belong to group `dialout` to access `/dev/ttyAMA0` (`crw-rw---- 1 root dialout`). In `systemd/autonomous-drone.service`, line 9 specifies `SupplementaryGroups=dialout video`, satisfying this requirement.

### 2.3 Fallback Logic Analysis in `backend/flight/mavlink_service.py`
In `backend/flight/mavlink_service.py`, lines 280–295 contain the following logic:
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
                self._connection_string = target_conn  # Bug: attribute is self.connection_string
```

**Deficiencies & Risks**:
1. **Violation of R1 Acceptance Criteria**: This logic automatically falls back to USB (`/dev/ttyACM*` or `/dev/ttyUSB*`). If TELEM2 GPIO UART is selected, it must NOT fall back to USB or change devices silently.
2. **Variable Mismatch**: Line 293 writes to `self._connection_string`, whereas lines 104, 281, 460, and 513 read/write `self.connection_string`.
3. **Simulation Separation**: If connection fails, lines 305–310 catch `Exception`, set `self._connected = False`, and retry. It does NOT flip `self.simulate` to `True`. This correctly preserves separation between physical hardware and simulation.

### 2.4 Strict Safety Protections Review
1. **`FLIGHT_CONTROL_ENABLED`**:
   - `backend/api/flight_routes.py` blocks `/arm`, `/disarm`, `/mode`, `/takeoff`, `/rtl`, `/land` with HTTP 403 (`CONTROL_DISABLED`).
   - Verified by `test_01_disabled_by_default` and `test_02_http_403_when_disabled`.
2. **`ARMING_CHECKS_ENABLED`**:
   - `config/settings.py` `validate_configuration()` raises `ValueError` if `ARMING_CHECKS_ENABLED` is false.
   - Outdoor restoration script `scripts/enable_arming_checks.py` sets `ARMING_CHECK=1` and `BRD_SAFETYENABLE=1`.
3. **`FORCE_ARM` Prevention**:
   - `config/settings.py` raises `ValueError` if `FORCE_ARM` is true.
   - `FlightController.request_arm()` hardcodes `param2=0.0` (never passes 21196 force-arm magic value).
4. **Automatic Arming Guards**:
   - Verified that QR detection (`test_14_no_automatic_arming_from_qr_detection`) and mission activation (`test_15_no_automatic_arming_from_mission_association`) never trigger arming.
5. **Heartbeat Freshness**:
   - When heartbeat age exceeds 5.0s, `snap.is_stale` is set to `True`, `snap.connected` becomes `False`, and flight commands are rejected with `HEARTBEAT_STALE` or `NOT_CONNECTED`.

### 2.5 Heartbeat Handling and Telemetry APIs
1. **Heartbeat Ingestion (`mavlink_service.py:334-365`)**:
   - Extracts `custom_mode` and maps through `COPTER_MODES` dictionary.
   - Extracts `base_mode & 128` to determine armed state.
   - Sends GCS heartbeat every 1.0s to announce companion computer presence.
   - Requests telemetry data streams (`MAV_DATA_STREAM_ALL` at 4 Hz).
   - **Limitation**: `_autopilot_type` is currently hardcoded to `"ArduPilot ArduCopter"` rather than dynamically decoded from `msg.autopilot` (e.g. `MAV_AUTOPILOT_ARDUPILOTMEGA=3`, `MAV_AUTOPILOT_PX4=12`) and `msg.type` (e.g. `MAV_TYPE_QUADROTOR=2`).
2. **Exposed Fields in `/api/flight/status`**:
   - `flight_control_enabled`: boolean interlock state.
   - `connected`: active connection status.
   - `is_simulated`: boolean simulation indicator.
   - `connection_type`: `"SERIAL_UART"`, `"UDP_WIFI"`, or `"SIMULATION"`.
   - `connection_string`: active device path (e.g. `/dev/serial0`).
   - `baudrate`: active baud rate (e.g. `115200`).
   - `autopilot_type`: autopilot identifier.
   - `heartbeat_age_seconds`: elapsed seconds since last heartbeat.
   - `is_stale`: boolean freshness indicator.
   - `armed`: boolean armed status from heartbeat.
   - `flight_mode`: current mode string (e.g. `"ALT_HOLD"`, `"LOITER"`).
   - `target_mode`: default mode from settings.
   - `prearm_status`: `"PASSED"`, `"CHECKS_FAILED"`, `"READY"`, or `"STANDBY"`.
   - `prearm_messages`: list of recent pre-arm STATUSTEXT messages.
   - `last_command`: audit record of last command executed.

---

## 3. Test Suite & Validation Infrastructure

### 3.1 Test Architecture
The test suite consists of 11 unit and integration test files located in `tests/`:

| Test Module | Test Count | Scope & Coverage |
|-------------|------------|------------------|
| `test_api.py` | 11 | REST APIs: health, hardware, missions, geofence, camera |
| `test_camera_manager.py` | 11 | Camera lifecycle, mock backend, capture handling |
| `test_e2e_integration.py` | 4 | System startup, telemetry stream, mission upload, QR scan |
| `test_flight_controller.py` | 7 | FlightController unit tests, command history, disabled lock |
| `test_flight_control_activation.py` | 21 | Mandatory flight safety criteria (arm/disarm confirmation, 403, stale heartbeats, token auth, concurrency lock) |
| `test_geofence_service.py` | 9 | Geofence polygon ray-casting, circular fences, breach checks |
| `test_hardware_info.py` | 5 | Hardware metrics, CPU/RAM/disk, Raspberry Pi temperature |
| `test_health_monitor.py` | 10 | Background monitor thread, warning/critical thresholds |
| `test_mavlink_telemetry.py` | 10 | Telemetry snapshots, stale heartbeat detection, telemetry routes |
| `test_mission_service.py` | 11 | Mission model, waypoint schema validation, CRUD operations |
| `test_qr_detector.py` | 13 | QR barcode decoding, rate limiting, bounding coordinates |
| **Total** | **112** | **100% Passed in 7.15 seconds on Python 3.10.11 / Windows** |

### 3.2 Pytest Configuration & Dependencies
- **Pytest Version**: 9.0.2
- **Plugins**: `anyio-4.12.1`, `langsmith-0.7.25`, `asyncio-1.3.0`, `cov-7.0.0`
- **Root Directory**: `C:\Users\IDEAL\AUTONOMOUS-DRONE`
- **Execution Command**: `pytest`
- **Dependencies**: `Flask`, `Flask-Cors`, `python-dotenv`, `psutil`, `opencv-python`, `numpy`, `Pillow`, `qrcode`, `pymavlink`, `requests`.

---

## 4. Map & Heatmap Visualizations (R4) Analysis

### 4.1 Existing Frontend Canvas Radar/Map
- Located in `frontend/index.html` under `#pane-geofence` (`#geofenceCanvas`).
- Renders:
  - Range rings and radar crosshairs.
  - Designated circular or polygonal geofence boundaries (yellow dashed lines).
  - Mission waypoints sequence (magenta lines and markers with `#seq` labels).
  - Drone current GPS position (cyan dot) and heading vector.
  - Connected/stale/disconnected status.

### 4.2 Untracked Search & Heatmap Engine
- Located in `backend/search/coverage_planner.py`:
  - Implements `GeofenceCoveragePlanner` supporting arbitrary polygons, rectangles, and circles.
  - Discretizes geofences into metric grid cells (`grid_res=2.0` meters).
  - Tracks scanned cells via `update_drone_position()`.
  - Calculates Boustrophedon sweep and dynamic cluster search vectors.
  - Provides `get_coverage_snapshot()` exporting `total_area_m2`, `scanned_area_m2`, `coverage_pct`, and `scanned_points` for live heatmap generation.
- **Architectural Gap**: This module is not yet exposed via Flask API routes in `backend/app.py` or connected to dashboard map switching.

---

## 5. Architectural Recommendations for Implementation Agents

### Recommendation 1: MAVLink Service Hardening (`backend/flight/mavlink_service.py`)
1. **Remove Automatic USB Fallback for Serial Configurations**:
   When `self.connection_string` is configured for UART (`/dev/serial0` or `/dev/ttyAMA0`), do not search for or fall back to `/dev/ttyACM*` or `/dev/ttyUSB*`. If the port is not ready, continue retrying the designated serial device.
2. **Fix Class Attribute Typo**:
   Line 293: Change `self._connection_string = target_conn` to `self.connection_string = target_conn`.
3. **Dynamic Autopilot & Vehicle Type Decoding**:
   In `msg_type == "HEARTBEAT"`, inspect `msg.autopilot` (e.g. `MAV_AUTOPILOT_ARDUPILOTMEGA`, `MAV_AUTOPILOT_PX4`) and `msg.type` (e.g. `MAV_TYPE_QUADROTOR`) to populate `self._autopilot_type` and vehicle type dynamically.

### Recommendation 2: Configuration & Raspberry Pi `.env` Settings
Ensure `.env` on Raspberry Pi 4 is configured as follows:
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

### Recommendation 3: Normal Map & Heatmap Integration
1. Register a dedicated map API blueprint (`backend/api/map_routes.py` or within `geofence_routes.py`) that returns both the geofence geometry, telemetry position, and coverage snapshot from `GeofenceCoveragePlanner`.
2. In `frontend/index.html` and `dashboard.js`, add a clean toggle button (`Normal Map` / `Heatmap Coverage`) on the canvas visualizer.
   - **Normal Map mode**: Renders geofence boundary, waypoints, drone GPS position, and heading vector.
   - **Heatmap mode**: Renders grid cell coverage intensity (green/amber heat gradient for scanned cells, transparent/dark for unscanned), using real data from the coverage planner.

### Recommendation 4: Frontend Asset Cache-Busting (R6)
In `backend/app.py`, implement cache-control headers on static proxy responses (e.g., `Cache-Control: no-cache, must-revalidate` for `.js` and `.css` in development mode) and append version query strings to asset links in `index.html`:
```html
<script src="/js/dashboard.js?v=20261105.1"></script>
<link rel="stylesheet" href="/css/dashboard.css?v=20261105.1" />
```

### Recommendation 5: Git Tree Hygiene & Staging
1. Commit the existing uncommitted safety improvements (`flight_routes.py`, `flight_controller.py`, `index.html`, `dashboard.js`, `test_flight_control_activation.py`, `missions.json`) cleanly.
2. Track `backend/search/coverage_planner.py`.
3. Remove the stray shell artifact `bject FullName`.
