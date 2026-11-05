"""
Computer Vision and QR Detection REST API Routes.
Exposes endpoints for controlling detection worker, querying real-time QR hits,
retrieving detection history, and processing uploaded images.
"""
from flask import Blueprint, jsonify, request
import cv2
import numpy as np

from backend.vision.vision_service import vision_service
from backend.vision.task2_vision_service import task2_vision_engine
from backend.vision.geoprojector import DronePose
import time
from config.logging_config import setup_logging

logger = setup_logging("vision_routes")
vision_bp = Blueprint("vision_bp", __name__, url_prefix="/api/vision/qr")
heatmap_bp = Blueprint("heatmap_bp", __name__)


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


# ============================================================================
# Task 2: Live Heatmap & Priority Candidate Vision Endpoints
# ============================================================================

@heatmap_bp.route("/api/vision/heatmap", methods=["GET"])
@heatmap_bp.route("/api/v2/vision/heatmap", methods=["GET"])
def get_live_heatmap():
    """
    GET /api/vision/heatmap (and /api/v2/vision/heatmap)
    Returns live 7-category heatmap payload with spatial clusters, raw counts,
    and performance metrics.
    """
    category_filter = request.args.get("category", "all")
    payload = task2_vision_engine.get_live_heatmap()
    if category_filter and category_filter != "all":
        payload["clusters"] = [c for c in payload["clusters"] if c.get("category") == category_filter]
        payload["markers"] = [m for m in payload.get("markers", []) if m.get("category") == category_filter]
        payload["heatmap_points"] = [p for p in payload["heatmap_points"] if p.get("category") == category_filter]
    return jsonify(payload), 200


@heatmap_bp.route("/api/vision/heatmap/clear", methods=["POST"])
def clear_live_heatmap():
    """POST /api/vision/heatmap/clear - Clear all active target clusters and history."""
    task2_vision_engine.clear_state()
    return jsonify({
        "status": "success",
        "message": "Task 2 live heatmap and target clusters cleared"
    }), 200


@heatmap_bp.route("/api/vision/heatmap/process-frame", methods=["POST"])
def process_heatmap_frame():
    """
    POST /api/vision/heatmap/process-frame
    Synchronous processing of a frame with telemetry pose for testing and analysis.
    Accepts image in multipart file ('file' or 'image') or raw body bytes,
    with optional pose parameters (lat, lon, alt, roll_deg, pitch_deg, yaw_deg, hdop).
    """
    image_bytes = None
    if "file" in request.files:
        uploaded_file = request.files["file"]
        if uploaded_file.filename != "":
            image_bytes = uploaded_file.read()
    elif "image" in request.files:
        uploaded_file = request.files["image"]
        if uploaded_file.filename != "":
            image_bytes = uploaded_file.read()
    elif request.data:
        image_bytes = request.data

    if not image_bytes:
        return jsonify({
            "status": "error",
            "message": "No image data or file provided in request"
        }), 400

    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        return jsonify({
            "status": "error",
            "message": "Failed decoding image data"
        }), 400

    def get_val(key, default=None):
        if key in request.form:
            try:
                return float(request.form[key])
            except (ValueError, TypeError):
                pass
        if key in request.args:
            try:
                return float(request.args[key])
            except (ValueError, TypeError):
                pass
        return default

    lat = get_val("lat")
    lon = get_val("lon")
    alt = get_val("alt", get_val("alt_agl_m"))
    roll = get_val("roll_deg", 0.0)
    pitch = get_val("pitch_deg", 0.0)
    yaw = get_val("yaw_deg", 0.0)
    hdop = get_val("hdop", 1.0)

    # Fallback to MAVLink telemetry if lat/lon not provided in request
    if lat is None or lon is None or alt is None:
        try:
            from backend.flight.mavlink_service import mavlink_service
            snap = mavlink_service.get_snapshot()
            if lat is None:
                lat = snap.latitude
            if lon is None:
                lon = snap.longitude
            if alt is None:
                alt = snap.altitude_relative_m
            if hdop == 1.0 and snap.gps_hdop is not None:
                hdop = snap.gps_hdop
        except Exception:
            pass

    gps_fix = (lat is not None and lon is not None and not (lat == 0.0 and lon == 0.0))
    pose = DronePose(
        timestamp=time.time(),
        lat=lat,
        lon=lon,
        alt_agl_m=alt if alt is not None else 0.0,
        roll_deg=roll if roll is not None else 0.0,
        pitch_deg=pitch if pitch is not None else 0.0,
        yaw_deg=yaw if yaw is not None else 0.0,
        gps_fix_valid=gps_fix,
        hdop=hdop if hdop is not None else 1.0,
    )

    records = task2_vision_engine.process_frame_sync(frame, pose)
    heatmap = task2_vision_engine.get_live_heatmap()
    return jsonify({
        "status": "success",
        "detections_count": len(records),
        "detections": records,
        "heatmap": heatmap
    }), 200


