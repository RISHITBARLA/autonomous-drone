# AUTONOMOUS-DRONE

Autonomous QR Code Detection, Computer Vision, MAVLink Telemetry, and Mission-Based Drone Platform for Raspberry Pi 4 Companion Computer and Pixhawk 2.4.8 Flight Controller.

---

## 1. Hardware Architecture
- **Companion Computer:** Raspberry Pi 4 Model B (High-level vision, QR detection, mission state machine, web ground station)
- **Flight Controller:** Pixhawk 2.4.8 running ArduPilot/PX4 (Low-level stabilization, motor control, GPS navigation)
- **Airframe:** S500 Quadcopter Frame with Brushless Motors & 4S ESCs
- **Primary Vision Sensor:** Sony IMX477 12.3MP High Quality Camera (MIPI CSI-2 ribbon)
- **Navigation:** Pixhawk-compatible GPS/Compass Module
- **Telemetry:** MAVLink bidirectional serial bridge (TELEM2 UART @ 57600 baud)

---

## 2. Technology Stack
- **Backend:** Python 3.10+, Flask, REST APIs, JSON
- **Computer Vision:** OpenCV, libcamera/Picamera2, NumPy, Pillow, qrcode
- **Flight Controller Communication:** MAVLink 2.0, pymavlink
- **System Monitoring:** psutil, Linux `/sys` thermal zones, `vcgencmd`
- **Frontend Ground Station:** HTML5, Modern CSS3 (Glassmorphic Cyber-Aerospace design), Modern ES6 JavaScript
- **Testing:** pytest, pytest-cov, unittest, Mock hardware interfaces

---

## 3. Project Directory Structure
```text
AUTONOMOUS-DRONE/
├── backend/
│   ├── app.py                      # Main Flask application, blueprint registry & shutdown hooks
│   ├── system/                     # Companion system telemetry & hardware metrics
│   │   ├── hardware_info.py        # Raspberry Pi & host detection, SoC & CPU info
│   │   ├── health_monitor.py       # CPU, RAM, Disk, Uptime metrics
│   │   └── temperature.py          # Thermal zone & vcgencmd throttling monitor
│   ├── camera/                     # Camera management & Sony IMX477 driver
│   │   ├── camera_config.py        # Configurable resolution, framerate, rotation & parameters
│   │   ├── camera_detector.py      # CSI-2 / V4L2 probe & backend recommendation
│   │   └── camera_manager.py       # Libcamera, OpenCV, & Mock frame engine with concurrency lock
│   ├── vision/                     # Computer vision & QR code detection (Milestone 02)
│   │   ├── qr_detector.py          # Multi-QR detector & decoder with bounding box geometry
│   │   └── vision_service.py       # Background worker thread, duplicate cooldown, history buffer
│   ├── flight/                     # Pixhawk telemetry & flight control (Milestones 03 & 07)
│   │   ├── mavlink_service.py      # Read-only MAVLink telemetry bridge & simulated drone physics
│   │   └── flight_controller.py    # Isolated flight controller (disabled by default for safety)
│   ├── mission/                    # Autonomous mission control (Milestone 04)
│   │   ├── mission_model.py        # Waypoint & Mission models, explicit FSM transitions
│   │   └── mission_service.py      # CRUD, JSON persistence, and safe QR mission association
│   ├── geofence/                   # Boundary validation & safety (Milestone 05)
│   │   └── geofence_service.py     # Circular & polygon fences, ray-casting, navigation metrics
│   └── api/                        # REST API blueprints
│       ├── health_routes.py        # System health & hardware endpoints
│       ├── camera_routes.py        # Camera status, capture, list, & MJPEG stream endpoints
│       ├── vision_routes.py        # QR detection controls, latest hits, history, image uploads
│       ├── telemetry_routes.py     # Drone connection status, GPS, battery, attitude
│       ├── mission_routes.py       # Mission CRUD, FSM state changes, QR association
│       ├── geofence_routes.py      # Geofence boundary parameters, point check, plan preview
│       └── flight_routes.py        # Arm, mode, takeoff, land, RTL endpoints (isolated)
├── frontend/                       # Ground Station Web Dashboard
│   ├── index.html                  # Responsive 7-tab ground station UI
│   ├── css/dashboard.css           # Glassmorphic cyber-aerospace stylesheet
│   └── js/dashboard.js             # Telemetry controller, radar canvas, & interactive actions
├── config/                         # Centralized configuration & logging
│   ├── settings.py                 # Application settings with .env loading
│   └── logging_config.py           # Rotating file & console logging
├── data/                           # Persistent JSON storage for missions & geofence (.gitkeep)
├── captures/                       # Persisted camera snapshots (.gitkeep)
├── logs/                           # System rotating logs (.gitkeep)
├── systemd/                        # Production systemd service unit
│   └── autonomous-drone.service    # Auto-start daemon on Raspberry Pi 4
├── docs/                           # Comprehensive engineering documentation
│   ├── ARCHITECTURE.md             # Complete system architecture & data flows
│   ├── INSTALLATION.md             # Setup guide for Windows & Raspberry Pi 4
│   ├── CAMERA_SETUP.md             # Sony IMX477 installation & troubleshooting
│   ├── API.md                      # Complete REST API reference
│   ├── FLIGHT_CONTROL.md           # Flight control isolation & safety documentation
│   └── TROUBLESHOOTING.md          # Diagnostic runbook for camera, telemetry, and power
├── tests/                          # Automated unit, integration, & E2E tests (91/91 pass)
├── requirements.txt                # Pinned Python dependencies
├── .env.example                    # Environment configuration template
└── README.md
```

