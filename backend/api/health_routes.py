"""
System Health and Companion Computer Telemetry API Routes.
Exposes endpoints for CPU, Memory, Disk, Temperature, and Hardware metrics.
"""
from flask import Blueprint, jsonify, request
from backend.system.health_monitor import HealthMonitor
from backend.system.hardware_info import HardwareInfo
from backend.system.temperature import TemperatureMonitor
from config.settings import settings

health_bp = Blueprint("health_bp", __name__, url_prefix="/api/health")


@health_bp.route("", methods=["GET"])
def get_health():
    """
    GET /api/health
    Returns comprehensive system health status and hardware metrics.
    Supports query param ?mock=true to simulate Pi 4 hardware on non-Pi hosts.
    """
    mock_hw = request.args.get("mock", "").lower() in ("true", "1") or settings.ENABLE_MOCK_HARDWARE
    health_data = HealthMonitor.get_full_health(mock_hardware=mock_hw)
    return jsonify({
        "status": "success",
        "data": health_data
    }), 200


@health_bp.route("/summary", methods=["GET"])
def get_health_summary():
    """
    GET /api/health/summary
    Lightweight health summary for high-frequency dashboard telemetry polling.
    """
    cpu = HealthMonitor.get_cpu_metrics()
    mem = HealthMonitor.get_memory_metrics()
    disk = HealthMonitor.get_disk_metrics()
    temp = TemperatureMonitor.get_temperature()
    uptime = HealthMonitor.get_uptime_metrics()
    status_eval = HealthMonitor.evaluate_system_status(cpu, mem, disk, temp)

    return jsonify({
        "status": "success",
        "data": {
            "overall_status": status_eval["status"],
            "healthy": status_eval["healthy"],
            "warnings": status_eval["warnings"],
            "cpu_percent": cpu["usage_percent"],
            "ram_percent": mem["usage_percent"],
            "disk_percent": disk["usage_percent"],
            "temperature_c": temp["celsius"],
            "uptime_formatted": uptime["formatted"]
        }
    }), 200


@health_bp.route("/hardware", methods=["GET"])
def get_hardware_info():
    """
    GET /api/health/hardware
    Returns Raspberry Pi and host hardware details.
    """
    mock_hw = request.args.get("mock", "").lower() in ("true", "1") or settings.ENABLE_MOCK_HARDWARE
    hw_info = HardwareInfo.get_system_summary(mock_if_not_rpi=mock_hw)
    return jsonify({
        "status": "success",
        "data": hw_info
    }), 200


@health_bp.route("/temperature", methods=["GET"])
def get_temperature():
    """
    GET /api/health/temperature
    Returns CPU temperature, safety evaluation, and Pi throttling bitmask.
    """
    temp_data = TemperatureMonitor.get_temperature()
    return jsonify({
        "status": "success",
        "data": temp_data
    }), 200
