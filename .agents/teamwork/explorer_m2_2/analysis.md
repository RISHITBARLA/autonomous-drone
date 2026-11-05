# Milestone M2 Frontend Exploration & Visualizer Design Analysis

**Agent**: `explorer_m2_2` (Frontend Visualizer & Map Mode Explorer)  
**Date**: 2026-11-05T12:00:00Z  
**Status**: Completed  
**Target Files**:
- `frontend/index.html` (Tab 7 `#pane-geofence`)
- `frontend/js/dashboard.js` (`renderGeofenceCanvas()`, `switchTab()`, telemetry polling, breadcrumbs ring buffer)
- `frontend/css/dashboard.css` (Segmented toggle buttons, HUD overlays, responsive layout)
**Reference Documents**:
- `ORIGINAL_REQUEST.md` (Requirements R4 & R6)
- `PROJECT.md` (Milestone M2 Specifications)
- `explorer_survey_3/survey_report.md` (Map & Visualization Survey)

---

## 1. Executive Summary & Problem Scope

Requirement R4 dictates restoring the dashboard's Normal Map and Heatmap visualization systems without fabricating data or replacing existing algorithms:
1. **Normal Map**: Renders designated geofence boundaries, real-time GPS position from telemetry, search boundaries, historical flight path breadcrumbs (ring buffer of up to 300 points), and prominent HUD overlays for disconnected or waiting-for-GPS states.
2. **Heatmap**: Displays genuine search coverage and observation intensity directly derived from `backend/search/coverage_planner.py` (`GeofenceCoveragePlanner`) and `backend/vision/vision_service.py` via `/api/geofence/coverage`. The coverage grid must be shaded with a thermal color gradient (cyan $\rightarrow$ green $\rightarrow$ amber $\rightarrow$ red) based on scan count/intensity, accompanied by a Coverage Stats HUD.
3. **Map Mode Toggle**: A segmented button toggle (`#btnMapNormal` and `#btnMapHeatmap`) located in the `#geofenceCanvas` card header, matching the existing glassmorphic styling, preserving `#geofenceSafetyBadge`, and allowing seamless switching without DOM recreation, canvas flicker, or JavaScript console errors.

All investigations were conducted directly against local repository files.

---

## 2. Deep Dive: Current Implementation & Gap Analysis

### 2.1 Current Visualizer Layout (`frontend/index.html:840-856`)
```html
<div class="card">
  <div class="card-header">
    <span class="card-title">Geofence Radar Visualizer</span>
    <span class="card-badge highlight" id="geofenceSafetyBadge">SAFE ENVELOPE</span>
  </div>
  <div class="card-body">
    <div class="map-canvas-container">
      <canvas id="geofenceCanvas"></canvas>
    </div>
    <div style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted);">
      <span>● Cyan: Drone Position</span>
      <span>○ Yellow: Boundary Limit</span>
      <span>▲ Magenta: Waypoints</span>
    </div>
  </div>
</div>
```
**Gaps Identified**:
1. Header contains only a static title and `#geofenceSafetyBadge`. There is no toggle control to switch between Normal Map and Heatmap modes.
2. Legend below canvas is static and only reflects Normal Map elements.

### 2.2 Current Canvas Rendering Engine (`frontend/js/dashboard.js:1576-1703`)
In `dashboard.js`, `renderGeofenceCanvas()`:
1. Handles High-DPI canvas resizing against parent container width/height.
2. Renders cyan concentric radar rings and crosshairs.
3. Computes equirectangular projection scale `scale = maxR / fenceRadiusM`.
4. Renders circular or polygonal boundary in yellow dashed lines (`#ffeb3b`).
5. Renders active mission waypoints in magenta.
6. If `this.currentTelemetry && this.currentTelemetry.connected`:
   - Renders a cyan circle for drone position and a 20px heading vector line.

**Gaps Identified**:
1. **No Historical Flight Path / Breadcrumbs**: Canvas calls `ctx.clearRect(0, 0, width, height)` on every tick (1.5s). Past drone positions are not stored, so no flight path trail is drawn.
2. **No Search Boundary**: The bounding box / coverage boundary from `coverage_planner` is omitted.
3. **Silent Failure on Disconnect / Lost GPS**: If `connected === false` or `gps_fix_type < 2` or `latitude === 0.0`, the drone icon simply disappears. No explanation is displayed to the operator.
4. **No Heatmap Mode**: `dashboard.js` has zero logic to render discretized grid cells, thermal color gradients, observation hot spots, or coverage statistics.
5. **No Mode State**: `DroneDashboard` does not track `this.mapMode`.

---

## 3. Detailed Architecture & Design Specifications

### 3.1 Card Header & Segmented Button Toggle Design (`frontend/index.html`)

We replace the simple title/badge header in `#pane-geofence` with a segmented button group matching the pattern used in the Live Vision card (`frontend/index.html:190-203`):

