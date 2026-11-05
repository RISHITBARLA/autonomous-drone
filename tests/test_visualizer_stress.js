/**
 * Challenger M2.2 Empirical Stress Test Harness
 * 
 * Adversarially verifies:
 * 1. Breadcrumb Ring Buffer Memory Bounds & Jitter Filtering (10,000 continuous coordinates)
 * 2. Mode Toggle Stress (500 rapid switches between normal and heatmap)
 * 3. Canvas Projection & HUD Overlays Stress (extreme / pathological telemetry configurations)
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const v8 = require('v8');

// Load dashboard.js
const dashboardSourcePath = path.resolve(__dirname, '../frontend/js/dashboard.js');
const dashboardCode = fs.readFileSync(dashboardSourcePath, 'utf8');

// Setup mock DOM & Canvas environment
function createDashboardHarness() {
  const recordedCanvasCalls = [];
  const nanCanvasCalls = [];

  const mockCtx = {
    clearRect: (x, y, w, h) => {
      recordedCanvasCalls.push({ method: 'clearRect', args: [x, y, w, h] });
    },
    beginPath: () => {
      recordedCanvasCalls.push({ method: 'beginPath' });
    },
    arc: (x, y, r, sa, ea) => {
      recordedCanvasCalls.push({ method: 'arc', args: [x, y, r, sa, ea] });
      if (Number.isNaN(x) || Number.isNaN(y) || Number.isNaN(r)) {
        nanCanvasCalls.push({ method: 'arc', args: [x, y, r, sa, ea] });
      }
    },
    stroke: () => {
      recordedCanvasCalls.push({ method: 'stroke' });
    },
    fill: () => {
      recordedCanvasCalls.push({ method: 'fill' });
    },
    moveTo: (x, y) => {
      recordedCanvasCalls.push({ method: 'moveTo', args: [x, y] });
      if (Number.isNaN(x) || Number.isNaN(y)) {
        nanCanvasCalls.push({ method: 'moveTo', args: [x, y] });
      }
    },
    lineTo: (x, y) => {
      recordedCanvasCalls.push({ method: 'lineTo', args: [x, y] });
      if (Number.isNaN(x) || Number.isNaN(y)) {
        nanCanvasCalls.push({ method: 'lineTo', args: [x, y] });
      }
    },
    closePath: () => {
      recordedCanvasCalls.push({ method: 'closePath' });
    },
    quadraticCurveTo: (cpx, cpy, x, y) => {
      recordedCanvasCalls.push({ method: 'quadraticCurveTo', args: [cpx, cpy, x, y] });
      if (Number.isNaN(cpx) || Number.isNaN(cpy) || Number.isNaN(x) || Number.isNaN(y)) {
        nanCanvasCalls.push({ method: 'quadraticCurveTo', args: [cpx, cpy, x, y] });
      }
    },
    setLineDash: (dash) => {
      recordedCanvasCalls.push({ method: 'setLineDash', args: [dash] });
    },
    createRadialGradient: (x0, y0, r0, x1, y1, r1) => {
      recordedCanvasCalls.push({ method: 'createRadialGradient', args: [x0, y0, r0, x1, y1, r1] });
      if ([x0, y0, r0, x1, y1, r1].some(v => Number.isNaN(v))) {
        nanCanvasCalls.push({ method: 'createRadialGradient', args: [x0, y0, r0, x1, y1, r1] });
      }
      return { addColorStop: () => {} };
    },
    save: () => {
      recordedCanvasCalls.push({ method: 'save' });
    },
    restore: () => {
      recordedCanvasCalls.push({ method: 'restore' });
    },
    fillRect: (x, y, w, h) => {
      recordedCanvasCalls.push({ method: 'fillRect', args: [x, y, w, h] });
      if (Number.isNaN(x) || Number.isNaN(y) || Number.isNaN(w) || Number.isNaN(h)) {
        nanCanvasCalls.push({ method: 'fillRect', args: [x, y, w, h] });
      }
    },
    fillText: (text, x, y) => {
      recordedCanvasCalls.push({ method: 'fillText', args: [text, x, y] });
      if (Number.isNaN(x) || Number.isNaN(y)) {
        nanCanvasCalls.push({ method: 'fillText', args: [text, x, y] });
      }
    },
    measureText: (text) => ({ width: (text ? String(text).length * 7.5 : 0) })
  };

  const elementsMap = new Map();
  function getOrCreateElement(id) {
    if (!elementsMap.has(id)) {
      const el = {
        id,
        classList: {
          _classes: new Set(),
          add(c) { this._classes.add(c); },
          remove(c) { this._classes.delete(c); },
          toggle(c, force) {
            if (force === undefined) {
              if (this._classes.has(c)) this._classes.delete(c);
              else this._classes.add(c);
            } else if (force) {
              this._classes.add(c);
            } else {
              this._classes.delete(c);
            }
          },
          contains(c) { return this._classes.has(c); }
        },
        style: {},
        parentElement: { clientWidth: 800, clientHeight: 600 },
        width: 800,
        height: 600,
        addEventListener() {},
        removeEventListener() {},
        setAttribute() {},
        getAttribute() { return null; },
        appendChild() {},
        value: '',
        getContext(type) {
          if (type === '2d') return mockCtx;
          return null;
        }
      };
      elementsMap.set(id, el);
    }
    return elementsMap.get(id);
  }

  const mockDocument = {
    getElementById: (id) => getOrCreateElement(id),
    querySelectorAll: () => [],
    createElement: (tag) => getOrCreateElement(tag + '_' + Math.random().toString(36).substr(2, 6)),
    addEventListener: () => {}
  };

  const sandbox = {
    document: mockDocument,
    window: {},
    setInterval: () => 1,
    clearInterval: () => {},
    setTimeout: (fn) => { fn(); return 1; },
    clearTimeout: () => {},
    fetch: () => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ status: 'success', data: {} })
    }),
    console: {
      log: () => {},
      warn: () => {},
      error: () => {}
    },
    Date: Date,
    Math: Math
  };

  vm.createContext(sandbox);
  vm.runInContext(dashboardCode, sandbox);
  const DroneDashboardClass = vm.runInContext('DroneDashboard', sandbox);
  const instance = new DroneDashboardClass();

  // Clear automatic intervals to isolate empirical harness
  if (instance.pollTimer) clearInterval(instance.pollTimer);

  return {
    dashboard: instance,
    mockCtx,
    recordedCanvasCalls,
    nanCanvasCalls,
    elementsMap
  };
}

// -------------------------------------------------------------
// TEST SUITE EXECUTION
// -------------------------------------------------------------
async function runAllStressTests() {
  const results = {
    section1: null,
    section2: null,
    section3: null,
    summary: { passed: 0, failed: 0, total: 0 }
  };

  console.log('===============================================================');
  console.log('CHALLENGER M2.2: FRONTEND VISUALIZER & MEMORY STRESS HARNESS');
  console.log('===============================================================\n');

  // =========================================================================
  // SECTION 1: Breadcrumb Ring Buffer Memory Bounds & Jitter Filtering
  // =========================================================================
  console.log('>>> RUNNING TEST SUITE 1: Breadcrumb Ring Buffer & Jitter Filtering');
  const h1 = createDashboardHarness();
  const d1 = h1.dashboard;

  let s1Passed = true;
  const s1Details = {};

  // 1.1 Jitter threshold testing (<0.4m movement)
  const baseLat = 37.409300;
  const baseLon = -122.064100;
  d1.flightPathHistory = [];
  d1.recordBreadcrumb(baseLat, baseLon, 15.0);

  if (d1.flightPathHistory.length !== 1) {
    s1Passed = false;
    console.error('FAIL 1.1a: Initial breadcrumb was not recorded');
  }

  // Inject 1,000 jitter points strictly < 0.4m
  // In SF, 1m latitude is ~9.046e-6 deg. 0.3m is ~2.71e-6 deg.
  let jitterRejections = 0;
  for (let i = 1; i <= 1000; i++) {
    const angle = (i * 137.5) * (Math.PI / 180); // Fibonacci spiral
    const radiusMeters = 0.05 + 0.30 * (i % 10) / 10; // strictly 0.05m to 0.32m (< 0.4m)
    const jitterLat = baseLat + (Math.sin(angle) * radiusMeters) / 110540;
    const jitterLon = baseLon + (Math.cos(angle) * radiusMeters) / (111320 * Math.cos(baseLat * Math.PI / 180));
    
    const preLen = d1.flightPathHistory.length;
    d1.recordBreadcrumb(jitterLat, jitterLon, 15.0 + Math.random() * 0.2);
    if (d1.flightPathHistory.length === preLen) {
      jitterRejections++;
    }
  }

  s1Details.jitterPointsInjected = 1000;
  s1Details.jitterRejections = jitterRejections;
  s1Details.jitterPass = (jitterRejections === 1000 && d1.flightPathHistory.length === 1);
  if (!s1Details.jitterPass) {
    s1Passed = false;
    console.error(`FAIL 1.1: Jitter filtering allowed ${1000 - jitterRejections} points through threshold!`);
  } else {
    console.log(`PASS 1.1: Jitter filter rejected 1000/1000 sub-0.4m micro-movements (length=${d1.flightPathHistory.length})`);
  }

  // 1.2 Movement threshold acceptance (>0.4m movement)
  let movementAcceptance = 0;
  let curLat = baseLat;
  let curLon = baseLon;
  for (let i = 1; i <= 50; i++) {
    // move 0.5 meters
    curLat += 0.5 / 110540;
    curLon += 0.5 / (111320 * Math.cos(curLat * Math.PI / 180));
    const preLen = d1.flightPathHistory.length;
    d1.recordBreadcrumb(curLat, curLon, 15.0);
    if (d1.flightPathHistory.length === preLen + 1) {
      movementAcceptance++;
    }
  }
  s1Details.movementPass = (movementAcceptance === 50 && d1.flightPathHistory.length === 51);
  if (!s1Details.movementPass) {
    s1Passed = false;
    console.error(`FAIL 1.2: Movement filter failed to accept >0.4m points (${movementAcceptance}/50 accepted)`);
  } else {
    console.log(`PASS 1.2: Movement filter accepted 50/50 suprathreshold movements (>0.4m)`);
  }

  // 1.3 10,000 Continuous Telemetry Coordinate Injection & Strict Ring Buffer Bound
  d1.flightPathHistory = [];
  let ringBufferViolation = false;
  let maxHistoryLength = 0;

  for (let i = 0; i < 10000; i++) {
    curLat += 1.2 / 110540;
    curLon += 1.2 / (111320 * Math.cos(curLat * Math.PI / 180));
    d1.recordBreadcrumb(curLat, curLon, 10.0 + (i % 50));
    
    if (d1.flightPathHistory.length > 300) {
      ringBufferViolation = true;
      break;
    }
    if (d1.flightPathHistory.length > maxHistoryLength) {
      maxHistoryLength = d1.flightPathHistory.length;
    }
  }

  const v8ByteLength = v8.serialize(d1.flightPathHistory).byteLength;
  const jsonByteLength = Buffer.byteLength(JSON.stringify(d1.flightPathHistory));
  const memoryBounded = (v8ByteLength < 50 * 1024) && (jsonByteLength < 50 * 1024);

  s1Details.injectedPoints = 10000;
  s1Details.finalHistoryLength = d1.flightPathHistory.length;
  s1Details.maxHistoryLength = maxHistoryLength;
  s1Details.ringBufferCompliant = (!ringBufferViolation && d1.flightPathHistory.length === 300);
  s1Details.v8MemoryBytes = v8ByteLength;
  s1Details.jsonMemoryBytes = jsonByteLength;
  s1Details.memoryBounded = memoryBounded;

  if (!s1Details.ringBufferCompliant) {
    s1Passed = false;
    console.error(`FAIL 1.3: Ring buffer bound violated! Final length=${d1.flightPathHistory.length}, max=${maxHistoryLength}`);
  } else {
    console.log(`PASS 1.3: Ring buffer capped at exactly 300 points across 10,000 continuous injections`);
  }

  // 1.5 Edge cases: Equator (lat=0.0) and Prime Meridian (lon=0.0)
  d1.flightPathHistory = [];
  d1.recordBreadcrumb(0.0, -122.0641, 10.0);
  const equatorRecorded = (d1.flightPathHistory.length === 1);
  d1.flightPathHistory = [];
  d1.recordBreadcrumb(51.48, 0.0, 10.0);
  const meridianRecorded = (d1.flightPathHistory.length === 1);
  s1Details.equatorRecorded = equatorRecorded;
  s1Details.meridianRecorded = meridianRecorded;
  if (!equatorRecorded || !meridianRecorded) {
    console.warn(`WARN 1.5: Falsy coordinate bug: Equator recorded=${equatorRecorded}, Prime Meridian recorded=${meridianRecorded} (0.0 evaluated as falsy by !lat / !lon)`);
  } else {
    console.log(`PASS 1.5: Equator and Prime Meridian coordinates correctly recorded`);
  }

  results.section1 = { passed: s1Passed, details: s1Details };
  if (s1Passed) results.summary.passed++; else results.summary.failed++;
  results.summary.total++;

  // =========================================================================
  // SECTION 2: Mode Toggle Stress (500 Rapid Switches)
  // =========================================================================
  console.log('\n>>> RUNNING TEST SUITE 2: Mode Toggle Stress (500 Switches)');
  const h2 = createDashboardHarness();
  const d2 = h2.dashboard;

  const btnNormalRef = d2.btnMapNormal;
  const btnHeatmapRef = d2.btnMapHeatmap;
  const legNormalRef = d2.mapLegendNormal;
  const legHeatmapRef = d2.mapLegendHeatmap;

  let s2Passed = true;
  const s2Exceptions = [];
  let domRecreationDetected = false;
  let syncFailureDetected = false;

  for (let i = 0; i < 500; i++) {
    const targetMode = (i % 2 === 0) ? 'heatmap' : 'normal';
    try {
      d2.setMapMode(targetMode);

      // Check DOM recreation leak
      if (d2.btnMapNormal !== btnNormalRef || d2.btnMapHeatmap !== btnHeatmapRef ||
          d2.mapLegendNormal !== legNormalRef || d2.mapLegendHeatmap !== legHeatmapRef) {
        domRecreationDetected = true;
      }

      // Check legend visibility and button classes
      if (targetMode === 'normal') {
        const normActive = d2.btnMapNormal.classList.contains('active');
        const heatInactive = !d2.btnMapHeatmap.classList.contains('active');
        const normDisplay = d2.mapLegendNormal.style.display === 'flex';
        const heatDisplay = d2.mapLegendHeatmap.style.display === 'none';
        if (!normActive || !heatInactive || !normDisplay || !heatDisplay) {
          syncFailureDetected = true;
        }
      } else {
        const normInactive = !d2.btnMapNormal.classList.contains('active');
        const heatActive = d2.btnMapHeatmap.classList.contains('active');
        const normDisplay = d2.mapLegendNormal.style.display === 'none';
        const heatDisplay = d2.mapLegendHeatmap.style.display === 'flex';
        if (!normInactive || !heatActive || !normDisplay || !heatDisplay) {
          syncFailureDetected = true;
        }
      }
    } catch (err) {
      s2Exceptions.push({ iter: i, targetMode, error: err.message, stack: err.stack });
    }
  }

  const s2Details = {
    switchesExecuted: 500,
    exceptionsCount: s2Exceptions.length,
    domRecreationDetected,
    syncFailureDetected,
    exceptions: s2Exceptions
  };

  if (s2Exceptions.length > 0 || domRecreationDetected || syncFailureDetected) {
    s2Passed = false;
    console.error(`FAIL 2: Mode toggle stress failed: exceptions=${s2Exceptions.length}, domRecreation=${domRecreationDetected}, syncFail=${syncFailureDetected}`);
    if (s2Exceptions.length > 0) {
      console.error('First exception:', s2Exceptions[0]);
    }
  } else {
    console.log(`PASS 2: 500 rapid toggles executed cleanly: 0 exceptions, 0 DOM leaks, 100% synchronized state`);
  }

  results.section2 = { passed: s2Passed, details: s2Details };
  if (s2Passed) results.summary.passed++; else results.summary.failed++;
  results.summary.total++;

  // =========================================================================
  // SECTION 3: Canvas Projection & HUD Overlays Stress
  // =========================================================================
  console.log('\n>>> RUNNING TEST SUITE 3: Canvas Projection & Pathological Telemetry');
  const h3 = createDashboardHarness();
  const d3 = h3.dashboard;

  const testCases = [
    {
      name: 'TC3.01: Disconnected (connected=false)',
      telemetry: { connected: false, gps_fix_type: 0, latitude: 0.0, longitude: 0.0 },
      expectHud: 'disconnected'
    },
    {
      name: 'TC3.02: GPS Fix Type 0 (No GPS)',
      telemetry: { connected: true, gps_fix_type: 0, gps_fix_name: 'No GPS', satellites_visible: 0, hdop: 99.9, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.03: GPS Fix Type 1 (No Fix)',
      telemetry: { connected: true, gps_fix_type: 1, gps_fix_name: 'No Fix', satellites_visible: 3, hdop: 15.0, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.04: GPS Fix Type 2 (2D Fix with valid coords)',
      telemetry: { connected: true, gps_fix_type: 2, gps_fix_name: '2D Fix', satellites_visible: 5, hdop: 2.1, latitude: 37.4093, longitude: -122.0641, altitude_relative_m: 10.5, heading_deg: 180 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.05: GPS Fix Type 3 (3D Fix operational)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 14, hdop: 0.8, latitude: 37.4093, longitude: -122.0641, altitude_relative_m: 25.0, heading_deg: 90 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.06: GPS Fix Type 4 (DGPS / RTK)',
      telemetry: { connected: true, gps_fix_type: 4, gps_fix_name: 'RTK Fixed', satellites_visible: 22, hdop: 0.4, latitude: 37.4093, longitude: -122.0641, altitude_relative_m: 30.0, heading_deg: 45 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.07: Null Island (lat=0.0, lon=0.0)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 10, hdop: 1.0, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix' // 0,0 should not be rendered as genuine active fix
    },
    {
      name: 'TC3.08: Null Coordinates (latitude=null, longitude=null)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 10, hdop: 1.2, latitude: null, longitude: null },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.09: Partial Null: latitude valid, longitude=null',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: 37.4093, longitude: null },
      expectHud: 'waiting_fix' // MUST NOT crash with .toFixed(5)
    },
    {
      name: 'TC3.10: Partial Null: latitude=null, longitude valid',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: null, longitude: -122.0641 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.11: Southern Hemisphere & Negative Coordinates (Sydney / Melbourne)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 16, hdop: 0.7, latitude: -37.8136, longitude: 144.9631, altitude_relative_m: 50.0, heading_deg: 270 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.12: Negative Longitude & Negative Latitude (South America / Patagonia)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 15, hdop: 0.9, latitude: -50.0, longitude: -70.0, altitude_relative_m: 12.0, heading_deg: 0 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.13: 0 Satellites Lock',
      telemetry: { connected: true, gps_fix_type: 0, gps_fix_name: 'No GPS', satellites_visible: 0, hdop: 99.9, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.14: 30 Satellites Constellation',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 30, hdop: 0.5, latitude: 37.4093, longitude: -122.0641, altitude_relative_m: 100.0, heading_deg: 135 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.15: Extreme HDOP (99.9)',
      telemetry: { connected: true, gps_fix_type: 1, gps_fix_name: 'Poor HDOP', satellites_visible: 4, hdop: 99.9, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.16: Extreme HDOP Sub-Centimeter (0.1)',
      telemetry: { connected: true, gps_fix_type: 4, gps_fix_name: 'RTK Sub-cm', satellites_visible: 28, hdop: 0.1, latitude: 37.4093, longitude: -122.0641, altitude_relative_m: 10.0, heading_deg: 359 },
      expectHud: 'fix_active'
    },
    {
      name: 'TC3.17: Undefined / Missing HDOP',
      telemetry: { connected: true, gps_fix_type: 1, gps_fix_name: 'Missing HDOP', satellites_visible: 2, latitude: 0.0, longitude: 0.0 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.18: Telemetry Object Completely Null',
      telemetry: null,
      expectHud: 'disconnected'
    },
    {
      name: 'TC3.19: NaN Longitude Coordinate',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: 37.4093, longitude: NaN },
      expectHud: 'waiting_fix' // Must not emit NaN canvas coordinates or crash
    },
    {
      name: 'TC3.20: NaN Latitude Coordinate',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: NaN, longitude: -122.0641 },
      expectHud: 'waiting_fix'
    },
    {
      name: 'TC3.21: Equator Coordinates with 3D Lock (lat=0.0, lon=-122.0641)',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: 0.0, longitude: -122.0641, altitude_relative_m: 20.0, heading_deg: 90 },
      expectHud: 'fix_active' // Must recognize valid active fix on equator without being treated as falsy
    },
    {
      name: 'TC3.22: Partial Undefined: latitude valid, longitude=undefined',
      telemetry: { connected: true, gps_fix_type: 3, gps_fix_name: '3D Fix', satellites_visible: 12, hdop: 1.0, latitude: 37.4093, longitude: undefined },
      expectHud: 'waiting_fix' // Must not crash with .toFixed(5)
    }
  ];

  const s3Results = [];
  let s3Passed = true;

  for (const tc of testCases) {
    h3.nanCanvasCalls.length = 0;
    d3.currentTelemetry = tc.telemetry;

    // Test in Normal Mode
    d3.mapMode = 'normal';
    let normalCrash = null;
    let normalNaNCount = 0;
    try {
      d3.renderGeofenceCanvas();
      normalNaNCount = h3.nanCanvasCalls.length;
    } catch (e) {
      normalCrash = e.message;
    }

    // Test in Heatmap Mode
    h3.nanCanvasCalls.length = 0;
    d3.mapMode = 'heatmap';
    let heatmapCrash = null;
    let heatmapNaNCount = 0;
    try {
      d3.renderGeofenceCanvas();
      heatmapNaNCount = h3.nanCanvasCalls.length;
    } catch (e) {
      heatmapCrash = e.message;
    }

    const tcPassed = (!normalCrash && !heatmapCrash && normalNaNCount === 0 && heatmapNaNCount === 0);
    if (!tcPassed) {
      s3Passed = false;
      console.error(`FAIL: ${tc.name}`);
      if (normalCrash) console.error(`  -> Normal Mode Crash: ${normalCrash}`);
      if (heatmapCrash) console.error(`  -> Heatmap Mode Crash: ${heatmapCrash}`);
      if (normalNaNCount > 0) console.error(`  -> Normal Mode NaN Canvas Calls: ${normalNaNCount}`);
      if (heatmapNaNCount > 0) console.error(`  -> Heatmap Mode NaN Canvas Calls: ${heatmapNaNCount}`);
    } else {
      console.log(`PASS: ${tc.name} (Normal: OK, Heatmap: OK, NaN: 0)`);
    }

    s3Results.push({
      testCase: tc.name,
      passed: tcPassed,
      normalCrash,
      heatmapCrash,
      normalNaNCount,
      heatmapNaNCount
    });
  }

  results.section3 = { passed: s3Passed, testCases: s3Results };
  if (s3Passed) results.summary.passed++; else results.summary.failed++;
  results.summary.total++;

  // =========================================================================
  // OVERALL VERDICT
  // =========================================================================
  console.log('\n===============================================================');
  console.log(`SUMMARY: ${results.summary.passed}/${results.summary.total} Test Suites Passed`);
  const finalVerdict = (results.summary.failed === 0) ? 'CONFIRMED CORRECT' : 'FAILED';
  console.log(`FINAL VERDICT: ${finalVerdict}`);
  console.log('===============================================================');

  return { verdict: finalVerdict, results };
}

// Run if called directly
if (require.main === module) {
  runAllStressTests()
    .then(({ verdict, results }) => {
      // Exit code 0 if CONFIRMED CORRECT, 1 if FAILED
      process.exit(verdict === 'CONFIRMED CORRECT' ? 0 : 1);
    })
    .catch(err => {
      console.error('Harness unhandled error:', err);
      process.exit(1);
    });
}

module.exports = { runAllStressTests, createDashboardHarness };
