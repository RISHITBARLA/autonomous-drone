"""
Mission Management Service for AUTONOMOUS-DRONE.
Provides thread-safe persistence, CRUD operations, state machine coordination,
and secure QR payload association.
"""
import json
import re
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from config.settings import settings
from config.logging_config import setup_logging
from .mission_model import Mission, MissionState

logger = setup_logging("mission_service")


class MissionService:
    """Coordinates storage, state transitions, and QR association for autonomous missions."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or settings.MISSIONS_FILE
        self._lock = threading.Lock()
        self._missions: Dict[str, Mission] = {}
        self._active_mission_id: Optional[str] = None

        self._load_missions()

    def _load_missions(self) -> None:
        """Load persisted missions from JSON storage."""
        if not self.storage_path.exists():
            # Populate with a default reference mission if empty
            self._create_default_reference_mission()
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                with self._lock:
                    self._missions.clear()
                    for m_dict in raw_list:
                        try:
                            mission = Mission.from_dict(m_dict)
                            self._missions[mission.id] = mission
                        except Exception as e:
                            logger.error("Failed deserializing mission entry: %s", e)
            logger.info("Loaded %d missions from %s", len(self._missions), self.storage_path)
        except Exception as e:
            logger.error("Failed loading missions file: %s; creating default", e)
            self._create_default_reference_mission()

    def _save_missions(self) -> None:
        """Persist missions to disk atomically."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                serialized = [m.to_dict() for m in self._missions.values()]

            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2)
            temp_path.replace(self.storage_path)
        except Exception as e:
            logger.error("Failed persisting missions to %s: %s", self.storage_path, e)

    def _create_default_reference_mission(self) -> None:
        """Create initial sample mission for testing."""
        default_data = {
            "id": "patrol-field-alpha",
            "name": "Alpha Field Patrol",
            "description": "Autonomous perimeter scan with QR target detection.",
            "waypoints": [
                {"seq": 1, "lat": 37.4093, "lon": -122.0641, "alt_m": 15.0, "action": "TAKEOFF"},
                {"seq": 2, "lat": 37.4098, "lon": -122.0635, "alt_m": 20.0, "action": "WAYPOINT"},
                {"seq": 3, "lat": 37.4092, "lon": -122.0632, "alt_m": 20.0, "action": "LOITER", "hold_time_s": 5.0},
                {"seq": 4, "lat": 37.4093, "lon": -122.0641, "alt_m": 15.0, "action": "RTL"}
            ]
        }
        mission = Mission.from_dict(default_data)
        mission.validate()
        with self._lock:
            self._missions[mission.id] = mission
            self._active_mission_id = mission.id
        self._save_missions()

    def create_mission(self, data: Dict[str, Any]) -> Mission:
        """Create, validate, and store a new mission."""
        mission_id = str(data.get("id", "")).strip()
        if not mission_id:
            raise ValueError("Mission ID is required")

        with self._lock:
            if mission_id in self._missions:
                raise ValueError(f"Mission with ID '{mission_id}' already exists")

        mission = Mission.from_dict(data)
        mission.validate()

        with self._lock:
            self._missions[mission.id] = mission

        self._save_missions()
        logger.info("Created mission '%s' (%s)", mission.id, mission.name)
        return mission

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """Retrieve mission by identifier."""
        with self._lock:
            return self._missions.get(mission_id)

    def list_missions(self) -> List[Mission]:
        """List all stored missions."""
        with self._lock:
            return list(self._missions.values())

    def update_mission(self, mission_id: str, updates: Dict[str, Any]) -> Optional[Mission]:
        """Update existing mission details and waypoints."""
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission:
                return None

            if "name" in updates:
                mission.name = str(updates["name"]).strip()
            if "description" in updates:
                mission.description = str(updates["description"])
            if "geofence_id" in updates:
                mission.geofence_id = updates["geofence_id"]
            if "waypoints" in updates:
                temp_dict = mission.to_dict()
                temp_dict["waypoints"] = updates["waypoints"]
                updated = Mission.from_dict(temp_dict)
                mission.waypoints = updated.waypoints

            mission.validate()

        self._save_missions()
        return mission

    def delete_mission(self, mission_id: str) -> bool:
        """Remove a mission from storage."""
        with self._lock:
            if mission_id not in self._missions:
                return False
            del self._missions[mission_id]
            if self._active_mission_id == mission_id:
                self._active_mission_id = None

        self._save_missions()
        logger.info("Deleted mission '%s'", mission_id)
        return True

    def set_mission_state(self, mission_id: str, target_state: MissionState, reason: str = "") -> Mission:
        """Transition mission state through the FSM."""
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission:
                raise KeyError(f"Mission '{mission_id}' not found")

            mission.transition_to(target_state, reason=reason)

        self._save_missions()
        return mission

    def get_active_mission(self) -> Optional[Mission]:
        """Return currently selected active mission."""
        with self._lock:
            if self._active_mission_id:
                return self._missions.get(self._active_mission_id)
            return None

    def set_active_mission(self, mission_id: str) -> Optional[Mission]:
        """Select active mission."""
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission:
                return None
            self._active_mission_id = mission_id
            return mission

    def associate_qr_payload(self, qr_text: str) -> Dict[str, Any]:
        """
        Safely parse a decoded QR payload and associate with a pre-configured mission.

        SECURITY GUARANTEE:
        Arbitrary shell or flight commands embedded in QR strings are NEVER executed.
        Only recognized, pre-validated mission identifiers will be loaded.
        """
        if not qr_text or not isinstance(qr_text, str):
            return {"associated": False, "reason": "Empty or non-string QR payload"}

        clean_text = qr_text.strip()
        matched_id: Optional[str] = None

        # Pattern 1: Structured prefix "MISSION:<id>" or "MISSION_ID=<id>"
        match = re.search(r"MISSION[:=]\s*([a-zA-Z0-9_\-]+)", clean_text, re.IGNORECASE)
        if match:
            matched_id = match.group(1).lower()

        # Pattern 2: JSON payload {"action": "SELECT_MISSION", "mission_id": "..."}
        if not matched_id and (clean_text.startswith("{") and clean_text.endswith("}")):
            try:
                parsed = json.loads(clean_text)
                if isinstance(parsed, dict) and "mission_id" in parsed:
                    matched_id = str(parsed["mission_id"]).strip().lower()
            except Exception:
                pass

        # Pattern 3: Direct match against existing mission IDs
        if not matched_id:
            with self._lock:
                for mid in self._missions:
                    if mid.lower() == clean_text.lower():
                        matched_id = mid
                        break

        if not matched_id:
            return {
                "associated": False,
                "reason": f"QR payload '{clean_text}' does not correspond to a valid mission pattern"
            }

        # Check if mission exists
        with self._lock:
            target_mission = None
            for mid, m in self._missions.items():
                if mid.lower() == matched_id.lower():
                    target_mission = m
                    break

        if not target_mission:
            return {
                "associated": False,
                "mission_id": matched_id,
                "reason": f"Mission '{matched_id}' identified by QR code was not found in storage"
            }

        # Validate target mission
        if not target_mission.validate():
            return {
                "associated": False,
                "mission_id": matched_id,
                "reason": f"Mission '{matched_id}' failed validation checks: {target_mission.validation_errors}"
            }

        # Set as active mission
        self.set_active_mission(target_mission.id)

        # Transition to READY if in VALIDATED state
        if target_mission.state == MissionState.VALIDATED:
            target_mission.transition_to(MissionState.READY, reason="Selected via verified QR payload")
            self._save_missions()

        logger.info("QR Code successfully associated with mission '%s'", target_mission.id)
        return {
            "associated": True,
            "mission_id": target_mission.id,
            "mission": target_mission.to_dict(),
            "reason": "Mission loaded and validated successfully from QR code"
        }


# Global singleton instance
mission_service = MissionService()

