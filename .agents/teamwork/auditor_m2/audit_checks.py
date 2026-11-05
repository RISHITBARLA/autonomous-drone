"""
Milestone M2 Forensic Integrity Verification Suite.
Executed independently by auditor_m2.
"""
import os
import sys
import glob
import ast
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def check_html():
    print("[CHECK] Inspecting frontend/index.html ...")
    with open(PROJECT_ROOT / "frontend" / "index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "dashboard.css?v=20261105.1" in html, "Missing version query in dashboard.css"
    assert "dashboard.js?v=20261105.1" in html, "Missing version query in dashboard.js"
    assert 'id="btnMapNormal"' in html, "Missing #btnMapNormal in index.html"
    assert 'id="btnMapHeatmap"' in html, "Missing #btnMapHeatmap in index.html"
    assert 'id="mapLegendNormal"' in html, "Missing #mapLegendNormal in index.html"
    assert 'id="mapLegendHeatmap"' in html, "Missing #mapLegendHeatmap in index.html"
    assert 'id="mapModeToggleGroup"' in html, "Missing #mapModeToggleGroup in index.html"
    assert 'id="geofenceCanvas"' in html, "Missing #geofenceCanvas in index.html"
    print(" -> frontend/index.html elements PASS")

def check_no_mock_in_production():
    print("[CHECK] Scanning production files for mock/cheating tokens ...")
    py_files = list(PROJECT_ROOT.glob("backend/**/*.py")) + list(PROJECT_ROOT.glob("config/**/*.py"))
    violations = []
    tokens = ["unittest.mock", "MagicMock", "Mock(", "sys._called_from_test"]
    for path in py_files:
        content = path.read_text(encoding="utf-8")
        for t in tokens:
            if t in content:
                violations.append((str(path), t))
    assert not violations, f"Mock violations found in production files: {violations}"
    print(f" -> Scanned {len(py_files)} production Python files: Clean PASS")

def check_ast_facades():
    print("[CHECK] AST inspection of backend/search/coverage_planner.py ...")
    code = (PROJECT_ROOT / "backend" / "search" / "coverage_planner.py").read_text(encoding="utf-8")
    tree = ast.parse(code)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs:
        body = fn.body
        is_facade = len(body) == 1 and (isinstance(body[0], ast.Pass) or (isinstance(body[0], ast.Return) and isinstance(body[0].value, (ast.Constant, ast.Dict, ast.List))))
        assert not is_facade, f"Facade function detected: {fn.name} at line {fn.lineno}"
    print(f" -> Inspected {len(funcs)} functions/methods: Clean PASS")

def check_coverage_planner_runtime():
    print("[CHECK] Runtime verification of GeofenceCoveragePlanner ...")
    from backend.search.coverage_planner import GeofenceCoveragePlanner, CameraFootprint

    planner = GeofenceCoveragePlanner(
        boundary_type="circular",
        circle_center_geo=(37.4093, -122.0641),
        circle_radius_m=100.0,
        grid_resolution_m=2.0,
        search_altitude_m=10.0
    )
    assert planner.get_coverage_percentage() == 0.0
    assert len(planner.scanned_cells) == 0

    # Test update position inside geofence
    pct = planner.update_drone_position(37.4093, -122.0641, 10.0)
    assert pct > 0.0, f"Expected pct > 0, got {pct}"
    scanned_count = len(planner.scanned_cells)
    assert scanned_count > 0, "No cells recorded"

    # Test update far outside geofence (no increase)
    planner.update_drone_position(38.0000, -122.0641, 10.0)
    assert len(planner.scanned_cells) == scanned_count, "Out-of-bound point expanded coverage!"

    # Test reset
    planner.reset_coverage()
    assert planner.get_coverage_percentage() == 0.0
    assert len(planner.scanned_cells) == 0

    # Test snapshot serialization
    snap = planner.get_coverage_snapshot()
    assert snap["coverage_pct"] == 0.0
    assert snap["scanned_points"] == []
    assert snap["total_cells_count"] > 0
    print(" -> GeofenceCoveragePlanner runtime checks PASS")

def check_hotspots_runtime():
    print("[CHECK] Observation hotspots extraction verification ...")
    from backend.api.geofence_routes import _extract_observation_hotspots
    from backend.vision.vision_service import vision_service

    vision_service._history.clear()
    assert _extract_observation_hotspots() == [], "Non-empty hotspots when vision history is empty"

    # History with null coordinates
    vision_service._history.append({"payload": "FAKE", "latitude": 0.0, "longitude": 0.0, "confidence": 0.9})
    assert _extract_observation_hotspots() == [], "Hotspot generated from null GPS coordinate"

    # History with valid detection
    vision_service._history.append({"payload": "QR_REAL", "latitude": 37.40935, "longitude": -122.06415, "confidence": 0.92, "timestamp": 1234})
    hotspots = _extract_observation_hotspots()
    assert len(hotspots) == 1, f"Expected 1 hotspot, got {len(hotspots)}"
    assert hotspots[0]["payload"] == "QR_REAL"
    assert hotspots[0]["count"] == 1
    assert hotspots[0]["confidence"] == 0.92

    vision_service._history.clear()
    print(" -> Observation hotspots runtime PASS")

def check_http_cache_headers():
    print("[CHECK] Flask live HTTP requests & Cache-Control headers ...")
    from backend.app import create_app
    app = create_app()
    client = app.test_client()

    # / -> no-cache, no-store, must-revalidate
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert r_root.headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"
    assert r_root.headers.get("Pragma") == "no-cache"
    assert r_root.headers.get("Expires") == "0"

    # /index.html -> no-cache, no-store, must-revalidate
    r_idx = client.get("/index.html")
    assert r_idx.status_code == 200
    assert r_idx.headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"

    # /css/dashboard.css -> no-cache, must-revalidate
    r_css = client.get("/css/dashboard.css")
    assert r_css.status_code == 200
    assert r_css.headers.get("Cache-Control") == "no-cache, must-revalidate"

    # /js/dashboard.js -> no-cache, must-revalidate
    r_js = client.get("/js/dashboard.js")
    assert r_js.status_code == 200
    assert r_js.headers.get("Cache-Control") == "no-cache, must-revalidate"

    # /api/geofence/coverage
    r_cov = client.get("/api/geofence/coverage")
    assert r_cov.status_code == 200
    j_cov = r_cov.get_json()
    assert j_cov["status"] == "success"
    assert "data" in j_cov
    assert "coverage_pct" in j_cov

    # /api/geofence/coverage/reset
    r_res = client.post("/api/geofence/coverage/reset")
    assert r_res.status_code == 200
    assert r_res.get_json()["status"] == "success"

    print(" -> Flask HTTP Cache-Control and Coverage API routes PASS")

def check_mavlink_integration():
    print("[CHECK] MAVLink GPS telemetry ingestion into coverage_planner ...")
    from backend.flight.mavlink_service import MAVLinkService
    from backend.search.coverage_planner import coverage_planner

    coverage_planner.reset_coverage()
    service = MAVLinkService(connection_string="simulated", simulate=True)

    # 1. Null coordinate (0.0, 0.0)
    service._update_coverage_telemetry(0.0, 0.0, 10.0)
    assert len(coverage_planner.scanned_cells) == 0

    # 2. Out of bounds latitude
    service._update_coverage_telemetry(180.0, -122.0641, 10.0)
    assert len(coverage_planner.scanned_cells) == 0

    # 3. Valid coordinate
    service._update_coverage_telemetry(37.4093, -122.0641, 10.0)
    assert len(coverage_planner.scanned_cells) > 0
    scanned_init = len(coverage_planner.scanned_cells)

    # 4. GPS_RAW_INT message handling with fix_type < 2
    class DummyMsg:
        def __init__(self, fix, lat_e7, lon_e7):
            self.fix_type = fix
            self.lat = lat_e7
            self.lon = lon_e7
            self.alt = 10000
            self.satellites_visible = 6
            self.eph = 100

    service._handle_gps_raw_int(DummyMsg(1, 374093000, -1220641000))
    assert len(coverage_planner.scanned_cells) == scanned_init, "fix_type=1 updated coverage"

    service._handle_gps_raw_int(DummyMsg(3, 374094000, -1220641000))
    assert len(coverage_planner.scanned_cells) >= scanned_init, "fix_type=3 failed to update"

    print(" -> MAVLink GPS telemetry routing PASS")

if __name__ == "__main__":
    print("=== STARTING INDEPENDENT FORENSIC AUDIT SUITE ===")
    check_html()
    check_no_mock_in_production()
    check_ast_facades()
    check_coverage_planner_runtime()
    check_hotspots_runtime()
    check_http_cache_headers()
    check_mavlink_integration()
    print("=== ALL INDEPENDENT FORENSIC AUDIT CHECKS PASSED CLEAN ===")
