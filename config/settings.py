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
    QR_RTL_ON_ANY: bool = os.getenv("QR_RTL_ON_ANY", "true").lower() in ("true", "1", "yes")

    # MAVLink & Flight Controller Communication
    MAVLINK_TRANSPORT: str = os.getenv("MAVLINK_TRANSPORT", "udp").lower()
    _DEFAULT_MAVLINK_CONN: str = "/dev/serial0" if MAVLINK_TRANSPORT == "serial" else "udpin:0.0.0.0:14550"
    MAVLINK_CONNECTION: str = os.getenv("MAVLINK_CONNECTION", os.getenv("MAVLINK_CONNECTION_STRING", _DEFAULT_MAVLINK_CONN))
    MAVLINK_CONNECTION_STRING: str = os.getenv("MAVLINK_CONNECTION_STRING", MAVLINK_CONNECTION)
    MAVLINK_BAUDRATE: int = int(os.getenv("MAVLINK_BAUDRATE", "115200" if MAVLINK_TRANSPORT == "serial" else "57600"))
    MAVLINK_HEARTBEAT_TIMEOUT: float = float(os.getenv("MAVLINK_HEARTBEAT_TIMEOUT", "5.0"))
    MAVLINK_SIMULATE: bool = os.getenv("MAVLINK_SIMULATE", "true").lower() in ("true", "1", "yes")

    # Flight Control Subsystem (Disabled by default for safety)
    FLIGHT_CONTROL_ENABLED: bool = os.getenv("FLIGHT_CONTROL_ENABLED", "false").lower() in ("true", "1", "yes")
    FLIGHT_MODE: str = os.getenv("FLIGHT_MODE", "ALT_HOLD").upper()
    ARMING_CHECKS_ENABLED: bool = os.getenv("ARMING_CHECKS_ENABLED", "true").lower() in ("true", "1", "yes")
    FORCE_ARM: bool = os.getenv("FORCE_ARM", "false").lower() in ("true", "1", "yes")

    # Logging settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE: Path = Path(os.getenv("LOG_FILE", LOGS_DIR / "drone_system.log"))

    @classmethod
    def ensure_directories(cls):
        """Ensure required operational directories exist."""
        cls.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate_configuration(cls) -> None:
        """Validate critical safety and runtime parameters at startup."""
        if cls.FORCE_ARM:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: FORCE_ARM must never be enabled. "
                "ArduPilot firmware pre-arm safety checks are mandatory."
            )
        if not cls.ARMING_CHECKS_ENABLED:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: ARMING_CHECKS_ENABLED cannot be disabled. "
                "Firmware pre-arm safety checks must remain active."
            )
        valid_transports = {"udp", "tcp", "serial"}
        if cls.MAVLINK_TRANSPORT not in valid_transports:
            raise ValueError(
                f"Invalid MAVLINK_TRANSPORT '{cls.MAVLINK_TRANSPORT}'. Must be one of {valid_transports}"
            )
        supported_modes = {
            "STABILIZE", "ALT_HOLD", "LOITER", "GUIDED", "AUTO", "RTL", "LAND", "BRAKE", "POSHOLD", "CIRCLE"
        }
        if cls.FLIGHT_MODE not in supported_modes:
            raise ValueError(
                f"Invalid default FLIGHT_MODE '{cls.FLIGHT_MODE}'. Must be one of {supported_modes}"
            )
        if not cls.MAVLINK_CONNECTION or not str(cls.MAVLINK_CONNECTION).strip():
            raise ValueError("MAVLINK_CONNECTION string cannot be empty.")

        # Environment consistency check between MAVLINK_CONNECTION and MAVLINK_CONNECTION_STRING
        env_conn = os.getenv("MAVLINK_CONNECTION")
        env_conn_str = os.getenv("MAVLINK_CONNECTION_STRING")
        if env_conn and env_conn_str and env_conn.strip() != env_conn_str.strip():
            raise ValueError(
                f"Configuration conflict: MAVLINK_CONNECTION ('{env_conn}') and "
                f"MAVLINK_CONNECTION_STRING ('{env_conn_str}') must be identical."
            )

        # Transport protocol vs connection target validation
        conn_str = str(cls.MAVLINK_CONNECTION).strip().lower()
        if cls.MAVLINK_TRANSPORT == "serial":
            if conn_str.startswith(("udp:", "udpin:", "udpout:", "tcp:", "tcpin:", "tcpout:")):
                raise ValueError(
                    f"MAVLINK_TRANSPORT is 'serial' but MAVLINK_CONNECTION is a network URI: '{cls.MAVLINK_CONNECTION}'"
                )
        elif cls.MAVLINK_TRANSPORT in ("udp", "tcp"):
            if conn_str.startswith(("/dev/", "com")):
                raise ValueError(
                    f"MAVLINK_TRANSPORT is '{cls.MAVLINK_TRANSPORT}' but MAVLINK_CONNECTION is a serial port: '{cls.MAVLINK_CONNECTION}'"
                )


settings = Settings()
settings.ensure_directories()
settings.validate_configuration()
