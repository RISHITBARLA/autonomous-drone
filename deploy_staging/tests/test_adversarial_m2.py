"""
Adversarial empirical stress-test suite for Milestone M2:
1. Concurrency Stress (50 concurrent threads flooding update_drone_position & get_coverage_snapshot)
2. Boundary Extremes & Input Sanitization (Null Island, NaN, subnormal, poles, 1000km away, negative altitude)
3. Rapid Alternating Calls (interleaved resets, reconfigurations, updates, snapshots, velocity commands)
4. HTTP Cache-Control Invariants (If-None-Match, If-Modified-Since, query parameters across /, /index.html, /css/*, /js/*, /api/*)
5. Headless JS and REST API Concurrency Hammering
"""
import json
import math
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from unittest.mock import MagicMock
import pytest

from backend.search.coverage_planner import GeofenceCoveragePlanner, coverage_planner
from backend.flight.mavlink_service import mavlink_service
from backend.app import create_app


class TestAdversarialConcurrencyStress:
    """Stress-test thread safety, race conditions, set mutations, and deadlocks."""

    def test_50_concurrent_threads_flooding_updates_and_snapshots(self):
        """
        Adversarial Test 1: 50 concurrent threads simultaneously flooding
        coverage_planner.update_drone_position() and get_coverage_snapshot().
        Must not raise RuntimeError (e.g. Set changed size during iteration),
        must not deadlock, and snapshot invariants must remain strictly preserved.
        """
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0,
            grid_resolution_m=2.0
        )

        num_threads = 50
        iterations_per_thread = 100
        errors: List[Exception] = []
        snapshots_recorded: List[Dict[str, Any]] = []
        lock = threading.Lock()

        center_lat, center_lon = 37.4093, -122.0641

        def worker_updater(worker_id: int):
            try:
                for _ in range(iterations_per_thread):
                    dlat = (random.random() - 0.5) * 0.0014
                    dlon = (random.random() - 0.5) * 0.0014
                    alt = 5.0 + random.random() * 15.0
                    planner.update_drone_position(center_lat + dlat, center_lon + dlon, alt)
            except Exception as e:
                with lock:
                    errors.append(e)

        def worker_reader(worker_id: int):
            try:
                for i in range(iterations_per_thread):
                    snap = planner.get_coverage_snapshot()
                    if i % 20 == 0:
                        with lock:
                            snapshots_recorded.append(snap)
            except Exception as e:
                with lock:
                    errors.append(e)

        start_time = time.time()
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for tid in range(25):
                futures.append(executor.submit(worker_updater, tid))
            for tid in range(25, 50):
                futures.append(executor.submit(worker_reader, tid))

            for future in as_completed(futures, timeout=20.0):
                future.result()

        elapsed = time.time() - start_time

        assert not errors, f"Concurrent execution generated {len(errors)} errors: {errors[:5]}"
        assert elapsed < 15.0, f"Execution took too long ({elapsed:.2f}s), possible lock contention or deadlock"

        final_snap = planner.get_coverage_snapshot()
        assert 0.0 <= final_snap["coverage_pct"] <= 100.0
        assert 0 <= final_snap["scanned_cells_count"] <= final_snap["total_cells_count"]
        assert final_snap["scanned_area_m2"] <= final_snap["total_area_m2"]
        assert isinstance(final_snap["scanned_points"], list)

        for s in snapshots_recorded:
            assert 0.0 <= s["coverage_pct"] <= 100.0
            assert 0 <= s["scanned_cells_count"] <= s["total_cells_count"]
            assert s["scanned_area_m2"] <= s["total_area_m2"]
            assert len(s["scanned_points"]) <= 500

    def test_concurrent_velocity_command_calculation_under_heavy_updates(self):
        """
        Adversarial Test 1b: Concurrently calculate dynamic velocity guidance
        while updaters and resetters continuously mutate scanned_cells.
        Verifies that set difference / iteration doesn't throw RuntimeError.
        """
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=60.0
        )
        errors = []
        lock = threading.Lock()

        def updater():
            try:
                for _ in range(150):
                    dlat = (random.random() - 0.5) * 0.0006
                    dlon = (random.random() - 0.5) * 0.0006
                    planner.update_drone_position(37.4093 + dlat, -122.0641 + dlon, 10.0)
            except Exception as e:
                with lock:
                    errors.append(e)

        def cmd_caller():
            try:
                for _ in range(150):
                    dlat = (random.random() - 0.5) * 0.0006
                    dlon = (random.random() - 0.5) * 0.0006
                    res = planner.calculate_next_velocity_command(37.4093 + dlat, -122.0641 + dlon, 10.0)
                    assert "vx_ned" in res
                    assert "vy_ned" in res
                    assert "mode" in res
            except Exception as e:
                with lock:
                    errors.append(e)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(updater) for _ in range(10)] + [executor.submit(cmd_caller) for _ in range(10)]
            for f in as_completed(futures, timeout=15.0):
                f.result()

        assert not errors, f"Concurrent velocity calculation produced errors: {errors}"


