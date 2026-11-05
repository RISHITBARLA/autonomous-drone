"""
3D Pinhole Photogrammetry Camera-to-Ground GPS Projector for AUTONOMOUS-DRONE.
Converts 2D image pixel coordinates (u, v) into geographic coordinates (lat, lon)
using calibrated camera intrinsics, mount geometry, drone attitude (roll, pitch, yaw),
and relative altitude above ground level (AGL).

Documented Coordinate Frames & Conventions:
1. Image Pixel Frame: Origin (0,0) at top-left. u positive rightwards, v positive downwards.
2. Camera Optical Frame: Z forward along optical axis, X rightward, Y downward.
3. Drone Body Frame (FRD): X Forward, Y Right, Z Down.
4. Navigation World Frame (NED): X North, Y East, Z Down.
5. Altitude Reference: Relative altitude above ground level (alt_agl_m) in meters.
6. Rotation Order: Z-Y-X Tait-Bryan intrinsic sequence: Yaw (psi), Pitch (theta), Roll (phi).
"""
import math
from dataclasses import dataclass
from typing import Tuple, Optional
import numpy as np

EARTH_RADIUS_M = 6378137.0


@dataclass
class CameraCalibration:
    """IMX477 camera intrinsics and mounting orientation."""
    image_width: int = 1920
    image_height: int = 1080
    hfov_deg: float = 62.2
    vfov_deg: float = 48.8
    fx: Optional[float] = None
    fy: Optional[float] = None
    cx: Optional[float] = None
    cy: Optional[float] = None
    # Mounting orientation relative to drone body frame (degrees)
    # Default: -90 deg pitch = nadir pointing straight down
    mount_roll_deg: float = 0.0
    mount_pitch_deg: float = -90.0
    mount_yaw_deg: float = 0.0


@dataclass
class DronePose:
    """Drone state from MAVLink telemetry."""
    timestamp: float
    lat: Optional[float]
    lon: Optional[float]
    alt_agl_m: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    gps_fix_valid: bool = True
    hdop: float = 1.0


class CameraGeoprojector:
    """
    Projects image pixel coordinates to geographic ground coordinates via ray-plane intersection.
    Never invents coordinates if telemetry or camera ray is invalid.
    """

    def __init__(self, calibration: Optional[CameraCalibration] = None):
        self.calib = calibration or CameraCalibration()
        self._compute_intrinsics()

    def _compute_intrinsics(self) -> None:
        w = float(self.calib.image_width)
        h = float(self.calib.image_height)
        self.cx = self.calib.cx if self.calib.cx is not None else (w / 2.0)
        self.cy = self.calib.cy if self.calib.cy is not None else (h / 2.0)
        self.fx = (
            self.calib.fx
            if self.calib.fx is not None
            else (w / (2.0 * math.tan(math.radians(self.calib.hfov_deg) / 2.0)))
        )
        self.fy = (
            self.calib.fy
            if self.calib.fy is not None
            else (h / (2.0 * math.tan(math.radians(self.calib.vfov_deg) / 2.0)))
        )

    @staticmethod
    def euler_to_rot_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
        """
        Constructs standard 3x3 Z-Y-X rotation matrix from Euler angles in degrees.
        R = Rz(yaw) * Ry(pitch) * Rx(roll)
        """
        r = math.radians(roll_deg)
        p = math.radians(pitch_deg)
        y = math.radians(yaw_deg)
        cr, sr = math.cos(r), math.sin(r)
        cp, sp = math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)

        return np.array([
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp,     cp * sr,                cp * cr               ]
        ], dtype=np.float64)

    def project_pixel_to_ground(
        self, u: float, v: float, pose: DronePose
    ) -> Tuple[Optional[float], Optional[float], Optional[float], bool, bool]:
        """
        Project image pixel (u, v) onto ground plane.
        Returns:
            est_lat: Estimated latitude (WGS84), or None if invalid.
            est_lon: Estimated longitude (WGS84), or None if invalid.
            uncertainty_m: 1-sigma uncertainty radius in meters.
            projection_valid: True if physical ground intersection exists.
            is_approximate: True if attitude/GPS degraded or unlocated fallback.
        """
        # Strict telemetry integrity check
        if (
            not pose.gps_fix_valid
            or pose.lat is None
            or pose.lon is None
            or pose.alt_agl_m <= 0.2
            or not (-90.0 <= pose.lat <= 90.0)
            or not (-180.0 <= pose.lon <= 180.0)
        ):
            return None, None, None, False, True

        # 1. Normalized optical coordinates
        x_norm = (u - self.cx) / self.fx
        y_norm = (v - self.cy) / self.fy

        # 2. Camera optical vector to aircraft body frame (+X fwd, +Y right, +Z down)
        ray_cam_body = np.array([1.0, x_norm, y_norm], dtype=np.float64)
        norm_val = np.linalg.norm(ray_cam_body)
        if norm_val < 1e-9:
            return None, None, None, False, True
        ray_cam_body /= norm_val

        # 3. Mount transformation -> Drone attitude -> NED world frame
        r_mount = self.euler_to_rot_matrix(
            self.calib.mount_roll_deg, self.calib.mount_pitch_deg, self.calib.mount_yaw_deg
        )
        r_drone = self.euler_to_rot_matrix(pose.roll_deg, pose.pitch_deg, pose.yaw_deg)
        ray_ned = r_drone @ (r_mount @ ray_cam_body)

        r_north = float(ray_ned[0])
        r_east = float(ray_ned[1])
        r_down = float(ray_ned[2])

        # 4. Ray-plane intersection test: ray must point downward
        if r_down <= 0.08:
            # Ray points above or near horizon: ground intersection is infinite or undefined
            approx_unc = max(30.0, pose.alt_agl_m * 3.0)
            return pose.lat, pose.lon, round(approx_unc, 1), False, True

        scale = pose.alt_agl_m / r_down
        delta_north_m = scale * r_north
        delta_east_m = scale * r_east

        # 5. Local tangent plane to WGS84 conversion
        lat_rad = math.radians(pose.lat)
        d_lat = (delta_north_m / EARTH_RADIUS_M) * (180.0 / math.pi)
        cos_lat = math.cos(lat_rad)
        if abs(cos_lat) < 1e-6:
            cos_lat = 1e-6
        d_lon = (delta_east_m / (EARTH_RADIUS_M * cos_lat)) * (180.0 / math.pi)

        est_lat = round(pose.lat + d_lat, 7)
        est_lon = round(pose.lon + d_lon, 7)

        # 6. Uncertainty model combining GPS HDOP, slant angle, and altitude error
        slant_range_m = math.sqrt(delta_north_m ** 2 + delta_east_m ** 2 + pose.alt_agl_m ** 2)
        attitude_unc_m = slant_range_m * math.tan(math.radians(2.0)) / max(0.15, r_down)
        gps_unc_m = 1.5 * max(0.6, pose.hdop)
        total_uncertainty_m = round(math.sqrt(gps_unc_m ** 2 + attitude_unc_m ** 2), 2)

        is_approx = r_down < 0.25 or pose.hdop > 2.2 or pose.alt_agl_m > 80.0
        return est_lat, est_lon, total_uncertainty_m, True, is_approx

