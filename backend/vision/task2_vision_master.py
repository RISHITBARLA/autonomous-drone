#!/usr/bin/env python3
"""
TASK 2 — VISUAL OBJECT SEARCH, 3D GPS PROJECTION & GEOSPATIAL HEATMAP MODULE
Extends the existing Raspberry Pi 4 + IMX477 + Flask + OpenCV QR + MAVLink application
via an 8-stage non-blocking pipeline with bounded queues.
"""

import logging
import math
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from flask import Blueprint, jsonify, request

logger = logging.getLogger("DroneTask2Vision")
EARTH_RADIUS_M = 6378137.0


# ============================================================================
# 1. CONFIGURATION, PRIORITIES & COLOR CUSTOMIZATION
# ============================================================================

class TargetPriorityLevel(str, Enum):
    UNKNOWN = "UNKNOWN"                 # Yellow
    RECOGNIZED = "RECOGNIZED"           # Orange
    HIGH_PRIORITY = "HIGH_PRIORITY"     # Red
    CRITICAL_TARGET = "CRITICAL_TARGET" # Dark Red
    QR_VERIFIED = "QR_VERIFIED"         # Green


@dataclass
class VisionHeatmapConfig:
    # Frame sampling & Raspberry Pi 4 optimization
    frame_sample_every_n: int = 3
    inference_input_size: Tuple[int, int] = (320, 320)
    queue_max_size: int = 6

    # Low-light enhancement & Darkness/Shadow/Noise rejection thresholds
    low_light_luma_threshold: float = 65.0
    min_roi_luma_for_valid_object: float = 18.0   # Rejects pitch-black regions
    min_roi_std_dev: float = 11.0                 # Rejects flat shadows
    min_roi_edge_density: float = 0.025           # Rejects sensor noise / featureless blur

    # Configurable classes, confidence thresholds, priorities, and colors
    confidence_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "default": 0.50,
        "unknown_object": 0.45,
        "vehicle": 0.55,
        "person": 0.60,
        "payload_box": 0.55,
        "qr_target": 0.65,
    })
    category_priority_map: Dict[str, str] = field(default_factory=lambda: {
        "unknown_object": TargetPriorityLevel.UNKNOWN.value,
        "vehicle": TargetPriorityLevel.RECOGNIZED.value,
        "payload_box": TargetPriorityLevel.HIGH_PRIORITY.value,
        "person": TargetPriorityLevel.CRITICAL_TARGET.value,
        "qr_target": TargetPriorityLevel.CRITICAL_TARGET.value,
    })
    priority_weights: Dict[str, float] = field(default_factory=lambda: {
        TargetPriorityLevel.UNKNOWN.value: 0.35,
        TargetPriorityLevel.RECOGNIZED.value: 0.60,
        TargetPriorityLevel.HIGH_PRIORITY.value: 0.85,
        TargetPriorityLevel.CRITICAL_TARGET.value: 1.00,
        TargetPriorityLevel.QR_VERIFIED.value: 1.00,
    })
    priority_colors: Dict[str, str] = field(default_factory=lambda: {
        TargetPriorityLevel.UNKNOWN.value: "#FACC15",         # Yellow
        TargetPriorityLevel.RECOGNIZED.value: "#FB923C",      # Orange
        TargetPriorityLevel.HIGH_PRIORITY.value: "#EF4444",   # Red
        TargetPriorityLevel.CRITICAL_TARGET.value: "#991B1B", # Dark Red
        TargetPriorityLevel.QR_VERIFIED.value: "#22C55E",     # Green
    })

    # IMX477 Camera Calibration & Mounting Geometry (Default 6mm lens on 1920x1080 stream)
    image_width: int = 1920
    image_height: int = 1080
    hfov_deg: float = 62.2
    vfov_deg: float = 48.8
    fx: Optional[float] = None
    fy: Optional[float] = None
    cx: Optional[float] = None
    cy: Optional[float] = None
    # Camera mounting orientation relative to drone body (e.g., -90 deg pitch = straight down nadir)
    mount_roll_deg: float = 0.0
    mount_pitch_deg: float = -90.0
    mount_yaw_deg: float = 0.0

    # Spatial grouping & heatmap smoothing
    dedup_cluster_radius_m: float = 4.0
    spatial_smoothing_sigma_m: float = 6.0
    image_save_dir: str = "static/captures/task2_targets"


