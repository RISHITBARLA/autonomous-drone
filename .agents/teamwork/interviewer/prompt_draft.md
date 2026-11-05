Synchronize and deploy the AUTONOMOUS-DRONE application to the live Raspberry Pi 4 environment, configuring Pixhawk TELEM2 GPIO UART communication, restoring Normal Map and Heatmap visualizations on the dashboard, and ensuring all flight safety protections remain strictly enforced.

Working directory: c:\Users\IDEAL\AUTONOMOUS-DRONE
Integrity mode: development

## Requirements

### R1. GPIO UART MAVLink Configuration & Communication
Configure physical MAVLink communication to use the Raspberry Pi GPIO UART device (`/dev/serial0` pointing to `/dev/ttyAMA0`) via Pixhawk TELEM2 at physical pins 8 (TXD), 10 (RXD), and 6 (GND), keeping `MAVLINK_TRANSPORT=serial` and ensuring both `MAVLINK_CONNECTION` and `MAVLINK_CONNECTION_STRING` consistently resolve to `/dev/serial0`. Inspect and verify the Pixhawk TELEM2 baud rate (configured at 115200; inspect firmware parameters if safely readable, otherwise report the communication limitation without arbitrary guessing), prevent automatic USB fallback or silent switching into simulation when the physical port is unavailable, verify dialout group permissions for user `drone` to access `/dev/ttyAMA0`, and validate actual receipt of Pixhawk HEARTBEAT messages (exposing connection status, serial device, baud rate, heartbeat age, autopilot/vehicle type, flight mode, armed state, and pre-arm messages in API and dashboard).

### R2. Strict Safety Configuration & Protections
Back up `.env` on the Raspberry Pi and enforce `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, and `MAVLINK_SIMULATE=false`. Physical flight-control, arming, takeoff, motor commands, and autonomous missions are strictly prohibited; all existing arming confirmations, firmware pre-arm checks, and command auditing mechanisms must remain active and intact.

### R3. Environment Synchronization & Git State Reconciliation
Inspect and compare the Windows development environment (`C:\Users\IDEAL\AUTONOMOUS-DRONE`) and Raspberry Pi live deployment environment (`/home/drone/AUTONOMOUS-DRONE`), analyzing Git roots, commit hashes, uncommitted/untracked files, backend APIs, frontend assets, and caching behavior. Reconcile differences without deleting untracked files, running destructive git commands (`git reset --hard`, `git clean -fd`, `git pull`), or overwriting unmerged Pi features, producing a detailed synchronization report before deployment.

### R4. Normal Map & Heatmap Restoration
Restore the existing Normal Map and Heatmap visualization systems on the dashboard without fabricating data or replacing algorithms. The Normal Map must render designated geofences, drone position from real GPS telemetry, search boundaries, and mission info (or clear disconnected/waiting indicators when unavailable). The Heatmap must display search coverage and observation intensity from existing search algorithms/observations. Provide a clean UI switching interface between both maps while preserving existing dashboard controls, styling, and navigation.

### R5. Direct Raspberry Pi Deployment & Service Restart
Create a timestamped backup directory on the Raspberry Pi for all files to be replaced. Selectively deploy verified files from Windows to `/home/drone/AUTONOMOUS-DRONE` using shell SSH and SCP/SFTP commands (`ssh drone@192.168.10.235` using existing configured keys/credentials), verify transfer integrity via hashes, restart the `autonomous-drone` systemd service, verify service status and journal logs, and validate the live dashboard and API endpoints (`/api/flight/status`, map endpoints).

### R6. Frontend Asset Cache-Busting & Dashboard Verification
Implement appropriate cache-busting for versioned frontend assets (HTML, JavaScript, CSS) served by Flask to ensure the browser loads the latest assets without runtime errors or stale caching, verifying that map switching, maps, telemetry feeds, and controls operate properly.

### R7. Verification & Final Reporting
Execute existing test suites on Windows and Raspberry Pi (where dependencies allow). Produce a comprehensive final report covering root causes, files changed, hardware communication status (heartbeat, autopilot type, connection stability), map/heatmap restoration, deployment verification details, test results (unit, API, integration, hardware separation), and remaining physical verification checks.

## Acceptance Criteria

### MAVLink & Serial Communication
- [ ] `/dev/serial0` is configured as the active MAVLink connection and resolves consistently across `.env`, `config/settings.py`, and `mavlink_service.py` without falling back to USB `/dev/ttyACM0`.
- [ ] Physical connection failure does not silently activate simulation mode (`MAVLINK_SIMULATE=false` enforced).
- [ ] User `drone` has access to `/dev/ttyAMA0` via group `dialout`.
- [ ] An actual Pixhawk HEARTBEAT message is received and validated over TELEM2 UART, or the exact communication limitation is documented if firmware parameters are unreadable.
- [ ] Telemetry API (`/api/flight/status`) and dashboard expose connection status, serial port, baud rate, heartbeat reception/age, autopilot type, flight mode, and armed status.

### Safety Guardrails
- [ ] Raspberry Pi `.env` has `FLIGHT_CONTROL_ENABLED=false`, `ARMING_CHECKS_ENABLED=true`, and `MAVLINK_SIMULATE=false`.
- [ ] No arming, motor spinning, takeoff, or autonomous mission execution occurs during diagnostics and testing.
- [ ] Pre-arm checks and confirmation dialogs remain active.

### Environment Synchronization & Deployment
- [ ] Timestamped backup directory created on Raspberry Pi preserving all modified or replaced files.
- [ ] No untracked Pi files or independent local features are deleted or overwritten.
- [ ] Transferred files match Windows verified versions via file hashes.
- [ ] `autonomous-drone` service restarts cleanly without errors in `systemctl status` or `journalctl`.
- [ ] Live HTTP endpoints (`http://127.0.0.1:5000/` and `/api/flight/status`) respond with HTTP 200 and expected payload.

### Map & Heatmap Visualizations
- [ ] Normal Map displays geofence, search boundary, and telemetry position (or disconnected state if no GPS).
- [ ] Heatmap displays search coverage and observation intensity using existing algorithms without fabricated data.
- [ ] Dashboard provides working UI toggle between Normal Map and Heatmap without JavaScript console errors.
- [ ] Frontend assets load with cache-busting preventing stale browser cache.

### Verification & Testing
- [ ] Existing automated test suite passes via `pytest` in `tests/` in the Windows environment.
- [ ] Relevant tests execute and pass via `pytest` on the Raspberry Pi environment where dependencies permit.
- [ ] Final report delivered addressing all required sections (A through G).

## Verification Resources
- Test suite: Run `pytest` on tests located in `tests/` in the Windows environment and where feasible on the Raspberry Pi.
- Execution environment: Shell SSH and SCP/SFTP commands (`ssh drone@192.168.10.235` and `scp`) using existing configured keys/credentials.
