"""
Application and hardware settings for AUTONOMOUS-DRONE.
Loads configuration from environment variables (.env) with production-ready defaults.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Central configuration container for backend, hardware, and camera services."""

    # Base paths
    BASE_DIR: Path = BASE_DIR
    CAPTURES_DIR: Path = Path(os.getenv("CAPTURES_DIR", BASE_DIR / "captures"))
    LOGS_DIR: Path = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    FRONTEND_DIR: Path = BASE_DIR / "frontend"

    MISSIONS_FILE: Path = DATA_DIR / "missions.json"
    GEOFENCE_FILE: Path = DATA_DIR / "geofence.json"

    # Server settings
    HOST: str = os.getenv("DRONE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("DRONE_PORT", "5000"))
    DEBUG: bool = os.getenv("DRONE_DEBUG", "false").lower() in ("true", "1", "yes")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "autonomous-drone-dev-secret-key-2026")

    # Hardware & System Monitoring
    ENABLE_MOCK_HARDWARE: bool = os.getenv("ENABLE_MOCK_HARDWARE", "false").lower() in ("true", "1", "yes")
    SYSTEM_POLL_INTERVAL_SECONDS: float = float(os.getenv("SYSTEM_POLL_INTERVAL_SECONDS", "1.0"))
    TEMP_WARNING_THRESHOLD: float = float(os.getenv("TEMP_WARNING_THRESHOLD", "75.0"))
    TEMP_CRITICAL_THRESHOLD: float = float(os.getenv("TEMP_CRITICAL_THRESHOLD", "85.0"))
    RAM_WARNING_THRESHOLD: float = float(os.getenv("RAM_WARNING_THRESHOLD", "85.0"))
    DISK_WARNING_THRESHOLD: float = float(os.getenv("DISK_WARNING_THRESHOLD", "90.0"))

    # Camera settings
    CAMERA_BACKEND: str = os.getenv("CAMERA_BACKEND", "auto").lower()
    CAMERA_INDEX: int = int(os.getenv("CAMERA_INDEX", "0"))
    CAMERA_WIDTH: int = int(os.getenv("CAMERA_WIDTH", "1920"))
    CAMERA_HEIGHT: int = int(os.getenv("CAMERA_HEIGHT", "1080"))
    CAMERA_PREVIEW_WIDTH: int = int(os.getenv("CAMERA_PREVIEW_WIDTH", "640"))
    CAMERA_PREVIEW_HEIGHT: int = int(os.getenv("CAMERA_PREVIEW_HEIGHT", "480"))
    CAMERA_FRAMERATE: int = int(os.getenv("CAMERA_FRAMERATE", "30"))

    # Computer Vision & QR Detection
    QR_DETECTION_ENABLED: bool = os.getenv("QR_DETECTION_ENABLED", "true").lower() in ("true", "1", "yes")
    QR_COOLDOWN_SECONDS: float = float(os.getenv("QR_COOLDOWN_SECONDS", "2.0"))
    QR_HISTORY_LIMIT: int = int(os.getenv("QR_HISTORY_LIMIT", "50"))
    QR_PROCESS_FPS: float = float(os.getenv("QR_PROCESS_FPS", "10.0"))

    # MAVLink & Flight Controller Communication
    MAVLINK_CONNECTION_STRING: str = os.getenv("MAVLINK_CONNECTION_STRING", "udpin:0.0.0.0:14550")
    MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "57600"))
    MAVLINK_HEARTBEAT_TIMEOUT: float = float(os.getenv("MAVLINK_HEARTBEAT_TIMEOUT", "5.0"))
    MAVLINK_SIMULATE: bool = os.getenv("MAVLINK_SIMULATE", "true").lower() in ("true", "1", "yes")

    # Flight Control Subsystem (Disabled by default for safety)
    FLIGHT_CONTROL_ENABLED: bool = os.getenv("FLIGHT_CONTROL_ENABLED", "false").lower() in ("true", "1", "yes")

    # Logging settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE: Path = Path(os.getenv("LOG_FILE", LOGS_DIR / "drone_system.log"))

    @classmethod
    def ensure_directories(cls):
        """Ensure required operational directories exist."""
        cls.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
