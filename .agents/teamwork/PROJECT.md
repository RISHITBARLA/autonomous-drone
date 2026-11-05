# Project: AUTONOMOUS-DRONE Live Synchronization & Deployment

## Architecture
- **Companion Hardware Platform**: Raspberry Pi 4 Model B (Debian 12 Bookworm, IP `192.168.10.235`).
- **Autopilot Hardware**: Pixhawk 2.4.8 running ArduPilot Copter firmware connected via TELEM2.
- **Physical UART Interconnect**:
  - Pixhawk TELEM2 Pin 2 (TX) ↔ Raspberry Pi Pin 10 (GPIO 15 / RXD / `/dev/ttyAMA0`)
  - Pixhawk TELEM2 Pin 3 (RX) ↔ Raspberry Pi Pin 8 (GPIO 14 / TXD / `/dev/ttyAMA0`)
  - Pixhawk TELEM2 Pin 6 (GND) ↔ Raspberry Pi Pin 6 (GND)
  - Device Symlink: `/dev/serial0` points to `/dev/ttyAMA0`
  - Access Permissions: `drone:dialout` via `systemd/autonomous-drone.service` (`SupplementaryGroups=dialout video`)
- **Backend Architecture**:
  - Python 3.10 Flask REST & WebSocket Ground Control Station (GCS).
  - `MAVLinkService`: Async worker streaming telemetry via `pymavlink`, handling heartbeats, telemetry snapshots, and stream rate controls.
  - `CoveragePlanner`: Metric grid discretization, camera footprint projection, and live observation intensity.
  - `FlightController`: Safety interlocks, command serialization, mode switching, and arming checks.
- **Frontend Architecture**:
  - Single Page Application (`frontend/index.html`, `frontend/js/dashboard.js`, `frontend/css/dashboard.css`).
  - Offline HTML5 2D Canvas Visualizer (`#geofenceCanvas`) supporting dual visualization modes: Normal Map and Heatmap Coverage.
  - Cache-busted asset delivery via Flask response headers and versioned asset URL query parameters.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | MAVLink Serial UART Resolution | Enforce `/dev/serial0` resolution across `.env`, `settings.py`, and `mavlink_service.py` at 115200 baud | M1 | R1, Survey |
