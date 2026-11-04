"""
Flight Control REST API Routes for AUTONOMOUS-DRONE.
Provides isolated, explicit interfaces for arming, mode change, takeoff, and RTL.
Returns HTTP 403 Forbidden whenever flight controls are disabled.
"""
from flask import Blueprint, jsonify, request
from backend.flight.flight_controller import flight_controller
from backend.flight.mavlink_service import mavlink_service
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
    """
    POST /api/flight/arm - Send arm command to Pixhawk flight controller.
    Requires explicit operator confirmation parameter: {"confirm": true}.
    """
    body = request.get_json(silent=True) or {}
    confirm = bool(body.get("confirm", False))
    res = flight_controller.request_arm(arm=True, confirm=confirm)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"], "data": res}), 200


@flight_bp.route("/disarm", methods=["POST"])
def disarm_vehicle():
    """POST /api/flight/disarm - Send disarm command to Pixhawk flight controller."""
    res = flight_controller.request_arm(arm=False, confirm=True)
    if not res["success"]:
        code = 403 if res.get("code") == "CONTROL_DISABLED" else 400
        return jsonify({"status": "error", "message": res["message"], "code": res.get("code")}), code
    return jsonify({"status": "success", "message": res["message"], "data": res}), 200


@flight_bp.route("/mode", methods=["POST"])
def set_flight_mode():
    """POST /api/flight/mode - Request flight mode change (e.g. ALT_HOLD, GUIDED, LOITER, RTL)."""
    body = request.get_json(silent=True) or {}
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
    body = request.get_json(silent=True) or {}
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


@flight_bp.route("/prearm-messages", methods=["GET"])
def get_prearm_messages():
    """GET /api/flight/prearm-messages - Retrieve recent Pixhawk STATUSTEXT pre-arm messages."""
    limit = request.args.get("limit", default=20, type=int)
    messages = mavlink_service.get_status_texts(limit=limit, prearm_only=True)
    return jsonify({
        "status": "success",
        "count": len(messages),
        "data": messages
    }), 200


@flight_bp.route("/connect", methods=["POST"])
def connect_flight_controller():
    """POST /api/flight/connect - Connect or reconnect MAVLink bridge."""
    body = request.get_json(silent=True) or {}
    conn_str = body.get("connection_string", mavlink_service.connection_string)
    baudrate = int(body.get("baudrate", mavlink_service.baudrate))
    simulate = body.get("simulate", mavlink_service.simulate)

    mavlink_service.set_connection(connection_string=conn_str, baudrate=baudrate, simulate=simulate)
    return jsonify({
        "status": "success",
        "message": f"Updated MAVLink connection to {conn_str}",
        "data": {
            "connection_string": mavlink_service.connection_string,
            "baudrate": mavlink_service.baudrate,
            "simulate": mavlink_service.simulate
        }
    }), 200


@flight_bp.route("/disconnect", methods=["POST"])
def disconnect_flight_controller():
    """POST /api/flight/disconnect - Disconnect MAVLink bridge."""
    mavlink_service.stop()
    return jsonify({
        "status": "success",
        "message": "MAVLink connection stopped"
    }), 200


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


@flight_bp.route("/disable-arming-checks", methods=["POST"])
def disable_arming_checks():
    """
    POST /api/flight/disable-arming-checks
    Configure Pixhawk for indoor bench testing:
    - ARMING_CHECK = 0 (disable pre-arm sensor checks)
    - FENCE_ENABLE = 0 (disable geofence GPS position checks)
    - BRD_SAFETYENABLE = 0 (disable hardware safety switch requirement)
    """
    from pymavlink import mavutil
    try:
        mavlink_service.set_param("ARMING_CHECK", 0.0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
        mavlink_service.set_param("FENCE_ENABLE", 0.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        mavlink_service.set_param("BRD_SAFETYENABLE", 0.0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
        return jsonify({
            "status": "success",
            "message": "Indoor bench parameters applied: ARMING_CHECK=0, FENCE_ENABLE=0, BRD_SAFETYENABLE=0"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed setting bench parameters: {str(e)}"
        }), 500

