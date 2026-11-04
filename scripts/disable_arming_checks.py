#!/usr/bin/env python3
"""
Indoor Bench-Testing Configuration Script.
Disables ARMING_CHECK and FENCE_ENABLE on Pixhawk running ArduPilot via MAVLink.
Run on Raspberry Pi with Pixhawk connected at /dev/ttyACM0.
"""
import sys
import time
from pymavlink import mavutil

DEVICE = "/dev/ttyACM0"
BAUD = 115200


def set_param(master, param_name, param_val, param_type):
    param_bytes = param_name.encode("utf-8")
    print(f"Setting {param_name} = {param_val}...")
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

    # 1. Disable ARMING_CHECK
    set_param(master, "ARMING_CHECK", 0, mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    time.sleep(0.5)

    # 2. Disable FENCE_ENABLE
    set_param(master, "FENCE_ENABLE", 0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
    time.sleep(0.5)

    # 3. Read back parameters to confirm
    print("\nVerifying parameters from Pixhawk...")
    master.mav.param_request_read_send(
        master.target_system,
        master.target_component,
        b"ARMING_CHECK",
        -1
    )
    master.mav.param_request_read_send(
        master.target_system,
        master.target_component,
        b"FENCE_ENABLE",
        -1
    )

    verified = {"ARMING_CHECK": None, "FENCE_ENABLE": None}
    start = time.time()
    while time.time() - start < 4.0:
        msg = master.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
        if msg:
            p_id = msg.param_id.rstrip("\x00")
            if p_id in verified:
                verified[p_id] = msg.param_value
                print(f"  Confirmed: {p_id} = {msg.param_value}")
        if all(v is not None for v in verified.values()):
            break

    print("\n" + "=" * 50)
    if verified["ARMING_CHECK"] == 0.0 and verified["FENCE_ENABLE"] == 0.0:
        print("🎉 SUCCESS: Pre-arm checks and Geofence disabled on Pixhawk!")
        print("You can now start backend/app.py and click '⚡ ARM Drone' in ALT_HOLD mode.")
    else:
        print("⚠️ Parameter update sent. Current readback:", verified)
    print("=" * 50)


if __name__ == "__main__":
    main()