```html
<!-- 2D Canvas Visualizer -->
<div class="card">
  <div class="card-header">
    <div class="card-title-group">
      <span class="card-title">Geofence &amp; Navigation Visualizer</span>
    </div>
    <div style="display: flex; gap: 8px; align-items: center;">
      <div class="camera-actions" id="mapModeToggleGroup">
        <button class="btn btn-sm btn-ghost active" id="btnMapNormal" title="Normal Navigation Map">Normal Map</button>
        <button class="btn btn-sm btn-ghost" id="btnMapHeatmap" title="Search Coverage &amp; Observation Heatmap">Heatmap</button>
      </div>
      <span class="card-badge highlight" id="geofenceSafetyBadge">SAFE ENVELOPE</span>
    </div>
  </div>
  <div class="card-body">
    <div class="map-canvas-container">
      <canvas id="geofenceCanvas"></canvas>
    </div>
    <!-- Dynamic Legend for Normal Map -->
    <div id="mapLegendNormal" style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted); flex-wrap: wrap; gap: 6px;">
      <span>● Cyan: Drone Position</span>
      <span>○ Yellow: Geofence Limit</span>
      <span>▢ Orange: Search Boundary</span>
      <span>▲ Magenta: Waypoints</span>
      <span>┈ Cyan Trail: Flight Path</span>
    </div>
    <!-- Dynamic Legend for Heatmap -->
    <div id="mapLegendHeatmap" style="display: none; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted); flex-wrap: wrap; gap: 6px;">
      <span>🟦 Cyan: Low Coverage</span>
      <span>🟩 Green: Medium</span>
      <span>🟨 Amber: High</span>
      <span>🟥 Red: QR / Target Hotspot</span>
      <span>○ Yellow: Boundary Limit</span>
    </div>
  </div>
</div>
```

**Design Strengths**:
- Utilizes existing classes `.camera-actions`, `.btn`, `.btn-sm`, `.btn-ghost`, and `.active` from `frontend/css/dashboard.css:773-787`.
- Retains `#geofenceSafetyBadge` and responsive layout without breaking any existing styling.
- Introduces `#mapLegendNormal` and `#mapLegendHeatmap`, toggled synchronously with map mode.

---

### 3.2 Frontend State Management (`frontend/js/dashboard.js`)

In `DroneDashboard`:

#### State Properties:
```javascript
// Map & Visualizer State
this.mapMode = 'normal'; // 'normal' | 'heatmap'
this.coverageData = null; // Cached snapshot from /api/geofence/coverage
this.flightPathHistory = []; // Ring buffer of past GPS positions
this.maxBreadcrumbs = 300; // Requirement: up to 300 points
this.lastCoverageFetch = 0;
```

#### Element Registration in `initElements()`:
```javascript
this.btnMapNormal = document.getElementById('btnMapNormal');
this.btnMapHeatmap = document.getElementById('btnMapHeatmap');
this.mapLegendNormal = document.getElementById('mapLegendNormal');
this.mapLegendHeatmap = document.getElementById('mapLegendHeatmap');
```

#### Event Binding in `bindEvents()`:
```javascript
if (this.btnMapNormal) {
  this.btnMapNormal.addEventListener('click', () => this.setMapMode('normal'));
}
if (this.btnMapHeatmap) {
  this.btnMapHeatmap.addEventListener('click', () => this.setMapMode('heatmap'));
}
```

#### Mode Switching Method `setMapMode(mode)`:
```javascript
setMapMode(mode) {
  if (this.mapMode === mode) return;
  this.mapMode = mode;

  // Toggle button active states
  if (this.btnMapNormal) this.btnMapNormal.classList.toggle('active', mode === 'normal');
  if (this.btnMapHeatmap) this.btnMapHeatmap.classList.toggle('active', mode === 'heatmap');

  // Toggle legends
  if (this.mapLegendNormal) this.mapLegendNormal.style.display = (mode === 'normal') ? 'flex' : 'none';
  if (this.mapLegendHeatmap) this.mapLegendHeatmap.style.display = (mode === 'heatmap') ? 'flex' : 'none';

  // If switching to heatmap, fetch fresh coverage immediately
  if (mode === 'heatmap') {
    this.fetchCoverage();
  }

  // Redraw canvas immediately
  this.renderGeofenceCanvas();
}
```

#### Historical Breadcrumb Recording:
In `fetchTelemetry()`:
```javascript
if (json.status === 'success' && json.data) {
  this.currentTelemetry = json.data;
  this.updateTelemetryUI(json.data);

  // Record breadcrumb if valid non-zero GPS fix
  if (json.data.connected && json.data.latitude && json.data.longitude &&
      (json.data.latitude !== 0.0 || json.data.longitude !== 0.0)) {
    this.recordBreadcrumb(json.data.latitude, json.data.longitude, json.data.altitude_relative_m);
  }
}
```

Method `recordBreadcrumb(lat, lon, alt)`:
```javascript
recordBreadcrumb(lat, lon, alt) {
  if (!lat || !lon || (lat === 0.0 && lon === 0.0)) return;

  const last = this.flightPathHistory[this.flightPathHistory.length - 1];
  if (last) {
    // Suppress stationary jitter: only record if moved > 0.4 meters
    const dLat = (lat - last.lat) * 110540;
    const dLon = (lon - last.lon) * 111320 * Math.cos(lat * Math.PI / 180);
    if (Math.hypot(dLat, dLon) < 0.4) return;
  }

  this.flightPathHistory.push({ lat, lon, alt, t: Date.now() });

  // Ring buffer enforcement: strictly cap at 300 points
  if (this.flightPathHistory.length > this.maxBreadcrumbs) {
    this.flightPathHistory.shift();
  }
}
```

#### Coverage Polling `fetchCoverage()`:
```javascript
async fetchCoverage() {
  try {
    const res = await fetch('/api/geofence/coverage');
    if (!res.ok) return;
    const json = await res.json();
    const data = json.data || json;
    if (data.status === 'success' || data.total_area_m2 !== undefined) {
      this.coverageData = data;
      this.lastCoverageFetch = Date.now();
      if (this.activeTab === 'geofence' && this.mapMode === 'heatmap') {
        this.renderGeofenceCanvas();
      }
    }
  } catch (err) {
    console.warn('Coverage API offline or unreachable:', err);
  }
}
```

