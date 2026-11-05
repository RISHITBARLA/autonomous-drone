# Milestone M2: Frontend Cache-Busting & Automated Test Verification Architecture

**Author**: `explorer_m2_3` (Cache-Busting & Test Verification Explorer)  
**Date**: 2026-11-05T12:00:00Z  
**Target Milestone**: M2 — Map & Heatmap Visualizations & Cache-Busting  
**Working Directory**: `c:\Users\IDEAL\AUTONOMOUS-DRONE\.agents\teamwork\explorer_m2_3\`  
**Scope**: `backend/app.py`, `frontend/index.html`, `tests/test_api.py`, `tests/test_geofence_service.py`, `tests/test_geofence.py`

---

## 1. Executive Summary & Problem Boundary

Milestone M2 restores the Normal Map and Heatmap visualizations on the Ground Control Station (GCS) and introduces real-time search coverage tracking. In both field quadcopter operations and laboratory development, a critical failure mode is **stale browser asset caching**:
1. When modified JavaScript (`dashboard.js`) or CSS (`dashboard.css`) is deployed to the Raspberry Pi companion computer, client browsers often serve cached versions from memory or disk, causing UI lockouts, broken canvas renders, missing event handlers, or silent script errors.
2. The HTML shell (`index.html`) can be cached aggressively by browsers if HTTP caching directives are omitted.
3. Lack of automated regression tests for cache headers, the newly created coverage endpoints (`GET /api/geofence/coverage`, `POST /api/geofence/coverage/reset`), and GPS telemetry coverage integration risks regressions during deployment.

This document delivers:
- Exact line-by-line inspection of static file serving in `backend/app.py` and frontend asset links in `frontend/index.html`.
- Dual-layer cache-busting design combining Flask `@app.after_request` headers and HTML version query parameters (`?v=20261105.1`).
- Complete, copy-pasteable, robust automated test suites verifying:
  - Cache-Control headers on `/`, `/index.html`, `/css/dashboard.css`, and `/js/dashboard.js`.
  - HTTP status, JSON schema, and mathematical consistency for `GET /api/geofence/coverage`.
  - State clearing and verification for `POST /api/geofence/coverage/reset`.
  - Unit and integration tests for `GeofenceCoveragePlanner` and `MAVLinkService` GPS position update ingestion.

---

## 2. Static Asset Serving & Cache-Control Architecture (`backend/app.py`)

### 2.1 Inspection of Local Codebase (`backend/app.py:14-70`)
In `backend/app.py`:
```python
# Lines 14-15
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS

...

# Lines 56-70
    # Web Dashboard Routes
    @app.route("/")
    def index():
        """Serve Ground Station Dashboard homepage."""
        return send_from_directory(str(settings.FRONTEND_DIR), "index.html")

    @app.route("/<path:path>")
    def static_proxy(path):
        """Serve frontend static assets (CSS, JS, assets)."""
        file_path = settings.FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return send_from_directory(str(settings.FRONTEND_DIR), path)
        # Default fallback to index.html for SPA client-side routing
        return send_from_directory(str(settings.FRONTEND_DIR), "index.html")
```

### 2.2 Root Cause of Stale Asset Caching
1. **Missing `request` import**: `request` is currently not imported in `backend/app.py`.
2. **Default Cache Behavior**: `send_from_directory()` relies on Werkzeug/Flask defaults. When `DEBUG=False` in production on the Raspberry Pi (`DRONE_DEBUG=false`), Flask sets `max-age=43200` (12 hours) on static assets.
3. **HTML Shell Caching**: Browsers cache `index.html` unless explicit `Cache-Control: no-cache, no-store, must-revalidate` and `Pragma: no-cache` headers are attached to the response.
4. **Silent Client Failures**: When new DOM elements (such as `#btnMapNormal` and `#btnMapHeatmap`) are added to `index.html`, but an older `dashboard.js` is loaded from browser cache, `document.getElementById('btnMapNormal')` will be ignored or mismatched, causing map switching to fail silently.

### 2.3 Proposed Flask Cache Header Implementation
In `backend/app.py`:
1. Update Flask imports on line 14:
   ```python
   from flask import Flask, send_from_directory, jsonify, request
   ```
