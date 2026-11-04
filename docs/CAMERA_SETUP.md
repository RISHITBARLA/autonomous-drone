# Sony IMX477 Camera Setup Guide for Raspberry Pi 4

This document describes the physical installation, kernel configuration, and driver verification for the **Sony IMX477 High Quality (HQ) Camera** connected to the Raspberry Pi 4 companion computer.

---

## 1. Hardware Specifications

| Parameter | Specification |
|---|---|
| Sensor | Sony IMX477R Back-Illuminated CMOS |
| Resolution | 12.3 Megapixels (4056 × 3040) |
| Sensor Size | 7.9mm diagonal (Type 1/2.3) |
| Pixel Size | 1.55 µm × 1.55 µm |
| Lens Mount | C-mount and CS-mount (with supplied adapter) |
| Interface | MIPI CSI-2 (2-lane ribbon cable) |
| Default Capture Mode | 1920 × 1080 (30 FPS) |

---

## 2. Physical Connection to Raspberry Pi 4

> [!CAUTION]
> Always power off the Raspberry Pi 4 before connecting or disconnecting the CSI ribbon cable. Connecting or disconnecting while powered can damage the camera sensor or the Raspberry Pi CSI port.

1. Locate the **CSI camera port** on the Raspberry Pi 4 (located between the HDMI ports and the 3.5mm audio jack).
2. Gently lift the plastic collar/latch on the CSI connector vertically.
3. Insert the 15-pin ribbon cable:
   - **Silver contact pins:** Must face **towards the micro-HDMI ports**.
   - **Blue reinforcing strip:** Must face **towards the USB/Ethernet ports**.
4. Push the plastic collar down firmly until it clicks flat to lock the ribbon in place.
5. On the camera board end, connect the ribbon with contacts facing the camera board circuitry.

---

## 3. Kernel Configuration & Driver Setup

### Raspberry Pi OS (Bookworm / Bullseye 64-bit)

Modern Raspberry Pi OS uses **`libcamera`** and kernel device tree overlays.

1. Open the boot configuration file:
   ```bash
   sudo nano /boot/firmware/config.txt
   # On older Bullseye systems: sudo nano /boot/config.txt
   ```

2. Verify or add the IMX477 camera overlay:
   ```ini
   # Auto-detect cameras (default on Bookworm)
   camera_auto_detect=1

   # If camera_auto_detect does not load IMX477 automatically, add:
   dtoverlay=imx477
   ```

3. Ensure camera interface is enabled:
   ```bash
   sudo raspi-config
   # Navigate to: Interface Options -> Camera -> Enable -> Reboot
   ```

4. Reboot the companion computer:
   ```bash
   sudo reboot
   ```

---

## 4. Hardware Verification Commands

After rebooting, verify that the sensor is detected by the Linux kernel:

1. **Query libcamera / rpicam devices:**
   ```bash
   rpicam-hello --list-cameras
   # or
   libcamera-hello --list-cameras
   ```
   *Expected output:*
   ```text
   Available cameras
   -----------------
   0 : imx477 [4056x3040] (/base/soc/i2c0mux/i2c@1/imx477@1a)
       Modes: 'SRGGB10_CSI2P' : 1332x990 [120.05 fps - (760, 526)/2536x1980 crop]
                              : 2028x1080 [50.03 fps - (0, 440)/4056x2160 crop]
                              : 2028x1520 [40.01 fps - (0, 0)/4056x3040 crop]
                              : 4056x3040 [10.00 fps - (0, 0)/4056x3040 crop]
   ```

2. **Test snapshot capture with rpicam-still:**
   ```bash
   rpicam-still -o test_imx477.jpg --width 1920 --height 1080
   ```

3. **Verify V4L2 device nodes:**
   ```bash
   v4l2-ctl --list-devices
   ```

---

## 5. Troubleshooting Common Issues

| Issue | Cause | Solution |
|---|---|---|
| `no cameras available` | Ribbon cable orientation inverted | Ensure silver pins face micro-HDMI ports; blue strip faces Ethernet/USB. |
| `Device or resource busy` | Another process is holding the camera open | Terminate conflicting process: `sudo fuser /dev/video* -k`. |
| Black or extremely dark frames | Missing lens or aperture ring closed | Ensure CS-mount lens aperture is opened; focus ring calibrated. |
| Kernel driver not loaded | `dtoverlay=imx477` missing in config.txt | Add `dtoverlay=imx477` to `/boot/firmware/config.txt` and reboot. |
