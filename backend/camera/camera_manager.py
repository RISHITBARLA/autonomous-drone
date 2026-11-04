"""
Camera Management Subsystem for AUTONOMOUS-DRONE.
Provides unified interface across Raspberry Pi Libcamera/Picamera2,
OpenCV VideoCapture, and high-fidelity Mock Drone Camera.
"""
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import cv2
import numpy as np

from config.settings import settings
from config.logging_config import setup_logging
from .camera_config import CameraConfig
from .camera_detector import CameraDetector

logger = setup_logging("camera_manager")


class CameraManager:
    """Manages camera lifecycle, frame capture, image storage, and telemetry overlays."""

    def __init__(self, config: Optional[CameraConfig] = None):
        self.config = config or CameraConfig.from_settings()
        self._lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._active_backend: str = "mock"
        self._connected: bool = False
        self._sensor_name: str = "Unknown"
        self._capture_device: Any = None
        self._frame_count: int = 0
        self._error_log: List[Dict[str, Any]] = []
        self._latest_capture: Optional[Dict[str, Any]] = None

        # Initialize backend
        self.initialize_camera()

    def record_error(self, message: str, exc: Optional[Exception] = None) -> None:
        """Log and store camera error."""
        err_msg = f"{message}: {exc}" if exc else message
        logger.error(err_msg)
        with self._lock:
            self._error_log.append({
                "timestamp": time.time(),
                "time_str": datetime.now().isoformat(),
                "error": err_msg
            })
            # Keep last 50 errors
            if len(self._error_log) > 50:
                self._error_log.pop(0)

    def initialize_camera(self) -> bool:
        """Determine and initialize camera backend based on configuration and hardware."""
        target_backend = self.config.backend.lower()

        if target_backend == "auto":
            hw_info = CameraDetector.detect_camera_hardware()
            target_backend = hw_info["recommended_backend"]
            self._sensor_name = hw_info["camera_model"]
            logger.info("Auto-detected camera recommendation: %s (%s)", target_backend, self._sensor_name)

        success = False
        if target_backend == "libcamera":
            success = self._init_libcamera()
            if not success:
                logger.warning("Libcamera initialization failed; falling back to OpenCV/Mock")
                target_backend = "opencv"

        if target_backend == "opencv" and not success:
            success = self._init_opencv()
            if not success:
                logger.warning("OpenCV initialization failed; falling back to Mock camera")
                target_backend = "mock"

        if target_backend == "mock" or not success:
            success = self._init_mock()

        self._connected = success
        return success

    def _init_libcamera(self) -> bool:
        """Initialize Raspberry Pi Picamera2 or libcamera backend."""
        try:
            # Check if picamera2 is available
            from picamera2 import Picamera2
            picam = Picamera2()
            cam_config = picam.create_preview_configuration(
                main={"size": (self.config.width, self.config.height), "format": "RGB888"}
            )
            picam.configure(cam_config)
            picam.start()
            self._capture_device = picam
            self._active_backend = "libcamera"
            self._sensor_name = "Sony IMX477 (Picamera2)"
            logger.info("Successfully initialized Picamera2 with IMX477")
            return True
        except Exception as e:
            self.record_error("Failed to initialize libcamera/Picamera2", e)
            return False

    def _init_opencv(self) -> bool:
        """Initialize OpenCV VideoCapture device."""
        try:
            cap = cv2.VideoCapture(self.config.camera_index)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                cap.set(cv2.CAP_PROP_FPS, self.config.framerate)
                self._capture_device = cap
                self._active_backend = "opencv"
                self._sensor_name = f"OpenCV Camera (Device {self.config.camera_index})"
                logger.info("Successfully opened OpenCV VideoCapture device %d", self.config.camera_index)
                return True
            else:
                self.record_error(f"Cannot open OpenCV VideoCapture at index {self.config.camera_index}")
                return False
        except Exception as e:
            self.record_error("OpenCV VideoCapture exception", e)
            return False

    def _init_mock(self) -> bool:
        """Initialize mock camera for offline testing and Windows environment."""
        self._active_backend = "mock"
        self._capture_device = None
        self._sensor_name = "Simulated IMX477 Drone Camera"
        logger.info("Mock Camera initialized successfully")
        return True

    def _generate_mock_frame(self, width: int, height: int) -> np.ndarray:
        """Generate high-fidelity synthetic drone camera view with HUD and horizon."""
        self._frame_count += 1
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Gradient ground & sky background
        horizon_y = int(height * 0.48)
        # Sky: blue gradient
        for y in range(0, horizon_y):
            val = int(80 + (y / max(horizon_y, 1)) * 40)
            frame[y, :] = [val + 30, val, 25]  # BGR
        # Ground: earthy slate/dark green
        for y in range(horizon_y, height):
            val = int(40 + ((y - horizon_y) / max(height - horizon_y, 1)) * 30)
            frame[y, :] = [20, val + 15, 25]

        # Artificial horizon line
        cv2.line(frame, (int(width * 0.2), horizon_y), (int(width * 0.8), horizon_y), (0, 230, 255), 1)

        # Center crosshairs
        cx, cy = width // 2, height // 2
        arm = int(min(width, height) * 0.06)
        cv2.line(frame, (cx - arm, cy), (cx + arm, cy), (0, 230, 255), 1)
        cv2.line(frame, (cx, cy - arm), (cx, cy + arm), (0, 230, 255), 1)
        cv2.circle(frame, (cx, cy), arm // 2, (0, 230, 255), 1)

        # Simulated landing pad / target marker on ground
        target_x, target_y = int(width * 0.65), int(height * 0.72)
        cv2.circle(frame, (target_x, target_y), int(min(width, height) * 0.08), (255, 255, 255), 2)
        cv2.circle(frame, (target_x, target_y), int(min(width, height) * 0.04), (0, 0, 255), 2)
        cv2.putText(frame, "TARGET-A1", (target_x - 35, target_y - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # Telemetry HUD overlays
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        cv2.putText(frame, "AUTONOMOUS-DRONE // COMPANION VISION", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, f"SENSOR: {self._sensor_name}", (20, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(frame, f"RES: {width}x{height} | FPS: {self.config.framerate}", (20, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(frame, f"UTC: {now_str}", (20, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 128), 1, cv2.LINE_AA)
        cv2.putText(frame, f"FRAME: #{self._frame_count:06d}", (20, 115),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        # Drone attitude watermark on top right
        status_text = "MODE: MOCK SIMULATION"
        cv2.putText(frame, status_text, (width - 240, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 180, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "ALT: 15.4m | HDG: 042*", (width - 240, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        return frame

    def get_frame(self, preview: bool = False) -> Optional[np.ndarray]:
        """
        Capture or generate a single frame.

        Args:
            preview: If True, returns lower resolution frame optimized for live streaming.
        """
        target_w = self.config.preview_width if preview else self.config.width
        target_h = self.config.preview_height if preview else self.config.height

        with self._lock:
            # 1. Libcamera backend
            if self._active_backend == "libcamera" and self._capture_device:
                try:
                    frame = self._capture_device.capture_array()
                    # Convert RGB to BGR for OpenCV consistency
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    if preview:
                        frame_bgr = cv2.resize(frame_bgr, (target_w, target_h))
                    return frame_bgr
                except Exception as e:
                    self.record_error("Libcamera frame acquisition failed", e)

            # 2. OpenCV backend
            if self._active_backend == "opencv" and self._capture_device:
                try:
                    ret, frame = self._capture_device.read()
                    if ret and frame is not None:
                        if preview:
                            frame = cv2.resize(frame, (target_w, target_h))
                        return frame
                    else:
                        self.record_error("OpenCV read() returned empty frame")
                except Exception as e:
                    self.record_error("OpenCV frame acquisition failed", e)

            # 3. Fallback: Mock Generator
            frame = self._generate_mock_frame(target_w, target_h)

        # Apply rotation if configured
        if frame is not None and self.config.rotation != 0:
            if self.config.rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif self.config.rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self.config.rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        return frame

    def get_jpeg_frame(self, preview: bool = True) -> bytes:
        """Encode latest frame as JPEG bytes (for MJPEG video streaming)."""
        frame = self.get_frame(preview=preview)
        if frame is None:
            # Empty fallback black frame
            h = self.config.preview_height if preview else self.config.height
            w = self.config.preview_width if preview else self.config.width
            frame = np.zeros((h, w, 3), dtype=np.uint8)

        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality]
        success, jpeg_bytes = cv2.imencode(".jpg", frame, encode_params)
        if success:
            return jpeg_bytes.tobytes()
        return b""

    def capture_image(self) -> Dict[str, Any]:
        """
        Capture full resolution image and persist to captures/ directory.
        Returns capture metadata. Thread-safe and prevents conflicting concurrent captures.
        """
        if not self._capture_lock.acquire(blocking=False):
            raise RuntimeError("Camera capture already in progress")

        try:
            # Ensure captures directory exists
            self.config.captures_dir.mkdir(parents=True, exist_ok=True)

            # High-resolution frame
            frame = self.get_frame(preview=False)
            if frame is None:
                raise RuntimeError("Camera failed to acquire frame for image capture")

            now = datetime.now()
            filename = f"capture_{now.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = self.config.captures_dir / filename

            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality]
            write_success = cv2.imwrite(str(filepath), frame, encode_params)

            if not write_success:
                err = f"Failed to write image file to {filepath}"
                self.record_error(err)
                raise IOError(err)

            file_size = filepath.stat().st_size
            metadata = {
                "filename": filename,
                "filepath": str(filepath),
                "relative_url": f"/api/camera/image/{filename}",
                "timestamp": now.timestamp(),
                "iso_time": now.isoformat(),
                "width": frame.shape[1],
                "height": frame.shape[0],
                "channels": frame.shape[2],
                "size_bytes": file_size,
                "size_kb": round(file_size / 1024, 1),
                "backend": self._active_backend,
                "sensor": self._sensor_name
            }

            with self._lock:
                self._latest_capture = metadata

            logger.info("Captured image saved: %s (%dx%d, %s KB)", filename, metadata["width"], metadata["height"], metadata["size_kb"])
            return metadata
        finally:
            self._capture_lock.release()

    def get_latest_capture(self) -> Optional[Dict[str, Any]]:
        """Return metadata for the most recently captured image."""
        with self._lock:
            if self._latest_capture and Path(self._latest_capture["filepath"]).exists():
                return self._latest_capture

        # Search directory if memory cache is empty
        captures = self.list_captures(limit=1)
        if captures:
            with self._lock:
                self._latest_capture = captures[0]
            return captures[0]
        return None

    def list_captures(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List captured images sorted by newest first."""
        captures = []
        if not self.config.captures_dir.exists():
            return captures

        files = sorted(
            self.config.captures_dir.glob("capture_*.jpg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for path in files[:limit]:
            stat = path.stat()
            captures.append({
                "filename": path.name,
                "filepath": str(path),
                "relative_url": f"/api/camera/image/{path.name}",
                "timestamp": stat.st_mtime,
                "iso_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "size_bytes": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1)
            })

        return captures

    def get_status(self) -> Dict[str, Any]:
        """Provide camera status, hardware details, active backend, and error logs."""
        return {
            "connected": self._connected,
            "active_backend": self._active_backend,
            "is_mock": self._active_backend == "mock",
            "sensor_model": self._sensor_name,
            "total_frames_generated": self._frame_count,
            "config": self.config.to_dict(),
            "latest_capture": self.get_latest_capture(),
            "error_count": len(self._error_log),
            "recent_errors": self._error_log[-5:]
        }

    def release(self) -> None:
        """Release underlying hardware resources gracefully."""
        with self._lock:
            if self._active_backend == "opencv" and self._capture_device:
                try:
                    self._capture_device.release()
                except Exception:
                    pass
            elif self._active_backend == "libcamera" and self._capture_device:
                try:
                    self._capture_device.stop()
                except Exception:
                    pass
            self._capture_device = None
            self._connected = False


# Global singleton instance for application use
camera_manager = CameraManager()
