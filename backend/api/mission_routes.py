"""
Mission Management REST API Routes for AUTONOMOUS-DRONE.
Provides full CRUD capabilities for missions, FSM state transitions,
active mission assignment, and safe QR code mission selection.
"""
from flask import Blueprint, jsonify, request
from backend.mission.mission_service import mission_service
from backend.mission.mission_model import MissionState
from config.logging_config import setup_logging

logger = setup_logging("mission_routes")
mission_bp = Blueprint("mission_bp", __name__, url_prefix="/api/missions")


@mission_bp.route("", methods=["GET"])
def list_missions():
    """GET /api/missions - Return list of all configured missions."""
    missions = mission_service.list_missions()
    active = mission_service.get_active_mission()
    return jsonify({
        "status": "success",
        "count": len(missions),
        "active_mission_id": active.id if active else None,
        "data": [m.to_dict() for m in missions]
    }), 200


@mission_bp.route("", methods=["POST"])
def create_mission():
    """POST /api/missions - Create and validate a new mission record."""
    body = request.get_json() or {}
    try:
        mission = mission_service.create_mission(body)
        return jsonify({
            "status": "success",
            "message": f"Mission '{mission.id}' created successfully",
            "data": mission.to_dict()
        }), 201
    except ValueError as ve:
        return jsonify({
            "status": "error",
            "message": str(ve)
        }), 400
    except Exception as e:
        logger.error("Failed creating mission: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Internal error: {str(e)}"
        }), 500


@mission_bp.route("/active", methods=["GET"])
def get_active_mission():
    """GET /api/missions/active - Return currently active/loaded mission."""
    mission = mission_service.get_active_mission()
    if not mission:
        return jsonify({
            "status": "success",
            "data": None,
            "message": "No active mission selected"
        }), 200
    return jsonify({
        "status": "success",
        "data": mission.to_dict()
    }), 200


@mission_bp.route("/active", methods=["POST"])
def set_active_mission():
    """POST /api/missions/active - Set currently active mission by ID."""
    body = request.get_json() or {}
    mission_id = body.get("mission_id")
    if not mission_id:
        return jsonify({"status": "error", "message": "mission_id required"}), 400

    mission = mission_service.set_active_mission(mission_id)
    if not mission:
        return jsonify({"status": "error", "message": f"Mission '{mission_id}' not found"}), 404

    return jsonify({
        "status": "success",
        "message": f"Mission '{mission_id}' is now active",
        "data": mission.to_dict()
    }), 200


@mission_bp.route("/<mission_id>", methods=["GET"])
def get_mission(mission_id: str):
    """GET /api/missions/<id> - Retrieve details for specific mission."""
    mission = mission_service.get_mission(mission_id)
    if not mission:
        return jsonify({
            "status": "error",
            "message": f"Mission '{mission_id}' not found"
        }), 404
    return jsonify({
        "status": "success",
        "data": mission.to_dict()
    }), 200


@mission_bp.route("/<mission_id>", methods=["PUT"])
def update_mission(mission_id: str):
    """PUT /api/missions/<id> - Update mission metadata and waypoints."""
    body = request.get_json() or {}
    mission = mission_service.update_mission(mission_id, body)
    if not mission:
        return jsonify({
            "status": "error",
            "message": f"Mission '{mission_id}' not found"
        }), 404
    return jsonify({
        "status": "success",
        "message": f"Mission '{mission_id}' updated",
        "data": mission.to_dict()
    }), 200


@mission_bp.route("/<mission_id>", methods=["DELETE"])
def delete_mission(mission_id: str):
    """DELETE /api/missions/<id> - Remove a mission."""
    success = mission_service.delete_mission(mission_id)
    if not success:
        return jsonify({
            "status": "error",
            "message": f"Mission '{mission_id}' not found"
        }), 404
    return jsonify({
        "status": "success",
        "message": f"Mission '{mission_id}' deleted"
    }), 200