2. Add `@app.after_request` filter inside `create_app()` immediately following route declarations:
   ```python
    @app.after_request
    def add_cache_control_headers(response):
        """
        Enforce strict HTTP caching rules for Ground Station frontend:
        - HTML shell (/, /index.html) must never be cached to ensure fresh asset manifests.
        - Static versioned assets (/css/*, /js/*) must revalidate with server on each request.
        """
        path = request.path
        if path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith(("/css/", "/js/")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
   ```

### 2.4 Behavior & Edge-Case Analysis
| Request Path | Matching Condition | Generated Headers | Rationale |
|---|---|---|---|
| `GET /` | `path in ("/", "/index.html")` | `Cache-Control: no-cache, no-store, must-revalidate`<br>`Pragma: no-cache`<br>`Expires: 0` | Ensures client browser never stores the root HTML shell. Fresh HTML is requested on every page load. |
| `GET /index.html` | `path in ("/", "/index.html")` | `Cache-Control: no-cache, no-store, must-revalidate`<br>`Pragma: no-cache`<br>`Expires: 0` | Covers explicit requests to `/index.html`. |
| `GET /css/dashboard.css` | `path.startswith(("/css/", "/js/"))` | `Cache-Control: no-cache, must-revalidate` | Forces browser to check with server (HTTP 304 or fresh 200) before using cached styles. |
| `GET /css/dashboard.css?v=20261105.1` | `path.startswith(("/css/", "/js/"))` | `Cache-Control: no-cache, must-revalidate` | In Flask, `request.path` contains only the URL path without query string. Matches correctly. |
| `GET /js/dashboard.js` | `path.startswith(("/css/", "/js/"))` | `Cache-Control: no-cache, must-revalidate` | Forces browser to revalidate scripts. |
| `GET /js/dashboard.js?v=20261105.1` | `path.startswith(("/css/", "/js/"))` | `Cache-Control: no-cache, must-revalidate` | Matches correctly. |
| `GET /api/*` | None | Default Flask JSON headers | API responses are untouched by static caching rules. |

---

## 3. Frontend HTML Cache-Busting Specification (`frontend/index.html`)

### 3.1 Inspection of Local Codebase (`frontend/index.html`)
Inspection confirms:
- **Line 11**: `<link rel="stylesheet" href="/css/dashboard.css">`
- **Line 965**: `<script src="/js/dashboard.js"></script>`
- No other local static CSS or JS assets are referenced in `index.html` (other tags are external Google Fonts).

### 3.2 Cache-Busting Query String Modifications
Update lines 11 and 965 in `frontend/index.html`:

```html
<!-- Line 11: Updated with build timestamp version tag -->
<link rel="stylesheet" href="/css/dashboard.css?v=20261105.1">
```

```html
<!-- Line 965: Updated with build timestamp version tag -->
<script src="/js/dashboard.js?v=20261105.1"></script>
```

### 3.3 Synergistic Operation (Layer 1 + Layer 2)
The combination of Layer 1 (Flask Cache-Control headers) and Layer 2 (HTML query strings) provides an ironclad guarantee against stale assets:
1. **Always-Fresh HTML**: Because `/` is served with `Cache-Control: no-cache, no-store, must-revalidate`, the browser will NEVER use a cached copy of `index.html`. Every navigation or browser refresh fetches the latest HTML manifest.
2. **Instant Cache Bypassing on Version Bump**: When a new version is deployed with an incremented query string (e.g. `v=20261105.1`), the browser treats `dashboard.js?v=20261105.1` as an entirely distinct resource URI and immediately fetches it over the network, ignoring any cached `dashboard.js` without requiring manual browser cache clearing (`Ctrl+F5`).
3. **Revalidation Safety**: Even if the query string remains unchanged during iterative development, `Cache-Control: no-cache, must-revalidate` forces the browser to send an `If-Modified-Since` request to Flask, which immediately returns the updated file if the file modified timestamp has changed.

---

## 4. Automated Test Verification Architecture & Implementation

To ensure complete coverage across all Milestone M2 requirements, four distinct automated test suites are formulated below.

