"""
Computer Vision and QR Detection REST API Routes.
Exposes endpoints for controlling detection worker, querying real-time QR hits,
retrieving detection history, and processing uploaded images.
"""
from flask import Blueprint, jsonify, request
from backend.vision.vision_service import vision_service
from config.logging_config import setup_logging

logger = setup_logging("vision_routes")
vision_bp = Blueprint("vision_bp", __name__, url_prefix="/api/vision/qr")


@vision_bp.route("/status", methods=["GET"])
def get_qr_status():
    """GET /api/vision/qr/status - Return QR detection engine status."""
    return jsonify({
        "status": "success",
        "data": vision_service.get_status()
    }), 200


@vision_bp.route("/start", methods=["POST"])
def start_qr_detection():
    """POST /api/vision/qr/start - Start background QR detection worker."""
    vision_service.start()
    return jsonify({
        "status": "success",
        "message": "QR detection service started",
        "data": vision_service.get_status()
    }), 200


@vision_bp.route("/stop", methods=["POST"])
def stop_qr_detection():
    """POST /api/vision/qr/stop - Stop background QR detection worker."""
    vision_service.stop()
    return jsonify({
        "status": "success",
        "message": "QR detection service stopped",
        "data": vision_service.get_status()
    }), 200


@vision_bp.route("/latest", methods=["GET"])
def get_latest_qr():
    """GET /api/vision/qr/latest - Retrieve the most recently decoded QR code."""
    latest = vision_service.get_latest()
    return jsonify({
        "status": "success",
        "data": latest
    }), 200


@vision_bp.route("/history", methods=["GET"])
def get_qr_history():
    """GET /api/vision/qr/history?limit=20 - Retrieve historical detections."""
    limit = request.args.get("limit", default=20, type=int)
    history = vision_service.get_history(limit=limit)
    return jsonify({
        "status": "success",
        "count": len(history),
        "data": history
    }), 200


@vision_bp.route("/clear", methods=["POST"])
def clear_qr_history():
    """POST /api/vision/qr/clear - Clear history and cooldown caches."""
    vision_service.clear_history()
    return jsonify({
        "status": "success",
        "message": "QR detection history cleared"
    }), 200


@vision_bp.route("/process-image", methods=["POST"])
def process_uploaded_image():
    """
    POST /api/vision/qr/process-image
    Accepts multipart file upload or raw binary data to decode QR codes on demand.
    """
    image_bytes = None
    filename = "uploaded_file.jpg"

    if "file" in request.files:
        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({
                "status": "error",
                "message": "No file selected"
            }), 400

        filename = uploaded_file.filename
        image_bytes = uploaded_file.read()
    elif request.data:
        image_bytes = request.data
    else:
        return jsonify({
            "status": "error",
            "message": "No image data or file provided in request"
        }), 400

    try:
        results = vision_service.process_image_bytes(image_bytes, filename=filename)
        return jsonify({
            "status": "success",
            "count": len(results),
            "data": results
        }), 200
    except ValueError as ve:
        return jsonify({
            "status": "error",
            "message": str(ve)
        }), 400
    except Exception as e:
        logger.error("Failed processing uploaded image for QR: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Processing error: {str(e)}"
        }), 500