In `switchTab(tabName)`:
```javascript
if (tabName === 'geofence') {
  if (this.mapMode === 'heatmap') {
    this.fetchCoverage();
  }
  this.renderGeofenceCanvas();
}
```

In background poll loop (`start()`):
```javascript
if (this.activeTab === 'geofence') {
  if (this.mapMode === 'heatmap') {
    // Poll coverage every ~3 seconds
    const now = Date.now();
    if (now - this.lastCoverageFetch > 3000) {
      this.fetchCoverage();
    }
  }
  this.renderGeofenceCanvas();
}
```

---

### 3.3 Normal Map Visualization Architecture

When `this.mapMode === 'normal'`:

1. **Radar Grid & Axes**:
   - Concentric circles at 40px intervals (`rgba(0, 229, 255, 0.12)`).
   - Crosshair axes through center `(cx, cy)`.
2. **Equirectangular Projection**:
   - Computes dynamic bounding radius from geofence config (`circle_radius_m` or polygon bounding radius).
   - Scale factor: `scale = maxR / maxDistanceM`.
   - Function `toCanvasCoords(lat, lon)`:
     ```javascript
     const dx = (lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
     const dy = -(lat - centerLat) * 110540 * scale;
     return { px: cx + dx, py: cy + dy };
     ```
3. **Geofence Boundary**:
   - Circular: Yellow dashed line (`#ffeb3b`, dash `[6, 4]`, width 2), with faint envelope tint `rgba(255, 235, 59, 0.03)`.
   - Polygon: Traced through `polygon_vertices` in yellow dashed line with faint fill.
4. **Search Boundary (Perimeter)**:
   - If `this.coverageData && this.coverageData.boundary_geo`:
     - Drawn as an orange dashed perimeter (`rgba(255, 152, 0, 0.8)`, dash `[4, 4]`, width 1.5).
     - Label: `SEARCH BOUNDARY` in orange monospace text.
5. **Waypoints**:
   - Connected via magenta lines (`rgba(233, 30, 99, 0.6)`) with numbered waypoint markers.
6. **Historical Flight Path Breadcrumbs**:
   - Connected polyline in cyan dashed line (`rgba(0, 229, 255, 0.4)`, dash `[3, 3]`).
   - Breadcrumb markers with time-based alpha gradient: oldest points at $\alpha=0.15$, recent points at $\alpha=0.70$.
7. **Real-time GPS Drone Marker**:
   - If telemetry connected and has valid fix:
     - Outer glowing pulse circle: radius 9px, `rgba(0, 229, 255, 0.25)`.
     - Core solid dot: radius 5px, `#00e5ff`.
     - Heading vector line: length 24px, oriented along `(heading_deg - 90) * Math.PI / 180`, `#00e5ff`.
8. **HUD Overlays**:
   - **Disconnected**:
     If `!telem || !telem.connected`:
     Render high-contrast red warning box:
     `⚠️ MAVLINK DISCONNECTED // WAITING FOR TELEMETRY`
     Subtext: `Pixhawk TELEM2 /dev/serial0 offline • Check physical UART & power`
   - **Waiting for GPS Lock**:
     If `telem.connected && (telem.gps_fix_type < 2 || !telem.latitude || (telem.latitude === 0 && telem.longitude === 0))`:
     Render amber warning box:
     `🛰️ WAITING FOR GPS FIX // NO SATELLITE LOCK`
     Subtext: `Fix: ${fixName} • Satellites: ${sats} • HDOP: ${hdop} • Awaiting 3D lock`
   - **Normal 3D Fix**:
     If connected with valid 3D GPS fix:
     Render subtle status tag in top-left corner:
     `● GPS ${fixName} (${sats} Sats) • ${lat.toFixed(5)}, ${lon.toFixed(5)} • Alt: ${alt}m`

---

### 3.4 Heatmap Visualization Architecture

When `this.mapMode === 'heatmap'`:

1. **Background & Muted Boundary**:
   - Subtle radar rings and axes.
   - Geofence boundary drawn in muted yellow (`rgba(255, 235, 59, 0.4)`, dash `[4, 4]`) so situational envelope is maintained.
2. **Thermal Color Gradient Grid Rendering**:
   - Iterates through `this.coverageData.scanned_points`.
   - Each point contains `{lat, lon, radius_m, intensity}`.
   - Converts to canvas coordinates `(px, py)` and pixel radius `r = Math.max(3, (radius_m || 2.4) * scale)`.
   - Evaluates `getThermalColor(intensity, alpha)`:
     - $I \in [0.0, 0.25]$: Cyan (`rgba(0, 229, 255, alpha)`)
     - $I \in (0.25, 0.50]$: Green (`rgba(0, 230, 118, alpha)`)
     - $I \in (0.50, 0.75]$: Amber (`rgba(255, 171, 0, alpha)`)
     - $I > 0.75$: Red (`rgba(255, 23, 68, alpha)`)
   - Uses radial gradient fills (`createRadialGradient`) for smooth natural heat falloff.
3. **Observation Intensity Hotspots**:
   - If `this.coverageData.observations` contains detections:
     - Renders a glowing red/magenta beacon (`#ff1744`) with outer ring and text tag (e.g. `🎯 QR #1`).
4. **Live Drone Marker**:
   - Shows current drone position and heading vector in Heatmap mode so the operator tracks current scanning in real-time.
5. **Coverage Statistics HUD**:
   - Top-left glassmorphic HUD panel displaying:
     - Header: `HEATMAP COVERAGE: ${coverage_pct.toFixed(1)}%` (Cyan bold)
     - Scanned Area: `${scanned_area_m2} m² / ${total_area_m2} m²` (White)
     - Grid Cells: `${scanned_cells_count} / ${total_cells_count} cells (Res: ${grid_res}m)` (Muted)
