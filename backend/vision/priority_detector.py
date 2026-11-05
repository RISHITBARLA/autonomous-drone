"""
Priority-Based Visual Target and Pattern Candidate Detector for AUTONOMOUS-DRONE.
Detects square/rectangular candidates, high-contrast black-and-white patterns,
and general visual contours without falsely confirming unvalidated geometric shapes.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np


class DetectionCategory(str, Enum):
    SQUARE_CANDIDATE = "SQUARE_CANDIDATE"       # Priority 1: Orange
    RECTANGLE_CANDIDATE = "RECTANGLE_CANDIDATE" # Priority 1: Orange
    BW_PATTERN = "BW_PATTERN"                   # High-contrast B/W: Yellow
    QR_UNVERIFIED = "QR_UNVERIFIED"             # QR detected, awaiting validation: Blue
    QR_VALIDATED = "QR_VALIDATED"               # QR decoded and validated: Green
    OTHER_OBJECT = "OTHER_OBJECT"               # Other detected object: Purple
    UNCERTAIN = "UNCERTAIN"                     # Low confidence: Grey


CATEGORY_COLORS: Dict[DetectionCategory, str] = {
    DetectionCategory.SQUARE_CANDIDATE: "#FB923C",   # Orange
    DetectionCategory.RECTANGLE_CANDIDATE: "#FB923C",# Orange
    DetectionCategory.BW_PATTERN: "#FACC15",         # Yellow
    DetectionCategory.QR_UNVERIFIED: "#38BDF8",       # Blue
    DetectionCategory.QR_VALIDATED: "#22C55E",         # Green
    DetectionCategory.OTHER_OBJECT: "#A855F7",         # Purple
    DetectionCategory.UNCERTAIN: "#94A3B8",           # Grey
}


@dataclass
class CandidateDetection:
    """Raw visual detection before spatial geoprojection."""
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    center_xy: Tuple[int, int]
    category: DetectionCategory
    confidence: float
    is_confirmed: bool = False
    evidence_score: float = 0.0
    qr_payload: Optional[str] = None
    extra_meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def color(self) -> str:
        return CATEGORY_COLORS.get(self.category, "#94A3B8")


class PriorityTargetDetector:
    """
    Analyzes visual contours, aspect ratios, convexity, and contrast
    to identify candidate targets without making unverified assumptions.
    """

    def __init__(
        self,
        min_area_px: int = 150,
        max_area_px: int = 400000,
        min_confidence: float = 0.40,
    ):
        self.min_area_px = min_area_px
        self.max_area_px = max_area_px
        self.min_confidence = min_confidence

    def detect_candidates(self, frame_bgr: np.ndarray) -> List[CandidateDetection]:
        """
        Analyze single BGR frame for geometric targets and high-contrast patterns.
        Returns list of CandidateDetection objects.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return []

        h, w = frame_bgr.shape[:2]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        # 1. Edge & Adaptive Threshold for Contour Segmentation
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 140)

        # Morphological close to bridge broken contour lines
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: List[CandidateDetection] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area_px or area > self.max_area_px:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.035 * peri, True)
            x, y, bw, bh = cv2.boundingRect(approx)

            # Ignore edge-hugging image boundaries
            if x <= 1 or y <= 1 or (x + bw) >= (w - 2) or (y + bh) >= (h - 2):
                continue

            aspect_ratio = float(bw) / float(max(1, bh))
            center = (x + bw // 2, y + bh // 2)
            roi_gray = gray[y:y + bh, x:x + bw]
            if roi_gray.size == 0:
                continue

            # Contrast & Luminance Metrics
            roi_std = float(np.std(roi_gray))
            roi_mean = float(np.mean(roi_gray))

            # High-Contrast Black/White Pattern Test
            # B/W patterns have bimodal intensity (high standard deviation) and balanced dark/light pixels
            is_high_contrast_bw = False
            bw_score = 0.0
            if roi_std > 42.0:
                _, thresh = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                dark_ratio = float(np.count_nonzero(thresh == 0)) / float(thresh.size)
                # Ideal B/W pattern has roughly 25% - 75% dark elements
                if 0.20 <= dark_ratio <= 0.80:
                    is_high_contrast_bw = True
                    bw_score = min(1.0, (roi_std / 75.0) * (1.0 - abs(0.5 - dark_ratio)))

            # Geometric Classification
            vertices = len(approx)
            convexity = float(area) / max(1.0, float(bw * bh))

            if vertices == 4 and convexity >= 0.65:
                # Quadrilateral candidate
                if 0.75 <= aspect_ratio <= 1.30:
                    # Square-like pattern
                    conf = min(0.95, 0.50 + 0.35 * convexity + 0.15 * min(1.0, roi_std / 50.0))
                    candidates.append(CandidateDetection(
                        bbox=(x, y, bw, bh),
                        center_xy=center,
                        category=DetectionCategory.SQUARE_CANDIDATE,
                        confidence=round(conf, 2),
                        is_confirmed=False,
                        evidence_score=round(convexity, 2),
                        extra_meta={"vertices": 4, "aspect_ratio": round(aspect_ratio, 2)}
                    ))
                elif 0.30 <= aspect_ratio <= 3.30:
                    # Rectangular pattern
                    conf = min(0.92, 0.45 + 0.30 * convexity + 0.15 * min(1.0, roi_std / 50.0))
                    candidates.append(CandidateDetection(
                        bbox=(x, y, bw, bh),
                        center_xy=center,
                        category=DetectionCategory.RECTANGLE_CANDIDATE,
                        confidence=round(conf, 2),
                        is_confirmed=False,
                        evidence_score=round(convexity, 2),
                        extra_meta={"vertices": 4, "aspect_ratio": round(aspect_ratio, 2)}
                    ))
            elif is_high_contrast_bw and bw_score >= 0.45:
                # Black & White pattern candidate
                conf = round(min(0.88, 0.45 + 0.45 * bw_score), 2)
                candidates.append(CandidateDetection(
                    bbox=(x, y, bw, bh),
                    center_xy=center,
                    category=DetectionCategory.BW_PATTERN,
                    confidence=conf,
                    is_confirmed=False,
                    evidence_score=round(bw_score, 2),
                    extra_meta={"bw_score": round(bw_score, 2), "std_dev": round(roi_std, 1)}
                ))
            elif area >= 350 and convexity >= 0.50:
                # Other generic visible blob
                candidates.append(CandidateDetection(
                    bbox=(x, y, bw, bh),
                    center_xy=center,
                    category=DetectionCategory.OTHER_OBJECT,
                    confidence=0.45,
                    is_confirmed=False,
                    evidence_score=round(convexity, 2),
                    extra_meta={"vertices": vertices, "area": int(area)}
                ))

        return candidates