### 4.1 Test Suite 1: Cache-Control Headers & Asset Query Strings
This test suite verifies:
- Root route `/` returns status 200 and strict no-cache headers.
- `/index.html` returns status 200 and strict no-cache headers.
- Static assets `/css/dashboard.css` and `/js/dashboard.js` return status 200 and `no-cache, must-revalidate`.
- Static assets with query strings (`?v=20261105.1`) return status 200 and `no-cache, must-revalidate`.
- Dashboard HTML returned by `/` contains the explicit cache-busting query strings.
- REST API routes (e.g. `/api/health`) are not erroneously tagged with frontend static cache headers.

#### Implementation in `tests/test_api.py`:
```python
    # -------------------------------------------------------------
    # Milestone M2: Frontend Cache-Busting Verification Tests
    # -------------------------------------------------------------
    def test_cache_control_headers_root_route(self):
        """Verify GET / returns strict no-cache headers for HTML shell."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_cache_control_headers_index_html(self):
        """Verify GET /index.html returns strict no-cache headers."""
        response = self.client.get("/index.html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_cache_control_headers_static_assets(self):
        """Verify /css/* and /js/* assets return no-cache, must-revalidate."""
        # CSS asset
        res_css = self.client.get("/css/dashboard.css")
        self.assertEqual(res_css.status_code, 200)
        self.assertEqual(
            res_css.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

        # JS asset
        res_js = self.client.get("/js/dashboard.js")
        self.assertEqual(res_js.status_code, 200)
        self.assertEqual(
            res_js.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

    def test_cache_control_headers_with_version_query_params(self):
        """Verify version query string requests preserve revalidate cache headers."""
        res_css = self.client.get("/css/dashboard.css?v=20261105.1")
        self.assertEqual(res_css.status_code, 200)
        self.assertEqual(
            res_css.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

        res_js = self.client.get("/js/dashboard.js?v=20261105.1")
        self.assertEqual(res_js.status_code, 200)
        self.assertEqual(
            res_js.headers.get("Cache-Control"),
            "no-cache, must-revalidate"
        )

    def test_index_html_contains_cache_busting_version_tags(self):
        """Verify frontend/index.html includes ?v=20261105.1 in CSS and JS tags."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/css/dashboard.css?v=20261105.1", response.data)
        self.assertIn(b"/js/dashboard.js?v=20261105.1", response.data)

    def test_api_routes_unaffected_by_static_cache_headers(self):
        """Verify API endpoints do not receive frontend static cache-control headers."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(
            response.headers.get("Cache-Control"),
            "no-cache, no-store, must-revalidate"
        )
```

---

### 4.2 Test Suite 2: GET `/api/geofence/coverage` Status, Schema, & Calculations
This test suite verifies:
- `GET /api/geofence/coverage` returns HTTP 200 and `"status": "success"`.
- Response contains all required coverage fields: `boundary_type`, `boundary_geo`, `total_area_m2`, `scanned_area_m2`, `coverage_pct`, `scanned_cells_count`, `total_cells_count`, `grid_resolution_m`, and `scanned_points`.
- Values conform to physical bounds ($total\_area > 0$, $0.0 \le coverage\_pct \le 100.0$, $total\_cells > 0$).
- Mathematical derivation consistency:
  $$scanned\_area\_m2 \approx scanned\_cells\_count \times (grid\_resolution\_m)^2$$
  $$coverage\_pct = \text{round}\left(\frac{scanned\_cells\_count}{total\_cells\_count} \times 100.0, 2\right)$$
- Compatibility: Verifies both top-level and nested `data` dictionary fields.