6. **Awaiting Telemetry State**:
   - If `!this.coverageData || !this.coverageData.scanned_points || this.coverageData.scanned_points.length === 0`:
     - Displays centered amber HUD:
       `SEARCH GRID READY // AWAITING COVERAGE TELEMETRY (0.0% Scanned)`

---

## 4. Complete Implementation Diffs & Line-by-Line Changes

### 4.1 Target File: `frontend/index.html`

**Location**: Lines 841–856  
**Existing Content**:
```html
            <!-- 2D Canvas Visualizer -->
            <div class="card">
              <div class="card-header">
                <span class="card-title">Geofence Radar Visualizer</span>
                <span class="card-badge highlight" id="geofenceSafetyBadge">SAFE ENVELOPE</span>
              </div>
              <div class="card-body">
                <div class="map-canvas-container">
                  <canvas id="geofenceCanvas"></canvas>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted);">
                  <span>● Cyan: Drone Position</span>
                  <span>○ Yellow: Boundary Limit</span>
                  <span>▲ Magenta: Waypoints</span>
                </div>
              </div>
            </div>
```

**Replacement Content**:
```html
            <!-- 2D Canvas Visualizer -->
            <div class="card">
              <div class="card-header">
                <div class="card-title-group">
                  <span class="card-title">Geofence &amp; Navigation Visualizer</span>
                </div>
                <div style="display: flex; gap: 8px; align-items: center;">
                  <div class="camera-actions" id="mapModeToggleGroup">
                    <button class="btn btn-sm btn-ghost active" id="btnMapNormal" title="Normal Navigation Map">Normal Map</button>
                    <button class="btn btn-sm btn-ghost" id="btnMapHeatmap" title="Search Coverage &amp; Observation Heatmap">Heatmap</button>
                  </div>
                  <span class="card-badge highlight" id="geofenceSafetyBadge">SAFE ENVELOPE</span>
                </div>
              </div>
              <div class="card-body">
                <div class="map-canvas-container">
                  <canvas id="geofenceCanvas"></canvas>
                </div>
                <!-- Dynamic Legend for Normal Map -->
                <div id="mapLegendNormal" style="display: flex; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted); flex-wrap: wrap; gap: 6px;">
                  <span>● Cyan: Drone Position</span>
                  <span>○ Yellow: Geofence Limit</span>
                  <span>▢ Orange: Search Boundary</span>
                  <span>▲ Magenta: Waypoints</span>
                  <span>┈ Cyan Trail: Flight Path</span>
                </div>
                <!-- Dynamic Legend for Heatmap -->
                <div id="mapLegendHeatmap" style="display: none; justify-content: space-between; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted); flex-wrap: wrap; gap: 6px;">
                  <span>🟦 Cyan: Low Coverage</span>
                  <span>🟩 Green: Medium</span>
                  <span>🟨 Amber: High</span>
                  <span>🟥 Red: QR / Target Hotspot</span>
                  <span>○ Yellow: Boundary Limit</span>
                </div>
              </div>
            </div>
```

---

### 4.2 Target File: `frontend/css/dashboard.css`

**Location**: Lines 955–970 (append responsive and header wrapping enhancements)  
**Addition Content**:
```css
/* Geofence & Navigation Map Enhancements */
#mapModeToggleGroup {
  margin-right: 4px;
}

@media (max-width: 600px) {
  #pane-geofence .card-header {
    flex-wrap: wrap;
    gap: 8px;
  }
}
```

---

### 4.3 Target File: `frontend/js/dashboard.js`

#### Modification A: Constructor Properties
**Location**: In `constructor()`, lines 17–20:
```javascript
<<<< BEFORE
    // State caches
    this.currentTelemetry = null;
    this.geofenceConfig = null;
    this.activeMission = null;
==== AFTER
    // State caches
    this.currentTelemetry = null;
    this.geofenceConfig = null;
    this.activeMission = null;

    // Visualizer Mode & History
    this.mapMode = 'normal'; // 'normal' | 'heatmap'
    this.coverageData = null;
    this.flightPathHistory = []; // Ring buffer up to 300 points
    this.maxBreadcrumbs = 300;
    this.lastCoverageFetch = 0;
>>>>
```

#### Modification B: Element Registration
**Location**: In `initElements()`, around line 220:
```javascript
<<<< BEFORE
    // Geofence Elements
    this.geofenceSafetyBadge = document.getElementById('geofenceSafetyBadge');
    this.geofenceCanvas = document.getElementById('geofenceCanvas');
==== AFTER
    // Geofence Elements
    this.geofenceSafetyBadge = document.getElementById('geofenceSafetyBadge');
    this.geofenceCanvas = document.getElementById('geofenceCanvas');
    this.btnMapNormal = document.getElementById('btnMapNormal');
    this.btnMapHeatmap = document.getElementById('btnMapHeatmap');
    this.mapLegendNormal = document.getElementById('mapLegendNormal');
    this.mapLegendHeatmap = document.getElementById('mapLegendHeatmap');
>>>>
```

#### Modification C: Event Listeners
**Location**: In `bindEvents()`, around line 387:
```javascript
    if (this.btnEmergencyRTL) {
      this.btnEmergencyRTL.addEventListener('click', () => this.setFlightMode('RTL'));
    }

    // Map Mode Toggle
    if (this.btnMapNormal) {
      this.btnMapNormal.addEventListener('click', () => this.setMapMode('normal'));
    }
    if (this.btnMapHeatmap) {
      this.btnMapHeatmap.addEventListener('click', () => this.setMapMode('heatmap'));
    }
```

