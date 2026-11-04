"""
Structured logging configuration for AUTONOMOUS-DRONE.
Supports rotating file logs and colorized or clean console formatting.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from .settings import settings


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that ignores I/O writes if stream was already closed during interpreter exit."""
    def emit(self, record):
        try:
            if self.stream and hasattr(self.stream, "closed") and self.stream.closed:
                return
            super().emit(record)
        except (ValueError, IOError):
            pass


def setup_logging(name: str = "drone") -> logging.Logger:
    """Configure and return logger with console and rotating file handlers."""
    logger = logging.getLogger(name)

    # Avoid duplicate handlers on re-initialization
    if logger.handlers:
        return logger

    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    log_format = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # Rotating File Handler (Max 10MB, 5 backups)
    try:
        settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)
    except Exception as exc:
        print(f"Warning: Failed to initialize file logger at {settings.LOG_FILE}: {exc}", file=sys.stderr)

    return logger