#### Implementation in `tests/test_api.py`:
```python
    # -------------------------------------------------------------
    # Milestone M2: Geofence Coverage API Endpoint Tests
    # -------------------------------------------------------------
    def test_get_geofence_coverage_endpoint_schema_and_calculations(self):
        """Verify GET /api/geofence/coverage returns valid status, schema, and metrics."""
        response = self.client.get("/api/geofence/coverage")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")

        # Support both data container and direct top-level fields
        data = payload.get("data", payload)
        self.assertIn("boundary_type", data)
        self.assertIn("total_area_m2", data)
        self.assertIn("scanned_area_m2", data)
        self.assertIn("coverage_pct", data)
        self.assertIn("scanned_cells_count", data)
        self.assertIn("total_cells_count", data)
        self.assertIn("grid_resolution_m", data)
        self.assertIn("scanned_points", data)

        # Numerical bounds
        self.assertGreater(data["total_area_m2"], 0.0)
        self.assertGreaterEqual(data["scanned_area_m2"], 0.0)
        self.assertGreaterEqual(data["coverage_pct"], 0.0)
        self.assertLessEqual(data["coverage_pct"], 100.0)
        self.assertGreater(data["total_cells_count"], 0)
        self.assertGreaterEqual(data["scanned_cells_count"], 0)
        self.assertIsInstance(data["scanned_points"], list)

        # Mathematical derivation checks (Zero fabricated numbers)
        grid_res = data["grid_resolution_m"]
        expected_scanned_area = round(data["scanned_cells_count"] * (grid_res ** 2), 1)
        self.assertAlmostEqual(data["scanned_area_m2"], expected_scanned_area, delta=0.5)

        expected_pct = round((data["scanned_cells_count"] / data["total_cells_count"]) * 100.0, 2)
        self.assertAlmostEqual(data["coverage_pct"], expected_pct, places=2)
```

---

### 4.3 Test Suite 3: POST `/api/geofence/coverage/reset`
This test suite verifies:
- `POST /api/geofence/coverage/reset` returns HTTP 200 and `"status": "success"`.
- After calling reset, a subsequent `GET /api/geofence/coverage` confirms:
  - `scanned_cells_count == 0`
  - `scanned_area_m2 == 0.0`
  - `coverage_pct == 0.0`
  - `len(scanned_points) == 0`

#### Implementation in `tests/test_api.py`:
```python
    def test_post_geofence_coverage_reset_flow(self):
        """Verify POST /api/geofence/coverage/reset resets scanned cells to zero."""
        # 1. Trigger reset
        reset_res = self.client.post("/api/geofence/coverage/reset")
        self.assertEqual(reset_res.status_code, 200)
        reset_data = reset_res.get_json()
        self.assertEqual(reset_data["status"], "success")

        # 2. Query coverage and verify 0% state
        cov_res = self.client.get("/api/geofence/coverage")
        self.assertEqual(cov_res.status_code, 200)
        cov_data = cov_res.get_json()
        data = cov_data.get("data", cov_data)

        self.assertEqual(data["scanned_cells_count"], 0)
        self.assertEqual(data["scanned_area_m2"], 0.0)
        self.assertEqual(data["coverage_pct"], 0.0)
        self.assertEqual(len(data["scanned_points"]), 0)
```

---

### 4.4 Test Suite 4: GPS Position Update Integration & Coverage Planner Mathematical Engine
This test suite verifies:
- `GeofenceCoveragePlanner` mathematical grid discretization and camera footprint calculations.
- Accumulation of coverage cells when genuine GPS positions inside the geofence are received.
- Clamping and non-recording of cells outside the geofence boundary.
- Integration with `MAVLinkService`: when simulated or physical GPS telemetry updates occur, `coverage_planner.update_drone_position()` is safely invoked across threads.