#### Modification D: Tab Switching & Telemetry Loop
**Location**: In `switchTab()`, around lines 421–424:
```javascript
<<<< BEFORE
    if (tabName === 'geofence') {
      this.renderGeofenceCanvas();
    }
==== AFTER
    if (tabName === 'geofence') {
      if (this.mapMode === 'heatmap') {
        this.fetchCoverage();
      }
      this.renderGeofenceCanvas();
    }
>>>>
```

**Location**: In background telemetry loop (`start()`), around line 438:
```javascript
<<<< BEFORE
      if (this.activeTab === 'geofence') {
        this.renderGeofenceCanvas();
      }
==== AFTER
      if (this.activeTab === 'geofence') {
        if (this.mapMode === 'heatmap') {
          const now = Date.now();
          if (now - this.lastCoverageFetch > 3000) {
            this.fetchCoverage();
          }
        }
        this.renderGeofenceCanvas();
      }
>>>>
```

**Location**: In `fetchAll()`, around line 454:
```javascript
    this.fetchGeofence();
    this.fetchCoverage();
    this.fetchCapturesList();
```

**Location**: In `fetchTelemetry()`, around line 563:
```javascript
<<<< BEFORE
      if (json.status === 'success' && json.data) {
        this.currentTelemetry = json.data;
        this.updateTelemetryUI(json.data);
      }
==== AFTER
      if (json.status === 'success' && json.data) {
        this.currentTelemetry = json.data;
        this.updateTelemetryUI(json.data);
        if (json.data.connected && json.data.latitude && json.data.longitude &&
            (json.data.latitude !== 0.0 || json.data.longitude !== 0.0)) {
          this.recordBreadcrumb(json.data.latitude, json.data.longitude, json.data.altitude_relative_m);
        }
      }
>>>>
```

#### Modification E: New Methods & Overhauled `renderGeofenceCanvas()`
**Location**: Replace lines 1576–1703 in `frontend/js/dashboard.js`:

