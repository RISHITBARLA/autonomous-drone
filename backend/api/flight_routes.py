"""
Flight Control REST API Routes for AUTONOMOUS-DRONE.
Provides isolated, explicit interfaces for arming, mode change, takeoff, and RTL.
Returns HTTP 403 Forbidden whenever flight controls are disabled.
"""
from flask import Blueprint, jsonify, request
from backend.flight.flight_controller import flight_controller
from config.logging_config import setup_logging

logger = setup_logging("flight_routes")
flight_bp = Blueprint("flight_bp", __name__, url_prefix="/api/flight")


@flight_bp.route("/status", methods=["GET"])
def get_flight_status():
    """GET /api/flight/status - Return flight control state, safety interlock, and mode."""
    return jsonify({
        "status": "success",
        "data": flight_controller.get_status()
    }), 200


@flight_bp.route("/arm", methods=["POST"])
def arm_vehicle():
    """POST /api/flight/arm - Send arm command to Pixhawk flight controller."""
    res = flight_controller.request_arm(arm=True)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"]}), 200


@flight_bp.route("/disarm", methods=["POST"])
def disarm_vehicle():
    """POST /api/flight/disarm - Send disarm command to Pixhawk flight controller."""
    res = flight_controller.request_arm(arm=False)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"]}), 200


@flight_bp.route("/mode", methods=["POST"])
def set_flight_mode():
    """POST /api/flight/mode - Request flight mode change (e.g. GUIDED, LOITER, RTL)."""
    body = request.get_json() or {}
    mode = body.get("mode")
    if not mode:
        return jsonify({"status": "error", "message": "'mode' field is required"}), 400

    res = flight_controller.request_mode(mode)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"], "data": res}), 200


@flight_bp.route("/takeoff", methods=["POST"])
def request_takeoff():
    """POST /api/flight/takeoff - Request autonomous takeoff to target altitude."""
    body = request.get_json() or {}
    alt = body.get("altitude_m", 5.0)
    try:
        alt_m = float(alt)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid numeric altitude"}), 400

    res = flight_controller.request_takeoff(alt_m)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"]}), 200


@flight_bp.route("/rtl", methods=["POST"])
def request_rtl():
    """POST /api/flight/rtl - Request Return-to-Launch."""
    res = flight_controller.request_rtl()
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"]}), 200


@flight_bp.route("/land", methods=["POST"])
def request_land():
    """POST /api/flight/land - Request vehicle landing."""
    res = flight_controller.request_land()
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"]}), 200


@flight_bp.route("/command-log", methods=["GET"])
def get_command_log():
    """GET /api/flight/command-log - Retrieve audit history of executed flight commands."""
    limit = request.args.get("limit", default=50, type=int)
    log = flight_controller.get_command_log(limit=limit)
    return jsonify({
        "status": "success",
        "count": len(log),
        "data": log
    }), 200

