"""
Adversarial Stress Test Harness 3: Concurrency Locking and Operator Authorization
Challenger 2 (Milestone M1)
Tests:
1. Concurrent arming lock contention: simultaneous requests to request_arm() trigger HTTP 409 / COMMAND_IN_PROGRESS.
2. Thread safety under concurrent load (multiple worker threads bombarding flight endpoints).
3. Operator authorization: OPERATOR_TOKEN enforcement on /api/flight/arm and /api/flight/disarm.
4. Authorization audit: check which flight endpoints enforce vs omit _check_operator_auth.
"""
import os
import sys
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.flight.flight_controller import FlightController, flight_controller
from backend.flight.mavlink_service import mavlink_service
from backend.app import create_app


class StressTestConcurrencyAndAuth(unittest.TestCase):
    """Stress testing concurrent locking and operator authorization."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Telemetry mock state
        mavlink_service.simulate = True
        mavlink_service._connected = True
        mavlink_service._armed = False
        mavlink_service._last_heartbeat = time.time()
        mavlink_service._flight_mode = "ALT_HOLD"

        self._orig_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        flight_controller.enabled = False
        mavlink_service.stop()

    # --- 1. Concurrency Locking on request_arm ---
    def test_concurrent_request_arm_rejects_second_command(self):
        """Verify that when action is in progress, simultaneous request_arm returns COMMAND_IN_PROGRESS."""
        fc = FlightController(enabled=True)

        results = []
        started_event = threading.Event()
        release_event = threading.Event()

        orig_snapshot = mavlink_service.get_snapshot

        def delayed_snapshot():
            started_event.set()
            release_event.wait(timeout=2.0)
            return orig_snapshot()

        def slow_arm():
            with patch.object(mavlink_service, "get_snapshot", side_effect=delayed_snapshot):
                res = fc.request_arm(arm=True, confirm=True)
                results.append(("slow", res))

        def fast_arm():
            started_event.wait(timeout=2.0)
            time.sleep(0.02)  # ensure slow_arm is inside lock
            res = fc.request_arm(arm=True, confirm=True)
            results.append(("fast", res))
            release_event.set()

        t1 = threading.Thread(target=slow_arm)
        t2 = threading.Thread(target=fast_arm)

        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        res_map = dict(results)
        self.assertIn("fast", res_map, "Fast thread did not complete")
        self.assertFalse(res_map["fast"]["success"], f"Fast command should fail: {res_map['fast']}")
        self.assertEqual(res_map["fast"]["code"], "COMMAND_IN_PROGRESS")
        self.assertIn("currently executing", res_map["fast"]["message"])

    def test_http_arm_endpoint_concurrency_returns_409(self):
        """Verify that HTTP POST /api/flight/arm returns 409 Conflict when concurrent arm is running."""
        flight_controller.enabled = True

        responses = []
        started_event = threading.Event()
        release_event = threading.Event()

        orig_snapshot = mavlink_service.get_snapshot

        def delayed_snapshot():
            started_event.set()
            release_event.wait(timeout=2.0)
            return orig_snapshot()

        def slow_req():
            with patch.object(mavlink_service, "get_snapshot", side_effect=delayed_snapshot):
                with self.app.test_client() as c:
                    r = c.post("/api/flight/arm", json={"confirm": True})
                    responses.append(("slow", r.status_code, r.get_json()))

        def fast_req():
            started_event.wait(timeout=2.0)
            time.sleep(0.02)
            with self.app.test_client() as c:
                r = c.post("/api/flight/arm", json={"confirm": True})
                responses.append(("fast", r.status_code, r.get_json()))
            release_event.set()

        t1 = threading.Thread(target=slow_req)
        t2 = threading.Thread(target=fast_req)

        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        res_dict = {k: (code, data) for k, code, data in responses}
        self.assertIn("fast", res_dict, "Fast HTTP request did not complete")
        fast_code, fast_data = res_dict["fast"]
        self.assertEqual(fast_code, 409, f"Expected HTTP 409 for concurrent arming, got {fast_code}: {fast_data}")
        self.assertEqual(fast_data.get("code"), "COMMAND_IN_PROGRESS")

    def test_high_concurrency_flood_on_flight_controller(self):
        """Flood FlightController with 50 concurrent threads to ensure no deadlocks or corruption."""
        fc = FlightController(enabled=True)
        call_count = 50
        results = []

        def worker(idx):
            cmd_type = idx % 3
            if cmd_type == 0:
                res = fc.request_arm(arm=True, confirm=True)
            elif cmd_type == 1:
                res = fc.request_mode("ALT_HOLD")
            else:
                res = fc.get_status()
            results.append((cmd_type, res))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(call_count)]
            for f in futures:
                f.result()

        self.assertEqual(len(results), call_count)
        self.assertFalse(fc._action_in_progress)
        status = fc.get_status()
        self.assertIsInstance(status, dict)

    # --- 2. Operator Authorization (OPERATOR_TOKEN) ---
    def test_operator_token_unauthorized_rejection(self):
        """When OPERATOR_TOKEN is set, requests without matching token are rejected with HTTP 401."""
        test_token = "secure-pilot-credential-xyz-1234"
        os.environ["OPERATOR_TOKEN"] = test_token

        # 1. Missing token
        r_arm_missing = self.client.post("/api/flight/arm", json={"confirm": True})
        self.assertEqual(r_arm_missing.status_code, 401)
        self.assertEqual(r_arm_missing.get_json()["code"], "UNAUTHORIZED")

        r_disarm_missing = self.client.post("/api/flight/disarm", json={"confirm": True})
        self.assertEqual(r_disarm_missing.status_code, 401)
        self.assertEqual(r_disarm_missing.get_json()["code"], "UNAUTHORIZED")

        # 2. Invalid token in header
        r_arm_bad_hdr = self.client.post("/api/flight/arm", json={"confirm": True}, headers={"X-Operator-Token": "bad-token"})
        self.assertEqual(r_arm_bad_hdr.status_code, 401)

        # 3. Invalid token in JSON body
        r_arm_bad_body = self.client.post("/api/flight/arm", json={"confirm": True, "operator_token": "wrong-body-token"})
        self.assertEqual(r_arm_bad_body.status_code, 401)

        # 4. Valid token in header (passes auth, hits CONTROL_DISABLED -> 403)
        flight_controller.enabled = False
        r_arm_valid_hdr = self.client.post("/api/flight/arm", json={"confirm": True}, headers={"X-Operator-Token": test_token})
        self.assertEqual(r_arm_valid_hdr.status_code, 403, f"Expected 403 (control disabled) after valid auth, got {r_arm_valid_hdr.status_code}")

        # 5. Valid token in JSON body
        r_arm_valid_body = self.client.post("/api/flight/arm", json={"confirm": True, "operator_token": test_token})
        self.assertEqual(r_arm_valid_body.status_code, 403)

    def test_operator_token_audit_across_all_endpoints(self):
        """Audit which endpoints enforce OPERATOR_TOKEN vs which omit it."""
        test_token = "secure-pilot-token"
        os.environ["OPERATOR_TOKEN"] = test_token
        flight_controller.enabled = False

        endpoints_under_test = [
            ("POST", "/api/flight/arm", {"confirm": True}),
            ("POST", "/api/flight/disarm", {"confirm": True}),
            ("POST", "/api/flight/mode", {"mode": "ALT_HOLD"}),
            ("POST", "/api/flight/takeoff", {"altitude_m": 5.0}),
            ("POST", "/api/flight/rtl", {}),
            ("POST", "/api/flight/land", {}),
            ("POST", "/api/flight/disable-arming-checks", {}),
            ("POST", "/api/flight/enable-arming-checks", {}),
            ("POST", "/api/flight/connect", {}),
            ("POST", "/api/flight/disconnect", {}),
        ]

        auth_enforced = []
        auth_omitted = []

        for method, url, payload in endpoints_under_test:
            resp = self.client.post(url, json=payload)
            if resp.status_code == 401:
                auth_enforced.append(url)
            else:
                auth_omitted.append((url, resp.status_code))

        print("\n--- OPERATOR_TOKEN AUDIT RESULTS ---")
        print("Endpoints ENFORCING OPERATOR_TOKEN (HTTP 401 without token):")
        for ep in auth_enforced:
            print(f"  [ENFORCED] {ep}")
        print("Endpoints OMITTING OPERATOR_TOKEN (do not return 401):")
        for ep, status in auth_omitted:
            print(f"  [OMITTED]  {ep} (HTTP {status})")

        self.assertIn("/api/flight/arm", auth_enforced)
        self.assertIn("/api/flight/disarm", auth_enforced)


if __name__ == "__main__":
    unittest.main()