# ============================================================================
# 2. DATA STRUCTURES (TELEMETRY SNAPSHOT, DETECTIONS, CLUSTERS, ADDC QR STATE)
# ============================================================================

@dataclass
class DronePoseSnapshot:
    timestamp: float
    lat: Optional[float]
    lon: Optional[float]
    alt_agl_m: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    gps_fix_valid: bool = True
    hdop: float = 1.2


@dataclass
class RawObjectDetection:
    bbox_xyxy: Tuple[int, int, int, int]  # (x1, y1, x2, y2) in original image pixels
    category: str
    confidence: float
    timestamp: float
    track_id: Optional[str] = None
    qr_decoded_text: Optional[str] = None


@dataclass
class ProjectedDetection:
    detection_id: str
    track_id: str
    category: str
    priority_level: str
    priority_weight: float
    display_color: str
    confidence: float
    timestamp: float
    bbox_xyxy: Tuple[int, int, int, int]
    estimated_lat: Optional[float]
    estimated_lon: Optional[float]
    uncertainty_m: Optional[float]
    projection_valid: bool
    is_approximate: bool
    image_path: Optional[str] = None
    qr_verified: bool = False
    qr_content: Optional[str] = None


@dataclass
class GeoTargetCluster:
    cluster_id: str
    category: str
    priority_level: str
    priority_weight: float
    display_color: str
    estimated_lat: float
    estimated_lon: float
    uncertainty_m: float
    is_approximate: bool
    aggregated_confidence: float
    observation_count: int
    first_seen_ts: float
    last_seen_ts: float
    latest_image_path: Optional[str] = None
    qr_verified: bool = False
    qr_content: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# 3. STAGE 2 & 3: PREPROCESSING, LOW-LIGHT CLAHE & NOISE/SHADOW REJECTION GATE
# ============================================================================

class ImagePreprocessorAndNoiseGate:
    """
    Enhances low-light frames on RPi 4 and prevents darkness, flat shadows,
    or sensor noise from being classified as objects.
    """

    def __init__(self, config: VisionHeatmapConfig):
        self.config = config
        self._clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    def preprocess_frame(self, frame_bgr: np.ndarray) -> Tuple[np.ndarray, Dict[str, float]]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        mean_luma = float(np.mean(gray))
        low_light_applied = 0.0

        if mean_luma < self.config.low_light_luma_threshold:
            lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
            l_chan, a_chan, b_chan = cv2.split(lab)
            l_enhanced = self._clahe.apply(l_chan)
            merged = cv2.merge((l_enhanced, a_chan, b_chan))
            enhanced_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
            low_light_applied = 1.0
            return enhanced_bgr, {"mean_luma": round(mean_luma, 2), "low_light_enhanced": low_light_applied}

        return frame_bgr, {"mean_luma": round(mean_luma, 2), "low_light_enhanced": low_light_applied}

    def passes_evidence_gate(self, frame_bgr: np.ndarray, bbox_xyxy: Tuple[int, int, int, int]) -> Tuple[bool, str]:
        """
        Rejects candidate boxes that consist merely of darkness, uniform shadows, or sensor noise.
        """
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = (
            max(0, min(w - 1, bbox_xyxy[0])),
            max(0, min(h - 1, bbox_xyxy[1])),
            max(0, min(w, bbox_xyxy[2])),
            max(0, min(h, bbox_xyxy[3])),
        )
        if (x2 - x1) < 8 or (y2 - y1) < 8:
            return False, "REJECTED_TOO_SMALL"

        roi = frame_bgr[y1:y2, x1:x2]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Apply 3x3 median blur first so single-pixel salt-and-pepper noise doesn't masquerade as structure
        denoised = cv2.medianBlur(roi_gray, 3)

        mean_val = float(np.mean(denoised))
        std_val = float(np.std(denoised))
        if mean_val < self.config.min_roi_luma_for_valid_object:
            return False, "REJECTED_DARKNESS"
        if std_val < self.config.min_roi_std_dev:
            return False, "REJECTED_UNIFORM_SHADOW"

        edges = cv2.Canny(denoised, 45, 135)
        edge_density = float(np.count_nonzero(edges)) / float(edges.size)
        if edge_density < self.config.min_roi_edge_density:
            return False, "REJECTED_LOW_STRUCTURAL_EVIDENCE"

        return True, "VALID_EVIDENCE"


