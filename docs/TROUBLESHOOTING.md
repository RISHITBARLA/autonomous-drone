# AUTONOMOUS-DRONE Troubleshooting & Diagnostics Guide

## 1. Camera & Vision Diagnostics

### Issue: "No physical camera detected (Mock Mode)"
- **Cause:** Raspberry Pi OS has not initialized the CSI camera overlay or camera is disconnected.
- **Resolution:**
  1. Power off Raspberry Pi: `sudo poweroff`
  2. Inspect the 15-pin ribbon cable: silver contacts towards HDMI ports, blue backing towards USB ports.
  3. Verify `/boot/firmware/config.txt` contains:
     ```ini
     camera_auto_detect=1
     dtoverlay=imx477
     ```
  4. Test detection using kernel utility:
     ```bash
     rpicam-hello --list-cameras
     ```

### Issue: "Libcamera acquisition failed" or low framerate
- **Resolution:**
  - Increase GPU memory if needed or ensure `python3-picamera2` is installed from apt:
    ```bash
    sudo apt install -y python3-libcamera python3-picamera2
    ```
  - Lower the streaming preview resolution via `POST /api/camera/config` (`preview_width: 640`, `preview_height: 480`).

---

## 2. Pixhawk MAVLink Telemetry Issues

### Issue: Telemetry displays "OFFLINE" or "STALE"
- **Cause:** No heartbeat packets received within `MAVLINK_HEARTBEAT_TIMEOUT` (5 seconds).
- **Diagnostics:**
  1. Verify UART wiring: Pi TX (GPIO 14) connects to Pixhawk RX; Pi RX (GPIO 15) connects to Pixhawk TX; GND to GND.
  2. Verify serial port permissions on Linux:
     ```bash
     sudo usermod -a -G dialout $USER
     ```
  3. Ensure serial console login is disabled in `raspi-config`:
     ```bash
     sudo raspi-config
     # Interface Options -> Serial Port -> Login shell: No -> Serial hardware enabled: Yes
     ```
  4. Test with raw MAVLink listener:
     ```bash
     python3 -m pymavlink.tools.mavproxy --master=/dev/ttyAMA0,57600
     ```

---

## 3. QR Detection & Computer Vision Troubleshooting

### Issue: QR codes in camera feed are not detecting
- **Resolution:**
  1. Check lighting and focus: The Sony IMX477 lens has manual focus and aperture adjustment rings. Loosen the thumbscrew and rotate the front ring until the image is sharp.
  2. Verify QR detector worker is active via `/api/vision/qr/status` or click "Start QR Detection" in the dashboard.
  3. Ensure QR code occupies at least 60x60 pixels in the frame.

### Issue: Repeated duplicate hits flooding logs
- **Resolution:**
  - Increase cooldown window in `.env`: `QR_COOLDOWN_SECONDS=5.0`.

---

## 4. Raspberry Pi Thermal & Power Alerts

### Issue: "Under-voltage power brownout detected"
- **Cause:** Power supply cannot supply consistent 5.1V / 3A to Raspberry Pi 4 under motor load.
- **Resolution:**
  - Do not power Raspberry Pi 4 directly from Pixhawk 5V rail.
  - Use a dedicated 5V/3A or 5V/5A switching BEC connected to the drone's 4S LiPo power distribution board.

### Issue: "High CPU temperature (> 75°C)"
- **Resolution:**
  - Install passive heatsink and 5V cooling fan on the Broadcom BCM2711 SoC.
  - Lower camera framerate or telemetry polling frequency in `.env`.

