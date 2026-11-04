/**
 * AUTONOMOUS-DRONE Ground Station & Companion Telemetry Controller
 * Integrates System Health, Camera Stream, QR Code Detection, Pixhawk MAVLink Telemetry,
 * Mission State Management, and Geofence Safety Radar.
 */

class DroneDashboard {
  constructor() {
    this.pollInterval = 1500; // 1.5 seconds telemetry loop
    this.pollTimer = null;
    this.isCapturing = false;
    this.streamMode = 'stream'; // 'stream' or 'inspect'
    this.latestCaptureData = null;
    this.activeTab = 'overview';

    // State caches
    this.currentTelemetry = null;
    this.geofenceConfig = null;
    this.activeMission = null;

    this.initElements();
    this.bindEvents();
    this.start();
  }

  initElements() {
    // Navigation
    this.navButtons = document.querySelectorAll('.nav-item');
    this.tabPanes = document.querySelectorAll('.tab-pane');
    this.pageTitle = document.getElementById('pageTitle');

    // Health & System Metrics
    this.uptimeDisplay = document.getElementById('uptimeDisplay');
    this.systemHealthBadge = document.getElementById('systemHealthBadge');
    this.topbarCameraSensor = document.getElementById('topbarCameraSensor');
    this.topbarMavlinkState = document.getElementById('topbarMavlinkState');

    this.cpuUsageVal = document.getElementById('cpuUsageVal');
    this.cpuProgressBar = document.getElementById('cpuProgressBar');
    this.cpuFreqText = document.getElementById('cpuFreqText');
    this.cpuCoresBadge = document.getElementById('cpuCoresBadge');

    this.tempCelsiusVal = document.getElementById('tempCelsiusVal');
    this.tempProgressBar = document.getElementById('tempProgressBar');
    this.tempFahrenheitText = document.getElementById('tempFahrenheitText');
    this.tempStatusBadge = document.getElementById('tempStatusBadge');

    this.ramUsageVal = document.getElementById('ramUsageVal');
    this.ramProgressBar = document.getElementById('ramProgressBar');
    this.ramSubText = document.getElementById('ramSubText');
    this.ramTotalBadge = document.getElementById('ramTotalBadge');

    // Telemetry Summary Card (Overview)
    this.batteryPercentVal = document.getElementById('batteryPercentVal');
    this.batteryProgressBar = document.getElementById('batteryProgressBar');
    this.batteryVoltsText = document.getElementById('batteryVoltsText');
    this.telemetryModeBadge = document.getElementById('telemetryModeBadge');

    // Sidebar & Hardware Specs
    this.sidebarRpiStatus = document.getElementById('sidebarRpiStatus');
    this.sidebarRpiModel = document.getElementById('sidebarRpiModel');
    this.rpiHeartbeatDot = document.getElementById('rpiHeartbeatDot');
    this.hwPlatformBadge = document.getElementById('hwPlatformBadge');

    this.specModel = document.getElementById('specModel');
    this.specSoc = document.getElementById('specSoc');
    this.specArch = document.getElementById('specArch');
    this.specOs = document.getElementById('specOs');
    this.specSerial = document.getElementById('specSerial');
    this.specHostname = document.getElementById('specHostname');

    // Camera Station
    this.cameraStreamImg = document.getElementById('cameraStreamImg');
    this.cameraLatestPreviewImg = document.getElementById('cameraLatestPreviewImg');
    this.btnStreamMode = document.getElementById('btnStreamMode');
    this.btnInspectMode = document.getElementById('btnInspectMode');
    this.btnCapturePhoto = document.getElementById('btnCapturePhoto');
    this.captureSpinner = document.getElementById('captureSpinner');
    this.captureBtnText = document.getElementById('captureBtnText');

    this.hudBackendTag = document.getElementById('hudBackendTag');
    this.hudResolutionTag = document.getElementById('hudResolutionTag');
    this.camSensorName = document.getElementById('camSensorName');
    this.camFlightMode = document.getElementById('camFlightMode');
    this.camCaptureCount = document.getElementById('camCaptureCount');
    this.camConnectionState = document.getElementById('camConnectionState');

    // Capture Details Panel
    this.captureTimestampBadge = document.getElementById('captureTimestampBadge');
    this.captureThumbnail = document.getElementById('captureThumbnail');
    this.emptyCaptureMsg = document.getElementById('emptyCaptureMsg');
    this.metaFilename = document.getElementById('metaFilename');
    this.metaResolution = document.getElementById('metaResolution');
    this.metaFileSize = document.getElementById('metaFileSize');
    this.metaTimestamp = document.getElementById('metaTimestamp');
    this.metaFilepath = document.getElementById('metaFilepath');
    this.btnDownloadImage = document.getElementById('btnDownloadImage');
    this.btnOpenFullRes = document.getElementById('btnOpenFullRes');
    this.btnTriggerFirstCapture = document.getElementById('btnTriggerFirstCapture');

    // Camera Config Controls
    this.camConfigResolution = document.getElementById('camConfigResolution');
    this.camConfigRotation = document.getElementById('camConfigRotation');
    this.camConfigFps = document.getElementById('camConfigFps');
    this.btnSaveCameraConfig = document.getElementById('btnSaveCameraConfig');
    this.galleryTableBody = document.getElementById('galleryTableBody');
    this.btnRefreshGallery = document.getElementById('btnRefreshGallery');

    // QR Detection Elements
    this.qrStatusDot = document.getElementById('qrStatusDot');
    this.btnToggleQRWorker = document.getElementById('btnToggleQRWorker');
    this.btnClearQRHistory = document.getElementById('btnClearQRHistory');
    this.qrEngineTag = document.getElementById('qrEngineTag');
    this.qrScansTag = document.getElementById('qrScansTag');
    this.qrUploadZone = document.getElementById('qrUploadZone');
    this.qrFileInput = document.getElementById('qrFileInput');
    this.qrConfidenceBadge = document.getElementById('qrConfidenceBadge');
    this.qrPayloadVal = document.getElementById('qrPayloadVal');
    this.qrBboxVal = document.getElementById('qrBboxVal');
    this.qrCenterVal = document.getElementById('qrCenterVal');
    this.qrTimestampVal = document.getElementById('qrTimestampVal');
    this.qrScoreVal = document.getElementById('qrScoreVal');
    this.btnAssociateQRWithMission = document.getElementById('btnAssociateQRWithMission');
    this.qrMissionMatchFeedback = document.getElementById('qrMissionMatchFeedback');
    this.qrHistoryTableBody = document.getElementById('qrHistoryTableBody');

    // Drone Telemetry Elements
    this.telemetryArmedBadge = document.getElementById('telemetryArmedBadge');
    this.hudHorizonBar = document.getElementById('hudHorizonBar');
    this.telemRoll = document.getElementById('telemRoll');
    this.telemPitch = document.getElementById('telemPitch');
    this.telemYaw = document.getElementById('telemYaw');
    this.telemFixBadge = document.getElementById('telemFixBadge');
    this.telemLat = document.getElementById('telemLat');
    this.telemLon = document.getElementById('telemLon');
    this.telemAltRel = document.getElementById('telemAltRel');
    this.telemAltMsl = document.getElementById('telemAltMsl');
    this.telemSats = document.getElementById('telemSats');
    this.telemHdop = document.getElementById('telemHdop');
    this.telemGroundspeed = document.getElementById('telemGroundspeed');
    this.telemAirspeed = document.getElementById('telemAirspeed');
    this.telemClimb = document.getElementById('telemClimb');
    this.telemHeading = document.getElementById('telemHeading');
    this.telemVolts = document.getElementById('telemVolts');
    this.telemAmps = document.getElementById('telemAmps');
    this.mavlinkConnInput = document.getElementById('mavlinkConnInput');
    this.mavlinkBaudSelect = document.getElementById('mavlinkBaudSelect');
    this.mavlinkSimSelect = document.getElementById('mavlinkSimSelect');
    this.btnUpdateMavlinkConn = document.getElementById('btnUpdateMavlinkConn');

    // Mission Control Elements
    this.activeMissionStateBadge = document.getElementById('activeMissionStateBadge');
    this.activeMissionTitle = document.getElementById('activeMissionTitle');
    this.activeMissionDesc = document.getElementById('activeMissionDesc');
    this.btnValidateActiveMission = document.getElementById('btnValidateActiveMission');
    this.btnReadyActiveMission = document.getElementById('btnReadyActiveMission');
    this.btnPauseActiveMission = document.getElementById('btnPauseActiveMission');
    this.btnCancelActiveMission = document.getElementById('btnCancelActiveMission');
    this.missionWaypointsTableBody = document.getElementById('missionWaypointsTableBody');
    this.storedMissionsTableBody = document.getElementById('storedMissionsTableBody');
    this.btnRefreshMissions = document.getElementById('btnRefreshMissions');
    this.newMissionId = document.getElementById('newMissionId');
    this.newMissionName = document.getElementById('newMissionName');
    this.newMissionWaypoints = document.getElementById('newMissionWaypoints');
    this.btnSaveNewMission = document.getElementById('btnSaveNewMission');

    // Geofence Elements
    this.geofenceSafetyBadge = document.getElementById('geofenceSafetyBadge');
    this.geofenceCanvas = document.getElementById('geofenceCanvas');
    this.fenceTypeSelect = document.getElementById('fenceTypeSelect');
    this.fenceCenterLat = document.getElementById('fenceCenterLat');
    this.fenceCenterLon = document.getElementById('fenceCenterLon');
    this.fenceRadius = document.getElementById('fenceRadius');
    this.fenceMinAlt = document.getElementById('fenceMinAlt');
    this.fenceMaxAlt = document.getElementById('fenceMaxAlt');
    this.btnSaveGeofence = document.getElementById('btnSaveGeofence');

    // Console Logs
    this.consoleLogs = document.getElementById('consoleLogs');
    this.btnClearLogs = document.getElementById('btnClearLogs');
    this.btnRefreshHealth = document.getElementById('btnRefreshHealth');
  }