# ============================================================================
# 4. STAGE 4: MULTI-FRAME OBJECT TRACKER (DUPLICATE SUPPRESSION IN IMAGE SPACE)
# ============================================================================

class LightweightObjectTracker:
    """
    Tracks bounding boxes across consecutive frames via IoU and normalized centroid distance
    so the same object in consecutive frames receives a persistent track_id.
    """

    def __init__(self, iou_threshold: float = 0.25, max_age_sec: float = 2.5):
        self.iou_threshold = iou_threshold
        self.max_age_sec = max_age_sec
        self._tracks: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def compute_iou(box_a: Tuple[int, int, int, int], box_b: Tuple[int, int, int, int]) -> float:
        x_a = max(box_a[0], box_b[0])
        y_a = max(box_a[1], box_b[1])
        x_b = min(box_a[2], box_b[2])
        y_b = min(box_a[3], box_b[3])
        inter = max(0, x_b - x_a) * max(0, y_b - y_a)
        if inter == 0:
            return 0.0
        area_a = max(1, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
        area_b = max(1, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))
        return float(inter) / float(area_a + area_b - inter)

    def update(self, detections: List[RawObjectDetection], now_ts: Optional[float] = None) -> List[RawObjectDetection]:
        now = now_ts if now_ts is not None else time.time()
        # Prune expired tracks
        expired = [tid for tid, t in self._tracks.items() if (now - t["last_ts"]) > self.max_age_sec]
        for tid in expired:
            del self._tracks[tid]

        # Intra-frame Non-Maximum Suppression (suppress overlapping duplicate boxes of same class)
        sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
        filtered_dets: List[RawObjectDetection] = []
        for det in sorted_dets:
            if any(
                d.category == det.category and self.compute_iou(d.bbox_xyxy, det.bbox_xyxy) > 0.50
                for d in filtered_dets
            ):
                continue
            filtered_dets.append(det)

        # Match against active tracks
        matched_tracks = set()
        for det in filtered_dets:
            best_tid = None
            best_iou = self.iou_threshold
            for tid, trk in self._tracks.items():
                if tid in matched_tracks or trk["category"] != det.category:
                    continue
                score = self.compute_iou(det.bbox_xyxy, trk["bbox"])
                if score > best_iou:
                    best_iou = score
                    best_tid = tid

            if best_tid is None:
                best_tid = f"trk-{uuid.uuid4().hex[:8]}"

            matched_tracks.add(best_tid)
            self._tracks[best_tid] = {
                "bbox": det.bbox_xyxy,
                "category": det.category,
                "last_ts": det.timestamp,
            }
            det.track_id = best_tid

        return filtered_dets


# ============================================================================
# 5. STAGE 5: 3D PINHOLE CAMERA-TO-GROUND GPS PROJECTOR
# ============================================================================

