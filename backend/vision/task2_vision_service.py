"""
Integrated Asynchronous Task 2 Vision, Priority Candidate Detection & Live Heatmap Engine.
Features:
- Asynchronous pipeline with bounded queue (maxsize=6) and drop-oldest policy.
- Releases camera locks immediately after buffer acquisition.
- Priority-based candidate detection (Square/Rect: Orange, B/W pattern: Yellow, Other: Purple, Low Conf: Grey).
- QR code detection & allowlist validation (Blue unverified -> Green validated).
- 3D pinhole camera-to-ground photogrammetry with uncertainty radius and degraded flag.
- Haversine spatial deduplication and clustering (4.0m) preserving complete raw history.
- Evidence image persistence to captures/evidence/.
- Configurable, safe RTL recommendation logging with idempotent mission stop.
"""
import logging
import math
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

from config.settings import settings
from config.logging_config import setup_logging
from backend.camera.camera_manager import camera_manager
from backend.flight.mavlink_service import mavlink_service
from backend.flight.flight_controller import flight_controller
from backend.mission.mission_service import mission_service
from backend.mission.mission_model import MissionState
from backend.vision.geoprojector import (
    CameraGeoprojector,
    CameraCalibration,
    DronePose,
    EARTH_RADIUS_M,
)
from backend.vision.priority_detector import (
    PriorityTargetDetector,
    CandidateDetection,
    DetectionCategory,
    CATEGORY_COLORS,
)
from backend.vision.qr_detector import QRDetector

logger = setup_logging("task2_vision_service")


def haversine_dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


