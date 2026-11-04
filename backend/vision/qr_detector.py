"""
QR Code Detection and Decoding Engine for AUTONOMOUS-DRONE.
Supports single and multiple QR code detection per frame using OpenCV,
with robust bounding box extraction, center coordinates, and timestamping.
"""
import time
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

from config.logging_config import setup_logging

logger = setup_logging("qr_detector")


@dataclass
class QRDetectionResult:
    """Structured representation of a detected QR code."""
    payload: str
    points: List[List[int]]
    bbox: Dict[str, int]
    center: List[int]
    confidence: float
    timestamp: float
    iso_time: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to JSON-serializable dictionary."""
        return asdict(self)


class QRDetector:
    """
    Robust Computer Vision QR Detector.
    Processes OpenCV BGR/grayscale numpy frames and extracts decoded payloads with geometry.
    """

    def __init__(self):
        # Primary detector: OpenCV standard QR code detector
        self._detector = cv2.QRCodeDetector()

    def detect_and_decode(self, frame: Optional[np.ndarray]) -> List[QRDetectionResult]:
        """
        Detect and decode all QR codes present in the input frame.

        Args:
            frame: OpenCV image array (BGR or Grayscale).

        Returns:
            List of QRDetectionResult objects (empty list if none detected or invalid frame).
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return []

        # Validate minimum dimensions
        if frame.shape[0] < 20 or frame.shape[1] < 20:
            return []

        results: List[QRDetectionResult] = []
        now = time.time()
        iso_time = datetime.fromtimestamp(now).isoformat()

        # Convert to grayscale if 3-channel
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        try:
            # 1. Attempt multi-QR detection (OpenCV 4.x+)
            retval, decoded_info, points, _ = self._detector.detectAndDecodeMulti(gray)

            if retval and points is not None and len(points) > 0:
                for i, text in enumerate(decoded_info):
                    text_str = text.strip() if text else ""
                    if not text_str:
                        continue

                    pts = points[i]
                    parsed = self._build_detection_result(text_str, pts, now, iso_time)
                    if parsed:
                        results.append(parsed)

            # 2. Fallback to single QR detection if multi returned nothing
            if not results:
                text, pts, _ = self._detector.detectAndDecode(gray)
                text_str = text.strip() if text else ""
                if text_str and pts is not None and len(pts) > 0:
                    parsed = self._build_detection_result(text_str, pts[0], now, iso_time)
                    if parsed:
                        results.append(parsed)

        except Exception as e:
            logger.debug("QR detection failed gracefully on frame: %s", e)

        return results

    def _build_detection_result(
        self,
        text: str,
        pts: np.ndarray,
        timestamp: float,
        iso_time: str
    ) -> Optional[QRDetectionResult]:
        """Calculate bounding box, center coordinates, and confidence score."""
        try:
            # Reshape points to list of (x, y) integers
            pts_reshaped = pts.reshape(-1, 2)
            points_list = [[int(round(p[0])), int(round(p[1]))] for p in pts_reshaped]

            xs = [p[0] for p in points_list]
            ys = [p[1] for p in points_list]

            x_min = max(0, min(xs))
            y_min = max(0, min(ys))
            width = max(1, max(xs) - x_min)
            height = max(1, max(ys) - y_min)

            center_x = int(round(x_min + width / 2.0))
            center_y = int(round(y_min + height / 2.0))

            # Quality heuristic: area of polygon and aspect ratio closeness to 1.0
            aspect = float(width) / float(height) if height > 0 else 0.0
            aspect_score = 1.0 - min(abs(1.0 - aspect), 0.5)
            confidence = round(float(np.clip(aspect_score * 0.95 + 0.05, 0.5, 1.0)), 2)

            return QRDetectionResult(
                payload=text,
                points=points_list,
                bbox={"x": x_min, "y": y_min, "width": width, "height": height},
                center=[center_x, center_y],
                confidence=confidence,
                timestamp=timestamp,
                iso_time=iso_time
            )
        except Exception as e:
            logger.debug("Failed building QR result: %s", e)
            return None

    @classmethod
    def generate_test_qr_frame(
        cls,
        payload: str,
        width: int = 640,
        height: int = 480,
        box_size: int = 8,
        border: int = 4
    ) -> np.ndarray:
        """
        Utility to generate a realistic synthetic image containing a valid QR code.
        Used for unit tests and offline camera simulation.
        """
        import qrcode
        from PIL import Image

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=border,
        )
        qr.add_data(payload)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_np = np.array(qr_img)
        # Convert RGB to BGR for OpenCV
        qr_bgr = cv2.cvtColor(qr_np, cv2.COLOR_RGB2BGR)

        # Create canvas of desired size
        canvas = np.full((height, width, 3), 240, dtype=np.uint8)

        # Overlay QR centered or fitted
        qh, qw = qr_bgr.shape[:2]
        if qh > height or qw > width:
            qr_bgr = cv2.resize(qr_bgr, (min(qw, width - 20), min(qh, height - 20)))
            qh, qw = qr_bgr.shape[:2]

        oy = (height - qh) // 2
        ox = (width - qw) // 2
        canvas[oy:oy + qh, ox:ox + qw] = qr_bgr

        return canvas

