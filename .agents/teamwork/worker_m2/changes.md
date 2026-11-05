# Milestone M2 Implementation Changes

**Agent**: `worker_m2`  
**Milestone**: M2 — Map & Heatmap Visualizations & Cache-Busting  
**Date**: 2026-11-05T12:15:00Z  

---

## Summary of Changes

Milestone M2 restores real-time Normal Map and Heatmap visualizations on the Ground Control Station (GCS) dashboard, enforces strict HTTP cache-busting on frontend assets, and wires genuine Pixhawk GPS telemetry into the dynamic coverage planner.

### 1. `backend/search/coverage_planner.py`
- Added `import threading`.
- Initialized `self._lock = threading.Lock()` in `GeofenceCoveragePlanner.__init__`.
- Thread-safe synchronization applied in `update_drone_position()`, `get_coverage_percentage()`, and `get_coverage_snapshot()`.
- Implemented `reset_coverage(self)`: thread-safe clearing of `self.scanned_cells` and sweep trajectory state.
- Implemented `reconfigure(self, config: Any)`: thread-safe dynamic in-place reconfiguration of geofence boundaries (circular, polygonal, or rectangular) and grid cell regeneration.
- Added classmethod `from_geofence_config(cls, config: Any)`: factory constructor accepting `GeofenceConfig` instances or dictionaries.
- Exported global module-level singleton `coverage_planner` initialized from `geofence_service.config`.

### 2. `backend/api/geofence_routes.py`
- Imported `coverage_planner` from `backend.search.coverage_planner`.
- In `POST /api/geofence`, invoked `coverage_planner.reconfigure(updated)` upon boundary updates.
- Implemented `_extract_observation_hotspots()`: extracts genuine QR detections with non-zero coordinates from `vision_service.get_history()`, clustering repeated detections within 5 meters into weighted intensity beacons. Strictly returns `[]` if no detections exist (zero fabrication).
- Implemented `GET /api/geofence/coverage`: returns snapshot with `boundary_type`, `boundary_geo`, `total_area_m2`, `scanned_area_m2`, `coverage_pct`, `scanned_cells_count`, `total_cells_count`, `grid_resolution_m`, `scanned_points`, and `observations` (providing both nested `data` and top-level fields for total compatibility).
- Implemented `POST /api/geofence/coverage/reset`: resets coverage state to 0.0% and clears all scanned cells.

### 3. `backend/flight/mavlink_service.py`
- Implemented `_update_coverage_telemetry(self, lat: float, lon: float, alt: float)`: sanitizes coordinates (`lat != 0.0 and lon != 0.0`, `-90 <= lat <= 90`, `-180 <= lon <= 180`), safely invoking `coverage_planner.update_drone_position()` without holding the MAVLink lock.
- Implemented `_handle_gps_raw_int(self, msg: Any)`: updates GPS fix type, satellite count, and HDOP, routing valid fixes (`fix_type >= 2`) into `_update_coverage_telemetry`.
- Wired `_handle_gps_raw_int(msg)` into `GPS_RAW_INT` packet handling.
- Wired `_update_coverage_telemetry(g_lat, g_lon, g_alt)` into `GLOBAL_POSITION_INT` packet handling.
- Wired simulated coordinate updates into `_run_simulated_stream` to support offline testing and simulation.

### 4. `backend/app.py`
- Imported `request` from `flask`.
- Implemented `@app.after_request` filter `add_cache_control_headers(response)`:
  - Enforces `Cache-Control: no-cache, no-store, must-revalidate`, `Pragma: no-cache`, `Expires: 0` for `/` and `/index.html`.
  - Enforces `Cache-Control: no-cache, must-revalidate` for `/css/*` and `/js/*`.

### 5. `frontend/index.html`
- Appended version query string `?v=20261105.1` to `<link rel="stylesheet" href="/css/dashboard.css?v=20261105.1">` (line 11).
- Appended version query string `?v=20261105.1` to `<script src="/js/dashboard.js?v=20261105.1"></script>` (line 965).
- Replaced header and legend in `#pane-geofence`:
  - Added `#mapModeToggleGroup` containing segmented buttons `#btnMapNormal` and `#btnMapHeatmap`.
  - Added dynamic legends `#mapLegendNormal` and `#mapLegendHeatmap`, toggled synchronously with the active map mode.

