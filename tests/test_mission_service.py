"""
Comprehensive Unit and Integration tests for Mission Management Subsystem (Milestone 04).
Verifies waypoint validation, FSM state transitions, persistence, QR code payload association,
and REST API endpoints.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.mission.mission_model import Mission, MissionState, Waypoint
from backend.mission.mission_service import MissionService
from backend.app import create_app


class TestMissionModel(unittest.TestCase):
    """Test suite for Waypoint and Mission data models and FSM transitions."""

    def test_waypoint_validation_valid(self):
        """Verify normal waypoint passes validation with zero errors."""
        wp = Waypoint(seq=1, lat=37.4093, lon=-122.0641, alt_m=15.0, speed_m_s=5.0)
        self.assertEqual(wp.validate(), [])

    def test_waypoint_validation_invalid(self):
        """Verify out-of-bound coordinates and negative altitudes flag errors."""
        wp = Waypoint(seq=1, lat=95.0, lon=-190.0, alt_m=-5.0, speed_m_s=-1.0)
        errors = wp.validate()
        self.assertGreaterEqual(len(errors), 4)

    def test_mission_fsm_valid_transitions(self):
        """Verify allowed FSM state progression."""
        mission = Mission(
            id="test-m1",
            name="Test Mission",
            state=MissionState.CREATED,
            waypoints=[Waypoint(seq=1, lat=37.0, lon=-122.0, alt_m=10.0)]
        )
        self.assertTrue(mission.validate())
        self.assertEqual(mission.state, MissionState.VALIDATED)

        # Transition VALIDATED -> READY
        self.assertTrue(mission.transition_to(MissionState.READY))
        self.assertEqual(mission.state, MissionState.READY)

        # Transition READY -> EXECUTING
        self.assertTrue(mission.transition_to(MissionState.EXECUTING))
        self.assertEqual(mission.state, MissionState.EXECUTING)

        # Transition EXECUTING -> PAUSED -> EXECUTING -> COMPLETED
        self.assertTrue(mission.transition_to(MissionState.PAUSED))
        self.assertTrue(mission.transition_to(MissionState.EXECUTING))
        self.assertTrue(mission.transition_to(MissionState.COMPLETED))
        self.assertEqual(mission.state, MissionState.COMPLETED)

    def test_mission_fsm_invalid_transition_raises(self):
        """Verify jumping from CREATED directly to EXECUTING raises ValueError."""
        mission = Mission(
            id="test-m2",
            name="Test Invalid",
            state=MissionState.CREATED,
            waypoints=[Waypoint(seq=1, lat=37.0, lon=-122.0, alt_m=10.0)]
        )
        with self.assertRaises(ValueError):
            mission.transition_to(MissionState.EXECUTING)


class TestMissionService(unittest.TestCase):
    """Test suite for MissionService persistence and QR association."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage_file = self.temp_dir / "test_missions.json"
        self.service = MissionService(storage_path=self.storage_file)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_crud_lifecycle(self):
        """Verify create, get, list, update, and delete."""
        data = {
            "id": "survey-01",
            "name": "Perimeter Survey",
            "waypoints": [
                {"seq": 1, "lat": 37.40, "lon": -122.06, "alt_m": 12.0}
            ]
        }
        # Create
        created = self.service.create_mission(data)
        self.assertEqual(created.id, "survey-01")

        # Get
        fetched = self.service.get_mission("survey-01")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Perimeter Survey")

        # Update
        updated = self.service.update_mission("survey-01", {"name": "Updated Survey"})
        self.assertEqual(updated.name, "Updated Survey")

        # Delete
        self.assertTrue(self.service.delete_mission("survey-01"))
        self.assertIsNone(self.service.get_mission("survey-01"))

    def test_qr_association_structured_prefix(self):
        """Verify payload 'MISSION:patrol-field-alpha' matches and activates the mission."""
        res = self.service.associate_qr_payload("MISSION:patrol-field-alpha")
        self.assertTrue(res["associated"])
        self.assertEqual(res["mission_id"], "patrol-field-alpha")

        active = self.service.get_active_mission()
        self.assertIsNotNone(active)
        self.assertEqual(active.id, "patrol-field-alpha")

    def test_qr_association_json_payload(self):
        """Verify JSON formatted QR code string is parsed safely."""
        qr_str = '{"action": "SELECT_MISSION", "mission_id": "patrol-field-alpha"}'
        res = self.service.associate_qr_payload(qr_str)
        self.assertTrue(res["associated"])
        self.assertEqual(res["mission_id"], "patrol-field-alpha")

    def test_qr_association_malicious_input_safe(self):
        """Verify arbitrary shell injection or script is safely rejected without execution."""
        bad_payloads = [
            "; rm -rf / ;",
            "<script>alert(1)</script>",
            "UNKNOWN_MISSION_XYZ_999",
            "",
            None
        ]
        for bad in bad_payloads:
            res = self.service.associate_qr_payload(bad)
            self.assertFalse(res["associated"])


class TestMissionAPI(unittest.TestCase):
    """Test suite for /api/missions REST endpoints."""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_list_and_get_missions(self):
        """Verify GET /api/missions returns list with default mission."""
        res = self.client.get("/api/missions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["count"], 1)

    def test_create_and_delete_mission(self):
        """Verify POST and DELETE /api/missions."""
        payload = {
            "id": "api-temp-mission",
            "name": "API Test Mission",
            "waypoints": [{"seq": 1, "lat": 37.1, "lon": -122.1, "alt_m": 15.0}]
        }
        create_res = self.client.post("/api/missions", json=payload)
        self.assertEqual(create_res.status_code, 201)

        del_res = self.client.delete("/api/missions/api-temp-mission")
        self.assertEqual(del_res.status_code, 200)

    def test_qr_association_endpoint(self):
        """Verify POST /api/missions/associate-qr."""
        res = self.client.post("/api/missions/associate-qr", json={"payload": "MISSION:patrol-field-alpha"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["data"]["associated"])


if __name__ == "__main__":
    unittest.main()

