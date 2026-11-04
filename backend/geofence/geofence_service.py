"""
Geofence Boundary and Navigation Planning Subsystem for AUTONOMOUS-DRONE.
Implements ray-casting point-in-polygon and Haversine circular boundary checks,
altitude ceiling/floor verification, and mission waypoint safety audits.
"""
import json
import math
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple

from config.settings import settings
from config.logging_config import setup_logging
from backend.mission.mission_model import Mission, Waypoint

logger = setup_logging("geofence_service")


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute great-circle distance between two coordinates in meters.
    Formula: Haversine
    """
    R = 6371000.0  # Earth mean radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def point_in_polygon(lat: float, lon: float, polygon: List[Dict[str, float]]) -> bool:
    """
    Standard Jordan curve ray-casting algorithm to determine if point (lat, lon)
    is strictly inside a 2D planar polygon.
    """
    if len(polygon) < 3:
        return False

    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]["lat"], polygon[i]["lon"]
        xj, yj = polygon[j]["lat"], polygon[j]["lon"]

        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


@dataclass
class GeofenceConfig:
    """Configurable geographic safety boundary parameters."""
    enabled: bool = True
    fence_type: str = "circular"  # "circular" or "polygon"
    circle_center_lat: float = 37.4093
    circle_center_lon: float = -122.0641
    circle_radius_m: float = 250.0
    polygon_vertices: List[Dict[str, float]] = field(default_factory=lambda: [
        {"lat": 37.4110, "lon": -122.0660},
        {"lat": 37.4110, "lon": -122.0620},
        {"lat": 37.4075, "lon": -122.0620},
        {"lat": 37.4075, "lon": -122.0660}
    ])
    min_alt_m: float = 1.0
    max_alt_m: float = 120.0  # Standard FAA/regulatory 400ft ceiling in meters
    breach_action: str = "RTL"  # "RTL", "LAND", "WARN"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GeofenceConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            fence_type=str(data.get("fence_type", "circular")).lower(),
            circle_center_lat=float(data.get("circle_center_lat", 37.4093)),
            circle_center_lon=float(data.get("circle_center_lon", -122.0641)),
            circle_radius_m=float(data.get("circle_radius_m", 250.0)),
            polygon_vertices=data.get("polygon_vertices", []),
            min_alt_m=float(data.get("min_alt_m", 1.0)),
            max_alt_m=float(data.get("max_alt_m", 120.0)),
            breach_action=str(data.get("breach_action", "RTL")).upper()
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GeofenceService:
    """Validates real-time positions and planned waypoint missions against geofence boundaries."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or settings.GEOFENCE_FILE
        self._lock = threading.Lock()
        self.config = GeofenceConfig()
        self._load_config()

    def _load_config(self) -> None:
        """Load persisted geofence parameters."""
        if not self.storage_path.exists():
            self._save_config()
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.config = GeofenceConfig.from_dict(data)
            logger.info("Loaded geofence configuration (%s, radius: %.1fm)", self.config.fence_type, self.config.circle_radius_m)
        except Exception as e:
            logger.error("Failed loading geofence config: %s; using defaults", e)
            self._save_config()

    def _save_config(self) -> None:
        """Persist geofence parameters to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, indent=2)
        except Exception as e:
            logger.error("Failed persisting geofence config: %s", e)

    def update_config(self, updates: Dict[str, Any]) -> GeofenceConfig:
        """Safely update and persist geofence parameters."""
        with self._lock:
            cur = self.config.to_dict()
            cur.update(updates)
            self.config = GeofenceConfig.from_dict(cur)
            self._save_config()
        return self.config

    def check_coordinate(self, lat: float, lon: float, alt_m: float) -> Dict[str, Any]:
        """
        Verify if a given coordinate is strictly within configured horizontal and vertical boundaries.
        """
        # Coordinate sanity validation
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return {
                "inside": False,
                "horizontal_ok": False,
                "vertical_ok": False,
                "violations": ["Invalid GPS coordinates: latitude or longitude out of range"]
            }

        with self._lock:
            cfg = self.config

        if not cfg.enabled:
            return {
                "inside": True,
                "horizontal_ok": True,
                "vertical_ok": True,
                "geofence_enabled": False,
                "violations": []
            }

        violations: List[str] = []
        horizontal_ok = False
        dist_to_center = 0.0

        # Horizontal check
        if cfg.fence_type == "circular":
            dist_to_center = round(haversine_distance_m(lat, lon, cfg.circle_center_lat, cfg.circle_center_lon), 1)
            horizontal_ok = dist_to_center <= cfg.circle_radius_m
            if not horizontal_ok:
                violations.append(f"Position exceeds circular fence radius ({dist_to_center}m > {cfg.circle_radius_m}m)")
        elif cfg.fence_type == "polygon":
            horizontal_ok = point_in_polygon(lat, lon, cfg.polygon_vertices)
            if not horizontal_ok:
                violations.append("Position lies outside the designated polygon boundary")

        # Vertical check
        vertical_ok = True
        if alt_m < cfg.min_alt_m:
            vertical_ok = False
            violations.append(f"Altitude {alt_m:.1f}m below floor safety limit ({cfg.min_alt_m}m)")
        elif alt_m > cfg.max_alt_m:
            vertical_ok = False
            violations.append(f"Altitude {alt_m:.1f}m exceeds ceiling limit ({cfg.max_alt_m}m)")

        inside = horizontal_ok and vertical_ok

        return {
            "inside": inside,
            "horizontal_ok": horizontal_ok,
            "vertical_ok": vertical_ok,
            "fence_type": cfg.fence_type,
            "distance_to_center_m": dist_to_center if cfg.fence_type == "circular" else None,
            "altitude_m": alt_m,
            "violations": violations
        }

    def validate_mission(self, mission: Mission) -> Dict[str, Any]:
        """
        Verify that all waypoints of a mission conform to the geofence.
        """
        waypoint_reports: List[Dict[str, Any]] = []
        all_passed = True
        total_violations: List[str] = []

        for wp in mission.waypoints:
            check = self.check_coordinate(wp.lat, wp.lon, wp.alt_m)
            check["seq"] = wp.seq
            check["action"] = wp.action
            if not check["inside"]:
                all_passed = False
                for v in check["violations"]:
                    total_violations.append(f"Waypoint #{wp.seq}: {v}")
            waypoint_reports.append(check)

        path_metrics = self.calculate_path_metrics(mission.waypoints)

        return {
            "valid": all_passed,
            "mission_id": mission.id,
            "total_waypoints": len(mission.waypoints),
            "violations": total_violations,
            "path_metrics": path_metrics,
            "waypoint_reports": waypoint_reports
        }

    @classmethod
    def calculate_path_metrics(cls, waypoints: List[Waypoint]) -> Dict[str, Any]:
        """Calculate total trajectory length, leg distances, and estimated flight duration."""
        if len(waypoints) < 2:
            return {
                "total_distance_m": 0.0,
                "estimated_time_s": 0.0,
                "leg_distances_m": []
            }

        total_dist = 0.0
        total_time = 0.0
        leg_distances: List[float] = []

        for i in range(len(waypoints) - 1):
            w1 = waypoints[i]
            w2 = waypoints[i + 1]

            horiz_dist = haversine_distance_m(w1.lat, w1.lon, w2.lat, w2.lon)
            vert_dist = abs(w2.alt_m - w1.alt_m)
            leg_dist = math.sqrt(horiz_dist ** 2 + vert_dist ** 2)

            leg_distances.append(round(leg_dist, 1))
            total_dist += leg_dist

            cruise_speed = max(w2.speed_m_s, 1.0)
            total_time += (leg_dist / cruise_speed) + w2.hold_time_s

        return {
            "total_distance_m": round(total_dist, 1),
            "estimated_time_s": round(total_time, 1),
            "estimated_time_formatted": f"{int(total_time // 60)}m {int(total_time % 60)}s",
            "leg_distances_m": leg_distances
        }


# Global singleton instance
geofence_service = GeofenceService()