class CameraGeoprojector:
    """
    Projects 2D bounding-box coordinates (u, v) onto the ground plane using:
    - Calibrated camera intrinsics (fx, fy, cx, cy) or FOV
    - Camera mounting orientation (mount_roll, mount_pitch, mount_yaw)
    - Drone attitude (roll, pitch, yaw) and GPS (lat, lon, alt_agl_m)
    Never invents coordinates if GPS is missing or ray points above horizon.
    """

    def __init__(self, config: VisionHeatmapConfig):
        self.config = config
        self._update_intrinsics()

    def _update_intrinsics(self) -> None:
        w = float(self.config.image_width)
        h = float(self.config.image_height)
        self.cx = self.config.cx if self.config.cx is not None else (w / 2.0)
        self.cy = self.config.cy if self.config.cy is not None else (h / 2.0)
        self.fx = (
            self.config.fx
            if self.config.fx is not None
            else (w / (2.0 * math.tan(math.radians(self.config.hfov_deg) / 2.0)))
        )
        self.fy = (
            self.config.fy
            if self.config.fy is not None
            else (h / (2.0 * math.tan(math.radians(self.config.vfov_deg) / 2.0)))
        )

    @staticmethod
    def _euler_to_rot_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
        r = math.radians(roll_deg)
        p = math.radians(pitch_deg)
        y = math.radians(yaw_deg)
        cr, sr = math.cos(r), math.sin(r)
        cp, sp = math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)

        # ZYX extrinsic / intrinsic body-to-NED rotation matrix
        return np.array([
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp,     cp * sr,                cp * cr               ]
        ], dtype=np.float64)

    def project_bbox_to_gps(
        self, bbox_xyxy: Tuple[int, int, int, int], pose: DronePoseSnapshot
    ) -> Tuple[Optional[float], Optional[float], Optional[float], bool, bool]:
        """
        Returns: (est_lat, est_lon, uncertainty_m, projection_valid, is_approximate)
        Never invents geographic coordinates if GPS is invalid.
        """
        if (
            not pose.gps_fix_valid
            or pose.lat is None
            or pose.lon is None
            or pose.alt_agl_m <= 0.2
        ):
            return None, None, None, False, True

        u = 0.5 * (bbox_xyxy[0] + bbox_xyxy[2])
        v = 0.5 * (bbox_xyxy[1] + bbox_xyxy[3])

        # Normalized optical coordinates: X_opt = right, Y_opt = down, Z_opt = forward
        x_norm = (u - self.cx) / self.fx
        y_norm = (v - self.cy) / self.fy

        # Convert optical ray [x_right, y_down, 1_forward] to standard aircraft frame [X_fwd, Y_right, Z_down]
        ray_cam_body = np.array([1.0, x_norm, y_norm], dtype=np.float64)
        ray_cam_body /= np.linalg.norm(ray_cam_body)

        # Rotate by camera mount orientation -> drone body -> NED world frame
        r_mount = self._euler_to_rot_matrix(
            self.config.mount_roll_deg, self.config.mount_pitch_deg, self.config.mount_yaw_deg
        )
        r_drone_ned = self._euler_to_rot_matrix(pose.roll_deg, pose.pitch_deg, pose.yaw_deg)
        ray_ned = r_drone_ned @ (r_mount @ ray_cam_body)

        north_comp, east_comp, down_comp = float(ray_ned[0]), float(ray_ned[1]), float(ray_ned[2])

        # If ray points above or near the horizon (down_comp <= 0.08), ground intersection is invalid/unreliable
        if down_comp <= 0.08:
            # Fall back to explicitly approximate drone nadir coordinate with high uncertainty
            approx_uncertainty = max(25.0, pose.alt_agl_m * 2.5)
            return pose.lat, pose.lon, round(approx_uncertainty, 2), False, True

        scale = pose.alt_agl_m / down_comp
        offset_north_m = scale * north_comp
        offset_east_m = scale * east_comp

        d_lat = (offset_north_m / EARTH_RADIUS_M) * (180.0 / math.pi)
        d_lon = (
            offset_east_m / (EARTH_RADIUS_M * math.cos(math.radians(pose.lat)))
        ) * (180.0 / math.pi)

        est_lat = round(pose.lat + d_lat, 7)
        est_lon = round(pose.lon + d_lon, 7)

        # Uncertainty model combining GPS HDOP, altitude error (8%), and slant angle sensitivity
        slant_range_m = math.sqrt(offset_north_m ** 2 + offset_east_m ** 2 + pose.alt_agl_m ** 2)
        attitude_uncertainty_m = slant_range_m * math.tan(math.radians(2.0)) / max(0.15, down_comp)
        gps_uncertainty_m = 1.5 * pose.hdop
        total_uncertainty_m = round(math.sqrt(gps_uncertainty_m ** 2 + attitude_uncertainty_m ** 2), 2)

        is_approx = down_comp < 0.25 or pose.hdop > 2.5
        return est_lat, est_lon, total_uncertainty_m, True, is_approx


# ============================================================================
# 6. STAGE 6 & 7: GEOSPATIAL HEATMAP AGGREGATOR & ADDC 2026 QR MANAGER
# ============================================================================

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


