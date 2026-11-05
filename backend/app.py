"""
Main Flask Application for AUTONOMOUS-DRONE.
Serves Companion Computer REST APIs and Ground Station Web Dashboard.
"""
import atexit
import sys
from pathlib import Path

# Ensure project root is in sys.path when executed directly
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS

from config.settings import settings
from config.logging_config import setup_logging
from backend.api.health_routes import health_bp
from backend.api.camera_routes import camera_bp
from backend.api.vision_routes import vision_bp
from backend.api.telemetry_routes import telemetry_bp
from backend.api.mission_routes import mission_bp
from backend.api.geofence_routes import geofence_bp
from backend.api.flight_routes import flight_bp
from backend.camera.camera_manager import camera_manager
from backend.vision.vision_service import vision_service
from backend.flight.mavlink_service import mavlink_service

logger = setup_logging("app")


def create_app() -> Flask:
    """Application factory for the AUTONOMOUS-DRONE backend."""
    app = Flask(
        __name__,
        static_folder=str(settings.FRONTEND_DIR),
        static_url_path=""
    )

    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False

    # Enable CORS for flexible ground station clients
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register Blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(vision_bp)
    app.register_blueprint(telemetry_bp)
    app.register_blueprint(mission_bp)
    app.register_blueprint(geofence_bp)
    app.register_blueprint(flight_bp)

    # Web Dashboard Routes
    @app.route("/")
    def index():
        """Serve Ground Station Dashboard homepage."""
        return send_from_directory(str(settings.FRONTEND_DIR), "index.html")

    @app.route("/<path:path>")
    def static_proxy(path):
        """Serve frontend static assets (CSS, JS, assets)."""
        file_path = settings.FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return send_from_directory(str(settings.FRONTEND_DIR), path)
        # Default fallback to index.html for SPA client-side routing
        return send_from_directory(str(settings.FRONTEND_DIR), "index.html")

    @app.after_request
    def add_cache_control_headers(response):
        """
        Enforce strict HTTP caching rules for Ground Station frontend:
        - HTML shell (/, /index.html) must never be cached to ensure fresh asset manifests.
        - Static versioned assets (/css/*, /js/*) must revalidate with server on each request.
        """
        path = request.path
        if path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith(("/css/", "/js/")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    # Error Handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            "status": "error",
            "error": {
                "code": 404,
                "message": "Resource not found"
            }
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error("Internal Server Error: %s", error)
        return jsonify({
            "status": "error",
            "error": {
                "code": 500,
                "message": "Internal server error"
            }
        }), 500

    return app


# Clean shutdown of camera, vision, and telemetry services at exit
atexit.register(mavlink_service.stop)
atexit.register(vision_service.stop)
atexit.register(camera_manager.release)
app = create_app()

if __name__ == "__main__":
    logger.info("Starting drone companion server on %s:%d (debug=%s)", settings.HOST, settings.PORT, settings.DEBUG)
    # Start background telemetry and vision services
    mavlink_service.start()
    if settings.QR_DETECTION_ENABLED:
        vision_service.start()
    app.run(
        host=settings.HOST,
        port=settings.PORT,
        debug=settings.DEBUG,
        threaded=True
    )
