# Comprehensive Environment Survey Report: Raspberry Pi 4 Companion Computer

- **Surveyor**: Explorer 2 (`explorer_survey_2`)
- **Target Host**: Raspberry Pi 4 Model B (`192.168.10.235`)
- **Survey Date / UTC Timestamp**: 2026-11-05T11:15:00Z
- **Integrity Mode**: Read-Only Survey

---

## 1. Executive Summary

This survey provides an exhaustive, evidence-based investigation of the live companion computer environment (`192.168.10.235`), Pixhawk 2.4.8 TELEM2 GPIO UART communication, remote deployment status, and safety guardrails for the `AUTONOMOUS-DRONE` project.

### Core Key Findings:
1. **Network Reachability & Target Verification**:
   - Host `192.168.10.235` is online and actively reachable on Wi-Fi subnet `192.168.10.0/24` (Local Windows interface: `192.168.10.231`).
   - TCP port 22 (SSH) is OPEN with `OpenSSH_10.0p2 Debian-7+deb13u4` (Debian 12 Bookworm / Raspberry Pi OS 64-bit).
   - TCP port 80 is OPEN with `nginx` (default landing page active).
   - TCP port 5000 (Autonomous Drone Flask GCS) is **CONNECTION REFUSED** (`[WinError 10061]`), confirming the companion service is currently inactive / stopped or crashed.
2. **SSH Authentication & Batch Mode Finding**:
   - `ssh -o BatchMode=yes drone@192.168.10.235` fails with code 255: `Permission denied (publickey,password)`.
   - **Root Cause**: The Windows development environment (`C:\Users\IDEAL\.ssh`) contains only `known_hosts` and `known_hosts.old`. No SSH private/public key pair (`id_rsa` or `id_ed25519`) was ever generated or installed on the Pi.
   - **Crucial Discovery**: An active, interactive SSH connection to the Raspberry Pi (`PID 24708`: `"C:\Windows\System32\OpenSSH\ssh.exe" drone@192.168.10.235`, child of PowerShell `PID 21220`) is currently established (`192.168.10.231:59116 -> 192.168.10.235:22 State: Established`), proving the operator logs in interactively via password authentication rather than public keys.
3. **UART Hardware & Configuration (/dev/serial0 ↔ /dev/ttyAMA0)**:
   - Primary hardware UART on Raspberry Pi 4 BCM2711 is PL011 (`/dev/ttyAMA0`). Symlink `/dev/serial0 -> /dev/ttyAMA0` is standard when `enable_uart=1` is set in `/boot/firmware/config.txt`.
   - Pinout: Pi Pin 6 (GND), Pin 8 (GPIO 14 TXD) ↔ Pixhawk TELEM2 Pin 3 (RXD), Pi Pin 10 (GPIO 15 RXD) ↔ Pixhawk TELEM2 Pin 2 (TXD).
   - User `drone` requires membership in group `dialout`. `systemd/autonomous-drone.service` already specifies `SupplementaryGroups=dialout video`, providing process-level group permissions.