```javascript
  // -------------------------------------------------------------
  // Map Visualizer: Mode Control & Data Fetching
  // -------------------------------------------------------------
  setMapMode(mode) {
    if (this.mapMode === mode) return;
    this.mapMode = mode;

    if (this.btnMapNormal) this.btnMapNormal.classList.toggle('active', mode === 'normal');
    if (this.btnMapHeatmap) this.btnMapHeatmap.classList.toggle('active', mode === 'heatmap');

    if (this.mapLegendNormal) this.mapLegendNormal.style.display = (mode === 'normal') ? 'flex' : 'none';
    if (this.mapLegendHeatmap) this.mapLegendHeatmap.style.display = (mode === 'heatmap') ? 'flex' : 'none';

    if (mode === 'heatmap') {
      this.fetchCoverage();
    }
    this.renderGeofenceCanvas();
  }

  recordBreadcrumb(lat, lon, alt) {
    if (!lat || !lon || (lat === 0.0 && lon === 0.0)) return;
    const last = this.flightPathHistory[this.flightPathHistory.length - 1];
    if (last) {
      const dLat = (lat - last.lat) * 110540;
      const dLon = (lon - last.lon) * 111320 * Math.cos(lat * Math.PI / 180);
      if (Math.hypot(dLat, dLon) < 0.4) return;
    }
    this.flightPathHistory.push({ lat, lon, alt, t: Date.now() });
    if (this.flightPathHistory.length > this.maxBreadcrumbs) {
      this.flightPathHistory.shift();
    }
  }

  async fetchCoverage() {
    try {
      const res = await fetch('/api/geofence/coverage');
      if (!res.ok) return;
      const json = await res.json();
      const data = json.data || json;
      if (data.status === 'success' || data.total_area_m2 !== undefined) {
        this.coverageData = data;
        this.lastCoverageFetch = Date.now();
        if (this.activeTab === 'geofence' && this.mapMode === 'heatmap') {
          this.renderGeofenceCanvas();
        }
      }
    } catch (err) {
      console.warn('Coverage API offline or unreachable:', err);
    }
  }

  getThermalColor(intensity, alpha = 0.5) {
    const val = Math.max(0, Math.min(1, intensity));
    let r, g, b;
    if (val < 0.25) {
      const t = val / 0.25;
      r = 0;
      g = Math.round(100 + 129 * t);
      b = 255;
    } else if (val < 0.5) {
      const t = (val - 0.25) / 0.25;
      r = 0;
      g = Math.round(229 + 1 * t);
      b = Math.round(255 * (1 - t) + 118 * t);
    } else if (val < 0.75) {
      const t = (val - 0.5) / 0.25;
      r = Math.round(255 * t);
      g = Math.round(230 - 59 * t);
      b = Math.round(118 * (1 - t));
    } else {
      const t = (val - 0.75) / 0.25;
      r = 255;
      g = Math.round(171 * (1 - t) + 23 * t);
      b = Math.round(68 * t);
    }
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  drawRoundedRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  // -------------------------------------------------------------
  // Overhauled 2D Canvas Visualizer (Normal & Heatmap)
  // -------------------------------------------------------------
  renderGeofenceCanvas() {
    if (!this.geofenceCanvas) return;
    const canvas = this.geofenceCanvas;
    const ctx = canvas.getContext('2d');

    // Handle high DPI container sizing
    const width = canvas.parentElement.clientWidth || 400;
    const height = canvas.parentElement.clientHeight || 350;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    ctx.clearRect(0, 0, width, height);
    const cx = width / 2;
    const cy = height / 2;

    // Draw Radar rings
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.12)';
    ctx.lineWidth = 1;
    for (let r = 40; r < Math.min(width, height) / 2; r += 40) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Radar crosshairs
    ctx.beginPath();
    ctx.moveTo(cx, 10);
    ctx.lineTo(cx, height - 10);
    ctx.moveTo(10, cy);
    ctx.lineTo(width - 10, cy);
    ctx.stroke();

    // Default configuration fallbacks if backend geofence not loaded yet
    const config = this.geofenceConfig || {
      fence_type: 'circular',
      circle_center_lat: 37.4093,
      circle_center_lon: -122.0641,
      circle_radius_m: 250
    };

    const centerLat = config.circle_center_lat || 37.4093;
    const centerLon = config.circle_center_lon || -122.0641;
    let fenceRadiusM = config.circle_radius_m || 250;

    // In polygon mode, calculate bounding radius to scale canvas properly
    if (config.fence_type !== 'circular' && config.polygon_vertices && config.polygon_vertices.length > 2) {
      let maxDist = 50;
      config.polygon_vertices.forEach(p => {
        const dx = (p.lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180);
        const dy = (p.lat - centerLat) * 110540;
        const d = Math.hypot(dx, dy);
        if (d > maxDist) maxDist = d;
      });
      fenceRadiusM = maxDist * 1.15;
    }

    const maxR = Math.min(width, height) * 0.38;
    const scale = maxR / Math.max(50, fenceRadiusM);

    const toCanvasCoords = (lat, lon) => {
      const dx = (lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
      const dy = -(lat - centerLat) * 110540 * scale;
      return { px: cx + dx, py: cy + dy };
    };

    // ==========================================
    // RENDER MODE: HEATMAP
    // ==========================================
    if (this.mapMode === 'heatmap') {
      // 1. Draw Muted Geofence Boundary
      ctx.strokeStyle = 'rgba(255, 235, 59, 0.4)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      if (config.fence_type === 'circular') {
        ctx.beginPath();
        ctx.arc(cx, cy, (config.circle_radius_m || 250) * scale, 0, Math.PI * 2);
        ctx.stroke();
      } else if (config.polygon_vertices && config.polygon_vertices.length > 2) {
        ctx.beginPath();
        config.polygon_vertices.forEach((p, idx) => {
          const pt = toCanvasCoords(p.lat, p.lon);
          if (idx === 0) ctx.moveTo(pt.px, pt.py);
          else ctx.lineTo(pt.px, pt.py);
        });
        ctx.closePath();
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // 2. Render Discretized Coverage Grid Cells with Thermal Gradient
      const cov = this.coverageData;
      if (cov && Array.isArray(cov.scanned_points) && cov.scanned_points.length > 0) {
        cov.scanned_points.forEach(p => {
          const pt = toCanvasCoords(p.lat, p.lon);
          const intensity = p.intensity !== undefined ? p.intensity : 0.6;
          const cellRadius = Math.max(3, (p.radius_m || 2.4) * scale);

          const grad = ctx.createRadialGradient(pt.px, pt.py, 0, pt.px, pt.py, cellRadius);
          grad.addColorStop(0, this.getThermalColor(intensity, 0.7));
          grad.addColorStop(0.7, this.getThermalColor(intensity, 0.4));
          grad.addColorStop(1, this.getThermalColor(intensity, 0.0));

          ctx.fillStyle = grad;
          ctx.beginPath();
          ctx.arc(pt.px, pt.py, cellRadius, 0, Math.PI * 2);
          ctx.fill();
        });
      }

      // 3. Render Vision Observation Intensity Hotspots (Target / QR detections)
      if (cov && Array.isArray(cov.observations)) {
        cov.observations.forEach(obs => {
          const pt = toCanvasCoords(obs.lat, obs.lon);
          ctx.fillStyle = 'rgba(255, 23, 68, 0.3)';
          ctx.beginPath();
          ctx.arc(pt.px, pt.py, 12, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = '#ff1744';
          ctx.beginPath();
          ctx.arc(pt.px, pt.py, 5, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = '#ffffff';
          ctx.font = 'bold 9px JetBrains Mono, monospace';
          ctx.fillText(obs.label || 'TARGET', pt.px + 8, pt.py - 4);
        });
      }

      // 4. Real-time Drone Marker in Heatmap Mode
      const telem = this.currentTelemetry;
      if (telem && telem.connected && telem.gps_fix_type >= 2 && telem.latitude && (telem.latitude !== 0.0 || telem.longitude !== 0.0)) {
        const dronePt = toCanvasCoords(telem.latitude, telem.longitude);

        ctx.fillStyle = 'rgba(0, 229, 255, 0.3)';
        ctx.beginPath();
        ctx.arc(dronePt.px, dronePt.py, 9, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = '#00e5ff';
        ctx.beginPath();
        ctx.arc(dronePt.px, dronePt.py, 5, 0, Math.PI * 2);
        ctx.fill();

        const headingRad = ((telem.heading_deg || 0) - 90) * Math.PI / 180;
        ctx.strokeStyle = '#00e5ff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(dronePt.px, dronePt.py);
        ctx.lineTo(dronePt.px + Math.cos(headingRad) * 20, dronePt.py + Math.sin(headingRad) * 20);
        ctx.stroke();
      }

      // 5. Coverage Stats HUD Overlay
      if (cov) {
        ctx.save();
        const pct = (cov.coverage_pct !== undefined ? cov.coverage_pct : 0.0).toFixed(1);
        const scannedM2 = Math.round(cov.scanned_area_m2 || 0).toLocaleString();
        const totalM2 = Math.round(cov.total_area_m2 || 0).toLocaleString();
        const scannedCells = cov.scanned_cells_count || 0;
        const totalCells = cov.total_cells_count || 0;

        const boxW = Math.min(width - 24, 340);
        const boxH = 58;
        const bx = 12;
        const by = 12;

        ctx.fillStyle = 'rgba(6, 9, 16, 0.88)';
        ctx.strokeStyle = 'rgba(0, 229, 255, 0.4)';
        ctx.lineWidth = 1;
        this.drawRoundedRect(ctx, bx, by, boxW, boxH, 4);
        ctx.fill();
        ctx.stroke();

        ctx.font = 'bold 12px JetBrains Mono, monospace';
        ctx.fillStyle = '#00e5ff';
        ctx.fillText(`HEATMAP COVERAGE: ${pct}%`, bx + 12, by + 20);

        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.fillText(`Scanned: ${scannedM2} m² / ${totalM2} m²`, bx + 12, by + 36);

        ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
        ctx.fillText(`Discretized Grid: ${scannedCells} / ${totalCells} cells`, bx + 12, by + 50);
        ctx.restore();
      } else {
        // Awaiting telemetry
        ctx.save();
        const bannerW = Math.min(width - 40, 460);
        const bannerH = 56;
        const bx = (width - bannerW) / 2;
        const by = 25;

        ctx.fillStyle = 'rgba(28, 20, 6, 0.88)';
        ctx.strokeStyle = 'rgba(255, 171, 0, 0.7)';
        ctx.lineWidth = 1.5;
        this.drawRoundedRect(ctx, bx, by, bannerW, bannerH, 6);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = '#ffab00';
        ctx.fillRect(bx, by, 5, bannerH);
        ctx.font = 'bold 11px JetBrains Mono, monospace';
        ctx.fillText('SEARCH GRID INITIALIZED // AWAITING COVERAGE TELEMETRY', bx + 16, by + 24);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText('Coverage algorithm standing by for Pixhawk GPS coordinate updates', bx + 16, by + 42);
        ctx.restore();
      }
      return;
    }

    // ==========================================
    // RENDER MODE: NORMAL MAP
    // ==========================================

    // 1. Draw Geofence Boundary (Yellow dashed line + subtle envelope tint)
    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);

    if (config.fence_type === 'circular') {
      const fenceR = (config.circle_radius_m || 250) * scale;
      ctx.fillStyle = 'rgba(255, 235, 59, 0.03)';
      ctx.beginPath();
      ctx.arc(cx, cy, fenceR, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (config.polygon_vertices && config.polygon_vertices.length > 2) {
      ctx.fillStyle = 'rgba(255, 235, 59, 0.03)';
      ctx.beginPath();
      config.polygon_vertices.forEach((p, idx) => {
        const pt = toCanvasCoords(p.lat, p.lon);
        if (idx === 0) ctx.moveTo(pt.px, pt.py);
        else ctx.lineTo(pt.px, pt.py);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // 2. Draw Search Boundary (Orange dashed line)
    if (this.coverageData && Array.isArray(this.coverageData.boundary_geo) && this.coverageData.boundary_geo.length > 2) {
      ctx.strokeStyle = 'rgba(255, 152, 0, 0.7)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      this.coverageData.boundary_geo.forEach((p, idx) => {
        const pt = toCanvasCoords(p.lat, p.lon);
        if (idx === 0) ctx.moveTo(pt.px, pt.py);
        else ctx.lineTo(pt.px, pt.py);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 3. Draw Mission Waypoints (Magenta)
    if (this.activeMission && Array.isArray(this.activeMission.waypoints)) {
      ctx.strokeStyle = 'rgba(233, 30, 99, 0.6)';
      ctx.fillStyle = '#e91e63';
      ctx.lineWidth = 2;

      ctx.beginPath();
      this.activeMission.waypoints.forEach((wp, idx) => {
        const pt = toCanvasCoords(wp.lat, wp.lon);
        if (idx === 0) ctx.moveTo(pt.px, pt.py);
        else ctx.lineTo(pt.px, pt.py);
      });
      ctx.stroke();

      this.activeMission.waypoints.forEach(wp => {
        const pt = toCanvasCoords(wp.lat, wp.lon);
        ctx.beginPath();
        ctx.arc(pt.px, pt.py, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.fillText(`#${wp.seq}`, pt.px + 6, pt.py - 4);
        ctx.fillStyle = '#e91e63';
      });
    }

    // 4. Draw Historical Flight Path Breadcrumbs (Ring buffer)
    if (this.flightPathHistory && this.flightPathHistory.length > 1) {
      const hist = this.flightPathHistory;
      const total = hist.length;

      // Connecting polyline
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.35)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      for (let i = 0; i < total; i++) {
        const pt = toCanvasCoords(hist[i].lat, hist[i].lon);
        if (i === 0) ctx.moveTo(pt.px, pt.py);
        else ctx.lineTo(pt.px, pt.py);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Breadcrumb dots with fading alpha
      const step = total > 100 ? 3 : (total > 50 ? 2 : 1);
      for (let i = 0; i < total; i += step) {
        const pt = toCanvasCoords(hist[i].lat, hist[i].lon);
        const alpha = 0.15 + 0.55 * (i / total);
        ctx.fillStyle = `rgba(0, 229, 255, ${alpha.toFixed(2)})`;
        ctx.beginPath();
        ctx.arc(pt.px, pt.py, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // 5. Draw Real-time GPS Drone Marker & Heading Vector
    const telem = this.currentTelemetry;
    const isConnected = telem && telem.connected;
    const hasGpsFix = isConnected && telem.gps_fix_type >= 2 && telem.latitude && (telem.latitude !== 0.0 || telem.longitude !== 0.0);

    if (hasGpsFix) {
      const dronePt = toCanvasCoords(telem.latitude, telem.longitude);

      // Outer glow pulse
      ctx.fillStyle = 'rgba(0, 229, 255, 0.25)';
      ctx.beginPath();
      ctx.arc(dronePt.px, dronePt.py, 9, 0, Math.PI * 2);
      ctx.fill();

      // Solid cyan core
      ctx.fillStyle = '#00e5ff';
      ctx.beginPath();
      ctx.arc(dronePt.px, dronePt.py, 5, 0, Math.PI * 2);
      ctx.fill();

      // Heading vector line
      const headingRad = ((telem.heading_deg || 0) - 90) * Math.PI / 180;
      ctx.strokeStyle = '#00e5ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(dronePt.px, dronePt.py);
      ctx.lineTo(dronePt.px + Math.cos(headingRad) * 24, dronePt.py + Math.sin(headingRad) * 24);
      ctx.stroke();

      // 6. Subtle 3D Fix Telemetry HUD Tag
      ctx.save();
      const pad = 12;
      const tagH = 26;
      const sats = telem.satellites_visible || 0;
      const fix = telem.gps_fix_name || '3D Fix';
      const latStr = telem.latitude.toFixed(5);
      const lonStr = telem.longitude.toFixed(5);
      const altStr = (telem.altitude_relative_m || 0).toFixed(1);
      const hudText = `GPS ${fix} (${sats} Sats) • ${latStr}, ${lonStr} • Alt: ${altStr}m`;

      ctx.font = '10px JetBrains Mono, monospace';
      const tagW = ctx.measureText(hudText).width + 26;

      ctx.fillStyle = 'rgba(6, 9, 16, 0.85)';
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.35)';
      ctx.lineWidth = 1;
      this.drawRoundedRect(ctx, pad, pad, tagW, tagH, 4);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#00e676';
      ctx.beginPath();
      ctx.arc(pad + 10, pad + tagH / 2, 3.5, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = '#00e5ff';
      ctx.fillText(hudText, pad + 18, pad + 17);
      ctx.restore();

    } else if (!isConnected) {
      // 7. Disconnected State Warning Banner
      ctx.save();
      const bannerW = Math.min(width - 40, 480);
      const bannerH = 70;
      const bx = (width - bannerW) / 2;
      const by = 25;

      ctx.fillStyle = 'rgba(22, 6, 8, 0.88)';
      ctx.strokeStyle = 'rgba(255, 23, 68, 0.7)';
      ctx.lineWidth = 1.5;
      this.drawRoundedRect(ctx, bx, by, bannerW, bannerH, 6);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#ff1744';
      ctx.fillRect(bx, by, 5, bannerH);

      ctx.fillStyle = '#ff5252';
      ctx.font = 'bold 12px JetBrains Mono, monospace';
      ctx.fillText('⚠️ MAVLINK DISCONNECTED // WAITING FOR TELEMETRY', bx + 18, by + 28);

      ctx.fillStyle = 'rgba(255, 255, 255, 0.65)';
      ctx.font = '10px Inter, sans-serif';
      ctx.fillText('Pixhawk TELEM2 /dev/serial0 offline • Check physical UART & power', bx + 18, by + 48);
      ctx.restore();

    } else {
      // 8. Waiting for GPS Lock Warning Banner
      ctx.save();
      const bannerW = Math.min(width - 40, 480);
      const bannerH = 70;
      const bx = (width - bannerW) / 2;
      const by = 25;

      ctx.fillStyle = 'rgba(28, 20, 6, 0.88)';
      ctx.strokeStyle = 'rgba(255, 171, 0, 0.7)';
      ctx.lineWidth = 1.5;
      this.drawRoundedRect(ctx, bx, by, bannerW, bannerH, 6);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#ffab00';
      ctx.fillRect(bx, by, 5, bannerH);

      ctx.fillStyle = '#ffab00';
      ctx.font = 'bold 12px JetBrains Mono, monospace';
      ctx.fillText('🛰️ WAITING FOR GPS FIX // NO SATELLITE LOCK', bx + 18, by + 28);

      const fixName = telem.gps_fix_name || 'No Fix';
      const sats = telem.satellites_visible || 0;
      const hdop = telem.hdop !== undefined ? telem.hdop : '--';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
      ctx.font = '10px Inter, sans-serif';
      ctx.fillText(`Fix: ${fixName} • Satellites: ${sats} • HDOP: ${hdop} • Awaiting 3D lock`, bx + 18, by + 48);
      ctx.restore();
    }
  }
```

---

## 5. Verification & Testing Strategy

1. **Unit & Syntax Verification**:
   - Validate JavaScript syntax using node.js or powershell linting to confirm 0 parse errors.
2. **DOM & Event Binding Integrity**:
   - Verify `#btnMapNormal` and `#btnMapHeatmap` cleanly acquire active classes on click.
   - Verify legends `#mapLegendNormal` and `#mapLegendHeatmap` toggle without layout jumps.
3. **Canvas State Machine Robustness**:
   - Verify Disconnected HUD renders when MAVLink is offline.
   - Verify Waiting for GPS HUD renders when connected with fix type 0 or 1.
   - Verify 3D fix tag renders when valid GPS coordinates are received.
   - Verify breadcrumb buffer stores up to 300 points and drops oldest points beyond capacity.
   - Verify Heatmap renders thermal gradient without errors even if coverage data is initially null or empty.
4. **Existing API Compatibility**:
   - Run `pytest tests/test_api.py::test_frontend_index_route` to ensure HTTP 200 and `AUTONOMOUS-DRONE` root token pass 100%.

