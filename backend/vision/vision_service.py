"""
Background Vision and QR Detection Service for AUTONOMOUS-DRONE.
Runs continuous frame processing, enforces duplicate detection cooldowns,
maintains detection history, and handles on-demand image uploads.
"""
import io
import time
import threading
from typing import Dict, Any, List, Optional
import cv2
import numpy as np
from PIL import Image

from config.settings import settings
from config.logging_config import setup_logging
from backend.camera.camera_manager import camera_manager
from .qr_detector import QRDetector, QRDetectionResult

logger = setup_logging("vision_service")


class VisionService:
    """Manages background QR detection loop, cooldown filtering, and detection state."""

    def __init__(self):
        self.detector = QRDetector()
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # State
        self._latest_detections: List[Dict[str, Any]] = []
        self._history: List[Dict[str, Any]] = []
        self._last_seen_payloads: Dict[str, float] = {}  # payload -> timestamp
        self._total_scans: int = 0
        self._total_detections: int = 0
        self._cooldown_seconds: float = settings.QR_COOLDOWN_SECONDS
        self._history_limit: int = settings.QR_HISTORY_LIMIT
        self._fps: float = settings.QR_PROCESS_FPS

    @property
    def is_running(self) -> bool:
        """Return True if background detection worker is currently active."""
        with self._lock:
            return self._running

    def start(self) -> bool:
        """Start background vision detection thread."""
        with self._lock:
            if self._running:
                logger.info("Vision service is already running")
                return True

            self._running = True
            self._worker_thread = threading.Thread(
                target=self._detection_loop,
                name="VisionDetectionWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("Background vision detection loop started (target FPS: %.1f)", self._fps)
            return True

    def stop(self) -> bool:
        """Stop background vision detection thread safely."""
        with self._lock:
            if not self._running:
                return True
            self._running = False

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None

        try:
            logger.info("Background vision detection loop stopped")
        except Exception:
            pass
        return True

    def _detection_loop(self) -> None:
        """Continuous frame acquisition and QR detection background worker."""
        interval = 1.0 / max(self._fps, 1.0)
        while self.is_running:
            start_time = time.time()
            try:
                frame = camera_manager.get_frame(preview=True)
                if frame is not None:
                    try:
                        from backend.flight.mavlink_service import mavlink_service
                        from backend.vision.geoprojector import DronePose
                        from backend.vision.task2_vision_service import task2_vision_engine
                        snap = mavlink_service.get_snapshot()
                        gps_fix = bool(snap.gps_fix_type >= 2 and snap.latitude is not None and snap.longitude is not None)
                        pose = DronePose(
                            timestamp=time.time(),
                            lat=snap.latitude,
                            lon=snap.longitude,
                            alt_agl_m=snap.altitude_relative_m or 0.0,
                            roll_deg=snap.roll_deg or 0.0,
                            pitch_deg=snap.pitch_deg or 0.0,
                            yaw_deg=snap.heading_deg or 0.0,
                            gps_fix_valid=gps_fix,
                            hdop=snap.gps_hdop or 1.0,
                        )
                        task2_vision_engine.submit_frame(frame.copy(), pose)
                    except Exception as submit_err:
                        logger.debug("Task2 frame submission error: %s", submit_err)
                    self.process_frame(frame, source="live_camera")
            except Exception as e:
                logger.debug("Error in vision detection loop: %s", e)

            elapsed = time.time() - start_time
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    def process_frame(self, frame: np.ndarray, source: str = "direct") -> List[Dict[str, Any]]:
        """
        Process a single OpenCV frame for QR codes, update history and cooldown state.
        """
        with self._lock:
            self._total_scans += 1

        detections = self.detector.detect_and_decode(frame)
        accepted_results: List[Dict[str, Any]] = []

        now = time.time()
        for det in detections:
            payload = det.payload
            data_dict = det.to_dict()
            data_dict["source"] = source

            with self._lock:
                last_time = self._last_seen_payloads.get(payload, 0.0)
                is_duplicate = (now - last_time) < self._cooldown_seconds

                if not is_duplicate:
                    self._last_seen_payloads[payload] = now
                    self._total_detections += 1
                    data_dict["duplicate"] = False

                    # Attach spatial coordinates from MAVLink telemetry
                    try:
                        from backend.flight.mavlink_service import mavlink_service
                        snap = mavlink_service.get_snapshot()
                        data_dict["latitude"] = snap.latitude
                        data_dict["longitude"] = snap.longitude
                        data_dict["altitude"] = snap.altitude_relative_m
                    except Exception:
                        data_dict["latitude"] = 0.0
                        data_dict["longitude"] = 0.0
                        data_dict["altitude"] = 0.0

                    # QR Action Trigger: Trigger RTL on QR detection
                    payload_clean = payload.strip().lower()
                    qr_rtl_on_any = getattr(settings, "QR_RTL_ON_ANY", True)
                    is_rtl_trigger = ("rtl" in payload_clean or "return" in payload_clean or qr_rtl_on_any)

                    if is_rtl_trigger:
                        data_dict["action_triggered"] = "RTL"
                        logger.info("🎯 [VISION TRIGGER] QR Code '%s' triggered Return-to-Launch (RTL)", payload)
                        try:
                            from backend.flight.flight_controller import flight_controller
                            rtl_res = flight_controller.request_rtl()
                            data_dict["action_result"] = rtl_res
                            logger.info("RTL Execution Outcome: %s", rtl_res)
                        except Exception as e:
                            logger.error("Failed executing RTL on QR trigger: %s", e)
                            data_dict["action_result"] = {"success": False, "message": str(e)}

                    self._history.insert(0, data_dict)
                    if len(self._history) > self._history_limit:
                        self._history.pop()
                    accepted_results.append(data_dict)
                    logger.info("QR Code Detected [%s]: %s (conf: %.2f)", source, payload, det.confidence)
                else:
                    data_dict["duplicate"] = True

        with self._lock:
            self._latest_detections = [d.to_dict() for d in detections]

        return accepted_results if accepted_results else [d.to_dict() for d in detections]

    def process_image_bytes(self, image_bytes: bytes, filename: str = "upload.jpg") -> List[Dict[str, Any]]:
        """
        Decode QR codes from raw image file bytes (e.g. from file upload).
        """
        if not image_bytes or len(image_bytes) == 0:
            raise ValueError("Empty image buffer provided")

        if len(image_bytes) > 15 * 1024 * 1024:
            raise ValueError("Uploaded file exceeds 15MB size limit")

        # Decode using OpenCV from buffer
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            # Fallback to Pillow in case of uncommon formats
            try:
                pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except Exception as e:
                raise ValueError(f"Could not decode image file: {e}")

        return self.process_frame(frame, source=f"upload:{filename}")

    def get_status(self) -> Dict[str, Any]:
        """Return operational status and scan counters."""
        with self._lock:
            return {
                "running": self._running,
                "fps": self._fps,
                "cooldown_seconds": self._cooldown_seconds,
                "total_scans": self._total_scans,
                "total_unique_detections": self._total_detections,
                "history_count": len(self._history),
                "has_latest": len(self._latest_detections) > 0,
                "latest_detections_count": len(self._latest_detections)
            }

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Return the most recently scanned QR code, or None."""
        with self._lock:
            if self._latest_detections:
                return self._latest_detections[0]
            if self._history:
                return self._history[0]
            return None

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent detection history sorted newest first."""
        with self._lock:
            return list(self._history[:limit])

    def clear_history(self) -> None:
        """Clear detection history and cooldown cache."""
        with self._lock:
            self._history.clear()
            self._last_seen_payloads.clear()
            self._latest_detections.clear()


# Global singleton instance
vision_service = VisionService()
