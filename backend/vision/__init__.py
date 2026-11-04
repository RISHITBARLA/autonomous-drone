"""
Computer Vision and QR Detection Subsystem for AUTONOMOUS-DRONE.
"""
from .qr_detector import QRDetector, QRDetectionResult
from .vision_service import vision_service, VisionService

__all__ = ["QRDetector", "QRDetectionResult", "vision_service", "VisionService"]

