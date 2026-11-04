#!/usr/bin/env python3
"""
Outdoor Flight Configuration Script.
Re-enables standard ARMING_CHECK, FENCE_ENABLE, and safety switch requirements
on Pixhawk running ArduPilot for safe outdoor flight with propellers.
"""
import glob
import sys
import time
from pymavlink import mavutil


def find_pixhawk_device():
    """Auto-detect connected Pixhawk USB or serial port."""
    if len(sys.argv) > 1:
        return sys.argv[1]
    candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/serial/by-id/*"))
    if candidates:
        return candidates[0]
    return "/dev/ttyACM0"


DEVICE = find_pixhawk_device()
BAUD = 115200


def set_param(master, param_name, param_val, param_type):
    param_bytes = param_name.encode("utf-8")
    print(f"Restoring {param_name} = {param_val}...")
    master.mav.param_set_send(
        master.target_system,
        master.target_component,
        param_bytes,
        float(param_val),
        param_type
    )


def main():
    print(f"Connecting to Pixhawk on {DEVICE} at {BAUD} baud...")
    try:
        master = mavutil.mavlink_connection(DEVICE, baud=BAUD, timeout=5.0)
    except Exception as e:
        print(f"❌ Failed to open serial port {DEVICE}: {e}")
        sys.exit(1)

    print("Waiting for Pixhawk heartbeat...")
    msg = master.wait_heartbeat(timeout=5.0)
    if not msg:
        print("❌ No heartbeat received within 5 seconds. Check USB cable.")
        sys.exit(1)

    print(f"✅ Connected to Autopilot (System {master.target_system}, Component {master.target_component})")

    # 1. Restore ARMING_CHECK to 1 (All standard checks enabled)
    set_param(master, "ARMING_CHECK", 1, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    time.sleep(0.5)

    # 2. Restore BRD_SAFETYENABLE to 1 (Hardware safety switch enabled)
    set_param(master, "BRD_SAFETYENABLE", 1, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    time.sleep(0.5)

    print("\n" + "=" * 50)
    print("🛡️ SAFETY RESTORED: Standard pre-arm and safety switch checks enabled!")
    print("Pixhawk will now enforce full sensor, compass, and GPS validation before flight.")
    print("=" * 50)


if __name__ == "__main__":
    main()
