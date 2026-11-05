"""
Dynamic Geofence-Based Coverage Planner for AUTONOMOUS-DRONE.
Supports arbitrary polygonal, rectangular, irregular, and circular geofence boundaries.
Implements dynamic Boustrophedon / parallel sweep coverage tracking, camera footprint
projection, metric grid decomposition, and movement command generation without
uploading or depending on pre-programmed GPS waypoint lists.
"""
import math
import threading
from typing import List, Dict, Any, Tuple, Optional, Set
from dataclasses import dataclass, field


def geo_to_local_meters(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """
    Project WGS84 geographic coordinate to local tangent plane in meters
    using equirectangular projection centered at reference origin.
    """
    R = 6371000.0  # Earth mean radius in meters
    mean_lat_rad = math.radians((lat + ref_lat) / 2.0)
    x = R * math.radians(lon - ref_lon) * math.cos(mean_lat_rad)
    y = R * math.radians(lat - ref_lat)
    return (round(x, 3), round(y, 3))


def local_meters_to_geo(x: float, y: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """
    Inverse projection from local tangent plane in meters to WGS84 geographic coordinate.
    """
    R = 6371000.0
    lat = ref_lat + math.degrees(y / R)
    mean_lat_rad = math.radians((lat + ref_lat) / 2.0)
    cos_lat = math.cos(mean_lat_rad)
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6
    lon = ref_lon + math.degrees(x / (R * cos_lat))
    return (round(lat, 7), round(lon, 7))


def point_in_polygon_2d(x: float, y: float, polygon: List[Tuple[float, float]]) -> bool:
    """
    Standard Jordan curve ray-casting test for point (x, y) inside 2D polygon.
    """
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def polygon_area_2d(polygon: List[Tuple[float, float]]) -> float:
    """Compute 2D polygon area in square meters using Shoelace formula."""
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2.0


@dataclass
class CameraFootprint:
    """Optical footprint of downward-facing camera on ground plane."""
    width_m: float
    height_m: float
    effective_spacing_m: float
    hfov_deg: float
    vfov_deg: float
    altitude_m: float
    overlap_ratio: float

    @classmethod
    def calculate(
        cls,
        altitude_m: float = 10.0,
        hfov_deg: float = 62.2,
        vfov_deg: float = 48.8,
        overlap_ratio: float = 0.25
    ) -> "CameraFootprint":
        """Compute camera footprint based on altitude, field of view, and overlap."""
        alt = max(1.0, float(altitude_m))
        overlap = min(0.8, max(0.0, float(overlap_ratio)))
        width = 2.0 * alt * math.tan(math.radians(hfov_deg / 2.0))
        height = 2.0 * alt * math.tan(math.radians(vfov_deg / 2.0))
        spacing = width * (1.0 - overlap)
        return cls(
            width_m=round(width, 2),
            height_m=round(height, 2),
            effective_spacing_m=round(max(1.0, spacing), 2),
            hfov_deg=hfov_deg,
            vfov_deg=vfov_deg,
            altitude_m=alt,
            overlap_ratio=overlap
        )


class GeofenceCoveragePlanner:
    """
    Plans and tracks dynamic coverage inside any geofence boundary without waypoints.
    Discretizes the geofence into a metric grid and generates real-time velocity guidance
    toward unscanned sectors while enforcing geofence containment.
    """

    def __init__(
        self,
        boundary_type: str = "polygon",
        polygon_geo: Optional[List[Dict[str, float]]] = None,
        circle_center_geo: Optional[Tuple[float, float]] = None,
        circle_radius_m: float = 150.0,
        grid_resolution_m: float = 2.0,
        cruise_speed_m_s: float = 1.5,
        search_altitude_m: float = 10.0,
        camera_hfov_deg: float = 62.2,
        camera_vfov_deg: float = 48.8,
        overlap_ratio: float = 0.25
    ):
        self.boundary_type = boundary_type.lower()
        self.grid_res = max(0.5, float(grid_resolution_m))
        self.cruise_speed = max(0.2, min(5.0, float(cruise_speed_m_s)))
        self.search_altitude = max(2.0, float(search_altitude_m))
        self.overlap_ratio = overlap_ratio
        self._lock = threading.Lock()

        # Determine reference origin (ref_lat, ref_lon)
        if self.boundary_type == "circular" and circle_center_geo:
            self.ref_lat, self.ref_lon = circle_center_geo
        elif polygon_geo and len(polygon_geo) >= 3:
            self.ref_lat = sum(p["lat"] for p in polygon_geo) / len(polygon_geo)
            self.ref_lon = sum(p["lon"] for p in polygon_geo) / len(polygon_geo)
        else:
            self.ref_lat, self.ref_lon = (37.4093, -122.0641)

        # Build local 2D metric polygon boundary
        self.local_polygon: List[Tuple[float, float]] = []
        self.circle_radius_m = circle_radius_m

        if self.boundary_type == "circular":
            # Discretize circle into 36-vertex polygon for uniform geometric coverage
            num_pts = 36
            for i in range(num_pts):
                angle = 2.0 * math.pi * i / num_pts
                px = self.circle_radius_m * math.cos(angle)
                py = self.circle_radius_m * math.sin(angle)
                self.local_polygon.append((px, py))
        elif polygon_geo and len(polygon_geo) >= 3:
            for p in polygon_geo:
                lx, ly = geo_to_local_meters(p["lat"], p["lon"], self.ref_lat, self.ref_lon)
                self.local_polygon.append((lx, ly))
        else:
            # Default 150-yard (137m) square centered at origin
            half_side = 68.5
            self.local_polygon = [
                (-half_side, -half_side),
                (half_side, -half_side),
                (half_side, half_side),
                (-half_side, half_side)
            ]

        # Calculate bounding box in meters
        xs = [pt[0] for pt in self.local_polygon]
        ys = [pt[1] for pt in self.local_polygon]
        self.min_x = min(xs)
        self.max_x = max(xs)
        self.min_y = min(ys)
        self.max_y = max(ys)

        # Camera footprint
        self.footprint = CameraFootprint.calculate(
            altitude_m=self.search_altitude,
            hfov_deg=camera_hfov_deg,
            vfov_deg=camera_vfov_deg,
            overlap_ratio=self.overlap_ratio
        )

        # Discretize valid cells inside boundary
        self.total_cells: Set[Tuple[int, int]] = set()
        self.scanned_cells: Set[Tuple[int, int]] = set()

        # Fill grid
        curr_x = self.min_x
        while curr_x <= self.max_x:
            curr_y = self.min_y
            while curr_y <= self.max_y:
                if self.is_inside_boundary(curr_x, curr_y):
                    cell_idx = (int(round(curr_x / self.grid_res)), int(round(curr_y / self.grid_res)))
                    self.total_cells.add(cell_idx)
                curr_y += self.grid_res
            curr_x += self.grid_res

        self.total_area_m2 = len(self.total_cells) * (self.grid_res ** 2)

        # Dynamic search sweep state
        self.sweep_direction_x = 1.0  # 1.0 for +x, -1.0 for -x
        self.current_lane_y = self.min_y + (self.footprint.height_m / 2.0)
        self.safety_margin_m = max(3.0, self.footprint.width_m * 0.25)

    def is_inside_boundary(self, x: float, y: float, margin_m: float = 0.0) -> bool:
        """
        Check if local point (x, y) is strictly inside boundary,
        optionally accounting for an internal safety buffer margin.
        """
        if self.boundary_type == "circular":
            dist = math.hypot(x, y)
            return dist <= (self.circle_radius_m - margin_m)
        else:
            if margin_m <= 0.0:
                return point_in_polygon_2d(x, y, self.local_polygon)
            # Ray casting with margin check
            return point_in_polygon_2d(x, y, self.local_polygon) and (
                (self.min_x + margin_m) <= x <= (self.max_x - margin_m) and
                (self.min_y + margin_m) <= y <= (self.max_y - margin_m)
            )

    def update_drone_position(self, lat: float, lon: float, altitude_m: Optional[float] = None) -> float:
        """
        Update drone location, project camera footprint on ground,
        mark cells as scanned, and return current coverage percentage.
        """
        lx, ly = geo_to_local_meters(lat, lon, self.ref_lat, self.ref_lon)
        with self._lock:
            if altitude_m is not None and abs(altitude_m - self.search_altitude) > 2.0:
                self.search_altitude = max(2.0, altitude_m)
                self.footprint = CameraFootprint.calculate(
                    altitude_m=self.search_altitude,
                    hfov_deg=self.footprint.hfov_deg,
                    vfov_deg=self.footprint.vfov_deg,
                    overlap_ratio=self.overlap_ratio
                )

            # Determine scanned footprint bounds
            half_w = self.footprint.width_m / 2.0
            half_h = self.footprint.height_m / 2.0

            x_start = lx - half_w
            x_end = lx + half_w
            y_start = ly - half_h
            y_end = ly + half_h

            cx = x_start
            while cx <= x_end:
                cy = y_start
                while cy <= y_end:
                    cell_idx = (int(round(cx / self.grid_res)), int(round(cy / self.grid_res)))
                    if cell_idx in self.total_cells:
                        self.scanned_cells.add(cell_idx)
                    cy += self.grid_res
                cx += self.grid_res

            if not self.total_cells:
                return 100.0
            pct = (len(self.scanned_cells) / len(self.total_cells)) * 100.0
            return round(min(100.0, pct), 2)

    def get_coverage_percentage(self) -> float:
        """Return percentage of total permitted geofence scanned (0.0 - 100.0)."""
        with self._lock:
            if not self.total_cells:
                return 100.0
            pct = (len(self.scanned_cells) / len(self.total_cells)) * 100.0
            return round(min(100.0, pct), 2)

    def calculate_next_velocity_command(
        self,
        current_lat: float,
        current_lon: float,
        current_alt_m: float = 10.0
    ) -> Dict[str, Any]:
        """
        Calculate next dynamic velocity vector (vx, vy, vz) in local NED frame
        based on unsearched regions without generating or uploading waypoints.
        Enforces strict geofence containment so commands never exit the boundary.
        """
        lx, ly = geo_to_local_meters(current_lat, current_lon, self.ref_lat, self.ref_lon)
        coverage_pct = self.update_drone_position(current_lat, current_lon, current_alt_m)

        if coverage_pct >= 99.5:
            return {
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "speed_m_s": 0.0,
                "heading_deg": 0.0,
                "mode": "COVERAGE_COMPLETE",
                "coverage_pct": coverage_pct,
                "contained": True
            }

        # 1. Target Y lane alignment
        y_err = self.current_lane_y - ly
        step_speed = min(self.cruise_speed, max(0.3, abs(y_err)))

        # Check if approaching boundary along current X sweep direction
        next_x = lx + (self.sweep_direction_x * self.safety_margin_m)
        can_proceed_x = self.is_inside_boundary(next_x, ly, margin_m=self.safety_margin_m * 0.5)

        if can_proceed_x:
            # Normal sweep along current lane
            vx = self.sweep_direction_x * self.cruise_speed
            # Gentle cross-track error correction toward lane center
            vy = math.copysign(step_speed * 0.4, y_err) if abs(y_err) > 0.5 else 0.0
            search_mode = "SWEEP"
        else:
            # Reached boundary: Advance to next lane in +Y (or find nearest unscanned cluster)
            next_lane_y = self.current_lane_y + self.footprint.effective_spacing_m
            if next_lane_y <= (self.max_y - self.safety_margin_m):
                self.current_lane_y = next_lane_y
                self.sweep_direction_x *= -1.0  # Reverse horizontal sweep
                vx = 0.0
                vy = self.cruise_speed  # Step across to next lane
                search_mode = "LANE_TRANSITION"
            else:
                # Top of bounding box reached: Dynamically seek nearest unscanned cell cluster
                unscanned = self.total_cells - self.scanned_cells
                if unscanned:
                    # Find closest unscanned cell to current drone position
                    curr_cell = (int(round(lx / self.grid_res)), int(round(ly / self.grid_res)))
                    closest_cell = min(
                        unscanned,
                        key=lambda c: (c[0] - curr_cell[0]) ** 2 + (c[1] - curr_cell[1]) ** 2
                    )
                    target_x = closest_cell[0] * self.grid_res
                    target_y = closest_cell[1] * self.grid_res
                    dx = target_x - lx
                    dy = target_y - ly
                    dist = math.hypot(dx, dy)
                    if dist > 0.5:
                        vx = (dx / dist) * self.cruise_speed
                        vy = (dy / dist) * self.cruise_speed
                    else:
                        vx, vy = 0.0, 0.0
                    search_mode = "DYNAMIC_CLUSTER_SEARCH"
                else:
                    vx, vy = 0.0, 0.0
                    search_mode = "COMPLETE"

        # 2. Strict Boundary Containment Safety Filter
        # Check projected location after 1.5 seconds at commanded velocity
        proj_x = lx + (vx * 1.5)
        proj_y = ly + (vy * 1.5)
        if not self.is_inside_boundary(proj_x, proj_y, margin_m=1.0):
            # Clamping: nullify movement toward outside
            if not self.is_inside_boundary(proj_x, ly, margin_m=1.0):
                vx = -vx * 0.5  # Back off from boundary
            if not self.is_inside_boundary(lx, proj_y, margin_m=1.0):
                vy = -vy * 0.5

        speed = math.hypot(vx, vy)
        heading_deg = math.degrees(math.atan2(vx, vy)) % 360.0  # NED heading (vy=East, vx=North)

        # Convert to local NED: North = Y, East = X, Down = 0.0
        # In standard aviation NED:
        # vx_ned = movement in North (dy)
        # vy_ned = movement in East (dx)
        return {
            "vx_ned": round(vy, 3),  # North velocity (m/s)
            "vy_ned": round(vx, 3),  # East velocity (m/s)
            "vz_ned": 0.0,           # Altitude hold
            "speed_m_s": round(speed, 2),
            "heading_deg": round(heading_deg, 1),
            "mode": search_mode,
            "coverage_pct": coverage_pct,
            "contained": self.is_inside_boundary(lx, ly)
        }

    def reset_coverage(self) -> None:
        """Thread-safe reset of accumulated scanned cells and sweep state."""
        with self._lock:
            self.scanned_cells.clear()
            self.sweep_direction_x = 1.0
            self.current_lane_y = self.min_y + (self.footprint.height_m / 2.0)

    def reconfigure(self, config: Any) -> None:
        """
        Thread-safe dynamic reconfiguration of geofence boundaries and coverage grid.
        Rebuilds local polygon, bounding box, and total cells in-place.
        """
        with self._lock:
            if hasattr(config, "fence_type"):
                boundary_type = getattr(config, "fence_type", "circular")
                polygon_geo = getattr(config, "polygon_vertices", None)
                circle_center = (getattr(config, "circle_center_lat", 37.4093), getattr(config, "circle_center_lon", -122.0641))
                circle_radius = getattr(config, "circle_radius_m", 150.0)
            elif isinstance(config, dict):
                boundary_type = config.get("fence_type", "circular")
                polygon_geo = config.get("polygon_vertices", None)
                circle_center = (config.get("circle_center_lat", 37.4093), config.get("circle_center_lon", -122.0641))
                circle_radius = config.get("circle_radius_m", 150.0)
            else:
                boundary_type = "circular"
                polygon_geo = None
                circle_center = (37.4093, -122.0641)
                circle_radius = 150.0

            self.boundary_type = boundary_type.lower()
            self.circle_radius_m = float(circle_radius)

            if self.boundary_type == "circular" and circle_center:
                self.ref_lat, self.ref_lon = circle_center
            elif polygon_geo and len(polygon_geo) >= 3:
                self.ref_lat = sum(p["lat"] for p in polygon_geo) / len(polygon_geo)
                self.ref_lon = sum(p["lon"] for p in polygon_geo) / len(polygon_geo)
            else:
                self.ref_lat, self.ref_lon = (37.4093, -122.0641)

            self.local_polygon = []
            if self.boundary_type == "circular":
                num_pts = 36
                for i in range(num_pts):
                    angle = 2.0 * math.pi * i / num_pts
                    px = self.circle_radius_m * math.cos(angle)
                    py = self.circle_radius_m * math.sin(angle)
                    self.local_polygon.append((px, py))
            elif polygon_geo and len(polygon_geo) >= 3:
                for p in polygon_geo:
                    lx, ly = geo_to_local_meters(p["lat"], p["lon"], self.ref_lat, self.ref_lon)
                    self.local_polygon.append((lx, ly))
            else:
                half_side = 68.5
                self.local_polygon = [
                    (-half_side, -half_side),
                    (half_side, -half_side),
                    (half_side, half_side),
                    (-half_side, half_side)
                ]

            xs = [pt[0] for pt in self.local_polygon]
            ys = [pt[1] for pt in self.local_polygon]
            self.min_x = min(xs)
            self.max_x = max(xs)
            self.min_y = min(ys)
            self.max_y = max(ys)

            self.total_cells = set()
            self.scanned_cells = set()

            curr_x = self.min_x
            while curr_x <= self.max_x:
                curr_y = self.min_y
                while curr_y <= self.max_y:
                    if self.is_inside_boundary(curr_x, curr_y):
                        cell_idx = (int(round(curr_x / self.grid_res)), int(round(curr_y / self.grid_res)))
                        self.total_cells.add(cell_idx)
                    curr_y += self.grid_res
                curr_x += self.grid_res

            self.total_area_m2 = len(self.total_cells) * (self.grid_res ** 2)
            self.sweep_direction_x = 1.0
            self.current_lane_y = self.min_y + (self.footprint.height_m / 2.0)

    def get_coverage_snapshot(self) -> Dict[str, Any]:
        """Return comprehensive serialization of coverage state for API and live heatmap."""
        with self._lock:
            # Convert local polygon back to geo for map rendering
            polygon_geo = [
                {"lat": local_meters_to_geo(pt[0], pt[1], self.ref_lat, self.ref_lon)[0],
                 "lon": local_meters_to_geo(pt[0], pt[1], self.ref_lat, self.ref_lon)[1]}
                for pt in self.local_polygon
            ]

            # Sample scanned regions for heatmap representation (limit to 500 for lightweight JSON)
            scanned_sample = []
            scanned_list = list(self.scanned_cells)
            step = max(1, len(scanned_list) // 400) if scanned_list else 1
            for idx, cell in enumerate(scanned_list):
                if idx % step == 0:
                    cx = cell[0] * self.grid_res
                    cy = cell[1] * self.grid_res
                    clat, clon = local_meters_to_geo(cx, cy, self.ref_lat, self.ref_lon)
                    scanned_sample.append({
                        "lat": clat,
                        "lon": clon,
                        "radius_m": round(self.grid_res * 1.2, 2),
                        "intensity": 0.6
                    })

            pct = 0.0
            if self.total_cells:
                pct = round(min(100.0, (len(self.scanned_cells) / len(self.total_cells)) * 100.0), 2)

            snapshot = {
                "boundary_type": self.boundary_type,
                "boundary_geo": polygon_geo,
                "total_area_m2": round(self.total_area_m2, 1),
                "scanned_area_m2": round(len(self.scanned_cells) * (self.grid_res ** 2), 1),
                "coverage_pct": pct,
                "scanned_cells_count": len(self.scanned_cells),
                "total_cells_count": len(self.total_cells),
                "grid_resolution_m": self.grid_res,
                "search_altitude_m": self.search_altitude,
                "footprint_width_m": self.footprint.width_m,
                "footprint_height_m": self.footprint.height_m,
                "scanned_points": scanned_sample
            }

            if self.boundary_type == "circular":
                snapshot["circle_center_lat"] = self.ref_lat
                snapshot["circle_center_lon"] = self.ref_lon
                snapshot["circle_radius_m"] = self.circle_radius_m

            return snapshot

    @classmethod
    def from_geofence_config(cls, config: Any) -> "GeofenceCoveragePlanner":
        """Instantiate GeofenceCoveragePlanner from a GeofenceConfig or dictionary."""
        if hasattr(config, "fence_type"):
            b_type = getattr(config, "fence_type", "circular")
            poly = getattr(config, "polygon_vertices", None)
            center = (getattr(config, "circle_center_lat", 37.4093), getattr(config, "circle_center_lon", -122.0641))
            radius = getattr(config, "circle_radius_m", 150.0)
            grid_res = getattr(config, "grid_resolution_m", 2.0) if hasattr(config, "grid_resolution_m") else 2.0
            search_alt = getattr(config, "search_altitude_m", 10.0) if hasattr(config, "search_altitude_m") else 10.0
        elif isinstance(config, dict):
            b_type = config.get("fence_type", "circular")
            poly = config.get("polygon_vertices", None)
            center = (config.get("circle_center_lat", 37.4093), config.get("circle_center_lon", -122.0641))
            radius = config.get("circle_radius_m", 150.0)
            grid_res = config.get("grid_resolution_m", 2.0)
            search_alt = config.get("search_altitude_m", 10.0)
        else:
            b_type = "circular"
            poly = None
            center = (37.4093, -122.0641)
            radius = 150.0
            grid_res = 2.0
            search_alt = 10.0

        return cls(
            boundary_type=b_type,
            polygon_geo=poly,
            circle_center_geo=center,
            circle_radius_m=radius,
            grid_resolution_m=grid_res,
            search_altitude_m=search_alt
        )


# Global singleton instance synchronized with geofence_service
try:
    from backend.geofence.geofence_service import geofence_service
    coverage_planner = GeofenceCoveragePlanner.from_geofence_config(geofence_service.config)
except Exception:
    coverage_planner = GeofenceCoveragePlanner(
        boundary_type="circular",
        circle_center_geo=(37.4093, -122.0641),
        circle_radius_m=150.0
    )