| 2 | Eliminate USB Dynamic Fallback | Remove automatic dynamic fallback to `/dev/ttyACM*`/`/dev/ttyUSB*` when serial UART is configured | M1 | R1, Survey |
| 3 | MAVLink Service Attribute Bug Fix | Correct `self._connection_string` typo to `self.connection_string` | M1 | Survey |
| 4 | Dynamic Autopilot & Vehicle Decoding | Decode `msg.autopilot` and `msg.type` from HEARTBEAT instead of static string | M1 | R1, Survey |
| 5 | Strict Safety Interlocks Enforcement | Enforce `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, `MAVLINK_SIMULATE=false`, `FORCE_ARM=false` | M1 | R2, Survey |
| 6 | Coverage Planner API Endpoint | Expose `backend/search/coverage_planner.py` via `GET /api/geofence/coverage` and integrate live GPS updates | M2 | R4, Survey |
| 7 | Normal Map Canvas Enhancements | Render geofence, search boundary, GPS telemetry marker, heading vector, breadcrumbs, and disconnected HUD | M2 | R4, Survey |
| 8 | Heatmap Canvas Rendering | Render genuine metric grid coverage intensity and observation hot spots without fabricated data | M2 | R4, Survey |
| 9 | Map Mode UI Toggle | Provide clean segmented toggle between Normal Map and Heatmap without JavaScript console errors | M2 | R4, Survey |
| 10 | Frontend Asset Cache-Busting | Add Flask `@app.after_request` cache headers and `?v=20261105.1` query strings | M2 | R6, Survey |
| 11 | Git Workspace Reconciliation & Hygiene | Stage and commit uncommitted safety features, track `coverage_planner.py`, clean stray artifacts | M3 | R3, Survey |
| 12 | Deployment Packaging & Verification | Package verified files, calculate SHA256 hashes, prepare timestamped backup on Pi | M3 | R3, R5 |
| 13 | Service Restart & Health Verification | Restart `autonomous-drone.service`, verify journal logs, validate HTTP 200 on `/` and `/api/flight/status` | M3 | R5, Survey |
| 14 | Opaque-Box E2E Test Suite | Build comprehensive 4-Tier requirement-driven opaque-box test suite (`TEST_INFRA.md`) | E2E | Dual Track |
| 15 | System Integration & Final Reporting | Execute full test suites, verify hardware separation, compile Sections A-G final report | M4 | R7 |

## Code Layout
- `backend/`: Python backend services, routes, and utilities.
  - `backend/app.py`: Application entry point, static proxy, cache headers.
  - `backend/api/`: REST API blueprints (`flight_routes.py`, `geofence_routes.py`, `health_routes.py`, `hardware_routes.py`, `mission_routes.py`).
  - `backend/flight/`: Flight controller and MAVLink telemetry engine (`flight_controller.py`, `mavlink_service.py`).
  - `backend/search/`: Coverage planner and search algorithms (`coverage_planner.py`).
- `config/settings.py`: Central configuration and startup safety validation.
- `frontend/`: Static frontend web dashboard.
  - `frontend/index.html`: Dashboard UI layout and canvas containers.
  - `frontend/js/dashboard.js`: Dashboard state management, telemetry ingestion, canvas rendering.
  - `frontend/css/dashboard.css`: Dark-theme responsive styling.
- `systemd/`: Service and udev configuration (`autonomous-drone.service`, `99-pixhawk.rules`).
- `tests/`: Automated pytest unit, integration, and E2E test suite.
- `.env`: Environment variables and hardware configuration.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | MAVLink UART & Safety Interlocks | Features 1, 2, 3, 4, 5: `/dev/serial0` resolution, USB fallback removal, attribute fix, dynamic HEARTBEAT decoding, safety flags | none | DONE |
| M2 | Map & Heatmap Visualizations & Cache-Busting | Features 6, 7, 8, 9, 10: `coverage_planner.py` API, Normal Map HUD/breadcrumbs, Heatmap rendering, UI toggle, asset cache-busting | M1 | IN_PROGRESS |
| M3 | Environment Reconciliation & Deployment Staging | Features 11, 12, 13: Git clean commit, deployment packaging, hash manifests, Pi synchronization & service validation | M2 | PLANNED |
| E2E | Opaque-Box E2E Testing Track | Feature 14: Comprehensive 4-tier test suite (Tiers 1-4) published via `TEST_READY.md` | M1 (parallel) | IN_PROGRESS |
| M4 | Final Integration, Test Pass & Reporting | Feature 15: 100% E2E test verification, Windows/Pi test execution, Sections A-G final report | M3, E2E | PLANNED |

## Interface Contracts

### MAVLink Service ↔ Settings Contract
- `Settings.MAVLINK_CONNECTION` and `Settings.MAVLINK_CONNECTION_STRING` must strictly equal `"/dev/serial0"` when `MAVLINK_TRANSPORT="serial"`.
- `Settings.MAVLINK_SIMULATE` must be `False` for live hardware deployment.
- `Settings.FLIGHT_CONTROL_ENABLED` must be `False` by default.
- `Settings.ARMING_CHECKS_ENABLED` must be `True`.

### Coverage Planner ↔ Telemetry Ingestion Contract
- In `backend/flight/mavlink_service.py`:
  ```python
  def _handle_gps_raw_int(self, msg):
      lat = msg.lat / 1e7
      lon = msg.lon / 1e7
      alt = msg.alt / 1000.0
      if lat != 0.0 and lon != 0.0:
          coverage_planner.update_drone_position(lat, lon, alt)
  ```
- Endpoint `GET /api/geofence/coverage` returns:
  ```json
  {
    "status": "success",
    "total_area_m2": 4500.0,
    "scanned_area_m2": 1350.0,
    "coverage_pct": 30.0,
    "scanned_cells_count": 135,
    "total_cells_count": 450,
    "scanned_points": [{"lat": 37.4093, "lon": -122.0641, "intensity": 1.0}]
  }
  ```

### Frontend Map Visualizer Contract
- DOM element `#btnMapNormal` sets `dashboard.mapMode = 'normal'` and triggers `renderGeofenceCanvas()`.
- DOM element `#btnMapHeatmap` sets `dashboard.mapMode = 'heatmap'` and triggers `renderGeofenceCanvas()`.
- When MAVLink disconnected or GPS fix lost: render canvas HUD overlay without throwing exceptions.

