# Pixhawk Flight-Control Subsystem & Safety Guide

## 1. Safety Principles & Architectural Isolation

The flight-control module in **AUTONOMOUS-DRONE** is strictly isolated from sensor monitoring, computer vision, and ground station rendering:
1. **Disabled by Default:** The subsystem requires explicit operational opt-in via `FLIGHT_CONTROL_ENABLED=true` in `.env`. Out of the box, all command endpoints reject requests with HTTP 403 Forbidden.
2. **No Implicit Triggers:** Computer vision detections, QR code parsing, telemetry updates, or page reloads will **never** trigger flight commands.
3. **No Automatic Arming:** The system will never arm the vehicle without an explicit, direct operator request.
4. **Firmware Pre-Arm Authority:** The companion computer does not bypass or override Pixhawk internal failsafes. All pre-arm requirements (gyro calibration, compass health, GPS 3D lock, battery safety, and RC link) are evaluated by the Pixhawk firmware itself.

---

## 2. Hardware Architecture & Pinout

```text
Raspberry Pi 4 (Companion)               Pixhawk 2.4.8 (Flight Controller)
+-------------------------+              +--------------------------------+
| GPIO 14 (TXD)           | ------------>| TELEM2 RX                      |
| GPIO 15 (RXD)           | <------------| TELEM2 TX                      |
| Ground (GND)            | ------------>| TELEM2 GND                     |
+-------------------------+              +--------------------------------+
```

### Serial Parameters
- **Port on Raspberry Pi 4:** `/dev/ttyAMA0` (Primary PL011 UART)
- **Baud Rate:** `57600` or `115200` baud (8 data bits, 1 stop bit, no parity)
- **Protocol:** MAVLink 2.0

### Pixhawk Parameter Configuration (via Mission Planner / QGroundControl)
- `SERIAL2_PROTOCOL = 2` (MAVLink 2)
- `SERIAL2_BAUD = 57` (57600 baud) or `115` (115200 baud)
- `ARMING_CHECK = 1` (All pre-arm checks enabled: compass, accelerometer, barometer, GPS)

---

## 3. Operational Workflow for Flight Commands

When physical flight operations are scheduled:

1. **Safety Pre-Checks:**
   - Confirm propellers are removed during initial bench testing.
   - Confirm Pixhawk safety switch is pressed (solid red light).
   - Confirm GPS 3D Fix with at least 10 visible satellites and HDOP < 1.5.
   - Confirm 4S LiPo battery voltage is above 15.0V.

2. **Enable Flight Control via Environment:**
   In `.env`:
   ```bash
   FLIGHT_CONTROL_ENABLED=true
   MAVLINK_SIMULATE=false
   MAVLINK_CONNECTION_STRING=/dev/ttyAMA0
   MAVLINK_BAUDRATE=57600
   ```

3. **Command Execution Sequence:**
   - **Mode:** Switch to `GUIDED` or `LOITER`:
     ```bash
     curl -X POST http://<DRONE_IP>:5000/api/flight/mode -H "Content-Type: application/json" -d '{"mode": "GUIDED"}'
     ```
   - **Arm:** Request arming (Pixhawk evaluates pre-arm checks):
     ```bash
     curl -X POST http://<DRONE_IP>:5000/api/flight/arm
     ```
   - **Takeoff:** Issue takeoff to designated hover altitude:
     ```bash
     curl -X POST http://<DRONE_IP>:5000/api/flight/takeoff -H "Content-Type: application/json" -d '{"altitude_m": 5.0}'
     ```
   - **RTL:** In any contingency, trigger Return-to-Launch:
     ```bash
     curl -X POST http://<DRONE_IP>:5000/api/flight/rtl
     ```