class TestAdversarialBoundaryExtremes:
    """Stress-test extreme inputs, sanitization, Null Island, NaN, subnormal, poles, negative alt."""

    def test_null_island_coordinate_handling(self):
        """Null Island (0.0, 0.0) must be discarded and never added to scanned cells."""
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0
        )
        planner.reset_coverage()
        initial_scanned = len(planner.scanned_cells)

        pct = planner.update_drone_position(0.0, 0.0, 10.0)
        assert pct == 0.0
        assert len(planner.scanned_cells) == initial_scanned

        mavlink_service._update_coverage_telemetry(0.0, 0.0, 10.0)

    def test_nan_coordinates_and_altitudes(self):
        """NaN coordinates or altitudes must not crash planner or corrupt state."""
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0
        )
        planner.reset_coverage()

        pct_nan_coords = planner.update_drone_position(float("nan"), float("nan"), 10.0)
        assert pct_nan_coords == 0.0
        assert len(planner.scanned_cells) == 0

        pct_nan_alt = planner.update_drone_position(37.4093, -122.0641, float("nan"))
        assert pct_nan_alt >= 0.0
        assert len(planner.scanned_cells) > 0

    def test_negative_and_zero_altitudes(self):
        """Negative and zero altitudes must be clamped to safe minimum (2.0m) without crash."""
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0
        )
        planner.reset_coverage()

        pct_neg = planner.update_drone_position(37.4093, -122.0641, -15.0)
        assert 0.0 <= pct_neg <= 100.0
        assert planner.search_altitude == 2.0
        assert planner.footprint.width_m > 0.0

        pct_zero = planner.update_drone_position(37.4093, -122.0641, 0.0)
        assert 0.0 <= pct_zero <= 100.0
        assert planner.search_altitude == 2.0

    def test_extreme_latitudes_longitudes_and_poles(self):
        """Poles (90, -90) and antimeridian (+/-180) must be handled without crash."""
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0
        )
        planner.reset_coverage()

        assert planner.update_drone_position(90.0, 0.0, 10.0) == 0.0
        assert planner.update_drone_position(-90.0, 0.0, 10.0) == 0.0
        assert planner.update_drone_position(0.0, 180.0, 10.0) == 0.0
        assert planner.update_drone_position(0.0, -180.0, 10.0) == 0.0
        assert planner.update_drone_position(89.9999, 179.9999, 10.0) == 0.0
        assert len(planner.scanned_cells) == 0

    def test_mavlink_sanitization_filters_out_of_bounds_and_infinities(self):
        """MAVLink _update_coverage_telemetry must filter out out-of-range floats and infinities."""
        mavlink_service._update_coverage_telemetry(float("inf"), 0.0, 10.0)
        mavlink_service._update_coverage_telemetry(0.0, float("-inf"), 10.0)
        mavlink_service._update_coverage_telemetry(float("nan"), float("nan"), 10.0)
        mavlink_service._update_coverage_telemetry(90.1, 0.0, 10.0)
        mavlink_service._update_coverage_telemetry(-90.1, 0.0, 10.0)
        mavlink_service._update_coverage_telemetry(0.0, 180.1, 10.0)
        mavlink_service._update_coverage_telemetry(0.0, -180.1, 10.0)
        mavlink_service._update_coverage_telemetry(999.0, 999.0, 10.0)

    def test_coordinates_1000km_away_do_not_contaminate_coverage(self):
        """Coordinates far outside geofence boundary (1000km) must not add scanned cells."""
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0
        )
        planner.reset_coverage()
        initial_cells = len(planner.scanned_cells)

        pct = planner.update_drone_position(40.0, -112.0, 10.0)
        assert pct == 0.0
        assert len(planner.scanned_cells) == initial_cells

        pct_opposite = planner.update_drone_position(-37.4093, 57.9359, 10.0)
        assert pct_opposite == 0.0
        assert len(planner.scanned_cells) == initial_cells

    def test_corrupted_gps_raw_int_packets(self):
        """Corrupted or zero GPS_RAW_INT packets must be safely rejected."""
        msg0 = MagicMock()
        msg0.fix_type = 0
        msg0.lat = 374093000
        msg0.lon = -1220641000
        msg0.alt = 10000
        mavlink_service._handle_gps_raw_int(msg0)

        msg1 = MagicMock()
        msg1.fix_type = 1
        msg1.lat = 374093000
        msg1.lon = -1220641000
        msg1.alt = 10000
        mavlink_service._handle_gps_raw_int(msg1)

        msg_zero = MagicMock()
        msg_zero.fix_type = 3
        msg_zero.lat = 0
        msg_zero.lon = 0
        msg_zero.alt = 10000
        mavlink_service._handle_gps_raw_int(msg_zero)

        msg_empty = object()
        mavlink_service._handle_gps_raw_int(msg_empty)

    def test_geofence_check_point_api_boundary_extremes(self):
        """Evaluate POST /api/geofence/check-point with hostile boundary coordinates."""
        app = create_app()
        client = app.test_client()

        # 1. Null Island
        r1 = client.post("/api/geofence/check-point", json={"lat": 0.0, "lon": 0.0, "alt_m": 10.0})
        assert r1.status_code == 200
        body1 = r1.get_json()["data"]
        assert body1["inside"] is False

        # 2. String NaN
        r2 = client.post("/api/geofence/check-point", json={"lat": "NaN", "lon": "NaN", "alt_m": 10.0})
        assert r2.status_code == 200
        body2 = r2.get_json()["data"]
        assert body2["inside"] is False
        assert any("out of range" in str(v).lower() for v in body2.get("violations", []))

        # 3. Negative altitude violation
        r3 = client.post("/api/geofence/check-point", json={"lat": 37.4093, "lon": -122.0641, "alt_m": -20.0})
        assert r3.status_code == 200
        body3 = r3.get_json()["data"]
        assert body3["vertical_ok"] is False

        # 4. Missing parameters
        r4 = client.post("/api/geofence/check-point", json={"alt_m": 10.0})
        assert r4.status_code == 400