  bindEvents() {
    // Tab switching
    this.navButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        this.switchTab(targetTab);
      });
    });

    // Refresh & Action buttons
    if (this.btnRefreshHealth) {
      this.btnRefreshHealth.addEventListener('click', () => {
        this.fetchAll();
        this.log('Manual telemetry sync completed.', 'info');
      });
    }

    if (this.btnCapturePhoto) {
      this.btnCapturePhoto.addEventListener('click', () => this.triggerCapture());
    }
    if (this.btnTriggerFirstCapture) {
      this.btnTriggerFirstCapture.addEventListener('click', () => this.triggerCapture());
    }

    if (this.btnStreamMode) this.btnStreamMode.addEventListener('click', () => this.setStreamMode('stream'));
    if (this.btnInspectMode) this.btnInspectMode.addEventListener('click', () => this.setStreamMode('inspect'));

    if (this.btnClearLogs) {
      this.btnClearLogs.addEventListener('click', () => {
        this.consoleLogs.innerHTML = '';
        this.log('Event console cleared.', 'info');
      });
    }

    if (this.btnOpenFullRes) {
      this.btnOpenFullRes.addEventListener('click', () => {
        if (this.latestCaptureData && this.latestCaptureData.relative_url) {
          window.open(this.latestCaptureData.relative_url, '_blank');
        }
      });
    }

    // Camera config save
    if (this.btnSaveCameraConfig) {
      this.btnSaveCameraConfig.addEventListener('click', () => this.saveCameraConfig());
    }
    if (this.btnRefreshGallery) {
      this.btnRefreshGallery.addEventListener('click', () => this.fetchCapturesList());
    }

    // QR Detection Controls
    if (this.btnToggleQRWorker) {
      this.btnToggleQRWorker.addEventListener('click', () => this.toggleQRWorker());
    }
    if (this.btnClearQRHistory) {
      this.btnClearQRHistory.addEventListener('click', () => this.clearQRHistory());
    }
    if (this.qrUploadZone) {
      this.qrUploadZone.addEventListener('click', () => this.qrFileInput.click());
      this.qrFileInput.addEventListener('change', (e) => this.handleQRUpload(e));
    }
    if (this.btnAssociateQRWithMission) {
      this.btnAssociateQRWithMission.addEventListener('click', () => this.associateQRWithMission());
    }

    // MAVLink Connection update
    if (this.btnUpdateMavlinkConn) {
      this.btnUpdateMavlinkConn.addEventListener('click', () => this.updateMavlinkConn());
    }

    // Mission Control Actions
    if (this.btnRefreshMissions) {
      this.btnRefreshMissions.addEventListener('click', () => this.fetchMissions());
    }
    if (this.btnSaveNewMission) {
      this.btnSaveNewMission.addEventListener('click', () => this.createNewMission());
    }
    if (this.btnValidateActiveMission) {
      this.btnValidateActiveMission.addEventListener('click', () => this.transitionActiveMission('VALIDATED'));
    }
    if (this.btnReadyActiveMission) {
      this.btnReadyActiveMission.addEventListener('click', () => this.transitionActiveMission('READY'));
    }
    if (this.btnPauseActiveMission) {
      this.btnPauseActiveMission.addEventListener('click', () => this.transitionActiveMission('PAUSED'));
    }
    if (this.btnCancelActiveMission) {
      this.btnCancelActiveMission.addEventListener('click', () => this.transitionActiveMission('CANCELLED'));
    }

    // Geofence save
    if (this.btnSaveGeofence) {
      this.btnSaveGeofence.addEventListener('click', () => this.saveGeofenceConfig());
    }
  }

  switchTab(tabName) {
    this.activeTab = tabName;
    this.navButtons.forEach(b => {
      if (b.getAttribute('data-tab') === tabName) {
        b.classList.add('active');
      } else {
        b.classList.remove('active');
      }
    });

    this.tabPanes.forEach(pane => {
      if (pane.id === `pane-${tabName}`) {
        pane.classList.add('active');
      } else {
        pane.classList.remove('active');
      }
    });

    const titles = {
      'overview': 'Mission Overview & Camera Station',
      'health': 'Companion Computer System Health',
      'camera': 'Sony IMX477 Camera & Gallery',
      'qr': 'Computer Vision & QR Detection',
      'telemetry': 'Pixhawk MAVLink Telemetry HUD',
      'missions': 'Autonomous Mission Management',
      'geofence': 'Geofence Boundaries & Navigation Safety'
    };
    if (this.pageTitle) {
      this.pageTitle.textContent = titles[tabName] || 'Ground Station';
    }

    if (tabName === 'geofence') {
      this.renderGeofenceCanvas();
    }
  }

  start() {
    this.log('Connecting to Drone Companion Computer telemetry...', 'info');
    this.fetchAll();

    // Start periodic background telemetry loop
    this.pollTimer = setInterval(() => {
      this.fetchHealth();
      this.fetchTelemetry();
      if (this.activeTab === 'qr') {
        this.fetchQRStatus();
      }
      if (this.activeTab === 'geofence') {
        this.renderGeofenceCanvas();
      }
    }, this.pollInterval);
  }

  fetchAll() {
    this.fetchHardware();
    this.fetchCameraStatus();
    this.fetchLatestCapture();
    this.fetchHealth();
    this.fetchTelemetry();
    this.fetchQRStatus();
    this.fetchMissions();
    this.fetchGeofence();
    this.fetchCapturesList();
  }

  // -------------------------------------------------------------
  // System Health & Hardware
  // -------------------------------------------------------------
  async fetchHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        this.updateHealthUI(json.data);
      }
    } catch (err) {
      if (this.rpiHeartbeatDot) this.rpiHeartbeatDot.style.backgroundColor = '#ff1744';
      if (this.systemHealthBadge) {
        this.systemHealthBadge.className = 'system-badge critical';
        this.systemHealthBadge.textContent = 'LINK LOST';
      }
      if (this.sidebarRpiStatus) {
        this.sidebarRpiStatus.textContent = 'LINK DISCONNECTED';
        this.sidebarRpiStatus.style.color = '#ff1744';
      }
    }
  }

  updateHealthUI(data) {
    if (this.rpiHeartbeatDot) this.rpiHeartbeatDot.style.backgroundColor = '#00e676';
    const status = data.overall_status || 'HEALTHY';
    if (this.systemHealthBadge) {
      this.systemHealthBadge.textContent = `SYSTEM ${status}`;
      this.systemHealthBadge.className = `system-badge ${status.toLowerCase()}`;
    }
    if (this.sidebarRpiStatus) {
      this.sidebarRpiStatus.textContent = 'PI COMPANION ONLINE';
      this.sidebarRpiStatus.style.color = '#00e676';
    }

    if (data.uptime && data.uptime.formatted && this.uptimeDisplay) {
      this.uptimeDisplay.textContent = data.uptime.formatted;
    }

    if (data.cpu && this.cpuUsageVal) {
      const cpuVal = Math.round(data.cpu.usage_percent || 0);
      this.cpuUsageVal.textContent = cpuVal;
      this.cpuProgressBar.style.width = `${Math.min(cpuVal, 100)}%`;
      if (data.cpu.physical_cores && this.cpuCoresBadge) {
        this.cpuCoresBadge.textContent = `${data.cpu.physical_cores} Cores (${data.cpu.logical_cores}T)`;
      }
      if (data.cpu.frequency && data.cpu.frequency.current_mhz && this.cpuFreqText) {
        this.cpuFreqText.textContent = `Frequency: ${data.cpu.frequency.current_mhz} MHz`;
      }
    }

    if (data.temperature && this.tempCelsiusVal) {
      const tempC = data.temperature.celsius;
      this.tempCelsiusVal.textContent = tempC.toFixed(1);
      const tempPct = Math.min(Math.max((tempC / 90) * 100, 0), 100);
      this.tempProgressBar.style.width = `${tempPct}%`;
      const statusStr = data.temperature.status || 'NORMAL';
      this.tempStatusBadge.textContent = statusStr;
      this.tempStatusBadge.className = `card-badge ${statusStr.toLowerCase()}`;
      if (this.tempFahrenheitText) {
        this.tempFahrenheitText.textContent = `${data.temperature.fahrenheit}°F | Limit: 85°C`;
      }
    }

    if (data.memory && this.ramUsageVal) {
      const ramVal = Math.round(data.memory.usage_percent || 0);
      this.ramUsageVal.textContent = ramVal;
      this.ramProgressBar.style.width = `${ramVal}%`;
      if (this.ramTotalBadge) this.ramTotalBadge.textContent = `${data.memory.total_gb} GB`;
      if (this.ramSubText) this.ramSubText.textContent = `${data.memory.used_gb} / ${data.memory.total_gb} GB Used`;
    }
  }

  async fetchHardware() {
    try {
      const res = await fetch('/api/health/hardware');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        const d = json.data;
        if (this.specModel) this.specModel.textContent = d.device?.model || 'Unknown';
        if (this.specSoc) this.specSoc.textContent = d.device?.soc || 'Unknown';
        if (this.specArch) this.specArch.textContent = d.cpu?.architecture || 'Unknown';
        if (this.specOs) this.specOs.textContent = `${d.os?.system} ${d.os?.release}`;
        if (this.specSerial) this.specSerial.textContent = d.device?.serial_number || 'N/A';
        if (this.specHostname) this.specHostname.textContent = d.device?.hostname || 'drone-rpi';
        if (this.sidebarRpiModel) this.sidebarRpiModel.textContent = d.device?.model || 'Raspberry Pi 4';
        if (this.hwPlatformBadge) this.hwPlatformBadge.textContent = d.is_raspberry_pi ? 'Genuine RPi 4' : 'Simulated Pi 4';
      }
    } catch (err) {
      console.error('Error fetching hardware info:', err);
    }
  }

  // -------------------------------------------------------------
  // Pixhawk MAVLink Telemetry (Milestone 03)
  // -------------------------------------------------------------
  async fetchTelemetry() {
    try {
      const res = await fetch('/api/telemetry/current');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        this.currentTelemetry = json.data;
        this.updateTelemetryUI(json.data);
      }
    } catch (err) {
      console.error('Error fetching telemetry:', err);
    }
  }

  updateTelemetryUI(t) {
    if (this.topbarMavlinkState) {
      this.topbarMavlinkState.textContent = t.connected ? (t.is_simulated ? 'SIMULATED' : 'ONLINE') : 'OFFLINE';
      this.topbarMavlinkState.className = t.connected ? 'chip-val highlight' : 'chip-val';
    }

    if (this.telemetryModeBadge) this.telemetryModeBadge.textContent = t.flight_mode;
    if (this.camFlightMode) this.camFlightMode.textContent = t.flight_mode;
    if (this.batteryPercentVal) this.batteryPercentVal.textContent = t.battery_remaining_percent;
    if (this.batteryProgressBar) this.batteryProgressBar.style.width = `${t.battery_remaining_percent}%`;
    if (this.batteryVoltsText) this.batteryVoltsText.textContent = `${t.battery_voltage_v} V | Fix: ${t.gps_fix_name} (${t.satellites_visible} Sats)`;

    if (this.telemetryArmedBadge) {
      this.telemetryArmedBadge.textContent = t.armed ? 'ARMED' : 'DISARMED';
      this.telemetryArmedBadge.className = t.armed ? 'card-badge highlight' : 'card-badge normal';
    }

    if (this.hudHorizonBar) {
      this.hudHorizonBar.style.transform = `rotate(${-t.roll_deg}deg) translateY(${t.pitch_deg * 1.5}px)`;
    }
    if (this.telemRoll) this.telemRoll.textContent = `${t.roll_deg}°`;
    if (this.telemPitch) this.telemPitch.textContent = `${t.pitch_deg}°`;
    if (this.telemYaw) this.telemYaw.textContent = `${t.yaw_deg}°`;

    if (this.telemLat) this.telemLat.textContent = t.latitude.toFixed(6);
    if (this.telemLon) this.telemLon.textContent = t.longitude.toFixed(6);
    if (this.telemAltRel) this.telemAltRel.textContent = `${t.altitude_relative_m} m`;
    if (this.telemAltMsl) this.telemAltMsl.textContent = `${t.altitude_msl_m} m`;
    if (this.telemSats) this.telemSats.textContent = t.satellites_visible;
    if (this.telemHdop) this.telemHdop.textContent = t.hdop;

    if (this.telemGroundspeed) this.telemGroundspeed.textContent = `${t.groundspeed_m_s} m/s`;
    if (this.telemAirspeed) this.telemAirspeed.textContent = `${t.airspeed_m_s} m/s`;
    if (this.telemClimb) this.telemClimb.textContent = `${t.climb_rate_m_s} m/s`;
    if (this.telemHeading) this.telemHeading.textContent = `${t.heading_deg}°`;
    if (this.telemVolts) this.telemVolts.textContent = `${t.battery_voltage_v} V`;
    if (this.telemAmps) this.telemAmps.textContent = `${t.battery_current_a} A`;
  }

  async updateMavlinkConn() {
    const connStr = this.mavlinkConnInput.value.trim();
    const baud = parseInt(this.mavlinkBaudSelect.value, 10);
    const sim = this.mavlinkSimSelect.value === 'true';

    try {
      const res = await fetch('/api/telemetry/connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connection_string: connStr, baudrate: baud, simulate: sim })
      });
      const json = await res.json();
      if (res.ok) {
        this.log(`MAVLink connection updated: ${connStr} (Sim: ${sim})`, 'success');
        this.fetchTelemetry();
      }
    } catch (err) {
      this.log(`Failed updating MAVLink connection: ${err.message}`, 'error');
    }
  }

  // -------------------------------------------------------------
  // Camera & Image Capture
  // -------------------------------------------------------------
  async fetchCameraStatus() {
    try {
      const res = await fetch('/api/camera/status');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        const cam = json.data;
        if (this.camSensorName) this.camSensorName.textContent = cam.sensor_model || 'Sony IMX477';
        if (this.topbarCameraSensor) this.topbarCameraSensor.textContent = cam.sensor_model || 'Sony IMX477';
        if (this.camConnectionState) {
          this.camConnectionState.textContent = cam.connected ? 'ONLINE' : 'OFFLINE';
          this.camConnectionState.className = cam.connected ? 'meta-value status-online' : 'meta-value status-offline';
        }
        if (this.hudBackendTag) this.hudBackendTag.textContent = `BACKEND: ${cam.active_backend.toUpperCase()}`;
        if (cam.config && this.hudResolutionTag) {
          this.hudResolutionTag.textContent = `${cam.config.width}x${cam.config.height}`;
        }
      }
    } catch (err) {
      console.error('Error fetching camera status:', err);
    }
  }

  async fetchLatestCapture() {
    try {
      const res = await fetch('/api/camera/latest');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        this.updateLatestCaptureUI(json.data);
      }
    } catch (err) {
      console.error('Error fetching latest capture:', err);
    }
  }

  async triggerCapture() {
    if (this.isCapturing) return;
    this.isCapturing = true;
    if (this.btnCapturePhoto) this.btnCapturePhoto.disabled = true;
    if (this.captureSpinner) this.captureSpinner.classList.remove('hidden');
    if (this.captureBtnText) this.captureBtnText.textContent = 'Capturing...';
    this.log('Triggered image capture request to companion camera...', 'info');

    try {
      const res = await fetch('/api/camera/capture', { method: 'POST' });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        const capture = json.data;
        this.log(`Snapshot saved: ${capture.filename} (${capture.width}x${capture.height}, ${capture.size_kb} KB)`, 'success');
        this.updateLatestCaptureUI(capture);
        this.fetchCapturesList();
        if (this.streamMode === 'inspect' && this.cameraLatestPreviewImg) {
          this.cameraLatestPreviewImg.src = `${capture.relative_url}?t=${Date.now()}`;
        }
      } else {
        throw new Error(json.message || 'Capture failed');
      }
    } catch (err) {
      this.log(`Image capture error: ${err.message}`, 'error');
    } finally {
      this.isCapturing = false;
      if (this.btnCapturePhoto) this.btnCapturePhoto.disabled = false;
      if (this.captureSpinner) this.captureSpinner.classList.add('hidden');
      if (this.captureBtnText) this.captureBtnText.textContent = '📸 Capture Image';
    }
  }

  updateLatestCaptureUI(data) {
    if (!data) return;
    this.latestCaptureData = data;
    if (this.emptyCaptureMsg) this.emptyCaptureMsg.classList.add('hidden');
    if (this.captureThumbnail) {
      this.captureThumbnail.classList.remove('hidden');
      this.captureThumbnail.src = `${data.relative_url}?t=${Date.now()}`;
    }

    if (this.metaFilename) this.metaFilename.textContent = data.filename;
    if (this.metaResolution) this.metaResolution.textContent = `${data.width} × ${data.height} px`;
    if (this.metaFileSize) this.metaFileSize.textContent = `${data.size_kb} KB`;
    if (this.metaTimestamp) this.metaTimestamp.textContent = data.iso_time ? data.iso_time.replace('T', ' ').substring(0, 19) : '--';
    if (this.metaFilepath) this.metaFilepath.textContent = data.filepath;

    if (this.btnDownloadImage) {
      this.btnDownloadImage.href = data.relative_url;
      this.btnDownloadImage.classList.remove('disabled');
    }
    if (this.btnOpenFullRes) this.btnOpenFullRes.classList.remove('disabled');
  }

  setStreamMode(mode) {
    this.streamMode = mode;
    if (mode === 'stream') {
      if (this.btnStreamMode) this.btnStreamMode.classList.add('active');
      if (this.btnInspectMode) this.btnInspectMode.classList.remove('active');
      if (this.cameraStreamImg) this.cameraStreamImg.classList.remove('hidden');
      if (this.cameraLatestPreviewImg) this.cameraLatestPreviewImg.classList.add('hidden');
    } else {
      if (this.btnStreamMode) this.btnStreamMode.classList.remove('active');
      if (this.btnInspectMode) this.btnInspectMode.classList.add('active');
      if (this.cameraStreamImg) this.cameraStreamImg.classList.add('hidden');
      if (this.cameraLatestPreviewImg) {
        this.cameraLatestPreviewImg.classList.remove('hidden');
        if (this.latestCaptureData && this.latestCaptureData.relative_url) {
          this.cameraLatestPreviewImg.src = `${this.latestCaptureData.relative_url}?t=${Date.now()}`;
        }
      }
    }
  }

  async saveCameraConfig() {
    const resVal = this.camConfigResolution.value.split('x');
    const rotVal = parseInt(this.camConfigRotation.value, 10);
    const fpsVal = parseInt(this.camConfigFps.value, 10);

    try {
      const res = await fetch('/api/camera/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          width: parseInt(resVal[0], 10),
          height: parseInt(resVal[1], 10),
          rotation: rotVal,
          framerate: fpsVal
        })
      });
      const json = await res.json();
      if (res.ok) {
        this.log('Camera configuration applied successfully.', 'success');
        this.fetchCameraStatus();
      }
    } catch (err) {
      this.log(`Failed updating camera config: ${err.message}`, 'error');
    }
  }

  async fetchCapturesList() {
    try {
      const res = await fetch('/api/camera/list?limit=10');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && this.galleryTableBody) {
        if (!json.data || json.data.length === 0) {
          this.galleryTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No snapshots saved.</td></tr>';
          return;
        }
        this.galleryTableBody.innerHTML = json.data.map(item => `
          <tr>
            <td class="mono">${this.escapeHtml(item.filename)}</td>
            <td class="mono">${item.iso_time.replace('T', ' ').substring(0, 19)}</td>
            <td>${item.size_kb} KB</td>
            <td>
              <a href="${item.relative_url}" download class="btn btn-ghost btn-xs">Download</a>
            </td>
          </tr>
        `).join('');
      }
    } catch (err) {
      console.error('Error fetching gallery:', err);
    }
  }

  // -------------------------------------------------------------
  // Computer Vision & QR Detection (Milestone 02)
  // -------------------------------------------------------------
  async fetchQRStatus() {
    try {
      const [statusRes, latestRes, historyRes] = await Promise.all([
        fetch('/api/vision/qr/status'),
        fetch('/api/vision/qr/latest'),
        fetch('/api/vision/qr/history?limit=10')
      ]);

      if (statusRes.ok) {
        const sJson = await statusRes.json();
        const isRunning = sJson.data.running;
        if (this.qrStatusDot) {
          this.qrStatusDot.style.backgroundColor = isRunning ? 'var(--accent-green)' : 'var(--accent-red)';
        }
        if (this.btnToggleQRWorker) {
          this.btnToggleQRWorker.textContent = isRunning ? '⏹ Stop QR Detection' : '▶ Start QR Detection';
          this.btnToggleQRWorker.className = isRunning ? 'btn btn-secondary btn-sm' : 'btn btn-primary btn-sm';
        }
        if (this.qrEngineTag) this.qrEngineTag.textContent = `SCANNER: ${isRunning ? 'ACTIVE' : 'IDLE'}`;
        if (this.qrScansTag) this.qrScansTag.textContent = `SCANS: ${sJson.data.total_scans}`;
      }

      if (latestRes.ok) {
        const lJson = await latestRes.json();
        if (lJson.data) {
          const d = lJson.data;
          if (this.qrPayloadVal) this.qrPayloadVal.textContent = d.payload;
          if (this.qrConfidenceBadge) this.qrConfidenceBadge.textContent = `${Math.round(d.confidence * 100)}% Conf`;
          if (this.qrBboxVal) this.qrBboxVal.textContent = `(${d.bbox.x}, ${d.bbox.y}) ${d.bbox.width}x${d.bbox.height}`;
          if (this.qrCenterVal) this.qrCenterVal.textContent = `[${d.center[0]}, ${d.center[1]}]`;
          if (this.qrTimestampVal) this.qrTimestampVal.textContent = d.iso_time.replace('T', ' ').substring(0, 19);
          if (this.qrScoreVal) this.qrScoreVal.textContent = `${d.confidence}`;
        }
      }

      if (historyRes.ok) {
        const hJson = await historyRes.json();
        if (this.qrHistoryTableBody) {
          if (!hJson.data || hJson.data.length === 0) {
            this.qrHistoryTableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No detections yet. Start scanner or upload an image.</td></tr>';
          } else {
            this.qrHistoryTableBody.innerHTML = hJson.data.map(item => `
              <tr>
                <td class="mono">${item.iso_time.substring(11, 19)}</td>
                <td class="mono highlight" style="word-break: break-all;">${this.escapeHtml(item.payload)}</td>
                <td class="mono">[${item.center[0]}, ${item.center[1]}]</td>
                <td>${Math.round(item.confidence * 100)}%</td>
                <td><span class="card-badge">${item.source || 'camera'}</span></td>
              </tr>
            `).join('');
          }
        }
      }
    } catch (err) {
      console.error('Error fetching QR data:', err);
    }
  }

  async toggleQRWorker() {
    try {
      const statusRes = await fetch('/api/vision/qr/status');
      const sJson = await statusRes.json();
      const isRunning = sJson.data.running;
      const endpoint = isRunning ? '/api/vision/qr/stop' : '/api/vision/qr/start';
      await fetch(endpoint, { method: 'POST' });
      this.log(`QR Scanner worker ${isRunning ? 'stopped' : 'started'}.`, 'info');
      this.fetchQRStatus();
    } catch (err) {
      this.log(`Failed to toggle QR worker: ${err.message}`, 'error');
    }
  }

  async clearQRHistory() {
    try {
      await fetch('/api/vision/qr/clear', { method: 'POST' });
      this.log('QR detection history cleared.', 'info');
      this.fetchQRStatus();
    } catch (err) {
      this.log(`Failed to clear QR history: ${err.message}`, 'error');
    }
  }

  async handleQRUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    this.log(`Uploading ${file.name} to QR scanner engine...`, 'info');
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/vision/qr/process-image', {
        method: 'POST',
        body: formData
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        this.log(`QR Engine scanned image: found ${json.count} targets`, 'success');
        this.fetchQRStatus();
      } else {
        throw new Error(json.message || 'Scan failed');
      }
    } catch (err) {
      this.log(`QR Upload error: ${err.message}`, 'error');
    }
  }

  async associateQRWithMission() {
    const payload = this.qrPayloadVal.textContent;
    if (!payload || payload === '--') {
      this.qrMissionMatchFeedback.textContent = 'No QR target selected to match.';
      return;
    }

    this.log(`Attempting to associate QR payload '${payload}' with stored missions...`, 'info');
    try {
      const res = await fetch('/api/missions/associate-qr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload })
      });
      const json = await res.json();
      if (res.ok && json.status === 'success') {
        this.qrMissionMatchFeedback.textContent = `Matched mission: ${json.data.mission_id}!`;
        this.qrMissionMatchFeedback.style.color = 'var(--accent-green)';
        this.log(`QR Code matched to mission '${json.data.mission_id}'! State transitioned to READY.`, 'success');
        this.fetchMissions();
      } else {
        this.qrMissionMatchFeedback.textContent = json.message || 'No matching mission found.';
        this.qrMissionMatchFeedback.style.color = 'var(--accent-red)';
      }
    } catch (err) {
      this.qrMissionMatchFeedback.textContent = err.message;
      this.qrMissionMatchFeedback.style.color = 'var(--accent-red)';
    }
  }

  // -------------------------------------------------------------
  // Mission Management (Milestone 04)
  // -------------------------------------------------------------
  async fetchMissions() {
    try {
      const [listRes, activeRes] = await Promise.all([
        fetch('/api/missions'),
        fetch('/api/missions/active')
      ]);

      if (activeRes.ok) {
        const aJson = await activeRes.json();
        this.activeMission = aJson.data;
        this.updateActiveMissionUI(aJson.data);
      }

      if (listRes.ok) {
        const lJson = await listRes.json();
        this.updateStoredMissionsTable(lJson.data || []);
      }
    } catch (err) {
      console.error('Error fetching missions:', err);
    }
  }

  updateActiveMissionUI(mission) {
    if (!mission) {
      if (this.activeMissionTitle) this.activeMissionTitle.textContent = 'No Active Mission';
      if (this.activeMissionDesc) this.activeMissionDesc.textContent = 'Select or create a mission to begin autonomous flight.';
      if (this.activeMissionStateBadge) this.activeMissionStateBadge.textContent = 'IDLE';
      if (this.missionWaypointsTableBody) {
        this.missionWaypointsTableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No waypoints loaded.</td></tr>';
      }
      return;
    }

    if (this.activeMissionTitle) this.activeMissionTitle.textContent = `${mission.name} (${mission.id})`;
    if (this.activeMissionDesc) this.activeMissionDesc.textContent = mission.description || 'Configured autonomous waypoint trajectory.';
    if (this.activeMissionStateBadge) {
      this.activeMissionStateBadge.textContent = mission.state;
      this.activeMissionStateBadge.className = `card-badge ${mission.state.toLowerCase()}`;
    }

    if (this.missionWaypointsTableBody) {
      this.missionWaypointsTableBody.innerHTML = mission.waypoints.map(wp => `
        <tr>
          <td>#${wp.seq}</td>
          <td><span class="card-badge">${wp.action}</span></td>
          <td class="mono">${wp.lat.toFixed(6)}</td>
          <td class="mono">${wp.lon.toFixed(6)}</td>
          <td class="mono">${wp.alt_m} m</td>
          <td>${wp.speed_m_s} m/s</td>
          <td>${wp.hold_time_s} s</td>
        </tr>
      `).join('');
    }
  }

  updateStoredMissionsTable(missions) {
    if (!this.storedMissionsTableBody) return;
    if (missions.length === 0) {
      this.storedMissionsTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No stored missions found.</td></tr>';
      return;
    }

    this.storedMissionsTableBody.innerHTML = missions.map(m => `
      <tr>
        <td class="mono highlight">${this.escapeHtml(m.id)}</td>
        <td>${this.escapeHtml(m.name)}</td>
        <td><span class="card-badge ${m.state.toLowerCase()}">${m.state}</span></td>
        <td>
          <button class="btn btn-primary btn-xs" onclick="droneDashboard.activateMission('${m.id}')">Select</button>
          <button class="btn btn-ghost btn-xs" onclick="droneDashboard.deleteMission('${m.id}')">Delete</button>
        </td>
      </tr>
    `).join('');
  }

  async activateMission(missionId) {
    try {
      const res = await fetch('/api/missions/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mission_id: missionId })
      });
      if (res.ok) {
        this.log(`Mission '${missionId}' activated.`, 'info');
        this.fetchMissions();
      }
    } catch (err) {
      this.log(`Error activating mission: ${err.message}`, 'error');
    }
  }

  async deleteMission(missionId) {
    if (!confirm(`Delete mission '${missionId}'?`)) return;
    try {
      const res = await fetch(`/api/missions/${missionId}`, { method: 'DELETE' });
      if (res.ok) {
        this.log(`Mission '${missionId}' deleted.`, 'info');
        this.fetchMissions();
      }
    } catch (err) {
      this.log(`Error deleting mission: ${err.message}`, 'error');
    }
  }

  async transitionActiveMission(targetState) {
    if (!this.activeMission) {
      this.log('No active mission loaded to transition.', 'error');
      return;
    }
    try {
      const res = await fetch(`/api/missions/${this.activeMission.id}/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: targetState, reason: 'Ground Station operator request' })
      });
      const json = await res.json();
      if (res.ok) {
        this.log(`Mission transitioned to state ${targetState}`, 'success');
        this.fetchMissions();
      } else {
        throw new Error(json.message);
      }
    } catch (err) {
      this.log(`State transition rejected: ${err.message}`, 'error');
    }
  }

  async createNewMission() {
    const id = this.newMissionId.value.trim();
    const name = this.newMissionName.value.trim();
    const rawWaypoints = this.newMissionWaypoints.value.trim();

    if (!id || !name || !rawWaypoints) {
      alert('Please fill out Mission ID, Name, and Waypoints JSON');
      return;
    }

    try {
      const waypoints = JSON.parse(rawWaypoints);
      const res = await fetch('/api/missions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name, waypoints })
      });
      const json = await res.json();
      if (res.ok) {
        this.log(`Created mission '${id}' successfully.`, 'success');
        this.newMissionId.value = '';
        this.newMissionName.value = '';
        this.fetchMissions();
      } else {
        throw new Error(json.message);
      }
    } catch (err) {
      this.log(`Failed to create mission: ${err.message}`, 'error');
    }
  }

  // -------------------------------------------------------------
  // Geofence & Navigation Radar (Milestone 05)
  // -------------------------------------------------------------
  async fetchGeofence() {
    try {
      const res = await fetch('/api/geofence');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        this.geofenceConfig = json.data;
        if (this.fenceTypeSelect) this.fenceTypeSelect.value = json.data.fence_type;
        if (this.fenceCenterLat) this.fenceCenterLat.value = json.data.circle_center_lat;
        if (this.fenceCenterLon) this.fenceCenterLon.value = json.data.circle_center_lon;
        if (this.fenceRadius) this.fenceRadius.value = json.data.circle_radius_m;
        if (this.fenceMinAlt) this.fenceMinAlt.value = json.data.min_alt_m;
        if (this.fenceMaxAlt) this.fenceMaxAlt.value = json.data.max_alt_m;
        this.renderGeofenceCanvas();
      }
    } catch (err) {
      console.error('Error fetching geofence:', err);
    }
  }

  async saveGeofenceConfig() {
    const fType = this.fenceTypeSelect.value;
    const cLat = parseFloat(this.fenceCenterLat.value);
    const cLon = parseFloat(this.fenceCenterLon.value);
    const r = parseFloat(this.fenceRadius.value);
    const minAlt = parseFloat(this.fenceMinAlt.value);
    const maxAlt = parseFloat(this.fenceMaxAlt.value);

    try {
      const res = await fetch('/api/geofence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fence_type: fType,
          circle_center_lat: cLat,
          circle_center_lon: cLon,
          circle_radius_m: r,
          min_alt_m: minAlt,
          max_alt_m: maxAlt
        })
      });
      const json = await res.json();
      if (res.ok) {
        this.log('Geofence parameters updated and saved.', 'success');
        this.fetchGeofence();
      }
    } catch (err) {
      this.log(`Failed updating geofence: ${err.message}`, 'error');
    }
  }

  renderGeofenceCanvas() {
    if (!this.geofenceCanvas || !this.geofenceConfig) return;
    const canvas = this.geofenceCanvas;
    const ctx = canvas.getContext('2d');

    // Handle high DPI
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
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.15)';
    ctx.lineWidth = 1;
    for (let r = 40; r < Math.min(width, height) / 2; r += 40) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Radar axes
    ctx.beginPath();
    ctx.moveTo(cx, 10);
    ctx.lineTo(cx, height - 10);
    ctx.moveTo(10, cy);
    ctx.lineTo(width - 10, cy);
    ctx.stroke();

    // Scale factor: radius maps to ~70% of canvas half-size
    const maxR = Math.min(width, height) * 0.38;
    const fenceRadiusM = this.geofenceConfig.circle_radius_m || 250;
    const scale = maxR / fenceRadiusM;

    // Draw Geofence Boundary (Yellow)
    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);

    if (this.geofenceConfig.fence_type === 'circular') {
      ctx.beginPath();
      ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
      ctx.stroke();
    } else if (this.geofenceConfig.polygon_vertices && this.geofenceConfig.polygon_vertices.length > 2) {
      ctx.beginPath();
      const centerLat = this.geofenceConfig.circle_center_lat;
      const centerLon = this.geofenceConfig.circle_center_lon;

      this.geofenceConfig.polygon_vertices.forEach((p, idx) => {
        // Simple equirectangular projection centered on geofence center
        const dx = (p.lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
        const dy = -(p.lat - centerLat) * 110540 * scale;
        if (idx === 0) ctx.moveTo(cx + dx, cy + dy);
        else ctx.lineTo(cx + dx, cy + dy);
      });
      ctx.closePath();
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Draw Waypoints (Magenta)
    if (this.activeMission && this.activeMission.waypoints) {
      const centerLat = this.geofenceConfig.circle_center_lat;
      const centerLon = this.geofenceConfig.circle_center_lon;
      ctx.strokeStyle = 'rgba(233, 30, 99, 0.6)';
      ctx.fillStyle = '#e91e63';
      ctx.lineWidth = 2;

      ctx.beginPath();
      this.activeMission.waypoints.forEach((wp, idx) => {
        const dx = (wp.lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
        const dy = -(wp.lat - centerLat) * 110540 * scale;
        const px = cx + dx;
        const py = cy + dy;

        if (idx === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.stroke();

      this.activeMission.waypoints.forEach((wp) => {
        const dx = (wp.lon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
        const dy = -(wp.lat - centerLat) * 110540 * scale;
        const px = cx + dx;
        const py = cy + dy;

        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px JetBrains Mono';
        ctx.fillText(`#${wp.seq}`, px + 6, py - 4);
        ctx.fillStyle = '#e91e63';
      });
    }

    // Draw Current Drone Position (Cyan dot with pulse)
    if (this.currentTelemetry && this.currentTelemetry.connected) {
      const centerLat = this.geofenceConfig.circle_center_lat;
      const centerLon = this.geofenceConfig.circle_center_lon;
      const dLat = this.currentTelemetry.latitude;
      const dLon = this.currentTelemetry.longitude;

      const dx = (dLon - centerLon) * 111320 * Math.cos(centerLat * Math.PI / 180) * scale;
      const dy = -(dLat - centerLat) * 110540 * scale;
      const px = cx + dx;
      const py = cy + dy;

      ctx.fillStyle = '#00e5ff';
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fill();

      // Heading vector
      const headingRad = (this.currentTelemetry.heading_deg - 90) * Math.PI / 180;
      ctx.strokeStyle = '#00e5ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(px + Math.cos(headingRad) * 20, py + Math.sin(headingRad) * 20);
      ctx.stroke();
    }
  }

  // -------------------------------------------------------------
  // Utility & Logging Console
  // -------------------------------------------------------------
  log(message, type = 'info') {
    if (!this.consoleLogs) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    const now = new Date();
    const timeStr = `[${now.toTimeString().substring(0, 8)}]`;
    entry.innerHTML = `<span class="log-time">${timeStr}</span> <span class="log-text">${this.escapeHtml(message)}</span>`;
    this.consoleLogs.appendChild(entry);
    this.consoleLogs.scrollTop = this.consoleLogs.scrollHeight;
  }

  escapeHtml(str) {
    if (typeof str !== 'string') return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
  window.droneDashboard = new DroneDashboard();
});
