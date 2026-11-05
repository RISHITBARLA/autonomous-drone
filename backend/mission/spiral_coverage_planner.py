"""
Archimedean Spiral and Tangential Coverage Planner for AUTONOMOUS-DRONE.
Generates safe, geofence-validated waypoint scanning trajectories covering the complete
interior of circular boundaries with configurable camera footprint, overlap, and altitude.
"""
import math
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

from backend.geofence.geofence_service import (
    geofence_service,
    haversine_distance_m,
)
from backend.mission.mission_model import Waypoint, Mission, MissionState

EARTH_RADIUS_M = 6378137.0


def geo_to_tangent_plane(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """
    Local tangent plane equirectangular projection centered at reference point.
    Returns: (x_east_meters, y_north_meters)
    """
    lat_rad = math.radians(lat)
    ref_lat_rad = math.radians(ref_lat)
    d_lat = lat_rad - ref_lat_rad
    d_lon = math.radians(lon - ref_lon)
    mean_lat = (lat_rad + ref_lat_rad) / 2.0

    x = EARTH_RADIUS_M * d_lon * math.cos(mean_lat)
    y = EARTH_RADIUS_M * d_lat
    return (round(x, 3), round(y, 3))


def tangent_plane_to_geo(x: float, y: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """
    Inverse projection from local tangent plane (meters) to geographic coordinates.
    Returns: (lat, lon)
    """
    ref_lat_rad = math.radians(ref_lat)
    d_lat = y / EARTH_RADIUS_M
    lat_rad = ref_lat_rad + d_lat
    mean_lat = (ref_lat_rad + lat_rad) / 2.0
    cos_mean = math.cos(mean_lat)
    if abs(cos_mean) < 1e-6:
        cos_mean = 1e-6

    d_lon = x / (EARTH_RADIUS_M * cos_mean)
    lon_rad = math.radians(ref_lon) + d_lon

    return (round(math.degrees(lat_rad), 7), round(math.degrees(lon_rad), 7))


@dataclass
class SpiralCoverageConfig:
    """Configuration parameters for circular boundary scanning."""
    center_lat: float
    center_lon: float
    radius_m: float
    alt_m: float = 15.0
    speed_m_s: float = 4.0
    camera_hfov_deg: float = 62.2   # Sony IMX477 with 6mm lens
    overlap_pct: float = 25.0       # 25% lateral overlap to prevent blind spots
    explicit_spacing_m: Optional[float] = None
    min_turn_radius_m: float = 4.0   # Minimum flight turn radius to prevent severe bank
    pattern_type: str = "spiral"     # "spiral" (Archimedean) or "tangential" (concentric rings)
    safety_buffer_m: float = 3.0     # Buffer inside radius to prevent boundary overshoot


class SpiralCoveragePlanner:
    """
    Calculates camera ground footprint and generates interior-covering flight waypoints
    in Archimedean spiral or concentric tangential geometries.
    """

    def __init__(self, config: SpiralCoverageConfig):
        self.config = config

    def calculate_camera_swath(self) -> float:
        """
        Calculate ground swath width in meters based on altitude, HFOV, and overlap.
        swath = 2 * alt * tan(HFOV/2) * (1 - overlap)
        """
        alt = max(1.0, self.config.alt_m)
        half_fov_rad = math.radians(self.config.camera_hfov_deg / 2.0)
        full_footprint_m = 2.0 * alt * math.tan(half_fov_rad)
        overlap_factor = max(0.05, min(0.85, (100.0 - self.config.overlap_pct) / 100.0))
        effective_swath_m = full_footprint_m * overlap_factor
        return max(2.0, round(effective_swath_m, 2))

    def generate_waypoints(self) -> Tuple[List[Waypoint], Dict[str, Any]]:
        """
        Generate safe sequence of navigation waypoints covering the circular interior.
        Returns: (waypoints, metadata_dict)
        """
        if self.config.radius_m <= 0:
            raise ValueError("Radius must be greater than zero")
        if not (-90.0 <= self.config.center_lat <= 90.0) or not (-180.0 <= self.config.center_lon <= 180.0):
            raise ValueError("Invalid center GPS coordinates")

        swath_m = self.calculate_camera_swath()
        track_spacing_m = (
            self.config.explicit_spacing_m
            if self.config.explicit_spacing_m and self.config.explicit_spacing_m > 0
            else swath_m
        )

        effective_radius_m = max(5.0, self.config.radius_m - self.config.safety_buffer_m)
        pattern = self.config.pattern_type.lower()

        if pattern == "tangential":
            local_pts = self._generate_concentric_tangential_points(effective_radius_m, track_spacing_m)
        else:
            local_pts = self._generate_archimedean_spiral_points(effective_radius_m, track_spacing_m)

        # Convert local tangent plane points (x_east, y_north) to WGS84 Waypoints
        waypoints: List[Waypoint] = []
        ref_lat = self.config.center_lat
        ref_lon = self.config.center_lon
        alt = self.config.alt_m
        speed = self.config.speed_m_s

        for idx, (x, y) in enumerate(local_pts, start=1):
            lat, lon = tangent_plane_to_geo(x, y, ref_lat, ref_lon)
            wp = Waypoint(
                seq=idx,
                lat=lat,
                lon=lon,
                alt_m=alt,
                speed_m_s=speed,
                hold_time_s=0.5 if idx == 1 or idx == len(local_pts) else 0.0,
                action="WAYPOINT",
            )
            waypoints.append(wp)

        # Calculate path metrics
        path_length_m = 0.0
        for i in range(1, len(waypoints)):
            w1 = waypoints[i - 1]
            w2 = waypoints[i]
            path_length_m += haversine_distance_m(w1.lat, w1.lon, w2.lat, w2.lon)

        est_duration_s = round((path_length_m / max(0.5, speed)) + (len(waypoints) * 0.4), 1)
        total_area_m2 = round(math.pi * (self.config.radius_m ** 2), 1)

        metadata = {
            "pattern": pattern,
            "center": {"lat": ref_lat, "lon": ref_lon},
            "radius_m": self.config.radius_m,
            "effective_radius_m": round(effective_radius_m, 2),
            "altitude_m": alt,
            "swath_width_m": swath_m,
            "track_spacing_m": track_spacing_m,
            "waypoint_count": len(waypoints),
            "total_path_length_m": round(path_length_m, 1),
            "estimated_duration_s": est_duration_s,
            "scan_area_m2": total_area_m2,
        }

        return waypoints, metadata

    def _generate_archimedean_spiral_points(
        self, max_radius_m: float, spacing_m: float
    ) -> List[Tuple[float, float]]:
        """
        Generate Archimedean spiral coordinates: r(theta) = b * theta.
        Expands outward from center to max_radius_m.
        """
        points: List[Tuple[float, float]] = []
        b = spacing_m / (2.0 * math.pi)
        min_r = max(self.config.min_turn_radius_m, spacing_m * 0.6)

        theta_start = min_r / b
        theta_end = max_radius_m / b

        # Start with an initial point near center
        points.append((0.0, 0.0))

        # Discretize along theta with chord length roughly equal to step size
        theta = theta_start
        while theta <= theta_end:
            r = b * theta
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            points.append((round(x, 2), round(y, 2)))

            # Step theta dynamically so linear distance between waypoints remains ~4-6m
            target_chord_m = max(3.5, min(8.0, spacing_m * 0.75))
            d_theta = target_chord_m / max(min_r, r)
            theta += d_theta

        # Add closing boundary point at max radius
        final_x = max_radius_m * math.cos(theta_end)
        final_y = max_radius_m * math.sin(theta_end)
        points.append((round(final_x, 2), round(final_y, 2)))

        return points

    def _generate_concentric_tangential_points(
        self, max_radius_m: float, spacing_m: float
    ) -> List[Tuple[float, float]]:
        """
        Generate concentric circular rings connected by tangential transitions.
        """
        points: List[Tuple[float, float]] = [(0.0, 0.0)]
        min_r = max(self.config.min_turn_radius_m, spacing_m * 0.7)

        current_r = min_r
        ring_index = 0

        while current_r <= max_radius_m:
            # Number of waypoints on this circle ring scales with circumference
            circumference = 2.0 * math.pi * current_r
            num_pts = max(6, int(round(circumference / max(4.0, spacing_m * 0.75))))

            # Alternate clockwise and counter-clockwise to reduce large 360 loops
            angles = [2.0 * math.pi * i / num_pts for i in range(num_pts)]
            if ring_index % 2 == 1:
                angles.reverse()

            for ang in angles:
                x = current_r * math.cos(ang)
                y = current_r * math.sin(ang)
                points.append((round(x, 2), round(y, 2)))

            current_r += spacing_m
            ring_index += 1

        return points

    def validate_against_geofence(self, waypoints: List[Waypoint]) -> Tuple[bool, List[str]]:
        """
        Verify that every generated waypoint and the safe altitude envelope lie
        strictly inside the active geofence.
        Returns: (is_valid, list_of_violations)
        """
        violations: List[str] = []
        for wp in waypoints:
            res = geofence_service.check_coordinate(wp.lat, wp.lon, wp.alt_m)
            if not res.get("inside", False):
                wp_violations = res.get("violations", ["Outside geofence"])
                violations.append(f"Waypoint {wp.seq} ({wp.lat:.6f}, {wp.lon:.6f}): {', '.join(wp_violations)}")

        is_valid = len(violations) == 0
        return is_valid, violations

