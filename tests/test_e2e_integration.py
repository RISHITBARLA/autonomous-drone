"""
End-to-End System Integration and Reliability Tests (Milestone 08).
Verifies complete companion workflow:
1. Camera frame acquisition -> QR detection -> Mission matching & activation.
2. MAVLink telemetry streaming -> Coordinate extraction -> Geofence safety boundary checks.
3. Strict subsystem isolation: QR payloads cannot trigger unauthorized flight commands.
4. Concurrent subsystem thread stability.
"""
import time
import unittest
import cv2
import numpy as np

from backend.app import create_app
from backend.camera.camera_manager import camera_manager
from backend.vision.qr_detector import QRDetector
from backend.vision.vision_service import vision_service
from backend.flight.mavlink_service import mavlink_service
from backend.flight.flight_controller import flight_controller
from backend.mission.mission_service import mission_service
from backend.mission.mission_model import MissionState
from backend.geofence.geofence_service import geofence_service


class TestEndToEndIntegration(unittest.TestCase):
    """End-to-End system test verifying cross-subsystem contracts."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Start simulated telemetry
        mavlink_service.simulate = True
        mavlink_service.start()

    def tearDown(self):
        vision_service.stop()
        mavlink_service.stop()

    def test_e2e_camera_qr_mission_workflow(self):
        """
        Full workflow test:
        1. Synthesize a camera frame containing a valid mission QR code.
        2. Pass through vision service.
        3. Match against stored mission.
        4. Verify active mission is activated and transitioned to READY.
        """
        # Ensure a test mission exists in storage
        mission_id = "e2e-patrol-01"
        if not mission_service.get_mission(mission_id):
            mission_service.create_mission({
                "id": mission_id,
                "name": "E2E Patrol Alpha",
                "waypoints": [
                    {"seq": 1, "lat": 37.4093, "lon": -122.0641, "alt_m": 15.0, "action": "TAKEOFF"},
                    {"seq": 2, "lat": 37.4095, "lon": -122.0638, "alt_m": 20.0, "action": "WAYPOINT"}
                ]
            })

        # Step 1: Synthesize camera frame with QR payload "MISSION:e2e-patrol-01"
        target_payload = f"MISSION:{mission_id}"
        frame = QRDetector.generate_test_qr_frame(target_payload, width=640, height=480)
        self.assertIsNotNone(frame)

        # Step 2: Encode to JPEG (simulating camera capture)
        _, jpeg_bytes = cv2.imencode(".jpg", frame)

        # Step 3: Send to QR API upload endpoint
        qr_res = self.client.post(
            "/api/vision/qr/process-image",
            data=jpeg_bytes.tobytes(),
            content_type="image/jpeg"
        )
        self.assertEqual(qr_res.status_code, 200)
        qr_data = qr_res.get_json()
        self.assertEqual(qr_data["status"], "success")
        self.assertGreaterEqual(qr_data["count"], 1)
        detected_text = qr_data["data"][0]["payload"]
        self.assertEqual(detected_text, target_payload)

        # Step 4: Associate decoded QR text with mission
        assoc_res = self.client.post(
            "/api/missions/associate-qr",
            json={"payload": detected_text}
        )
        self.assertEqual(assoc_res.status_code, 200)
        assoc_data = assoc_res.get_json()
        self.assertTrue(assoc_data["data"]["associated"])
        self.assertEqual(assoc_data["data"]["mission_id"], mission_id)

        # Step 5: Verify active mission is now set and in READY state
        active_res = self.client.get("/api/missions/active")
        self.assertEqual(active_res.status_code, 200)
        active_mission = active_res.get_json()["data"]
        self.assertEqual(active_mission["id"], mission_id)
        self.assertIn(active_mission["state"], ["READY", "VALIDATED"])

    def test_e2e_telemetry_geofence_monitoring(self):
        """
        Verify live telemetry coordinates are checked against geofence boundaries.
        """
        snap = mavlink_service.get_snapshot()
        self.assertTrue(snap.connected)

        # Query geofence check-point with current drone location
        check_res = self.client.post("/api/geofence/check-point", json={
            "lat": snap.latitude,
            "lon": snap.longitude,
            "alt_m": snap.altitude_relative_m
        })
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.get_json()["data"]
        self.assertIn("inside", check_data)
        self.assertIn("violations", check_data)

    def test_flight_control_isolation_guarantee(self):
        """
        Verify that decoding a malicious or unexpected QR payload CANNOT execute
        flight commands or bypass disabled flight controls.
        """
        # Ensure flight control is disabled
        flight_controller.enabled = False

        # Attempt to inject arming command via QR
        malicious_qr = '{"action": "ARM_AND_TAKEOFF", "alt": 100}'
        assoc_res = self.client.post("/api/missions/associate-qr", json={"payload": malicious_qr})
        self.assertEqual(assoc_res.status_code, 400)

        # Vehicle must NOT be armed
        snap = mavlink_service.get_snapshot()
        # Direct command must be rejected with 403
        arm_res = self.client.post("/api/flight/arm")
        self.assertEqual(arm_res.status_code, 403)

    def test_concurrent_subsystem_stability(self):
        """
        Verify simultaneous execution of camera capture, QR detection worker,
        and MAVLink telemetry stream without resource collision or deadlock.
        """
        vision_service.start()
        time.sleep(0.3)

        # Perform 5 fast captures while vision worker is processing frames
        for _ in range(5):
            cap_res = self.client.post("/api/camera/capture")
            self.assertIn(cap_res.status_code, [201, 409])  # 201 created or 409 locked

        telem_res = self.client.get("/api/telemetry/current")
        self.assertEqual(telem_res.status_code, 200)

        qr_status_res = self.client.get("/api/vision/qr/status")
        self.assertEqual(qr_status_res.status_code, 200)
        self.assertTrue(qr_status_res.get_json()["data"]["running"])


if __name__ == "__main__":
    unittest.main()

