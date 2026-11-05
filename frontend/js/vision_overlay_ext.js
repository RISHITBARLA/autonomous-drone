/**
 * TASK 2 — NON-DESTRUCTIVE VISUAL DETECTION HEATMAP & MARKER OVERLAY EXTENSION
 * Attaches to the existing global Leaflet `map` object without replacing existing UI panels.
 */
(function () {
  let lastSequence = -1;
  let activeCategoryFilter = "all";
  const markerLayerGroup = window.L ? L.layerGroup() : null;
  const heatHaloLayerGroup = window.L ? L.layerGroup() : null;

  function initTask2Overlay(existingMap) {
    if (!existingMap || !window.L) return;
    heatHaloLayerGroup.addTo(existingMap);
    markerLayerGroup.addTo(existingMap);
    injectFilterToolbar();
    setInterval(pollIncrementalHeatmap, 1000);
  }

  function injectFilterToolbar() {
    if (document.getElementById("task2-vision-toolbar")) return;
    const bar = document.createElement("div");
    bar.id = "task2-vision-toolbar";
    bar.style.cssText =
      "position:fixed;bottom:16px;right:16px;z-index:9999;background:rgba(15,23,42,0.92);color:#f8fafc;padding:10px 14px;border-radius:8px;font-family:sans-serif;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
    bar.innerHTML = `
      <div style="font-weight:bold;margin-bottom:6px;">Visual Search Heatmap (Not Thermal)</div>
      <label>Filter Category: </label>
      <select id="task2-cat-filter" style="background:#1e293b;color:#fff;border:1px solid #475569;padding:2px 6px;border-radius:4px;">
        <option value="all">All Categories</option>
        <option value="unknown_object">Unknown (Yellow)</option>
        <option value="vehicle">Recognized Vehicle (Orange)</option>
        <option value="payload_box">High Priority Box (Red)</option>
        <option value="person">Critical Target (Dark Red)</option>
        <option value="qr_target">QR Verified (Green)</option>
      </select>
      <div id="task2-addc-code-banner" style="margin-top:6px;color:#38bdf8;">ADDC Code: Waiting for QR (2 digits) + Ground Puzzle (2 digits)</div>
    `;
    document.body.appendChild(bar);
    document.getElementById("task2-cat-filter").addEventListener("change", (e) => {
      activeCategoryFilter = e.target.value;
      lastSequence = -1; // Force refresh on filter change
      pollIncrementalHeatmap();
    });
  }

  async function pollIncrementalHeatmap() {
    try {
      const res = await fetch(`/api/v2/vision/heatmap?category=${encodeURIComponent(activeCategoryFilter)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.sequence === lastSequence) return; // Incremental no-op if nothing changed
      lastSequence = data.sequence;

      if (heatHaloLayerGroup) heatHaloLayerGroup.clearLayers();
      if (markerLayerGroup) markerLayerGroup.clearLayers();

      // Render visual detection density halos
      if (window.L && heatHaloLayerGroup) {
        (data.heatmap_points || []).forEach((pt) => {
          L.circle([pt.lat, pt.lon], {
            radius: 5.5,
            stroke: false,
            fillColor: pt.color,
            fillOpacity: Math.min(0.55, pt.intensity * 0.45),
          }).addTo(heatHaloLayerGroup);
        });
      }

      // Render clickable deduplicated target markers
      if (window.L && markerLayerGroup) {
        (data.markers || []).forEach((m) => {
          const marker = L.circleMarker([m.estimated_lat, m.estimated_lon], {
            radius: 9,
            color: "#ffffff",
            weight: 2,
            fillColor: m.display_color,
            fillOpacity: 0.95,
          });

          const approxBadge = m.is_approximate
            ? `<span style="color:#facc15;font-weight:bold;">[APPROXIMATE GPS]</span>`
            : `<span style="color:#4ade80;">[CALIBRATED 3D PROJECTION]</span>`;

          const imgHtml = m.latest_image_path
            ? `<img src="/${m.latest_image_path}" style="width:100%;max-width:220px;border-radius:4px;margin-top:6px;" alt="Captured Target"/>`
            : `<em>No image saved</em>`;

          marker.bindPopup(`
            <div style="min-width:220px;font-family:sans-serif;font-size:12px;">
              <strong style="font-size:13px;">${m.category.toUpperCase()} (${m.priority_level})</strong><br/>
              ${approxBadge}<br/>
              <b>Confidence:</b> ${(m.aggregated_confidence * 100).toFixed(1)}% (${m.observation_count} obs)<br/>
              <b>Est. GPS:</b> ${m.estimated_lat.toFixed(6)}, ${m.estimated_lon.toFixed(6)}<br/>
              <b>Uncertainty:</b> &plusmn;${m.uncertainty_m} m<br/>
              <b>QR Verified:</b> ${m.qr_verified ? "YES (" + m.qr_content + ")" : "No"}<br/>
              <b>Last Seen:</b> ${new Date(m.last_seen_ts * 1000).toLocaleTimeString()}<br/>
              ${imgHtml}
            </div>
          `);
          marker.addTo(markerLayerGroup);
        });
      }

      // Update ADDC 2026 2+2 digit status banner
      const addc = data.addc_intelligence || {};
      const banner = document.getElementById("task2-addc-code-banner");
      if (banner) {
        const dDigits = addc.drone_qr_2_digits || "__";
        const gDigits = addc.ground_operative_puzzle_2_digits || "__";
        banner.textContent = addc.intelligence_code_complete
          ? `ADDC 4-Digit Code Unlocked: ${addc.combined_4_digit_access_code}`
          : `ADDC Code Partial: Drone QR [${dDigits}] + Ground Puzzle [${gDigits}] (Incomplete)`;
      }
    } catch (err) {
      console.debug("Task 2 heatmap poll skipped:", err);
    }
  }

  window.initTask2VisionOverlay = initTask2Overlay;

  // Auto-initialize if DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      injectFilterToolbar();
      setInterval(pollIncrementalHeatmap, 1000);
    });
  } else {
    injectFilterToolbar();
    setInterval(pollIncrementalHeatmap, 1000);
  }
})();