@mission_bp.route("/<mission_id>/state", methods=["POST"])
def transition_state(mission_id: str):
    """POST /api/missions/<id>/state - Trigger state transition in mission FSM."""
    body = request.get_json() or {}
    target_state_str = body.get("state")
    reason = body.get("reason", "Operator request")

    if not target_state_str:
        return jsonify({"status": "error", "message": "Missing 'state' in request"}), 400

    try:
        target_state = MissionState(target_state_str)
    except ValueError:
        return jsonify({
            "status": "error",
            "message": f"Invalid state '{target_state_str}'. Allowed: {[s.value for s in MissionState]}"
        }), 400

    try:
        mission = mission_service.set_mission_state(mission_id, target_state, reason=reason)
        return jsonify({
            "status": "success",
            "message": f"Mission '{mission_id}' transitioned to {target_state.value}",
            "data": mission.to_dict()
        }), 200
    except KeyError:
        return jsonify({"status": "error", "message": f"Mission '{mission_id}' not found"}), 404
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400


@mission_bp.route("/associate-qr", methods=["POST"])
def associate_qr():
    """
    POST /api/missions/associate-qr
    Matches QR string against stored missions and activates target mission.
    """
    body = request.get_json() or {}
    qr_payload = body.get("payload")
    if not qr_payload:
        return jsonify({
            "status": "error",
            "message": "Missing 'payload' field in JSON request"
        }), 400

    res = mission_service.associate_qr_payload(qr_payload)
    if res["associated"]:
        return jsonify({
            "status": "success",
            "message": res["reason"],
            "data": res
        }), 200
    else:
        return jsonify({
            "status": "error",
            "message": res["reason"],
            "data": res
        }), 400


@mission_bp.route("/generate-spiral", methods=["POST"])
def generate_spiral_mission():
    """
    POST /api/missions/generate-spiral
    Generates an interior-covering Archimedean spiral or concentric tangential waypoint
    sequence for a circular scanning boundary and validates containment against geofence.
    """
    from backend.mission.spiral_coverage_planner import (
        SpiralCoverageConfig,
        SpiralCoveragePlanner,
    )

    body = request.get_json() or {}
    try:
        center_lat = float(body["center_lat"])
        center_lon = float(body["center_lon"])
        radius_m = float(body["radius_m"])
    except (KeyError, TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "Missing or invalid required parameters: center_lat, center_lon, radius_m"
        }), 400

    alt_m = float(body.get("alt_m", 15.0))
    speed_m_s = float(body.get("speed_m_s", 4.0))
    overlap_pct = float(body.get("overlap_pct", 25.0))
    pattern_type = str(body.get("pattern_type", "spiral")).lower()
    auto_save = bool(body.get("auto_save", False))
    explicit_spacing = float(body["spacing_m"]) if "spacing_m" in body and body["spacing_m"] is not None else None

    try:
        cfg = SpiralCoverageConfig(
            center_lat=center_lat,
            center_lon=center_lon,
            radius_m=radius_m,
            alt_m=alt_m,
            speed_m_s=speed_m_s,
            overlap_pct=overlap_pct,
            pattern_type=pattern_type,
            explicit_spacing_m=explicit_spacing,
        )
        planner = SpiralCoveragePlanner(cfg)
        waypoints, metadata = planner.generate_waypoints()
        is_valid, violations = planner.validate_against_geofence(waypoints)
        metadata["contained_in_geofence"] = is_valid
        metadata["violations"] = violations

        if not is_valid and not body.get("allow_uncontained", False):
            return jsonify({
                "status": "error",
                "message": f"Generated scanning route violates geofence ({len(violations)} points out of bounds)",
                "data": {
                    "waypoints": [w.__dict__ for w in waypoints],
                    "metadata": metadata,
                    "violations": violations,
                }
            }), 400

        saved_mission = None
        if auto_save and is_valid:
            mission_name = body.get("name", f"Spiral-Scan-{int(radius_m)}m")
            mission_data = {
                "name": mission_name,
                "description": f"Autonomous {pattern_type} area scan: center=({center_lat:.5f}, {center_lon:.5f}), R={radius_m}m",
                "waypoints": [w.__dict__ for w in waypoints],
            }
            saved_mission = mission_service.create_mission(mission_data).to_dict()

        return jsonify({
            "status": "success",
            "message": f"Generated {len(waypoints)} scanning waypoints ({pattern_type} pattern)",
            "data": {
                "waypoints": [w.__dict__ for w in waypoints],
                "metadata": metadata,
                "saved_mission": saved_mission,
            }
        }), 200

    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error("Failed generating spiral mission: %s", e)
        return jsonify({"status": "error", "message": f"Internal error: {str(e)}"}), 500


