"""
MAVLink Telemetry REST API Routes.
Exposes endpoints for vehicle connection status, GPS navigation data,
battery telemetry, attitude angles, and flight modes.
"""
from flask import Blueprint, jsonify, request
from backend.flight.mavlink_service import mavlink_service

telemetry_bp = Blueprint("telemetry_bp", __name__, url_prefix="/api/telemetry")


@telemetry_bp.route("/status", methods=["GET"])
def get_telemetry_status():
    """GET /api/telemetry/status - Return connection health, heartbeat age, and flight mode."""
    snap = mavlink_service.get_snapshot()
    return jsonify({
        "status": "success",
        "data": {
            "connected": snap.connected,
            "is_simulated": snap.is_simulated,
            "is_stale": snap.is_stale,
            "heartbeat_age_seconds": snap.heartbeat_age_seconds,
            "flight_mode": snap.flight_mode,
            "armed": snap.armed,
            "system_status": snap.system_status,
            "connection_string": mavlink_service.connection_string,
            "baudrate": mavlink_service.baudrate
        }
    }), 200


@telemetry_bp.route("/current", methods=["GET"])
def get_current_telemetry():
    """GET /api/telemetry/current - Complete real-time flight telemetry snapshot."""
    snap = mavlink_service.get_snapshot()
    return jsonify({
        "status": "success",
        "data": snap.to_dict()
    }), 200


@telemetry_bp.route("/gps", methods=["GET"])
def get_gps_telemetry():
    """GET /api/telemetry/gps - Coordinates, fix type, visible satellites, and altitude."""
    snap = mavlink_service.get_snapshot()
    return jsonify({
        "status": "success",
        "data": {
            "latitude": snap.latitude,
            "longitude": snap.longitude,
            "altitude_relative_m": snap.altitude_relative_m,
            "altitude_msl_m": snap.altitude_msl_m,
            "fix_type": snap.gps_fix_type,
            "fix_name": snap.gps_fix_name,
            "satellites": snap.satellites_visible,
            "hdop": snap.hdop,
            "heading": snap.heading_deg,
            "groundspeed": snap.groundspeed_m_s
        }
    }), 200


@telemetry_bp.route("/battery", methods=["GET"])
def get_battery_telemetry():
    """GET /api/telemetry/battery - Voltage, current, and remaining percentage."""
    snap = mavlink_service.get_snapshot()
    return jsonify({
        "status": "success",
        "data": {
            "voltage_v": snap.battery_voltage_v,
            "current_a": snap.battery_current_a,
            "remaining_percent": snap.battery_remaining_percent,
            "status": "CRITICAL" if snap.battery_remaining_percent < 20 else ("WARNING" if snap.battery_remaining_percent < 30 else "NORMAL")
        }
    }), 200


@telemetry_bp.route("/attitude", methods=["GET"])
def get_attitude_telemetry():
    """GET /api/telemetry/attitude - Roll, pitch, yaw, and climb rate."""
    snap = mavlink_service.get_snapshot()
    return jsonify({
        "status": "success",
        "data": {
            "roll_deg": snap.roll_deg,
            "pitch_deg": snap.pitch_deg,
            "yaw_deg": snap.yaw_deg,
            "heading_deg": snap.heading_deg,
            "climb_rate_m_s": snap.climb_rate_m_s
        }
    }), 200


@telemetry_bp.route("/connection", methods=["POST"])
def configure_connection():
    """POST /api/telemetry/connection - Configure MAVLink endpoint and restart worker."""
    body = request.get_json() or {}
    conn_str = body.get("connection_string", mavlink_service.connection_string)
    baudrate = int(body.get("baudrate", mavlink_service.baudrate))
    simulate = body.get("simulate", mavlink_service.simulate)

    mavlink_service.set_connection(connection_string=conn_str, baudrate=baudrate, simulate=simulate)

    return jsonify({
        "status": "success",
        "message": "MAVLink connection settings updated",
        "data": {
            "connection_string": mavlink_service.connection_string,
            "baudrate": mavlink_service.baudrate,
            "simulate": mavlink_service.simulate
        }
    }), 200

