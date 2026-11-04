# AUTONOMOUS-DRONE Complete REST API Reference

Base URL: `http://<DRONE_IP>:5000/api`

---

## 1. System Health & Hardware Endpoints (`/api/health`)

- **`GET /api/health`**
  - Returns complete telemetry: CPU (cores, usage, load, frequency), Memory (total, used, swap), Disk (mount, total, free), Temperature (celsius, status, throttling bitmask), Uptime, and Hardware specs.
  - Supports `?mock=true`.
- **`GET /api/health/summary`**
  - High-frequency polling endpoint: CPU %, RAM %, Disk %, Temperature °C, overall status, and formatted uptime.
- **`GET /api/health/hardware`**
  - Hardware model, SoC, serial number, kernel release, OS distribution.
- **`GET /api/health/temperature`**
  - Temperature readings, safety status (`NORMAL`, `WARNING`, `CRITICAL`), and `vcgencmd get_throttled` bitmask breakdown.

---

## 2. Camera Management Endpoints (`/api/camera`)

- **`GET /api/camera/status`**
  - Returns camera connection state, active backend (`libcamera`, `opencv`, `mock`), sensor model, resolution, and error log.
- **`POST /api/camera/capture`**
  - Captures immediate high-resolution snapshot and saves to `captures/`.
  - Non-blocking lock prevents concurrent conflicting captures (returns HTTP 409 on conflict).
- **`GET /api/camera/latest`**
  - Metadata and relative URL of most recent capture.
- **`GET /api/camera/list?limit=20`**
  - Chronological list of saved snapshot files.
- **`GET /api/camera/image/<filename>`**
  - Securely serves saved JPEG images with path traversal protection.
- **`GET /api/camera/stream`**
  - Multipart MJPEG live video feed stream.
- **`POST /api/camera/config`**
  - Dynamically updates resolution (`width`, `height`), `framerate`, `rotation` (0, 90, 180, 270), and `jpeg_quality`.

---

## 3. Computer Vision & QR Detection Endpoints (`/api/vision/qr`)

- **`GET /api/vision/qr/status`**
  - Worker state (`running`), target FPS, scan count, detection count, and cooldown settings.
- **`POST /api/vision/qr/start`**
  - Starts continuous background QR detection thread from camera feed.
- **`POST /api/vision/qr/stop`**
  - Safely stops background detection thread.
- **`GET /api/vision/qr/latest`**
  - Returns most recently decoded QR target with bounding box, center coordinates, confidence score, and timestamp.
- **`GET /api/vision/qr/history?limit=20`**
  - Returns recent unique QR detections filtered by duplicate cooldown window.
- **`POST /api/vision/qr/clear`**
  - Clears history ring buffer and cooldown cache.
- **`POST /api/vision/qr/process-image`**
  - Decodes QR codes from uploaded file (`multipart/form-data`) or raw image bytes.

---

## 4. Pixhawk MAVLink Telemetry Endpoints (`/api/telemetry`)

- **`GET /api/telemetry/status`**
  - MAVLink link status (`connected`, `is_simulated`, `is_stale`, `heartbeat_age_seconds`), flight mode, armed state, and baudrate.
- **`GET /api/telemetry/current`**
  - Complete telemetry snapshot: GPS coordinates, fix type, satellites, heading, groundspeed, airspeed, climb rate, attitude angles, battery voltage, current draw, and percentage.
- **`GET /api/telemetry/gps`**
  - Dedicated GPS navigation state (latitude, longitude, relative/MSL altitude, satellites, HDOP).
- **`GET /api/telemetry/battery`**
  - 4S LiPo telemetry (voltage, current, remaining percentage, safety status).
- **`GET /api/telemetry/attitude`**
  - Roll, pitch, yaw, heading, and climb rate.
- **`POST /api/telemetry/connection`**
  - Reconfigures MAVLink endpoint (`connection_string`, `baudrate`, `simulate`).

---

## 5. Mission Management Endpoints (`/api/missions`)

- **`GET /api/missions`**
  - Lists all configured missions and reports `active_mission_id`.
- **`POST /api/missions`**
  - Creates a new mission record. Validates all waypoints.
- **`GET /api/missions/active`**
  - Retrieves currently selected active mission.