#### Implementation in `tests/test_geofence_service.py` (or new standalone `tests/test_geofence.py`):
```python
# =====================================================================
# Milestone M2: Coverage Planner Unit & MAVLink Integration Test Suite
# =====================================================================
from backend.search.coverage_planner import (
    GeofenceCoveragePlanner,
    CameraFootprint,
    geo_to_local_meters,
    local_meters_to_geo,
    coverage_planner
)
from backend.flight.mavlink_service import MAVLinkService


class TestCoveragePlannerModel(unittest.TestCase):
    """Unit test suite for GeofenceCoveragePlanner mathematical algorithms."""

    def setUp(self):
        # Configure a standard circular geofence centered at Moffett Field
        self.planner = GeofenceCoveragePlanner(
            boundary_type="circular",
            circle_center_geo=(37.4093, -122.0641),
            circle_radius_m=100.0,
            grid_resolution_m=2.0,
            search_altitude_m=10.0
        )

    def test_initial_grid_and_area(self):
        """Verify circular grid discretization area matches analytical geometry."""
        # Theoretical area: pi * r^2 = pi * 100^2 ~ 31415.9 m^2
        self.assertAlmostEqual(self.planner.total_area_m2, 31415.0, delta=1500.0)
        self.assertGreater(len(self.planner.total_cells), 0)
        self.assertEqual(len(self.planner.scanned_cells), 0)
        self.assertEqual(self.planner.get_coverage_percentage(), 0.0)

    def test_camera_footprint_scaling(self):
        """Verify camera footprint dimensions scale linearly with flight altitude."""
        fp10 = CameraFootprint.calculate(altitude_m=10.0)
        fp20 = CameraFootprint.calculate(altitude_m=20.0)
        self.assertAlmostEqual(fp20.width_m, fp10.width_m * 2.0, delta=0.2)
        self.assertAlmostEqual(fp20.height_m, fp10.height_m * 2.0, delta=0.2)

    def test_gps_position_update_accumulates_scanned_cells(self):
        """Verify GPS updates inside geofence accumulate scanned cells and coverage."""
        # 1. Update at center
        pct1 = self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        self.assertGreater(pct1, 0.0)
        scanned_count_1 = len(self.planner.scanned_cells)
        self.assertGreater(scanned_count_1, 0)

        # 2. Update at adjacent location (+15m North ~ +0.000135 lat)
        pct2 = self.planner.update_drone_position(37.409435, -122.0641, altitude_m=10.0)
        self.assertGreaterEqual(pct2, pct1)
        self.assertGreater(len(self.planner.scanned_cells), scanned_count_1)

    def test_gps_position_outside_geofence_does_not_expand_coverage(self):
        """Verify GPS updates outside geofence boundary do not add invalid cells."""
        # Initial scan at center
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        valid_scanned = len(self.planner.scanned_cells)

        # Update 10 km away (out of bounds)
        pct = self.planner.update_drone_position(37.5000, -122.0641, altitude_m=10.0)
        self.assertEqual(len(self.planner.scanned_cells), valid_scanned)

    def test_reset_coverage_clears_scanned_cells(self):
        """Verify reset_coverage() clears scanned cells and resets percentage to zero."""
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        self.assertGreater(len(self.planner.scanned_cells), 0)

        # Reset
        self.planner.reset_coverage()
        self.assertEqual(len(self.planner.scanned_cells), 0)
        self.assertEqual(self.planner.get_coverage_percentage(), 0.0)

    def test_coverage_snapshot_structure(self):
        """Verify get_coverage_snapshot() serializes all required fields."""
        self.planner.update_drone_position(37.4093, -122.0641, altitude_m=10.0)
        snap = self.planner.get_coverage_snapshot()
        self.assertEqual(snap["boundary_type"], "circular")
        self.assertGreater(snap["total_area_m2"], 0.0)
        self.assertGreater(snap["scanned_area_m2"], 0.0)
        self.assertGreater(snap["coverage_pct"], 0.0)
        self.assertGreater(snap["scanned_cells_count"], 0)
        self.assertGreater(snap["total_cells_count"], 0)
        self.assertEqual(snap["grid_resolution_m"], 2.0)
        self.assertEqual(snap["search_altitude_m"], 10.0)
        self.assertIsInstance(snap["scanned_points"], list)
        self.assertGreater(len(snap["scanned_points"]), 0)


class TestMAVLinkCoverageIntegration(unittest.TestCase):
    """Integration test suite verifying MAVLink GPS stream feeds CoveragePlanner."""

    def setUp(self):
        coverage_planner.reset_coverage()

    def tearDown(self):
        coverage_planner.reset_coverage()

    def test_simulated_mavlink_stream_updates_coverage_planner(self):
        """Verify simulated MAVLink telemetry thread feeds GPS updates to coverage_planner."""
        initial_scanned = len(coverage_planner.scanned_cells)
        service = MAVLinkService(
            connection_string="simulated",
            heartbeat_timeout=1.0,
            simulate=True
        )
        try:
            service.start()
            import time
            time.sleep(0.35)  # Allow worker thread to run a few simulated orbital steps
            # Drone orbits around base coordinate (37.4093, -122.0641) inside geofence
            self.assertGreater(len(coverage_planner.scanned_cells), initial_scanned)
            self.assertGreater(coverage_planner.get_coverage_percentage(), 0.0)
        finally:
            service.stop()

    def test_direct_mavlink_gps_update_handling(self):
        """Verify _update_coverage_telemetry safely filters invalid/null coordinates."""
        service = MAVLinkService(connection_string="simulated", simulate=True)
        initial_cells = len(coverage_planner.scanned_cells)

        # 1. Null Island coordinate (0, 0) should be dropped
        service._update_coverage_telemetry(0.0, 0.0, 15.0)
        self.assertEqual(len(coverage_planner.scanned_cells), initial_cells)

        # 2. Out of range coordinates should be dropped
        service._update_coverage_telemetry(999.0, -122.0641, 15.0)
        self.assertEqual(len(coverage_planner.scanned_cells), initial_cells)

        # 3. Valid coordinate should update
        service._update_coverage_telemetry(37.4093, -122.0641, 15.0)
        self.assertGreater(len(coverage_planner.scanned_cells), initial_cells)
```