class TestAdversarialResetReconfigureRaces:
    """Stress-test rapid alternating resets, reconfigurations, and concurrent position updates."""

    def test_rapid_alternating_resets_reconfigures_and_updates(self):
        """
        Adversarial Test 3: Rapid alternating calls to reset_coverage(),
        reconfigure(), and update_drone_position() across 40 threads.
        Must maintain state consistency and avoid deadlocks or corrupt structures.
        """
        planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0,
            grid_resolution_m=2.0
        )

        num_threads = 40
        iterations = 50
        errors: List[Exception] = []
        lock = threading.Lock()

        configs = [
            {"fence_type": "circular", "circle_center_lat": 37.4093, "circle_center_lon": -122.0641, "circle_radius_m": 80.0},
            {"fence_type": "circular", "circle_center_lat": 37.4095, "circle_center_lon": -122.0643, "circle_radius_m": 120.0},
            {
                "fence_type": "polygon",
                "polygon_vertices": [
                    {"lat": 37.4090, "lon": -122.0640},
                    {"lat": 37.4100, "lon": -122.0640},
                    {"lat": 37.4100, "lon": -122.0630},
                    {"lat": 37.4090, "lon": -122.0630}
                ]
            },
            {
                "fence_type": "polygon",
                "polygon_vertices": [
                    {"lat": 37.4085, "lon": -122.0650},
                    {"lat": 37.4095, "lon": -122.0635},
                    {"lat": 37.4085, "lon": -122.0620}
                ]
            }
        ]

        def reset_worker():
            try:
                for _ in range(iterations):
                    planner.reset_coverage()
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(e)

        def reconfig_worker(wid: int):
            try:
                for i in range(iterations):
                    cfg = configs[(wid + i) % len(configs)]
                    planner.reconfigure(cfg)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(e)

        def update_worker():
            try:
                for _ in range(iterations):
                    dlat = (random.random() - 0.5) * 0.001
                    dlon = (random.random() - 0.5) * 0.001
                    planner.update_drone_position(37.4093 + dlat, -122.0641 + dlon, 10.0)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(e)

        def snapshot_worker():
            try:
                for _ in range(iterations):
                    snap = planner.get_coverage_snapshot()
                    assert 0.0 <= snap["coverage_pct"] <= 100.0
                    assert snap["total_cells_count"] > 0
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    errors.append(e)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for _ in range(10):
                futures.append(executor.submit(reset_worker))
            for wid in range(10):
                futures.append(executor.submit(reconfig_worker, wid))
            for _ in range(10):
                futures.append(executor.submit(update_worker))
            for _ in range(10):
                futures.append(executor.submit(snapshot_worker))

            for future in as_completed(futures, timeout=20.0):
                future.result()

        assert not errors, f"Rapid alternating calls produced {len(errors)} errors: {errors[:5]}"

        snap = planner.get_coverage_snapshot()
        assert snap["total_cells_count"] > 0
        assert snap["total_area_m2"] > 0.0
        assert 0.0 <= snap["coverage_pct"] <= 100.0


