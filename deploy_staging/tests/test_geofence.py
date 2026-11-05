"""
Automated tests for Geofence Boundary and Navigation Planning Subsystem.
Encompasses Haversine distance, ray-casting point-in-polygon, geofence services,
REST APIs, coverage planning algorithms, and MAVLink GPS integration.
"""
import unittest

from tests.test_geofence_service import (
    TestGeofenceAlgorithms,
    TestGeofenceService,
    TestGeofenceAPI,
    TestCoveragePlannerModel,
    TestMAVLinkCoverageIntegration,
)

__all__ = [
    "TestGeofenceAlgorithms",
    "TestGeofenceService",
    "TestGeofenceAPI",
    "TestCoveragePlannerModel",
    "TestMAVLinkCoverageIntegration",
]

if __name__ == "__main__":
    unittest.main()

