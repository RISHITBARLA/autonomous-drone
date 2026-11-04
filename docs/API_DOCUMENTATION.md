# AUTONOMOUS-DRONE REST API Documentation

This document specifies the REST API exposed by the Raspberry Pi companion computer for ground station telemetry and camera control.

**Base URL:** `http://<DRONE_IP>:5000/api`

---

## 1. System Health & Hardware Endpoints

### 1.1 Full System Health
- **Endpoint:** `GET /api/health`
- **Query Parameters:**
  - `mock` *(optional, boolean)*: Set to `true` to return simulated Raspberry Pi 4 specifications on development hosts.
- **Description:** Returns comprehensive companion computer metrics including CPU cores, RAM breakdown, disk utilization, thermal status, throttling bitmask, and uptime.
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "timestamp": 1793610613.38,
      "overall_status": "HEALTHY",
      "healthy": true,
      "warnings": [],
      "cpu": {
        "usage_percent": 14.2,
        "per_core_percent": [12.0, 15.1, 14.5, 15.0],
        "physical_cores": 4,
        "logical_cores": 4,
        "frequency": {
          "current_mhz": 1500.0,
          "min_mhz": 600.0,
          "max_mhz": 1800.0
        }
      },
      "memory": {
        "total_gb": 3.79,
        "used_gb": 0.84,
        "available_gb": 2.95,
        "usage_percent": 22.1
      },
      "disk": {
        "mount_path": "/",
        "total_gb": 29.1,
        "used_gb": 4.2,
        "free_gb": 23.5,
        "usage_percent": 15.1
      },
      "temperature": {
        "celsius": 46.5,
        "fahrenheit": 115.7,
        "status": "NORMAL",
        "is_mocked": false,
        "throttling": {
          "available": true,
          "under_voltage_detected": false,
          "currently_throttled": false
        }
      },
      "uptime": {
        "uptime_seconds": 12450,
        "formatted": "3h 27m 30s"
      }
    }
  }
  ```

### 1.2 Telemetry Summary
- **Endpoint:** `GET /api/health/summary`
- **Description:** Lightweight telemetry designed for high-frequency dashboard polling.
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "overall_status": "HEALTHY",
      "healthy": true,
      "cpu_percent": 14.2,
      "ram_percent": 22.1,
      "disk_percent": 15.1,
      "temperature_c": 46.5,
      "uptime_formatted": "3h 27m 30s",
      "warnings": []
    }
  }
  ```

### 1.3 Hardware Information
- **Endpoint:** `GET /api/health/hardware`
- **Description:** Returns Raspberry Pi model, revision, processor SoC, OS release, and serial number.
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "is_raspberry_pi": true,
      "device": {
        "model": "Raspberry Pi 4 Model B Rev 1.4",
        "soc": "BCM2711",
        "revision": "c03114",
        "serial_number": "10000000a1b2c3d4",
        "hostname": "drone-companion"
      },
      "os": {
        "system": "Linux",
        "release": "6.1.0-rpi7-rpi-v8",
        "distribution": "Debian GNU/Linux 12 (bookworm)"
      }
    }
  }
  ```

### 1.4 Thermal & Throttling Status
- **Endpoint:** `GET /api/health/temperature`
- **Description:** Detailed temperature and power throttle diagnostics.

---

## 2. Camera Management & Vision Endpoints

### 2.1 Camera Status
- **Endpoint:** `GET /api/camera/status`
- **Description:** Probes camera hardware, active backend driver, resolution, and error history.
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "data": {
      "connected": true,
      "active_backend": "libcamera",
      "sensor_model": "Sony IMX477 High Quality Camera",
      "is_mock": false,
      "total_frames_generated": 1420,
      "config": {
        "width": 1920,
        "height": 1080,
        "preview_width": 640,
        "preview_height": 480,
        "framerate": 30
      },
      "latest_capture": { ... },
      "error_count": 0,
      "recent_errors": []
    }
  }
  ```

### 2.2 Trigger Snapshot Capture
- **Endpoint:** `POST /api/camera/capture`
- **Description:** Immediately acquires a full-resolution frame from the camera and persists it to `captures/`.
- **Response `201 Created`:**
  ```json
  {
    "status": "success",
    "message": "Image captured successfully",
    "data": {
      "filename": "capture_20261102_144144_179063.jpg",
      "filepath": "/home/drone/AUTONOMOUS-DRONE/captures/capture_20261102_144144_179063.jpg",
      "relative_url": "/api/camera/image/capture_20261102_144144_179063.jpg",
      "timestamp": 1793611304.179,
      "iso_time": "2026-11-02T14:41:44.179063",
      "width": 1920,
      "height": 1080,
      "size_kb": 78.6,
      "backend": "libcamera",
      "sensor": "Sony IMX477 High Quality Camera"
    }
  }
  ```

### 2.3 Latest Capture Metadata
- **Endpoint:** `GET /api/camera/latest`
- **Description:** Returns the metadata of the most recent photo capture.

### 2.4 List Captures
- **Endpoint:** `GET /api/camera/list?limit=20`
- **Description:** Lists captured images sorted newest first.

### 2.5 Serve Image File
- **Endpoint:** `GET /api/camera/image/<filename>`
- **Description:** Streams image file with `Content-Type: image/jpeg`. Protected against path traversal.

### 2.6 Live MJPEG Video Stream
- **Endpoint:** `GET /api/camera/stream`
- **Description:** Multipart live video stream (`multipart/x-mixed-replace; boundary=frame`) for low-latency browser preview.

### 2.7 Update Camera Configuration
- **Endpoint:** `POST /api/camera/config`
- **Payload:**
  ```json
  {
    "width": 1920,
    "height": 1080,
    "framerate": 30,
    "jpeg_quality": 95
  }
  ```