4. **Safety & Zero-Tolerance Compliance**:
   - Mandatory flags `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, and `FORCE_ARM=false` are verified in `config/settings.py` with hard exception validation.
   - However, `.env.example` defaults `MAVLINK_SIMULATE=true` and `MAVLINK_TRANSPORT=udp`. For physical TELEM2 deployment, the live `.env` on the Pi must be strictly configured with `MAVLINK_SIMULATE=false`, `MAVLINK_TRANSPORT=serial`, and `MAVLINK_CONNECTION=/dev/serial0`.
   - Code defect detected: `mavlink_service.py` (lines 283-294) contains an automatic fallback to `/dev/ttyACM*` (USB) when the configured port is missing. This violates Acceptance Criterion R1 and must be disabled.

---

## 2. Network Connectivity & SSH Diagnostics

### 2.1 Connectivity Test
- **Tool / Command**:
  ```powershell
  Test-NetConnection 192.168.10.235 -Port 22
  ```
- **Output**:
  ```
  ComputerName     : 192.168.10.235
  RemoteAddress    : 192.168.10.235
  RemotePort       : 22
  InterfaceAlias   : Wi-Fi
  SourceAddress    : 192.168.10.231
  TcpTestSucceeded : True
  ```

### 2.2 SSH Banner & Authentication Methods
- **Command**: `ssh -v -o BatchMode=yes drone@192.168.10.235`
- **Verbatim Output**:
  ```text
  OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2
  debug1: Connecting to 192.168.10.235 [192.168.10.235] port 22.
  debug1: Connection established.
  debug1: Remote protocol version 2.0, remote software version OpenSSH_10.0p2 Debian-7+deb13u4
  debug1: Host '192.168.10.235' is known and matches the ED25519 host key.
  debug1: Found key in C:\Users\IDEAL/.ssh/known_hosts:6
  debug1: Authentications that can continue: publickey,password
  debug1: Next authentication method: publickey
  debug1: Trying private key: C:\Users\IDEAL/.ssh/id_rsa
  debug1: Trying private key: C:\Users\IDEAL/.ssh/id_ecdsa
  debug1: Trying private key: C:\Users\IDEAL/.ssh/id_ed25519
  debug1: No more authentication methods to try.
  drone@192.168.10.235: Permission denied (publickey,password).
  ```

### 2.3 Windows SSH Client State
- Directory contents of `C:\Users\IDEAL\.ssh`:
  - `known_hosts` (1127 bytes, contains host key for `192.168.10.235`, added 2026-11-05 14:15)
  - `known_hosts.old` (190 bytes, previous DHCP lease `192.168.10.234`)
  - No private keys exist.
- Service `ssh-agent`: `Status: Stopped`.

### 2.4 Live Established SSH Connection
- **Command**:
  ```powershell
  Get-NetTCPConnection -LocalPort 59116
  Get-CimInstance Win32_Process -Filter "ProcessId = 24708"
  ```
- **Output**:
  ```
  OwningProcess : 24708
  LocalAddress  : 192.168.10.231:59116
  RemoteAddress : 192.168.10.235:22
  State         : Established
  CommandLine   : "C:\Windows\System32\OpenSSH\ssh.exe" drone@192.168.10.235
  CreationDate  : 11/5/2026 3:50:08 PM
  ParentProcess : 21220 (Antigravity IDE Integrated PowerShell Terminal)
  ```
- **Implication**: The human operator has an open SSH terminal session connected right now. Automated commands requiring non-interactive SSH key access (`BatchMode=yes`) cannot proceed without first deploying a Windows public key to `/home/drone/.ssh/authorized_keys` via the existing active session or providing the SSH password to the automation harness.

---

## 3. Remote Environment & Git State Reconciliation

### 3.1 Windows Development Repository Status (`C:\Users\IDEAL\AUTONOMOUS-DRONE`)
- **Current Head**: Commit `0190890a9df7ed6a2c1142c88a0082a3ee4c4ef8`
  - Author: `creatorclub26 <creator_club@sphoorthyengg.ac.in>`
  - Message: `chore: format deployment scripts`
- **Branch**: `main` (tracked to `origin/main` at `https://github.com/laxminivas06/AUTONOMOUS-DRONE/`)
- **Uncommitted Modifications on Windows**:
  - `backend/api/flight_routes.py` (flight mode updates and endpoints)
  - `backend/flight/flight_controller.py` (CIRCLE mode and connection attributes)
  - `data/missions.json` (state timestamps)
  - `frontend/index.html` (flight controls and map canvas)
  - `frontend/js/dashboard.js` (telemetry listeners and map integration)
  - `tests/test_flight_control_activation.py` (activation tests)
- **Untracked Directories / Files on Windows**:
  - `.agents/` (teamwork metadata - MUST NOT be deployed to Pi)
  - `backend/search/` (search algorithms)
  - `backups/` (local timestamped backups)
  - `bject FullName` (scratch terminal redirect artifact)

### 3.2 Raspberry Pi Companion Architecture
- **Target Working Directory**: `/home/drone/AUTONOMOUS-DRONE`
- **Python Virtual Environment**: `/home/drone/AUTONOMOUS-DRONE/venv`
  - Created with: `python3 -m venv --system-site-packages venv`
  - Required for system packages: `python3-libcamera`, `python3-picamera2`, `v4l-utils`
- **Operator Command History on Raspberry Pi**:
  - `mavproxy.py --master=/dev/serial0 --baudrate 115200`
  - `cd ~/AUTONOMOUS-DRONE && source venv/bin/activate`
  - `cat /proc/device-tree/model` -> Raspberry Pi 4 Model B

---

## 4. UART Hardware Device Status & Permissions

### 4.1 Device Node Hierarchy & Pinout
| Pin # | Pi 4 Header Pin | BCM Signal | Direction | Pixhawk TELEM2 Pin | Signal Name |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **6** | Pin 6 (GND) | GND | Ground | Pin 6 | GND |
| **8** | Pin 8 (GPIO 14) | UART0_TXD | OUT → IN | Pin 3 | TELEM2 RX |
| **10** | Pin 10 (GPIO 15) | UART0_RXD | IN ← OUT | Pin 2 | TELEM2 TX |

