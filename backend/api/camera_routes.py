"""
Camera Management and Image Capture REST API Routes.
Exposes status, snapshot capture, image retrieval, and live MJPEG streaming.
"""
import time
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, Response, abort

from backend.camera.camera_manager import camera_manager
from config.settings import settings
from config.logging_config import setup_logging

logger = setup_logging("camera_routes")
camera_bp = Blueprint("camera_bp", __name__, url_prefix="/api/camera")


@camera_bp.route("/status", methods=["GET"])
def get_camera_status():
    """
    GET /api/camera/status
    Returns hardware connection status, active backend, resolution, and error logs.
    """
    status = camera_manager.get_status()
    return jsonify({
        "status": "success",
        "data": status
    }), 200


@camera_bp.route("/capture", methods=["POST"])
def capture_image():
    """
    POST /api/camera/capture
    Triggers an immediate high-resolution image capture.
    Persists file to captures/ directory and returns file metadata.
    """
    try:
        metadata = camera_manager.capture_image()
        return jsonify({
            "status": "success",
            "message": "Image captured successfully",
            "data": metadata
        }), 201
    except RuntimeError as re:
        logger.warning("Capture request rejected: %s", re)
        return jsonify({
            "status": "error",
            "message": str(re)
        }), 409
    except Exception as e:
        logger.error("Capture request failed: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Failed to capture image: {str(e)}"
        }), 500


@camera_bp.route("/latest", methods=["GET"])
def get_latest_capture():
    """
    GET /api/camera/latest
    Returns metadata and URL of the most recently captured image.
    """
    latest = camera_manager.get_latest_capture()
    if not latest:
        return jsonify({
            "status": "success",
            "message": "No captures available yet",
            "data": None
        }), 200

    return jsonify({
        "status": "success",
        "data": latest
    }), 200


@camera_bp.route("/list", methods=["GET"])
def list_captures():
    """
    GET /api/camera/list?limit=20
    Returns list of captured image files.
    """
    limit = request.args.get("limit", default=20, type=int)
    captures = camera_manager.list_captures(limit=limit)
    return jsonify({
        "status": "success",
        "count": len(captures),
        "data": captures
    }), 200


@camera_bp.route("/image/<filename>", methods=["GET"])
def serve_image(filename: str):
    """
    GET /api/camera/image/<filename>
    Serves captured image file safely from the captures/ directory.
    """
    captures_dir = settings.CAPTURES_DIR
    target_file = captures_dir / filename

    # Sanitize and guard against path traversal
    try:
        target_file = target_file.resolve()
        captures_dir_resolved = captures_dir.resolve()
        if not str(target_file).startswith(str(captures_dir_resolved)):
            abort(403)
    except Exception:
        abort(400)

    if not target_file.exists() or not target_file.is_file():
        return jsonify({
            "status": "error",
            "message": f"Image '{filename}' not found"
        }), 404

    return send_from_directory(
        directory=str(captures_dir),
        path=filename,
        mimetype="image/jpeg",
        max_age=3600
    )


def generate_mjpeg_stream():
    """Generator function yielding multipart MJPEG frames for live browser preview."""
    target_delay = 1.0 / max(camera_manager.config.framerate, 1)
    while True:
        start_time = time.time()
        frame_bytes = camera_manager.get_jpeg_frame(preview=True)
        if frame_bytes:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n" +
                frame_bytes + b"\r\n"
            )

        elapsed = time.time() - start_time
        sleep_time = max(0.0, target_delay - elapsed)
        time.sleep(sleep_time)


@camera_bp.route("/stream", methods=["GET"])
def live_stream():
    """
    GET /api/camera/stream
    MJPEG live video stream feed suitable for <img src="..."> in the web dashboard.
    """
    return Response(
        generate_mjpeg_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@camera_bp.route("/config", methods=["POST"])
def update_camera_config():
    """
    POST /api/camera/config
    Updates camera parameters (resolution, framerate, quality).
    """
    body = request.get_json() or {}
    camera_manager.config.update(body)
    return jsonify({
        "status": "success",
        "message": "Camera configuration updated",
        "data": camera_manager.config.to_dict()
    }), 200