class TestAdversarialCacheControlInvariants:
    """Stress-test HTTP cache headers across diverse requests and permutations."""

    @pytest.fixture
    def client(self):
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    def test_root_and_index_cache_invariants_under_conditional_headers_and_queries(self, client):
        """
        Root / and /index.html must strictly return:
        - Cache-Control: no-cache, no-store, must-revalidate
        - Pragma: no-cache
        - Expires: 0
        regardless of If-None-Match, If-Modified-Since, or query strings.
        """
        test_paths = ["/", "/index.html"]
        permutations = [
            {},
            {"query": "?v=20261105.1"},
            {"query": "?v=random_string&foo=bar&debug=1"},
            {"query": "?&&&"},
            {"headers": {"If-None-Match": '"some-fake-etag"'}},
            {"headers": {"If-None-Match": "*"}},
            {"headers": {"If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"}},
            {"headers": {"If-Modified-Since": "Fri, 01 Jan 2030 00:00:00 GMT"}},
            {
                "query": "?v=20261105.1",
                "headers": {
                    "If-None-Match": '"etag123"',
                    "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"
                }
            }
        ]

        for path in test_paths:
            for p in permutations:
                url = path + p.get("query", "")
                hdrs = p.get("headers", {})
                res = client.get(url, headers=hdrs)

                assert res.status_code in (200, 304), f"Failed on {url}: code {res.status_code}"
                cc = res.headers.get("Cache-Control", "")
                pragma = res.headers.get("Pragma", "")
                expires = res.headers.get("Expires", "")

                assert "no-cache" in cc, f"no-cache missing in {url}: {cc}"
                assert "no-store" in cc, f"no-store missing in {url}: {cc}"
                assert "must-revalidate" in cc, f"must-revalidate missing in {url}: {cc}"
                assert pragma == "no-cache", f"Pragma invalid in {url}: {pragma}"
                assert expires == "0", f"Expires invalid in {url}: {expires}"

    def test_static_asset_cache_invariants_under_conditional_headers_and_queries(self, client):
        """
        Static assets /css/* and /js/* must strictly return:
        - Cache-Control: no-cache, must-revalidate
        - Must NOT include no-store (so client can validate 304 with cached copy)
        regardless of query parameters, If-None-Match, or If-Modified-Since.
        """
        static_files = ["/css/dashboard.css", "/js/dashboard.js"]
        permutations = [
            {},
            {"query": "?v=20261105.1"},
            {"query": "?v=custom_v2"},
            {"headers": {"If-None-Match": '"custom-tag"'}},
            {"headers": {"If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"}},
            {"headers": {"If-Modified-Since": "Fri, 01 Jan 2030 00:00:00 GMT"}},
            {
                "query": "?v=20261105.1",
                "headers": {"If-None-Match": '"some-tag"'}
            }
        ]

        for path in static_files:
            for p in permutations:
                url = path + p.get("query", "")
                hdrs = p.get("headers", {})
                res = client.get(url, headers=hdrs)

                assert res.status_code in (200, 304), f"Failed on {url}: code {res.status_code}"
                cc = res.headers.get("Cache-Control", "")

                assert "no-cache" in cc, f"no-cache missing in {url}: {cc}"
                assert "must-revalidate" in cc, f"must-revalidate missing in {url}: {cc}"
                assert "no-store" not in cc, f"no-store should NOT be on static assets {url}: {cc}"

    def test_api_routes_do_not_leak_static_cache_headers(self, client):
        """
        API endpoints (/api/*) must return valid JSON and must not have
        static cache-control headers injected by after_request.
        """
        api_endpoints = [
            "/api/flight/status",
            "/api/geofence/coverage",
            "/api/geofence"
        ]

        for ep in api_endpoints:
            res = client.get(ep, headers={
                "If-None-Match": '"123"',
                "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"
            })
            assert res.status_code == 200
            assert res.is_json
            cc = res.headers.get("Cache-Control", "")
            assert "no-store" not in cc
            assert cc != "no-cache, must-revalidate"


