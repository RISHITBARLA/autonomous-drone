"""
Mission Data Models and Finite State Machine for AUTONOMOUS-DRONE.
Defines Waypoint, Mission data structures, and strict state transition rules.
"""
import re
import time
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict


class MissionState(str, Enum):
    """Allowed operational states for an autonomous mission."""
    IDLE = "IDLE"
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Explicit state transition graph
ALLOWED_TRANSITIONS: Dict[MissionState, List[MissionState]] = {
    MissionState.IDLE: [MissionState.CREATED],
    MissionState.CREATED: [MissionState.VALIDATED, MissionState.CANCELLED],
    MissionState.VALIDATED: [MissionState.READY, MissionState.CREATED, MissionState.CANCELLED],
    MissionState.READY: [MissionState.EXECUTING, MissionState.VALIDATED, MissionState.CANCELLED],
    MissionState.EXECUTING: [MissionState.PAUSED, MissionState.COMPLETED, MissionState.FAILED, MissionState.CANCELLED],
    MissionState.PAUSED: [MissionState.EXECUTING, MissionState.CANCELLED, MissionState.FAILED],
    MissionState.COMPLETED: [MissionState.IDLE, MissionState.READY],
    MissionState.FAILED: [MissionState.IDLE, MissionState.VALIDATED],
    MissionState.CANCELLED: [MissionState.IDLE, MissionState.CREATED]
}


@dataclass
class Waypoint:
    """Individual navigation waypoint in a drone mission."""
    seq: int
    lat: float
    lon: float
    alt_m: float
    speed_m_s: float = 5.0
    hold_time_s: float = 0.0
    action: str = "WAYPOINT"  # "WAYPOINT", "LOITER", "LAND", "TAKEOFF", "RTL"

    def validate(self) -> List[str]:
        """Validate coordinate ranges and physical plausibility."""
        errors: List[str] = []
        if not (-90.0 <= self.lat <= 90.0):
            errors.append(f"Waypoint {self.seq}: Latitude {self.lat} outside valid [-90, 90] range")
        if not (-180.0 <= self.lon <= 180.0):
            errors.append(f"Waypoint {self.seq}: Longitude {self.lon} outside valid [-180, 180] range")
        if self.alt_m <= 0.0 or self.alt_m > 500.0:
            errors.append(f"Waypoint {self.seq}: Altitude {self.alt_m}m outside safe operating envelope (0 - 500m)")
        if self.speed_m_s <= 0.0 or self.speed_m_s > 25.0:
            errors.append(f"Waypoint {self.seq}: Speed {self.speed_m_s}m/s outside safe limit (0.1 - 25m/s)")
        if self.hold_time_s < 0.0:
            errors.append(f"Waypoint {self.seq}: Hold time cannot be negative")
        return errors


@dataclass
class Mission:
    """Complete autonomous mission record with waypoint sequence and lifecycle state."""
    id: str
    name: str
    description: str = ""
    state: MissionState = MissionState.CREATED
    waypoints: List[Waypoint] = field(default_factory=list)
    geofence_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Mission":
        """Deserialize mission from dictionary or JSON payload."""
        waypoints = [
            Waypoint(
                seq=w.get("seq", i + 1),
                lat=float(w["lat"]),
                lon=float(w["lon"]),
                alt_m=float(w["alt_m"]),
                speed_m_s=float(w.get("speed_m_s", 5.0)),
                hold_time_s=float(w.get("hold_time_s", 0.0)),
                action=str(w.get("action", "WAYPOINT"))
            )
            for i, w in enumerate(data.get("waypoints", []))
        ]

        state_str = data.get("state", MissionState.CREATED.value)
        try:
            state = MissionState(state_str)
        except ValueError:
            state = MissionState.CREATED

        return cls(
            id=str(data["id"]).strip(),
            name=str(data.get("name", "Unnamed Mission")).strip(),
            description=str(data.get("description", "")),
            state=state,
            waypoints=waypoints,
            geofence_id=data.get("geofence_id"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            state_history=data.get("state_history", []),
            validation_errors=data.get("validation_errors", [])
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert mission to JSON-serializable dictionary."""
        data = asdict(self)
        data["state"] = self.state.value
        return data

    def validate(self) -> bool:
        """Validate mission parameters and all constituent waypoints."""
        self.validation_errors.clear()

        # Identifier sanitization
        if not self.id or not re.match(r"^[a-zA-Z0-9_\-]+$", self.id):
            self.validation_errors.append("Mission ID must be alphanumeric and contain no spaces or special characters")

        if not self.name:
            self.validation_errors.append("Mission name cannot be empty")

        if len(self.waypoints) == 0:
            self.validation_errors.append("Mission must contain at least 1 valid waypoint")

        for wp in self.waypoints:
            self.validation_errors.extend(wp.validate())

        is_valid = len(self.validation_errors) == 0
        if is_valid and self.state == MissionState.CREATED:
            self.state = MissionState.VALIDATED
            self._record_state_change(MissionState.VALIDATED, "Automatic validation pass")

        self.updated_at = datetime.now().isoformat()
        return is_valid

    def can_transition_to(self, target_state: MissionState) -> bool:
        """Check if transition from current state to target state is permissible."""
        allowed = ALLOWED_TRANSITIONS.get(self.state, [])
        return target_state in allowed

    def transition_to(self, target_state: MissionState, reason: str = "") -> bool:
        """
        Safely execute a state machine transition.

        Raises:
            ValueError: If transition violates the allowed state graph.
        """
        if not self.can_transition_to(target_state):
            raise ValueError(
                f"Invalid state transition: Cannot transition from {self.state.value} to {target_state.value}. "
                f"Allowed target states: {[s.value for s in ALLOWED_TRANSITIONS.get(self.state, [])]}"
            )

        # Transition logic
        old_state = self.state
        self.state = target_state
        self.updated_at = datetime.now().isoformat()
        self._record_state_change(target_state, reason)
        return True

    def _record_state_change(self, state: MissionState, reason: str) -> None:
        self.state_history.append({
            "timestamp": time.time(),
            "iso_time": datetime.now().isoformat(),
            "state": state.value,
            "reason": reason
        })

