"""
Geofence and Navigation Planning REST API Routes.
Exposes endpoints for querying boundary parameters, testing coordinate safety,
auditing missions against fences, and previewing trajectory profiles.
"""
from flask import Blueprint, jsonify, request
from backend.geofence.geofence_service import geofence_service
from backend.mission.mission_service import mission_service
from backend.search.coverage_planner import coverage_planner
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
        coverage_planner.reconfigure(updated)
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


def _extract_observation_hotspots():
    """Extract and cluster genuine vision detection observation hot spots."""
    observations = []
    try:
        from backend.vision.vision_service import vision_service
        history = vision_service.get_history(limit=50)
        valid_dets = [
            d for d in history
            if d.get("latitude") is not None and d.get("longitude") is not None
            and (d["latitude"] != 0.0 or d["longitude"] != 0.0)
        ]
        clusters = []
        for d in valid_dets:
            matched = False
            for c in clusters:
                dlat = (d["latitude"] - c["lat"]) * 110540.0
                dlon = (d["longitude"] - c["lon"]) * 111320.0 * 0.794
                dist = (dlat ** 2 + dlon ** 2) ** 0.5
                if dist < 5.0 and d.get("payload") == c.get("payload"):
                    c["count"] += 1
                    c["confidence"] = max(c["confidence"], float(d.get("confidence", 0.0)))
                    c["intensity"] = min(1.0, c["count"] * 0.25)
                    matched = True
                    break
            if not matched:
                clusters.append({
                    "lat": float(d["latitude"]),
                    "lon": float(d["longitude"]),
                    "payload": str(d.get("payload", "TARGET")),
                    "label": f"QR: {str(d.get('payload', 'TARGET'))[:12]}",
                    "confidence": float(d.get("confidence", 0.0)),
                    "count": 1,
                    "intensity": 0.25,
                    "latest_timestamp": float(d.get("timestamp", 0.0))
                })
        observations = clusters
    except Exception as e:
        logger.debug("Vision detection hotspot extraction: %s", e)
    return observations


@geofence_bp.route("/coverage", methods=["GET"])
def get_geofence_coverage():
    """
    GET /api/geofence/coverage
    Return real-time geofence search coverage snapshot and vision observation hot spots.
    """
    snap = coverage_planner.get_coverage_snapshot()
    observations = _extract_observation_hotspots()

    response_data = dict(snap)
    response_data["observations"] = observations

    return jsonify({
        "status": "success",
        "data": response_data,
        "boundary_type": response_data["boundary_type"],
        "boundary_geo": response_data["boundary_geo"],
        "total_area_m2": response_data["total_area_m2"],
        "scanned_area_m2": response_data["scanned_area_m2"],
        "coverage_pct": response_data["coverage_pct"],
        "scanned_cells_count": response_data["scanned_cells_count"],
        "total_cells_count": response_data["total_cells_count"],
        "grid_resolution_m": response_data["grid_resolution_m"],
        "search_altitude_m": response_data["search_altitude_m"],
        "footprint_width_m": response_data["footprint_width_m"],
        "footprint_height_m": response_data["footprint_height_m"],
        "scanned_points": response_data["scanned_points"],
        "observations": observations
    }), 200


@geofence_bp.route("/coverage/reset", methods=["POST"])
def reset_geofence_coverage():
    """
    POST /api/geofence/coverage/reset
    Reset accumulated scanned coverage cells back to zero.
    """
    coverage_planner.reset_coverage()
    snap = coverage_planner.get_coverage_snapshot()
    response_data = dict(snap)
    response_data["observations"] = []

    return jsonify({
        "status": "success",
        "message": "Coverage state reset successfully",
        "data": response_data,
        "boundary_type": response_data["boundary_type"],
        "boundary_geo": response_data["boundary_geo"],
        "total_area_m2": response_data["total_area_m2"],
        "scanned_area_m2": response_data["scanned_area_m2"],
        "coverage_pct": response_data["coverage_pct"],
        "scanned_cells_count": response_data["scanned_cells_count"],
        "total_cells_count": response_data["total_cells_count"],
        "grid_resolution_m": response_data["grid_resolution_m"],
        "search_altitude_m": response_data["search_altitude_m"],
        "footprint_width_m": response_data["footprint_width_m"],
        "footprint_height_m": response_data["footprint_height_m"],
        "scanned_points": response_data["scanned_points"],
        "observations": []
    }), 200


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

