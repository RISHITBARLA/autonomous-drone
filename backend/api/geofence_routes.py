"""
Geofence and Navigation Planning REST API Routes.
Exposes endpoints for querying boundary parameters, testing coordinate safety,
auditing missions against fences, and previewing trajectory profiles.
"""
from flask import Blueprint, jsonify, request
from backend.geofence.geofence_service import geofence_service
from backend.mission.mission_service import mission_service
from config.logging_config import setup_logging

logger = setup_logging("geofence_routes")
geofence_bp = Blueprint("geofence_bp", __name__, url_prefix="/api/geofence")


@geofence_bp.route("", methods=["GET"])
def get_geofence():
    """GET /api/geofence - Return current geofence configuration."""
    return jsonify({
        "status": "success",
        "data": geofence_service.config.to_dict()
    }), 200


@geofence_bp.route("", methods=["POST"])
def update_geofence():
    """POST /api/geofence - Update geofence boundaries and altitude limits."""
    body = request.get_json() or {}
    try:
        updated = geofence_service.update_config(body)
        return jsonify({
            "status": "success",
            "message": "Geofence configuration updated",
            "data": updated.to_dict()
        }), 200
    except Exception as e:
        logger.error("Failed updating geofence: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Invalid configuration: {str(e)}"
        }), 400


@geofence_bp.route("/check-point", methods=["POST"])
def check_point():
    """
    POST /api/geofence/check-point
    Evaluate whether a given coordinate (lat, lon, alt_m) violates boundaries.
    """
    body = request.get_json() or {}
    if "lat" not in body or "lon" not in body:
        return jsonify({"status": "error", "message": "'lat' and 'lon' are required"}), 400

    try:
        lat = float(body["lat"])
        lon = float(body["lon"])
        alt_m = float(body.get("alt_m", 15.0))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid numeric coordinate parameters"}), 400

    result = geofence_service.check_coordinate(lat, lon, alt_m)
    return jsonify({
        "status": "success",
        "data": result
    }), 200


@geofence_bp.route("/validate-mission/<mission_id>", methods=["POST"])
def validate_mission_geofence(mission_id: str):
    """
    POST /api/geofence/validate-mission/<id>
    Check an existing mission's waypoints against active geofence boundaries.
    """
    mission = mission_service.get_mission(mission_id)
    if not mission:
        return jsonify({
            "status": "error",
            "message": f"Mission '{mission_id}' not found"
        }), 404

    report = geofence_service.validate_mission(mission)
    return jsonify({
        "status": "success",
        "data": report
    }), 200


@geofence_bp.route("/plan-preview", methods=["POST"])
def plan_preview():
    """
    POST /api/geofence/plan-preview
    Calculates trajectory distance, time estimates, and boundary checks for arbitrary waypoint list.
    """
    body = request.get_json() or {}
    waypoints_data = body.get("waypoints", [])
    if not isinstance(waypoints_data, list):
        return jsonify({"status": "error", "message": "'waypoints' must be a list"}), 400

    try:
        from backend.mission.mission_model import Waypoint
        waypoints = [
            Waypoint(
                seq=w.get("seq", i + 1),
                lat=float(w["lat"]),
                lon=float(w["lon"]),
                alt_m=float(w["alt_m"]),
                speed_m_s=float(w.get("speed_m_s", 5.0)),
                hold_time_s=float(w.get("hold_time_s", 0.0)),
                action=str(w.get("action", "WAYPOINT"))
            )
            for i, w in enumerate(waypoints_data)
        ]
    except Exception as e:
        return jsonify({"status": "error", "message": f"Malformed waypoint list: {str(e)}"}), 400

    metrics = geofence_service.calculate_path_metrics(waypoints)

    point_checks = [
        geofence_service.check_coordinate(wp.lat, wp.lon, wp.alt_m)
        for wp in waypoints
    ]
    all_inside = all(c["inside"] for c in point_checks)

    return jsonify({
        "status": "success",
        "data": {
            "all_points_inside": all_inside,
            "metrics": metrics,
            "checks": point_checks
        }
    }), 200