- **`POST /api/missions/active`**
  - Sets active mission by ID (`{"mission_id": "..."}`).
- **`GET /api/missions/<id>`**
  - Retrieves specific mission details and waypoint sequence.
- **`PUT /api/missions/<id>`**
  - Updates mission parameters and waypoints.
- **`DELETE /api/missions/<id>`**
  - Removes a mission from persistent storage.
- **`POST /api/missions/<id>/state`**
  - Transitions mission through FSM: `CREATED`, `VALIDATED`, `READY`, `EXECUTING`, `PAUSED`, `COMPLETED`, `CANCELLED`.
- **`POST /api/missions/associate-qr`**
  - Safely parses QR payload (`MISSION:<id>` or JSON), matches against validated stored missions, and activates matching mission.

---

## 6. Geofence & Boundary Endpoints (`/api/geofence`)

- **`GET /api/geofence`**
  - Current geofence geometry (`circular` or `polygon`), center coordinates, radius, vertices, and altitude limits.
- **`POST /api/geofence`**
  - Updates and persists geofence parameters.
- **`POST /api/geofence/check-point`**
  - Tests whether a point (`lat`, `lon`, `alt_m`) violates horizontal or vertical boundaries.
- **`POST /api/geofence/validate-mission/<id>`**
  - Audits all waypoints of a mission against the geofence.
- **`POST /api/geofence/plan-preview`**
  - Computes path length in meters, estimated flight duration, and boundary compliance for an arbitrary waypoint sequence.

---

## 7. Flight Control Subsystem Endpoints (`/api/flight`)

> [!WARNING]
> Flight commands are **disabled by default** (`FLIGHT_CONTROL_ENABLED=false`).
> When disabled, all command endpoints immediately return HTTP 403 Forbidden.
> Normal arming always evaluates ArduPilot firmware pre-arm safety checks. FORCE_ARM is never used.

- **`GET /api/flight/status`**
  - Safety interlock status (`flight_control_enabled`), vehicle connection state, hardware type (`is_simulated`, `connection_type`), autopilot identity (`autopilot_type`), heartbeat freshness (`heartbeat_age_seconds`, `is_stale`), armed state, flight mode, target mode (`ALT_HOLD`), pre-arm checks status (`prearm_status`, `prearm_messages`), and supported modes.
- **`POST /api/flight/arm`**
  - Sends normal arm command (`MAV_CMD_COMPONENT_ARM_DISARM`, `param1=1.0`, `param2=0.0`) to Pixhawk.
  - Requires explicit operator confirmation in body: `{"confirm": true}` (returns HTTP 400 `CONFIRMATION_REQUIRED` if omitted).
  - Waits for armed state confirmation from heartbeat; reports detailed pre-arm rejection reasons from Pixhawk `STATUSTEXT` if rejected.
- **`POST /api/flight/disarm`**
  - Sends normal disarm command (`MAV_CMD_COMPONENT_ARM_DISARM`, `param1=0.0`, `param2=0.0`) to Pixhawk and confirms disarmed state.
- **`POST /api/flight/mode`**
  - Requests ArduCopter flight mode transition (`{"mode": "ALT_HOLD" | "STABILIZE" | "LOITER" | "GUIDED" | "AUTO" | "RTL" | "LAND" | "POSHOLD" | "BRAKE"}`).
  - Maps `ALT_HOLD` to custom mode ID 2 and verifies mode change via heartbeat.
- **`GET /api/flight/prearm-messages`**
  - Retrieves circular buffer of recent Pixhawk `STATUSTEXT` messages filtered to pre-arm diagnostics.
- **`POST /api/flight/connect`**
  - Initiates connection to MAVLink endpoint (`connection_string`, `baudrate`, `simulate`).
- **`POST /api/flight/disconnect`**
  - Safely terminates MAVLink telemetry worker thread.
- **`POST /api/flight/takeoff`**
  - Requests takeoff to target altitude (`{"altitude_m": 5.0}`).
- **`POST /api/flight/rtl`**
  - Requests Return-to-Launch.
- **`POST /api/flight/land`**
  - Requests vehicle auto-land.
- **`GET /api/flight/command-log`**
  - Audit history of all issued flight commands, timestamps, parameters, and outcomes.