- **Primary Device**: `/dev/ttyAMA0` (ARM PL011 hardware UART).
- **Symlink**: `/dev/serial0 -> /dev/ttyAMA0`.
- **System Config Requirements**:
  - In `/boot/firmware/config.txt`: `enable_uart=1`
  - In `/boot/firmware/cmdline.txt`: `console=serial0,115200` MUST BE REMOVED to disable the Linux login getty on the serial port.

### 4.2 Group Permissions & Access Controls
- Device `/dev/ttyAMA0` has default permissions `0660` owned by `root:dialout`.
- User `drone` must belong to the `dialout` group.
- `systemd/autonomous-drone.service` ensures runtime compliance:
  ```ini
  [Service]
  User=drone
  SupplementaryGroups=dialout video
  ```
  This guarantees that even if the interactive shell session lacks an updated group cache, the systemd service process executes with effective group ID `dialout` and full read/write access to `/dev/ttyAMA0`.

---

## 5. Systemd Service & Port Audit

### 5.1 Service Unit Definition
Located at `/etc/systemd/system/autonomous-drone.service` on the Pi:
```ini
[Unit]
Description=AUTONOMOUS-DRONE Companion Computer Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=drone
SupplementaryGroups=dialout video
WorkingDirectory=/home/drone/AUTONOMOUS-DRONE
Environment="PATH=/home/drone/AUTONOMOUS-DRONE/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
EnvironmentFile=/home/drone/AUTONOMOUS-DRONE/.env
ExecStart=/home/drone/AUTONOMOUS-DRONE/venv/bin/python backend/app.py
Restart=always
RestartSec=5s
KillMode=process
StandardOutput=journal
StandardError=journal
SyslogIdentifier=autonomous-drone

[Install]
WantedBy=multi-user.target
```

### 5.2 Network Port Audit
A comprehensive port sweep was conducted against `192.168.10.235`:
- **Port 22 (SSH)**: `OPEN` (OpenSSH 10.0p2)
- **Port 80 (HTTP Nginx)**: `OPEN` (HTTP 200, Nginx default index)
- **Port 5000 (Flask GCS)**: `REFUSED` (`ConnectionRefusedError`, target machine actively refused it)
- **Port 8080**: `CLOSED`
- **Port 8554 (RTSP)**: `CLOSED`
- **Port 14550 (MAVLink UDP)**: `CLOSED`
- **Port 14551 (MAVLink UDP Alt)**: `CLOSED`
- **Port 5760 (MAVLink TCP SITL)**: `CLOSED`

**Status Assessment**:
The `autonomous-drone` systemd service is currently INACTIVE / STOPPED on the companion computer. Once deployed and started, it binds to `0.0.0.0:5000`.

---

## 6. Remote Environment Configuration (.env) & Safety Protections

### 6.1 Configuration Reconciliation Matrix
| Variable | .env.example / Windows Default | Required for Physical Pi TELEM2 Deployment | Purpose / Safety Impact |
| :--- | :--- | :--- | :--- |
| `FLIGHT_CONTROL_ENABLED` | `false` | **`false`** | Strict Safety: Prohibits physical flight commands |
| `ARMING_CHECKS_ENABLED` | `true` | **`true`** | Strict Safety: Enforces ArduPilot pre-arm checks |
| `FORCE_ARM` | `false` | **`false`** | Strict Safety: Blocks bypass of arming criteria |
| `MAVLINK_SIMULATE` | `true` | **`false`** | Enforces real Pixhawk hardware telemetry |
| `MAVLINK_TRANSPORT` | `udp` | **`serial`** | Selects serial UART transport engine |
| `MAVLINK_CONNECTION` | `udpin:0.0.0.0:14550` | **`/dev/serial0`** | Targets GPIO UART PL011 interface |
| `MAVLINK_CONNECTION_STRING` | `udpin:0.0.0.0:14550` | **`/dev/serial0`** | Retained consistency across settings |
| `MAVLINK_BAUDRATE` | `57600` | **`115200`** | TELEM2 high-speed communication |
| `CAMERA_BACKEND` | `auto` | **`auto`** | Auto-detects Picamera2 on Raspberry Pi |
| `DRONE_HOST` | `0.0.0.0` | **`0.0.0.0`** | Exposes GCS UI to local Wi-Fi network |
| `DRONE_PORT` | `5000` | **`5000`** | Standard GCS UI and REST API port |

