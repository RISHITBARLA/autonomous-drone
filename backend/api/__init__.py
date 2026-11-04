"""REST API blueprints package for AUTONOMOUS-DRONE."""
from .health_routes import health_bp
from .camera_routes import camera_bp

__all__ = ["health_bp", "camera_bp"]