---

## 4. Development Status & Milestone Roadmap

| Milestone | Subsystem | Status | Verification |
|---|---|:---:|---|
| **Milestone 01** | **Raspberry Pi System & Camera Integration** | **Completed** | **Verified (37/37 unit tests pass)** |
| **Milestone 02** | **Computer Vision & QR Detection** | **Completed** | **Verified (13/13 QR tests pass)** |
| **Milestone 03** | **Pixhawk & MAVLink Telemetry** | **Completed** | **Verified (10/10 telemetry tests pass)** |
| **Milestone 04** | **Mission Management & QR Association** | **Completed** | **Verified (11/11 mission tests pass)** |
| **Milestone 05** | **Geofence & Navigation Planning** | **Completed** | **Verified (9/9 geofence tests pass)** |
| **Milestone 06** | **Web Ground Station Full Suite** | **Completed** | **Verified (7-tab connected UI)** |
| **Milestone 07** | **Isolated Flight-Control Subsystem** | **Completed** | **Verified (7/7 flight tests pass)** |
| **Milestone 08** | **End-to-End Integration & Reliability** | **Completed** | **Verified (4/4 E2E integration tests pass)** |
| **Milestone 09** | **Production Deployment & Documentation** | **Completed** | **Verified (Systemd service & 6 guides)** |

---

## 5. Quickstart Guide

### Development & Testing on Windows PC (Simulation Mode)
```powershell
# 1. Install dependencies
py -3.10 -m pip install -r requirements.txt

# 2. Run complete test suite (91 passing automated tests)
py -3.10 -m pytest -v

# 3. Start companion server
py -3.10 backend/app.py
```
Open your browser to: `http://localhost:5000`

### Production Deployment on Raspberry Pi 4
```bash
# 1. Clone repository on Raspberry Pi
cd ~
git clone https://github.com/laxminivas06/AUTONOMOUS-DRONE.git
cd AUTONOMOUS-DRONE

# 2. Set up virtual environment
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment for physical hardware
cp .env.example .env
nano .env

# 4. Run test suite
pytest -v

# 5. Enable and start auto-start service
sudo cp systemd/autonomous-drone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autonomous-drone
sudo systemctl start autonomous-drone
```
Access the Ground Station at `http://<RASPBERRY_PI_IP>:5000`.

---

## 6. Complete Documentation Directory
- [System Architecture](docs/ARCHITECTURE.md)
- [Installation & Deployment Guide](docs/INSTALLATION.md)
- [Sony IMX477 Camera Setup Guide](docs/CAMERA_SETUP.md)
- [REST API Reference](docs/API.md)
- [Flight Control & Pixhawk Safety Guide](docs/FLIGHT_CONTROL.md)
- [Troubleshooting & Diagnostics Guide](docs/TROUBLESHOOTING.md)
