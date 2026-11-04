"""
Camera Configuration Data Model and Validation.
Supports Sony IMX477 resolutions and streaming parameters.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any
from config.settings import settings


@dataclass
class CameraConfig:
    """Configurable settings for Sony IMX477 and companion computer camera capture."""

    # Resolution (IMX477 native maximum is 4056x3040; default operational is 1920x1080)
    width: int = 1920
    height: int = 1080

    # Low-latency streaming resolution for live dashboard
    preview_width: int = 640
    preview_height: int = 480

    framerate: int = 30
    rotation: int = 0  # 0, 90, 180, 270 degrees
    jpeg_quality: int = 90  # 1 - 100
    backend: str = "auto"  # 'auto', 'libcamera', 'opencv', 'mock'
    camera_index: int = 0
    captures_dir: Path = settings.CAPTURES_DIR

    @classmethod
    def from_settings(cls) -> "CameraConfig":
        """Instantiate config populated from application settings and .env."""
        return cls(
            width=settings.CAMERA_WIDTH,
            height=settings.CAMERA_HEIGHT,
            preview_width=settings.CAMERA_PREVIEW_WIDTH,
            preview_height=settings.CAMERA_PREVIEW_HEIGHT,
            framerate=settings.CAMERA_FRAMERATE,
            backend=settings.CAMERA_BACKEND,
            camera_index=settings.CAMERA_INDEX,
            captures_dir=settings.CAPTURES_DIR
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to JSON-serializable dictionary."""
        data = asdict(self)
        data["captures_dir"] = str(self.captures_dir)
        return data

    def update(self, updates: Dict[str, Any]) -> None:
        """Safely update configuration parameters."""
        if "width" in updates and int(updates["width"]) > 0:
            self.width = int(updates["width"])
        if "height" in updates and int(updates["height"]) > 0:
            self.height = int(updates["height"])
        if "preview_width" in updates and int(updates["preview_width"]) > 0:
            self.preview_width = int(updates["preview_width"])
        if "preview_height" in updates and int(updates["preview_height"]) > 0:
            self.preview_height = int(updates["preview_height"])
        if "framerate" in updates and 1 <= int(updates["framerate"]) <= 60:
            self.framerate = int(updates["framerate"])
        if "rotation" in updates and int(updates["rotation"]) in (0, 90, 180, 270):
            self.rotation = int(updates["rotation"])
        if "jpeg_quality" in updates and 1 <= int(updates["jpeg_quality"]) <= 100:
            self.jpeg_quality = int(updates["jpeg_quality"])
        if "backend" in updates and updates["backend"] in ("auto", "libcamera", "opencv", "mock"):
            self.backend = updates["backend"]
        if "camera_index" in updates:
            self.camera_index = int(updates["camera_index"])