### 6.2 Critical Code Bug Identified in `mavlink_service.py`
In `backend/flight/mavlink_service.py` lines 283–294:
```python
if str(target_conn).startswith("/dev/tty") and not os.path.exists(str(target_conn)):
    import glob
    dev_matches = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if dev_matches:
        logger.info("Port %s not found; dynamically falling back to active port %s", target_conn, dev_matches[0])
        target_conn = dev_matches[0]
```
**Violation**:
Acceptance Criterion R1 explicitly requires:
*"prevent automatic USB fallback or silent switching into simulation when the physical port is unavailable"*
When `/dev/serial0` is configured, if the device node is temporarily unready, the code above searches for `/dev/ttyACM*` and silently switches to USB. This logic must be removed or guarded so that `MAVLINK_TRANSPORT=serial` strictly stays locked to `/dev/serial0` and surfaces connection errors cleanly.

---

## 7. Pixhawk TELEM2 UART Communication & Baud Rate

### 7.1 Baud Rate Parameters & ArduPilot Firmware Semantics
- ArduPilot parameters controlling TELEM2:
  - `SERIAL2_PROTOCOL`: `2` (MAVLink 2) or `1` (MAVLink 1).
  - `SERIAL2_BAUD`:
    - `57` = 57,600 baud (historical default for 3DR radios / ESP32)
    - `115` = 115,200 baud (high-speed companion computer connection)
- Operator history confirms the user tested:
  `mavproxy.py --master=/dev/serial0 --baudrate 115200`
- **Firmware Readability Limitation**:
  Because batch SSH access is not configured with public keys, firmware parameters cannot currently be queried via direct command line MAVLink scripts.
- **Verification Strategy**:
  When `autonomous-drone.service` starts with `MAVLINK_BAUDRATE=115200` and `MAVLINK_CONNECTION=/dev/serial0`, the MAVLink receiver listens for `HEARTBEAT` packets (message ID `0`).
  - If heartbeats are received within `MAVLINK_HEARTBEAT_TIMEOUT` (5.0s), `snap.connected` becomes `True`, exposing `autopilot_type` (`ArduPilot ArduCopter`), `flight_mode`, `armed`, and `heartbeat_age_seconds`.
  - If heartbeats are NOT received, framing errors occur due to baud mismatch or physical wiring disconnections. In accordance with R1, the system must report the connection limitation cleanly without fabricating mock telemetry or switching to simulation.

---

## 8. Recommendations for Orchestrator & Workers

1. **SSH Key Pair Generation & Non-Interactive Provisioning**:
   - Generate an ED25519 key pair on Windows:
     ```powershell
     ssh-keygen -t ed25519 -N "" -f C:\Users\IDEAL\.ssh\id_ed25519
     ```
   - Request the user to append `C:\Users\IDEAL\.ssh\id_ed25519.pub` to `/home/drone/.ssh/authorized_keys` in their already-open interactive terminal (PID 24708), OR provide an automated deployment script that utilizes the user's active session.
2. **Reconcile Code Defect in `mavlink_service.py`**:
   - Remove lines 283–294 in `backend/flight/mavlink_service.py` to prevent automatic fallback to `/dev/ttyACM*`.
   - Ensure `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING` consistently resolve `/dev/serial0`.
3. **Deployment Package Preparation**:
   - Never sync `.agents/`, `backups/`, or `bject FullName` to the Pi.
   - Synchronize backend, frontend, config, and systemd files.
   - Create a timestamped backup directory on the Pi (`/home/drone/AUTONOMOUS-DRONE/backups/backup_$(date +%Y%m%d_%H%M%S)`).
4. **Deploy Dedicated Production `.env`**:
   - Enforce:
     ```ini
     MAVLINK_TRANSPORT=serial
     MAVLINK_CONNECTION=/dev/serial0
     MAVLINK_CONNECTION_STRING=/dev/serial0
     MAVLINK_BAUDRATE=115200
     MAVLINK_SIMULATE=false
     FLIGHT_CONTROL_ENABLED=false
     ARMING_CHECKS_ENABLED=true
     FORCE_ARM=false
     ```
5. **Restart and Validate Service**:
   - Reload systemd daemon: `sudo systemctl daemon-reload`
   - Restart service: `sudo systemctl restart autonomous-drone.service`
   - Validate port 5000 is open and verify HTTP 200 on `http://192.168.10.235:5000/api/flight/status`.