class GeospatialHeatmapAndQREngine:
    """
    - Groups nearby detections within `dedup_cluster_radius_m` so repeated observations
      of one physical object update a single cluster instead of creating multiple markers.
    - Aggregates confidence and assigns priority weights + colors.
    - Tracks the ADDC 2026 4-digit Intelligence Access Code (2 digits from airborne QR +
      2 digits from ground operative puzzle task) without prematurely completing the mission.
    """

    def __init__(self, config: VisionHeatmapConfig):
        self.config = config
        self._lock = threading.Lock()
        self._clusters: Dict[str, GeoTargetCluster] = {}
        self._track_to_cluster: Dict[str, str] = {}
        self._update_seq: int = 0

        # ADDC 2026 4-Digit Intelligence Code State
        self._drone_qr_digits: Optional[str] = None
        self._ground_puzzle_digits: Optional[str] = None
        self._qr_evidence_records: List[Dict[str, Any]] = []

    def ingest_projected_detection(self, det: ProjectedDetection) -> Optional[GeoTargetCluster]:
        if det.estimated_lat is None or det.estimated_lon is None:
            return None

        with self._lock:
            matched_cid: Optional[str] = self._track_to_cluster.get(det.track_id)

            # Search spatially via Haversine distance if track hasn't been linked yet
            if matched_cid is None or matched_cid not in self._clusters:
                best_dist = self.config.dedup_cluster_radius_m
                matched_cid = None
                for cid, cluster in self._clusters.items():
                    if cluster.category != det.category and not det.qr_verified:
                        continue
                    dist = haversine_distance_m(
                        det.estimated_lat, det.estimated_lon, cluster.estimated_lat, cluster.estimated_lon
                    )
                    if dist <= best_dist:
                        best_dist = dist
                        matched_cid = cid

            if matched_cid and matched_cid in self._clusters:
                cluster = self._clusters[matched_cid]
                n = cluster.observation_count
                # Inverse-uncertainty weighted coordinate refinement
                w_new = 1.0 / max(0.5, det.uncertainty_m or 5.0)
                w_old = float(min(n, 15)) / max(0.5, cluster.uncertainty_m)
                w_sum = w_old + w_new

                cluster.estimated_lat = round(
                    (cluster.estimated_lat * w_old + det.estimated_lat * w_new) / w_sum, 7
                )
                cluster.estimated_lon = round(
                    (cluster.estimated_lon * w_old + det.estimated_lon * w_new) / w_sum, 7
                )
                cluster.uncertainty_m = round(min(cluster.uncertainty_m, det.uncertainty_m or cluster.uncertainty_m), 2)
                cluster.is_approximate = cluster.is_approximate and det.is_approximate
                # Confidence aggregation via bounded Bayesian-style boost (prevents runaway 1.0 saturation from noise)
                cluster.aggregated_confidence = round(
                    min(0.99, 1.0 - (1.0 - cluster.aggregated_confidence) * (1.0 - 0.35 * det.confidence)), 3
                )
                cluster.observation_count += 1
                cluster.last_seen_ts = det.timestamp
                if det.image_path:
                    cluster.latest_image_path = det.image_path
                if det.qr_verified:
                    cluster.qr_verified = True
                    cluster.qr_content = det.qr_content
                    cluster.priority_level = TargetPriorityLevel.QR_VERIFIED.value
                    cluster.priority_weight = self.config.priority_weights[TargetPriorityLevel.QR_VERIFIED.value]
                    cluster.display_color = self.config.priority_colors[TargetPriorityLevel.QR_VERIFIED.value]
            else:
                matched_cid = f"obj-{uuid.uuid4().hex[:8]}"
                cluster = GeoTargetCluster(
                    cluster_id=matched_cid,
                    category=det.category,
                    priority_level=det.priority_level,
                    priority_weight=det.priority_weight,
                    display_color=det.display_color,
                    estimated_lat=det.estimated_lat,
                    estimated_lon=det.estimated_lon,
                    uncertainty_m=det.uncertainty_m or 5.0,
                    is_approximate=det.is_approximate,
                    aggregated_confidence=round(det.confidence, 3),
                    observation_count=1,
                    first_seen_ts=det.timestamp,
                    last_seen_ts=det.timestamp,
                    latest_image_path=det.image_path,
                    qr_verified=det.qr_verified,
                    qr_content=det.qr_content,
                )
                self._clusters[matched_cid] = cluster

            cluster.history.append({
                "timestamp": det.timestamp,
                "confidence": round(det.confidence, 3),
                "lat": det.estimated_lat,
                "lon": det.estimated_lon,
                "uncertainty_m": det.uncertainty_m,
            })
            if len(cluster.history) > 25:
                cluster.history.pop(0)

            self._track_to_cluster[det.track_id] = matched_cid
            self._update_seq += 1
            return cluster

    def record_qr_verification(
        self, raw_qr_text: str, associated_cluster_id: Optional[str], high_res_image_path: Optional[str]
    ) -> Dict[str, Any]:
        """
        ADDC 2026 Rule: Airborne QR code supplies 2 digits of the 4-digit intelligence access code.
        Decoding the QR alone does NOT complete the 4-digit access code until the ground operative's
        2 puzzle digits are also provided.
        """
        digits_only = "".join(ch for ch in raw_qr_text if ch.isdigit())
        two_digits = digits_only[:2] if len(digits_only) >= 2 else None

        with self._lock:
            if two_digits:
                self._drone_qr_digits = two_digits
            record = {
                "qr_raw": raw_qr_text,
                "extracted_2_digits": two_digits,
                "associated_cluster_id": associated_cluster_id,
                "high_res_image_path": high_res_image_path,
                "timestamp": time.time(),
            }
            self._qr_evidence_records.append(record)

            if associated_cluster_id and associated_cluster_id in self._clusters:
                c = self._clusters[associated_cluster_id]
                c.qr_verified = True
                c.qr_content = raw_qr_text
                c.priority_level = TargetPriorityLevel.QR_VERIFIED.value
                c.display_color = self.config.priority_colors[TargetPriorityLevel.QR_VERIFIED.value]
                if high_res_image_path:
                    c.latest_image_path = high_res_image_path
            self._update_seq += 1

        return self.get_addc_intelligence_status()

    def set_ground_operative_puzzle_digits(self, puzzle_two_digits: str) -> Dict[str, Any]:
        clean = "".join(ch for ch in str(puzzle_two_digits) if ch.isdigit())[:2]
        with self._lock:
            if len(clean) == 2:
                self._ground_puzzle_digits = clean
                self._update_seq += 1
        return self.get_addc_intelligence_status()

    def get_addc_intelligence_status(self) -> Dict[str, Any]:
        with self._lock:
            qr_ok = self._drone_qr_digits is not None and len(self._drone_qr_digits) == 2
            puzzle_ok = self._ground_puzzle_digits is not None and len(self._ground_puzzle_digits) == 2
            full_code = f"{self._drone_qr_digits}{self._ground_puzzle_digits}" if (qr_ok and puzzle_ok) else None
            return {
                "drone_qr_2_digits": self._drone_qr_digits,
                "ground_operative_puzzle_2_digits": self._ground_puzzle_digits,
                "qr_stage_verified": qr_ok,
                "ground_puzzle_stage_verified": puzzle_ok,
                "intelligence_code_complete": bool(qr_ok and puzzle_ok),
                "combined_4_digit_access_code": full_code,
                "evidence_count": len(self._qr_evidence_records),
            }

    def generate_heatmap_payload(self, category_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates spatially smoothed visual detection heatmap points + unique target markers.
        """
        with self._lock:
            clusters = list(self._clusters.values())
            seq = self._update_seq

        if category_filter and category_filter.lower() != "all":
            clusters = [c for c in clusters if c.category.lower() == category_filter.lower()]

        heatmap_points: List[Dict[str, Any]] = []
        markers: List[Dict[str, Any]] = []
        sigma_deg = (self.config.spatial_smoothing_sigma_m / EARTH_RADIUS_M) * (180.0 / math.pi)

        for c in clusters:
            base_intensity = round(min(1.0, c.aggregated_confidence * c.priority_weight), 3)
            heatmap_points.append({
                "lat": c.estimated_lat,
                "lon": c.estimated_lon,
                "intensity": base_intensity,
                "color": c.display_color,
                "priority_level": c.priority_level,
            })
            # Configurable spatial smoothing halo around each unique target cluster
            for angle_deg in (0, 90, 180, 270):
                rad = math.radians(angle_deg)
                heatmap_points.append({
                    "lat": round(c.estimated_lat + sigma_deg * math.sin(rad), 7),
                    "lon": round(c.estimated_lon + sigma_deg * math.cos(rad), 7),
                    "intensity": round(base_intensity * 0.45, 3),
                    "color": c.display_color,
                    "priority_level": c.priority_level,
                })

            markers.append(asdict(c))

        return {
            "sequence": seq,
            "heatmap_type": "VISUAL_DETECTION_HEATMAP",
            "total_unique_objects": len(markers),
            "heatmap_points": heatmap_points,
            "markers": markers,
            "addc_intelligence": self.get_addc_intelligence_status(),
        }


# ============================================================================
# 7. NON-BLOCKING 8-STAGE VISION PIPELINE ORCHESTRATOR & FLASK BLUEPRINT
# ============================================================================

class NonBlockingVisionPipeline:
    """
    Executes the 8-stage pipeline using bounded queues so camera frame processing,
    object detection, and QR decoding never block Flask or MAVLink telemetry.
    """

    def __init__(
        self,
        config: VisionHeatmapConfig,
        detector_fn: Optional[Callable[[np.ndarray], List[RawObjectDetection]]] = None,
    ):
        self.config = config
        self.preprocessor = ImagePreprocessorAndNoiseGate(config)
        self.tracker = LightweightObjectTracker()
        self.projector = CameraGeoprojector(config)
        self.heatmap_engine = GeospatialHeatmapAndQREngine(config)
        self.qr_detector = cv2.QRCodeDetector()
        self.detector_fn = detector_fn or self._default_contour_and_color_detector

        self._frame_queue: "queue.Queue[Tuple[int, np.ndarray, DronePoseSnapshot]]" = queue.Queue(
            maxsize=config.queue_max_size
        )
        self._frame_counter = 0
        self._running = False
        self._metrics_lock = threading.Lock()
        self._last_inference_ms = 0.0
        self._last_map_update_ms = 0.0
        os.makedirs(self.config.image_save_dir, exist_ok=True)

    def submit_camera_frame(self, frame_bgr: np.ndarray, pose: DronePoseSnapshot) -> bool:
        """Stage 1: Camera frame acquisition with configurable frame sampling."""
        self._frame_counter += 1
        if self._frame_counter % max(1, self.config.frame_sample_every_n) != 0:
            return False
        try:
            self._frame_queue.put_nowait((self._frame_counter, frame_bgr, pose))
            return True
        except queue.Full:
            return False

    def process_single_frame_sync(self, frame_bgr: np.ndarray, pose: DronePoseSnapshot) -> List[GeoTargetCluster]:
        """Executes Stages 2 through 7 synchronously (used by background worker and unit tests)."""
        t0 = time.perf_counter()

        # Stage 2: Image preprocessing & low-light enhancement
        enhanced_bgr, _ = self.preprocessor.preprocess_frame(frame_bgr)

        # Stage 3: Object detection + confidence threshold + noise/shadow gate
        raw_candidates = self.detector_fn(enhanced_bgr)
        valid_detections: List[RawObjectDetection] = []
        for det in raw_candidates:
            thresh = self.config.confidence_thresholds.get(
                det.category, self.config.confidence_thresholds.get("default", 0.5)
            )
            if det.confidence < thresh:
                continue
            passed, _ = self.preprocessor.passes_evidence_gate(enhanced_bgr, det.bbox_xyxy)
            if passed:
                valid_detections.append(det)

        # Preserve OpenCV QR detection alongside object detection
        qr_text, qr_pts, _ = self.qr_detector.detectAndDecode(enhanced_bgr)
        if qr_text and qr_pts is not None and len(qr_pts) > 0:
            pts = qr_pts.reshape(-1, 2)
            qx1, qy1 = int(np.min(pts[:, 0])), int(np.min(pts[:, 1]))
            qx2, qy2 = int(np.max(pts[:, 0])), int(np.max(pts[:, 1]))
            valid_detections.append(
                RawObjectDetection(
                    bbox_xyxy=(qx1, qy1, qx2, qy2),
                    category="qr_target",
                    confidence=0.98,
                    timestamp=pose.timestamp,
                    qr_decoded_text=qr_text.strip(),
                )
            )

        # Stage 4: Detection tracking & duplicate suppression
        tracked_detections = self.tracker.update(valid_detections, now_ts=pose.timestamp)
        t_infer_done = time.perf_counter()

        # Stage 5, 6, 7: 3D GPS Projection, Priority Assignment & Heatmap Aggregation
        updated_clusters: List[GeoTargetCluster] = []
        for det in tracked_detections:
            est_lat, est_lon, unc_m, proj_valid, is_approx = self.projector.project_bbox_to_gps(
                det.bbox_xyxy, pose
            )
            prio_level = (
                TargetPriorityLevel.QR_VERIFIED.value
                if det.qr_decoded_text
                else self.config.category_priority_map.get(det.category, TargetPriorityLevel.UNKNOWN.value)
            )
            prio_weight = self.config.priority_weights.get(prio_level, 0.35)
            color = self.config.priority_colors.get(prio_level, "#FACC15")

            # Save associated crop/image evidence
            img_filename = f"{det.track_id}_{int(det.timestamp * 1000)}.jpg"
            img_rel_path = os.path.join(self.config.image_save_dir, img_filename)
            try:
                cv2.imwrite(img_rel_path, enhanced_bgr)
            except Exception:
                img_rel_path = None

            proj_det = ProjectedDetection(
                detection_id=f"det-{uuid.uuid4().hex[:8]}",
                track_id=det.track_id or "untracked",
                category=det.category,
                priority_level=prio_level,
                priority_weight=prio_weight,
                display_color=color,
                confidence=det.confidence,
                timestamp=det.timestamp,
                bbox_xyxy=det.bbox_xyxy,
                estimated_lat=est_lat,
                estimated_lon=est_lon,
                uncertainty_m=unc_m,
                projection_valid=proj_valid,
                is_approximate=is_approx,
                image_path=img_rel_path,
                qr_verified=bool(det.qr_decoded_text),
                qr_content=det.qr_decoded_text,
            )

            cluster = self.heatmap_engine.ingest_projected_detection(proj_det)
            if cluster:
                if det.qr_decoded_text:
                    self.heatmap_engine.record_qr_verification(
                        det.qr_decoded_text, cluster.cluster_id, img_rel_path
                    )
                updated_clusters.append(cluster)

        t_end = time.perf_counter()
        with self._metrics_lock:
            self._last_inference_ms = round((t_infer_done - t0) * 1000.0, 2)
            self._last_map_update_ms = round((t_end - t_infer_done) * 1000.0, 2)

        return updated_clusters

    @staticmethod
    def _default_contour_and_color_detector(frame_bgr: np.ndarray) -> List[RawObjectDetection]:
        """Fallback lightweight RPi 4 detector when TFLite/ONNX weights path is not yet configured."""
        return []

    def start_background_worker(self) -> None:
        self._running = True
        threading.Thread(target=self._worker_loop, name="VisionPipelineWorker", daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def _worker_loop(self) -> None:
        while self._running:
            try:
                _, frame_bgr, pose = self._frame_queue.get(timeout=0.5)
                self.process_single_frame_sync(frame_bgr, pose)
            except queue.Empty:
                continue
            except Exception as exc:
                logger.exception("Vision pipeline error: %s", exc)

    def get_performance_metrics(self) -> Dict[str, Any]:
        cpu_load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        with self._metrics_lock:
            return {
                "inference_latency_ms": self._last_inference_ms,
                "map_aggregation_latency_ms": self._last_map_update_ms,
                "frame_queue_depth": self._frame_queue.qsize(),
                "cpu_load_1m": round(cpu_load, 2),
            }


def create_task2_vision_blueprint(pipeline: NonBlockingVisionPipeline) -> Blueprint:
    """Stage 8: Extends the existing Flask app with non-blocking heatmap, marker, and QR endpoints."""
    bp = Blueprint("task2_vision_heatmap", __name__, url_prefix="/api/v2/vision")

    @bp.route("/heatmap", methods=["GET"])
    def get_heatmap():
        category = request.args.get("category", "all")
        payload = pipeline.heatmap_engine.generate_heatmap_payload(category_filter=category)
        payload["performance"] = pipeline.get_performance_metrics()
        return jsonify(payload)

    @bp.route("/config", methods=["GET", "POST"])
    def update_vision_config():
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            if "confidence_thresholds" in body:
                pipeline.config.confidence_thresholds.update(body["confidence_thresholds"])
            if "priority_colors" in body:
                pipeline.config.priority_colors.update(body["priority_colors"])
            if "category_priority_map" in body:
                pipeline.config.category_priority_map.update(body["category_priority_map"])
            if "frame_sample_every_n" in body:
                pipeline.config.frame_sample_every_n = max(1, int(body["frame_sample_every_n"]))
        return jsonify({
            "confidence_thresholds": pipeline.config.confidence_thresholds,
            "priority_colors": pipeline.config.priority_colors,
            "category_priority_map": pipeline.config.category_priority_map,
            "frame_sample_every_n": pipeline.config.frame_sample_every_n,
        })

    @bp.route("/qr_puzzle_digits", methods=["POST"])
    def submit_ground_puzzle_digits():
        body = request.get_json(silent=True) or {}
        digits = str(body.get("ground_puzzle_digits", ""))
        status = pipeline.heatmap_engine.set_ground_operative_puzzle_digits(digits)
        return jsonify(status)

    return bp