@dataclass
class DetectionCluster:
    """Spatially deduplicated cluster of visual target observations."""
    cluster_id: str
    category: str
    display_color: str
    estimated_lat: float
    estimated_lon: float
    uncertainty_m: float
    is_approximate: bool
    confidence: float
    observation_count: int
    first_seen_ts: float
    last_seen_ts: float
    is_confirmed: bool = False
    qr_payload: Optional[str] = None
    qr_validated: bool = False
    evidence_image_path: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Task2VisionEngine:
    """
    Orchestrates candidate detection, QR decoding, 3D geoprojection,
    spatial clustering, evidence storage, and live heatmap updates.
    """

    def __init__(self):
        self.priority_detector = PriorityTargetDetector()
        self.qr_detector = QRDetector()

        calib = CameraCalibration(
            image_width=settings.CAMERA_WIDTH,
            image_height=settings.CAMERA_HEIGHT,
            hfov_deg=settings.CAMERA_HFOV_DEG,
            vfov_deg=settings.CAMERA_VFOV_DEG,
            mount_pitch_deg=settings.CAMERA_MOUNT_PITCH_DEG,
            mount_roll_deg=settings.CAMERA_MOUNT_ROLL_DEG,
            mount_yaw_deg=settings.CAMERA_MOUNT_YAW_DEG,
        )
        self.projector = CameraGeoprojector(calib)

        # Queues and threading
        self._frame_queue: "queue.Queue[Tuple[int, np.ndarray, DronePose]]" = queue.Queue(maxsize=6)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State storage
        self._clusters: Dict[str, DetectionCluster] = {}
        self._raw_detections: List[Dict[str, Any]] = []
        self._sequence: int = 0
        self._total_frames_acquired = 0
        self._total_frames_processed = 0
        self._total_dropped_frames = 0
        self._qr_seen_cache: Dict[str, float] = {}
        self._rtl_dispatched: bool = False

        # Config
        self.cluster_radius_m = settings.HEATMAP_CLUSTER_RADIUS_M
        self.evidence_dir = settings.EVIDENCE_CAPTURES_DIR
        self.validation_regex = re.compile(settings.QR_VALIDATION_REGEX)
        self.auto_rtl_enabled = settings.QR_AUTO_RTL_ENABLED

        # Ensure evidence storage exists
        os.makedirs(self.evidence_dir, exist_ok=True)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop, name="Task2VisionWorker", daemon=True
            )
            self._worker_thread.start()
            logger.info("Task 2 Vision & Live Heatmap Engine started")
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._running:
                return True
            self._running = False

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None
        return True

    def submit_frame(self, frame_bgr: np.ndarray, pose: DronePose) -> bool:
        """
        Stage 1: Submit camera frame copy to processing queue with drop-oldest policy.
        Camera lock must be released before calling this.
        """
        self._total_frames_acquired += 1
        # Frame sampling: sample every Nth frame (default 3)
        if self._total_frames_acquired % max(1, settings.CANDIDATE_FRAME_SAMPLE_N) != 0:
            return False

        try:
            self._frame_queue.put_nowait((self._total_frames_acquired, frame_bgr, pose))
            return True
        except queue.Full:
            # Drop oldest frame to ensure fresh telemetry alignment and low latency
            try:
                self._frame_queue.get_nowait()
                self._total_dropped_frames += 1
                self._frame_queue.put_nowait((self._total_frames_acquired, frame_bgr, pose))
                return True
            except (queue.Empty, queue.Full):
                return False

    def _worker_loop(self) -> None:
        while self.is_running:
            try:
                seq, frame, pose = self._frame_queue.get(timeout=0.4)
                self.process_frame_sync(frame, pose)
                self._total_frames_processed += 1
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Error in vision worker loop: %s", e)

    def process_frame_sync(
        self, frame_bgr: np.ndarray, pose: DronePose, save_evidence: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Synchronous processing pipeline across candidate detection, QR decoding,
        geoprojection, and heatmap clustering.
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return []

        timestamp = pose.timestamp or time.time()
        accepted_records: List[Dict[str, Any]] = []

        # 1. Candidate Geometric & High-Contrast Detection
        candidates = self.priority_detector.detect_candidates(frame_bgr)

        # 2. QR Decoding Stage
        qr_results = self.qr_detector.detect_and_decode(frame_bgr)
        for qr in qr_results:
            is_valid_payload = bool(self.validation_regex.match(qr.payload.strip()))
            cat = DetectionCategory.QR_VALIDATED if is_valid_payload else DetectionCategory.QR_UNVERIFIED
            candidates.append(CandidateDetection(
                bbox=(qr.bbox["x"], qr.bbox["y"], qr.bbox["width"], qr.bbox["height"]),
                center_xy=tuple(qr.center),
                category=cat,
                confidence=round(qr.confidence, 2),
                is_confirmed=is_valid_payload,
                evidence_score=1.0 if is_valid_payload else 0.7,
                qr_payload=qr.payload.strip(),
                extra_meta={"source": "qr_decoder", "valid_payload": is_valid_payload}
            ))

        # 3. Process each candidate: Geoprojection, Evidence Capture, Spatial Clustering
        for cand in candidates:
            # Geoproject center pixel onto ground plane
            u, v = float(cand.center_xy[0]), float(cand.center_xy[1])
            est_lat, est_lon, unc_m, proj_valid, is_approx = self.projector.project_pixel_to_ground(u, v, pose)

            # High-res Evidence Capture for Priority candidates & QR detections
            evidence_rel_path = None
            if save_evidence and (cand.category in (
                DetectionCategory.SQUARE_CANDIDATE,
                DetectionCategory.RECTANGLE_CANDIDATE,
                DetectionCategory.BW_PATTERN,
                DetectionCategory.QR_UNVERIFIED,
                DetectionCategory.QR_VALIDATED,
            ) or cand.confidence >= 0.75):
                img_name = f"det_{int(timestamp * 1000)}_{uuid.uuid4().hex[:6]}.jpg"
                evidence_path = os.path.join(self.evidence_dir, img_name)
                evidence_rel_path = f"/api/camera/image/{img_name}"

                # Crop ROI with margin
                x, y, bw, bh = cand.bbox
                h_img, w_img = frame_bgr.shape[:2]
                pad_x = int(bw * 0.2)
                pad_y = int(bh * 0.2)
                x1 = max(0, x - pad_x)
                y1 = max(0, y - pad_y)
                x2 = min(w_img, x + bw + pad_x)
                y2 = min(h_img, y + bh + pad_y)

                roi_crop = frame_bgr[y1:y2, x1:x2]
                try:
                    cv2.imwrite(evidence_path, roi_crop if roi_crop.size > 0 else frame_bgr)
                except Exception as ex:
                    logger.debug("Failed saving evidence crop: %s", ex)
                    evidence_rel_path = None

            record = {
                "detection_id": f"det-{uuid.uuid4().hex[:8]}",
                "timestamp": timestamp,
                "category": cand.category.value,
                "color": cand.color,
                "confidence": cand.confidence,
                "is_confirmed": cand.is_confirmed,
                "bbox": {"x": cand.bbox[0], "y": cand.bbox[1], "width": cand.bbox[2], "height": cand.bbox[3]},
                "center": [cand.center_xy[0], cand.center_xy[1]],
                "estimated_lat": est_lat,
                "estimated_lon": est_lon,
                "uncertainty_m": unc_m,
                "projection_valid": proj_valid,
                "is_approximate": is_approx,
                "evidence_image": evidence_rel_path,
                "qr_payload": cand.qr_payload,
            }

            # Spatial Clustering & Deduplication
            cluster = self._ingest_into_spatial_cluster(record)
            accepted_records.append(record)

            # QR Validation & RTL Trigger Check
            if cand.category == DetectionCategory.QR_VALIDATED and cand.qr_payload:
                self._handle_validated_qr_event(cand.qr_payload, record)

        with self._lock:
            self._raw_detections.extend(accepted_records)
            if len(self._raw_detections) > 100:
                self._raw_detections = self._raw_detections[-100:]
            self._sequence += 1

        return accepted_records

    def _ingest_into_spatial_cluster(self, record: Dict[str, Any]) -> Optional[DetectionCluster]:
        """Group nearby detections within cluster_radius_m into a single cluster."""
        lat = record.get("estimated_lat")
        lon = record.get("estimated_lon")
        if lat is None or lon is None:
            return None

        cat = record["category"]
        conf = float(record["confidence"])
        unc = float(record.get("uncertainty_m") or 5.0)
        color = record["color"]
        img = record.get("evidence_image")
        qr = record.get("qr_payload")
        qr_val = bool(cat == DetectionCategory.QR_VALIDATED.value)

        with self._lock:
            # Find nearest existing cluster within radius
            best_cid = None
            best_dist = self.cluster_radius_m

            for cid, cluster in self._clusters.items():
                # Allow QR validated to merge into QR unverified or same category
                if cluster.category != cat and not qr_val:
                    continue
                d = haversine_dist_m(lat, lon, cluster.estimated_lat, cluster.estimated_lon)
                if d <= best_dist:
                    best_dist = d
                    best_cid = cid

            if best_cid and best_cid in self._clusters:
                c = self._clusters[best_cid]
                n = c.observation_count
                # Inverse-uncertainty weighted coordinate smoothing
                w_new = 1.0 / max(0.5, unc)
                w_old = float(min(n, 12)) / max(0.5, c.uncertainty_m)
                w_sum = w_old + w_new

                c.estimated_lat = round((c.estimated_lat * w_old + lat * w_new) / w_sum, 7)
                c.estimated_lon = round((c.estimated_lon * w_old + lon * w_new) / w_sum, 7)
                c.uncertainty_m = round(min(c.uncertainty_m, unc), 2)
                c.is_approximate = c.is_approximate and record.get("is_approximate", False)
                # Bounded Bayesian confidence accumulation
                c.confidence = round(min(0.99, 1.0 - (1.0 - c.confidence) * (1.0 - 0.30 * conf)), 3)
                c.observation_count += 1
                c.last_seen_ts = record["timestamp"]
                if img:
                    c.evidence_image_path = img
                if qr_val:
                    c.category = DetectionCategory.QR_VALIDATED.value
                    c.display_color = CATEGORY_COLORS[DetectionCategory.QR_VALIDATED]
                    c.qr_validated = True
                    c.qr_payload = qr
                    c.is_confirmed = True
                c.history.append({
                    "timestamp": record["timestamp"],
                    "confidence": conf,
                    "lat": lat,
                    "lon": lon,
                })
                if len(c.history) > 20:
                    c.history.pop(0)
                return c
            else:
                cid = f"target-{uuid.uuid4().hex[:8]}"
                cluster = DetectionCluster(
                    cluster_id=cid,
                    category=cat,
                    display_color=color,
                    estimated_lat=lat,
                    estimated_lon=lon,
                    uncertainty_m=unc,
                    is_approximate=record.get("is_approximate", False),
                    confidence=conf,
                    observation_count=1,
                    first_seen_ts=record["timestamp"],
                    last_seen_ts=record["timestamp"],
                    is_confirmed=record.get("is_confirmed", False),
                    qr_payload=qr,
                    qr_validated=qr_val,
                    evidence_image_path=img,
                    history=[{"timestamp": record["timestamp"], "confidence": conf, "lat": lat, "lon": lon}],
                )
                self._clusters[cid] = cluster
                return cluster

    def _handle_validated_qr_event(self, payload: str, record: Dict[str, Any]) -> None:
        """
        Handle validated QR payload:
        1. Debounce duplicates via cache.
        2. Idempotently halt active scanning mission.
        3. Log RTL recommendation; if QR_AUTO_RTL_ENABLED is explicitly True, dispatch RTL.
        """
        now = time.time()
        with self._lock:
            last_seen = self._qr_seen_cache.get(payload, 0.0)
            if (now - last_seen) < settings.QR_COOLDOWN_SECONDS:
                return  # Debounced duplicate
            self._qr_seen_cache[payload] = now

        logger.info("🎯 VALIDATED QR CODE DETECTED: '%s' at (lat: %s, lon: %s)",
                    payload, record.get("estimated_lat"), record.get("estimated_lon"))

        # Idempotently halt active mission
        active_mission = mission_service.get_active_mission()
        if active_mission and active_mission.state in (MissionState.EXECUTING, MissionState.READY):
            try:
                mission_service.set_mission_state(
                    active_mission.id,
                    MissionState.COMPLETED,
                    reason=f"Mission targets acquired: Validated QR '{payload}' verified.",
                )
                logger.info("Active mission '%s' halted upon QR target acquisition", active_mission.id)
            except Exception as e:
                logger.error("Failed halting mission on QR: %s", e)

        # Safety: Initially log RTL recommendation without blind flight commands
        if not self.auto_rtl_enabled:
            logger.info("⚠️ [SAFETY INTERLOCK] QR Validated. Automatic RTL is DISABLED in settings. Recommended operator action: RTL.")
            record["rtl_recommendation"] = "RECOMMENDED_BY_VISION"
            return

        # Automatic RTL (only when explicitly configured and vehicle is connected)
        with self._lock:
            if self._rtl_dispatched:
                return
            self._rtl_dispatched = True

        logger.warning("⚡ [AUTO-RTL TRIGGER] Requesting Return-to-Launch from Pixhawk...")
        try:
            res = flight_controller.request_rtl()
            record["rtl_dispatch_result"] = res
            logger.info("Auto-RTL outcome: %s", res)
        except Exception as ex:
            logger.error("Failed executing Auto-RTL: %s", ex)
            record["rtl_dispatch_result"] = {"success": False, "message": str(ex)}

    def get_live_heatmap(self) -> Dict[str, Any]:
        """
        Generate live 7-category heatmap payload with spatial clusters,
        detection counts, and performance metrics.
        """
        with self._lock:
            clusters_list = [c.to_dict() for c in self._clusters.values()]
            seq = self._sequence
            total_objs = len(clusters_list)
            raw_count = len(self._raw_detections)

        # Build heatmap intensity points and marker list for canvas and overlay
        heatmap_points = []
        markers = []
        for c in clusters_list:
            heatmap_points.append({
                "lat": c["estimated_lat"],
                "lon": c["estimated_lon"],
                "intensity": round(c["confidence"], 2),
                "category": c["category"],
                "color": c["display_color"],
                "is_confirmed": c["is_confirmed"],
                "uncertainty_m": c["uncertainty_m"],
            })
            markers.append({
                "cluster_id": c["cluster_id"],
                "estimated_lat": c["estimated_lat"],
                "estimated_lon": c["estimated_lon"],
                "uncertainty_m": c["uncertainty_m"],
                "is_approximate": c["is_approximate"],
                "category": c["category"],
                "priority_level": c["category"],
                "display_color": c["display_color"],
                "aggregated_confidence": c["confidence"],
                "observation_count": c["observation_count"],
                "qr_verified": c["qr_validated"],
                "qr_content": c["qr_payload"],
                "latest_image_path": c["evidence_image_path"],
                "first_seen_ts": c["first_seen_ts"],
                "last_seen_ts": c["last_seen_ts"],
            })

        return {
            "status": "success",
            "heatmap_type": "VISUAL_DETECTION_HEATMAP",
            "sequence": seq,
            "total_unique_targets": total_objs,
            "total_unique_objects": total_objs,
            "total_raw_detections": raw_count,
            "clusters": clusters_list,
            "markers": markers,
            "heatmap_points": heatmap_points,
            "category_colors": {k.value: v for k, v in CATEGORY_COLORS.items()},
            "addc_intelligence": {
                "drone_qr_2_digits": getattr(self, "_addc_qr_digits", None),
                "ground_operative_puzzle_2_digits": getattr(self, "_addc_puzzle_digits", None),
                "intelligence_code_complete": getattr(self, "_addc_complete", False),
                "combined_4_digit_access_code": getattr(self, "_addc_combined", None),
            },
            "metrics": {
                "frames_acquired": self._total_frames_acquired,
                "frames_processed": self._total_frames_processed,
                "frames_dropped": self._total_dropped_frames,
                "queue_depth": self._frame_queue.qsize(),
            }
        }

    def clear_state(self) -> None:
        """Clear all active clusters and raw detections (for testing and resets)."""
        with self._lock:
            self._clusters.clear()
            self._raw_detections.clear()
            self._qr_seen_cache.clear()
            self._rtl_dispatched = False
            self._sequence += 1


# Global Task 2 Vision Engine Singleton
task2_vision_engine = Task2VisionEngine()