---

## 5. Test File Placement & Organization

In the dispatch instructions, `tests/test_geofence.py` was specifically referenced alongside `tests/test_api.py`.
To ensure seamless execution regardless of whether tests are run via individual files or the entire directory:
1. **`tests/test_api.py`**:
   - Add Test Suite 1 (Cache-Control & Asset Query Strings).
   - Add Test Suite 2 (`GET /api/geofence/coverage` schema & calculations).
   - Add Test Suite 3 (`POST /api/geofence/coverage/reset`).
2. **`tests/test_geofence_service.py`**:
   - Add `TestCoveragePlannerModel` and `TestMAVLinkCoverageIntegration`.
3. **`tests/test_geofence.py` (New File)**:
   - Create `tests/test_geofence.py` importing and running both `TestGeofenceAlgorithms`, `TestGeofenceService`, `TestGeofenceAPI`, and `TestCoveragePlannerModel`.
   - This guarantees that any developer or automated script executing `pytest tests/test_geofence.py` succeeds without `file not found` errors.

---

## 6. Implementation Action Plan & Exact Line Diffs

### Action 1: Modify `backend/app.py`
- **Line 14**: Add `request` to Flask imports.
  ```python
  from flask import Flask, send_from_directory, jsonify, request
  ```
- **Lines 70-71**: Insert `@app.after_request` handler:
  ```python
    @app.after_request
    def add_cache_control_headers(response):
        """Enforce cache-busting headers for HTML shell and static assets."""
        path = request.path
        if path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith(("/css/", "/js/")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
  ```

### Action 2: Modify `frontend/index.html`
- **Line 11**:
  ```html
  <link rel="stylesheet" href="/css/dashboard.css?v=20261105.1">
  ```
- **Line 965**:
  ```html
  <script src="/js/dashboard.js?v=20261105.1"></script>
  ```

### Action 3: Append Tests to `tests/test_api.py`
- Add the 6 cache-busting test methods and 2 coverage endpoint test methods to `TestAPIEndpoints`.

### Action 4: Append Tests to `tests/test_geofence_service.py` & Create `tests/test_geofence.py`
- Add `TestCoveragePlannerModel` and `TestMAVLinkCoverageIntegration`.
- Create `tests/test_geofence.py` to ensure commands targeting `test_geofence.py` execute cleanly.

---

## 7. Verification Matrix

| Test Suite / Command | Target Component | Expected Result |
|---|---|---|
| `pytest tests/test_api.py -k "cache_control"` | Flask cache headers | 100% Pass (root no-cache, static revalidate) |
| `pytest tests/test_api.py -k "version_tags"` | HTML query strings | 100% Pass (`?v=20261105.1` found in HTML) |
| `pytest tests/test_api.py -k "coverage"` | Coverage REST endpoints | 100% Pass (GET schema, POST reset) |
| `pytest tests/test_geofence_service.py -k "Coverage"` | Mathematical model & integration | 100% Pass (discretization, GPS accumulation, thread safety) |
| `pytest` | Full project regression | 100% Pass (all 119 existing + ~15 new tests) |