### 6. `frontend/css/dashboard.css`
- Added `#mapModeToggleGroup` styling and responsive `@media (max-width: 600px)` wrapping rules for `#pane-geofence .card-header`.

### 7. `frontend/js/dashboard.js`
- Added state properties in `constructor`: `this.mapMode = 'normal'`, `this.coverageData = null`, `this.flightPathHistory = []`, `this.maxBreadcrumbs = 300`, `this.lastCoverageFetch = 0`.
- Registered `#btnMapNormal`, `#btnMapHeatmap`, `#mapLegendNormal`, `#mapLegendHeatmap` in `initElements()`.
- Bound click events to `setMapMode('normal')` and `setMapMode('heatmap')` in `bindEvents()`.
- Implemented `setMapMode(mode)`: toggles button active classes, toggles dynamic legends, triggers immediate coverage fetch and canvas re-render without DOM recreation or script errors.
- Implemented `recordBreadcrumb(lat, lon, alt)`: ring buffer capped at 300 points with distance delta filter (>0.4m) to prevent stationary jitter.
- Implemented `fetchCoverage()`: queries `/api/geofence/coverage` and updates `this.coverageData`.
- Implemented `getThermalColor(intensity, alpha)`: converts $[0.0, 1.0]$ into continuous thermal gradient (cyan $\rightarrow$ green $\rightarrow$ amber $\rightarrow$ red).
- Implemented `drawRoundedRect(ctx, x, y, width, height, radius)`: utility for high-contrast HUD cards.
- Overhauled `renderGeofenceCanvas()`:
  - **Normal Map Mode**: Renders geofence boundary with envelope tint, search perimeter, waypoints, historical breadcrumbs trail (with distance delta filter and fading alpha from 0.15 to 0.70), real-time cyan GPS drone marker with heading vector, and prominent HUD banners:
    - Red disconnected warning banner if MAVLink telemetry is offline.
    - Amber waiting-for-GPS warning banner showing satellite count and HDOP when satellite lock is absent.
    - 3D Fix telemetry tag showing live coordinates, satellites, and altitude when operational.
  - **Heatmap Mode**: Renders muted geofence boundary, discretized metric grid cells with radial thermal gradients, observation intensity hot spots for QR detections, live drone marker with heading vector, and Coverage Stats HUD (`HEATMAP COVERAGE: X%`, scanned $\text{m}^2$, discretized cells).
- In `fetchTelemetry()`, recorded valid GPS fixes into breadcrumb buffer.
- In `switchTab('geofence')` and telemetry polling loop, periodically polled coverage data.

### 8. `tests/test_api.py`
- Added 6 cache-control tests:
  - `test_cache_control_headers_root_route`
  - `test_cache_control_headers_index_html`
  - `test_cache_control_headers_static_assets`
  - `test_cache_control_headers_with_version_query_params`
  - `test_index_html_contains_cache_busting_version_tags`
  - `test_api_routes_unaffected_by_static_cache_headers`
- Added 2 coverage API tests:
  - `test_get_geofence_coverage_endpoint_schema_and_calculations`
  - `test_post_geofence_coverage_reset_flow`

### 9. `tests/test_geofence_service.py`
- Added `TestCoveragePlannerModel` (8 unit tests):
  - `test_initial_grid_and_area`
  - `test_camera_footprint_scaling`
  - `test_gps_position_update_accumulates_scanned_cells`
  - `test_gps_position_outside_geofence_does_not_expand_coverage`
  - `test_reset_coverage_clears_scanned_cells`
  - `test_coverage_snapshot_structure`
  - `test_reconfigure_boundary_geometry`
- Added `TestMAVLinkCoverageIntegration` (2 integration tests):
  - `test_simulated_mavlink_stream_updates_coverage_planner`
  - `test_direct_mavlink_gps_update_handling`

### 10. `tests/test_geofence.py`
- Created standalone test file importing and executing all geofence algorithm, service, API, coverage planner, and MAVLink integration test cases.