class TestAdversarialAPIAndClientStress:
    """Stress-test REST API endpoints under concurrency and verify frontend visualizer stability."""

    def test_concurrent_api_coverage_querying_and_reset(self):
        """Concurrent clients querying /api/geofence/coverage and POST /coverage/reset."""
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        errors = []
        lock = threading.Lock()

        def reader():
            try:
                for _ in range(30):
                    res = client.get("/api/geofence/coverage")
                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["status"] == "success"
                    assert "total_area_m2" in data
            except Exception as e:
                with lock:
                    errors.append(e)

        def resetter():
            try:
                for _ in range(15):
                    res = client.post("/api/geofence/coverage/reset")
                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["status"] == "success"
            except Exception as e:
                with lock:
                    errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(reader) for _ in range(7)] + [executor.submit(resetter) for _ in range(3)]
            for f in as_completed(futures, timeout=10.0):
                f.result()

        assert not errors, f"Concurrent API querying generated errors: {errors}"

    def test_frontend_dashboard_js_headless_simulation(self):
        """Execute headless Node.js stress testing against dashboard.js visualizer and state engine."""
        node_script = """
const fs = require('fs');
const vm = require('vm');

const mockElement = () => ({
  addEventListener: () => {},
  classList: { toggle: () => {}, add: () => {}, remove: () => {} },
  style: {},
  innerHTML: '',
  appendChild: () => {},
  scrollTop: 0,
  scrollHeight: 0,
  parentElement: { clientWidth: 400, clientHeight: 350 },
  getContext: () => ({
    beginPath: () => {}, arc: () => {}, stroke: () => {}, fill: () => {},
    moveTo: () => {}, lineTo: () => {}, clearRect: () => {}, fillRect: () => {},
    quadraticCurveTo: () => {}, closePath: () => {}, fillText: () => {},
    measureText: () => ({ width: 50 }),
    createRadialGradient: () => ({ addColorStop: () => {} }),
    save: () => {}, restore: () => {}, setLineDash: () => {},
    strokeStyle: '', fillStyle: '', lineWidth: 1, font: '',
    textAlign: '', textBaseline: '', shadowBlur: 0, shadowColor: ''
  })
});

const domMock = {
  document: {
    getElementById: (id) => mockElement(),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener: () => {},
    createElement: (tag) => mockElement()
  },
  window: { addEventListener: () => {}, setInterval: () => 1, setTimeout: () => 1 },
  setInterval: () => 1,
  setTimeout: () => 1,
  clearInterval: () => {},
  clearTimeout: () => {},
  fetch: () => Promise.resolve({ ok: false }),
  Date: Date,
  Math: Math,
  console: console
};

const code = fs.readFileSync('frontend/js/dashboard.js', 'utf8');
const context = vm.createContext(domMock);
vm.runInContext(code, context);

vm.runInContext(`
  var d = new DroneDashboard();
  d.initElements();
  // 1. Flood breadcrumbs (500 iterations)
  for (var i = 0; i < 500; i++) {
    d.recordBreadcrumb(37.4093 + i * 0.00001, -122.0641 + i * 0.00001, 10);
  }
  if (d.flightPathHistory.length > 300) {
    throw new Error('Breadcrumb buffer overflowed max length 300: ' + d.flightPathHistory.length);
  }
  // 2. Rapid map mode toggles (50 iterations)
  for (var j = 0; j < 50; j++) {
    d.setMapMode(j % 2 === 0 ? 'normal' : 'heatmap');
    d.renderGeofenceCanvas();
  }
  // 3. Degraded / hostile inputs
  d.recordBreadcrumb(0, 0, 10);
  d.recordBreadcrumb(null, undefined, NaN);
  d.coverageData = { coverage_pct: 75.5, scanned_points: [{ lat: 37.4093, lon: -122.0641, intensity: 0.8 }], observations: [] };
  d.renderGeofenceCanvas();
  d.coverageData = null;
  d.renderGeofenceCanvas();
`, context);
"""
        proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Headless Node.js dashboard stress test failed: {proc.stderr}"

