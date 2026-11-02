const PEACEFUL_COLOUR = '#0072B2';  // Blue  (colour-blind-safe)
const VIOLENT_COLOUR  = '#D55E00';  // Red   (colour-blind-safe)

const MAP_CENTRE    = [51.1032, -1.9541];
const MAP_ZOOM      = 6;
const DUBLIN_CENTRE = [53.3498, -6.2603];
const PARIS_CENTRE  = [48.8566, 2.3522];

const API_PINS_URL       = '/api/v1/pins/';
const API_BOUNDARIES_URL = '/api/v1/boundaries/';
const API_NEAREST_URL    = '/api/v1/pins/nearest/';
const API_WITHIN_URL     = '/api/v1/pins/within/';

const map = L.map('map', {
  center: MAP_CENTRE,
  zoom: MAP_ZOOM,
  zoomControl: true,
});

// OpenStreetMap tile layer
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
  minZoom: 3,
}).addTo(map);

// Dedicated pane so buffer polygons always render below markers
map.createPane('buffersPane');
map.getPane('buffersPane').style.zIndex = 350;

/** Markers layer – circle markers for each pin */
const markersLayer = L.layerGroup().addTo(map);

/** Buffers layer – 100 m polygon overlays (rendered below markers) */
const buffersLayer = L.layerGroup().addTo(map);

/** City Boundaries layer – PostGIS administrative boundaries (Paris, Dublin) */
const boundariesLayer = L.layerGroup().addTo(map);

/** Query visuals layer – search origin, radius circle, KNN connector lines */
const queryVisualsLayer = L.layerGroup().addTo(map);

/* --- State Variables --- */
let currentMode           = 'drop'; // 'drop' | 'nearest' | 'radius'
let currentCategoryFilter = '';     // '' | 'PEACEFUL' | 'VIOLENT'
let nearestLimit          = 5;
let radiusMeters          = 1000;
let activeQuery           = null;   // { type: 'nearest'|'radius', lat, lng, originLabel }

/* --- Prevent map clicks when interacting with overlay controls --- */
// Any click/mousedown on the toolbar, results panel, or legend must NOT
// propagate to the Leaflet map underneath.
document.querySelectorAll('#map-toolbar, #query-results-panel, #legend, #pin-count-badge').forEach((el) => {
  L.DomEvent.disableClickPropagation(el);
  L.DomEvent.disableScrollPropagation(el);
});

function colourForCategory(category) {
  return category === 'VIOLENT' ? VIOLENT_COLOUR : PEACEFUL_COLOUR;
}

function formatDistance(distMeters) {
  if (distMeters === undefined || distMeters === null) return '';
  if (distMeters < 1000) {
    return `${Math.round(distMeters)} m`;
  }
  return `${(distMeters / 1000).toFixed(2)} km`;
}

function buildPopupHtml(feature) {
  const p       = feature.properties || {};
  const pinId   = feature.id ?? p.id;
  const cat     = p.category || 'PEACEFUL';
  const colour  = colourForCategory(cat);
  const label   = cat === 'VIOLENT' ? 'Violent Incident' : 'Peaceful Protest';
  const icon    = cat === 'VIOLENT'
    ? '<i class="bi bi-exclamation-triangle-fill"></i>'
    : '<i class="bi bi-peace"></i>';
  const created = p.created_at
    ? new Date(p.created_at).toLocaleString()
    : '—';

  const distanceHtml = p.distance !== undefined && p.distance !== null
    ? `<div class="badge bg-light text-primary border border-primary-subtle d-inline-flex align-items-center gap-1 mb-2 font-monospace" style="font-size:0.75rem;">
         <i class="bi bi-arrows-expand"></i>
         Distance: <strong>${formatDistance(p.distance)}</strong>
       </div>`
    : '';

  return `
    <div class="pin-popup" style="min-width:220px;">
      <h6 class="fw-semibold mb-1" style="color:${colour};">
        ${icon} ${p.title || 'Unnamed Pin'}
      </h6>
      <div class="d-flex align-items-center gap-1 mb-2">
        <span class="badge" style="background-color:${colour};">${label}</span>
      </div>
      ${distanceHtml ? `<div>${distanceHtml}</div>` : ''}
      ${p.description ? `<p class="mb-1 text-secondary">${p.description}</p>` : ''}
      <p class="text-muted" style="font-size:0.72rem;">Added: ${created}</p>
      <button
        class="btn btn-sm btn-outline-danger mt-1 w-100 delete-pin-btn"
        data-pin-id="${pinId}"
      >
        <i class="bi bi-trash me-1"></i>Delete Pin
      </button>
    </div>`;
}

function addPinToMap(feature) {
  const p      = feature.properties || {};
  const coords = feature.geometry.coordinates; // [lng, lat]
  const lat    = coords[1];
  const lng    = coords[0];
  const colour = colourForCategory(p.category);

  /* --- Circle marker --- */
  const marker = L.circleMarker([lat, lng], {
    radius:              9,
    fillColor:           colour,
    color:               '#ffffff',
    weight:              2,
    opacity:             1,
    fillOpacity:         0.95,
    bubblingMouseEvents: false,
  });

  const popup = L.popup({ maxWidth: 290 }).setContent(buildPopupHtml(feature));
  marker.bindPopup(popup);

  // Wire up popup and click behavior
  marker.on('click', (e) => {
    L.DomEvent.stopPropagation(e);
    if (currentMode === 'nearest') {
      executeNearestQuery(lat, lng, p.title || 'Selected Pin');
    } else if (currentMode === 'radius') {
      executeRadiusQuery(lat, lng, p.title || 'Selected Pin');
    }
  });

  marker.on('popupopen', (e) => {
    const popupEl = e.popup.getElement();
    if (!popupEl) return;
    const btn = popupEl.querySelector('.delete-pin-btn');
    if (btn) {
      btn.onclick = async (btnEvent) => {
        L.DomEvent.stopPropagation(btnEvent);
        const pinId = btn.dataset.pinId;
        if (!pinId || pinId === 'undefined') {
          console.error('Invalid pin ID for deletion:', pinId);
          return;
        }
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Deleting...';
        const success = await deletePin(pinId);
        if (success) {
          marker.closePopup();
          await refreshPins();
          if (activeQuery) clearQuery();
        } else {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete Failed (Retry)';
        }
      };
    }
  });

  markersLayer.addLayer(marker);

  /* --- 100 m buffer polygon --- */
  if (p.buffer_geom && p.buffer_geom.coordinates) {
    const bufferLayer = L.geoJSON(p.buffer_geom, {
      pane:        'buffersPane',
      interactive: false,
      style: {
        fillColor:   colour,
        fillOpacity: 0.15,
        color:       colour,
        weight:      1.5,
        opacity:     0.5,
        dashArray:   '4 4',
      },
    });
    buffersLayer.addLayer(bufferLayer);
  }
}

async function loadBoundaries() {
  try {
    const response = await fetch(API_BOUNDARIES_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    boundariesLayer.clearLayers();
    L.geoJSON(data, {
      style: {
        color:       '#6f42c1',
        weight:      3,
        dashArray:   '8, 4',
        fillColor:   '#6f42c1',
        fillOpacity: 0.06,
        opacity:     0.9,
      },
      onEachFeature: (feature, layer) => {
        const name = feature.properties?.name || 'City';
        layer.bindTooltip(
          `<strong>${name}</strong> City Boundary<br><small class="text-muted">PostGIS ST_Contains enforced</small>`,
          { sticky: true, className: 'boundary-tooltip' }
        );
      },
    }).addTo(boundariesLayer);

    console.log(`Loaded ${(data.features || []).length} city boundary polygon(s)`);
  } catch (err) {
    console.error('Failed to load city boundaries:', err);
  }
}

async function refreshPins() {
  try {
    let url = API_PINS_URL;
    if (currentCategoryFilter) {
      url += `?category=${encodeURIComponent(currentCategoryFilter)}`;
    }
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const geojson = await response.json(); // GeoJSON FeatureCollection

    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    const features = geojson.features || [];
    features.forEach(addPinToMap);

    document.getElementById('pin-count').textContent = features.length;
  } catch (err) {
    console.error('Failed to load pins:', err);
  }
}

/* --- Spatial Query Execution --- */

async function executeNearestQuery(lat, lng, originLabel = 'Selected Point') {
  queryVisualsLayer.clearLayers();
  activeQuery = { type: 'nearest', lat, lng, originLabel };

  // Draw query origin marker
  const originMarker = L.circleMarker([lat, lng], {
    radius:      9,
    color:       '#0d6efd',
    fillColor:   '#ffc107',
    fillOpacity: 1,
    weight:      3,
  }).bindPopup(
    `<strong>KNN Query Origin</strong><br>${originLabel}<br><small class="text-muted">Lat: ${lat.toFixed(5)}, Lng: ${lng.toFixed(5)}</small>`
  );
  queryVisualsLayer.addLayer(originMarker);

  document.getElementById('btn-clear-query').classList.remove('d-none');

  try {
    let url = `${API_NEAREST_URL}?lat=${lat}&lon=${lng}&limit=${nearestLimit}`;
    if (currentCategoryFilter) {
      url += `&category=${encodeURIComponent(currentCategoryFilter)}`;
    }

    const response = await fetch(url);
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    const features = data.features || [];

    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    features.forEach((feature) => {
      addPinToMap(feature);
      const coords = feature.geometry.coordinates;
      // Draw dashed connector line between origin and nearest pin
      const line = L.polyline([[lat, lng], [coords[1], coords[0]]], {
        color:     '#0d6efd',
        weight:    2,
        dashArray: '5, 5',
        opacity:   0.75,
      });
      queryVisualsLayer.addLayer(line);
    });

    document.getElementById('pin-count').textContent = features.length;

    renderResultsPanel({
      title: `<i class="bi bi-crosshair text-primary me-1"></i>Nearest ${features.length} Pin(s)`,
      meta:  `KNN search from <strong>${originLabel}</strong> (${lat.toFixed(4)}, ${lng.toFixed(4)})`,
      features,
    });
  } catch (err) {
    console.error('Nearest query failed:', err);
  }
}

async function executeRadiusQuery(lat, lng, originLabel = 'Selected Point') {
  queryVisualsLayer.clearLayers();
  activeQuery = { type: 'radius', lat, lng, originLabel };

  // Draw query origin marker
  const originMarker = L.circleMarker([lat, lng], {
    radius:      9,
    color:       '#0d6efd',
    fillColor:   '#ffc107',
    fillOpacity: 1,
    weight:      3,
  }).bindPopup(
    `<strong>Radius Query Origin</strong><br>${originLabel}<br><small class="text-muted">Lat: ${lat.toFixed(5)}, Lng: ${lng.toFixed(5)}</small>`
  );
  queryVisualsLayer.addLayer(originMarker);

  // Draw search radius circle
  const searchCircle = L.circle([lat, lng], {
    radius:      radiusMeters,
    color:       '#0d6efd',
    fillColor:   '#0d6efd',
    fillOpacity: 0.12,
    weight:      2,
    dashArray:   '6, 6',
  });
  queryVisualsLayer.addLayer(searchCircle);

  document.getElementById('btn-clear-query').classList.remove('d-none');

  try {
    let url = `${API_WITHIN_URL}?lat=${lat}&lon=${lng}&radius_m=${radiusMeters}`;
    if (currentCategoryFilter) {
      url += `&category=${encodeURIComponent(currentCategoryFilter)}`;
    }

    const response = await fetch(url);
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    const features = data.features || [];

    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    features.forEach(addPinToMap);
    document.getElementById('pin-count').textContent = features.length;

    renderResultsPanel({
      title: `<i class="bi bi-record-circle text-primary me-1"></i>Within Radius (${formatDistance(radiusMeters)})`,
      meta:  `Found <strong>${features.length}</strong> pin(s) within ${formatDistance(radiusMeters)} of ${originLabel}`,
      features,
    });
  } catch (err) {
    console.error('Radius query failed:', err);
  }
}

function renderResultsPanel({ title, meta, features }) {
  const panel   = document.getElementById('query-results-panel');
  const titleEl = document.getElementById('results-title');
  const metaEl  = document.getElementById('results-meta');
  const listEl  = document.getElementById('results-list');

  titleEl.innerHTML = title;
  metaEl.innerHTML  = meta;
  listEl.innerHTML  = '';

  if (features.length === 0) {
    listEl.innerHTML = `
      <div class="p-3 text-center text-muted small">
        <i class="bi bi-inbox fs-4 d-block mb-1"></i>No pins found matching spatial query.
      </div>`;
    panel.classList.remove('d-none');
    return;
  }

  features.forEach((f) => {
    const p          = f.properties || {};
    const coords     = f.geometry.coordinates;
    const cat        = p.category || 'PEACEFUL';
    const isViolent  = cat === 'VIOLENT';
    const badgeClass = isViolent ? 'text-bg-danger' : 'text-bg-primary';
    const icon       = isViolent ? 'bi-exclamation-triangle-fill' : 'bi-peace';

    const item = document.createElement('div');
    item.className = 'result-item';
    item.innerHTML = `
      <div class="d-flex justify-content-between align-items-start gap-1">
        <strong class="small text-truncate" style="max-width: 180px;" title="${p.title || 'Pin'}">
          <i class="bi ${icon} me-1 text-${isViolent ? 'danger' : 'primary'}"></i>${p.title || 'Pin'}
        </strong>
        <span class="badge ${badgeClass}" style="font-size:0.65rem;">${cat}</span>
      </div>
      <div class="d-flex justify-content-between align-items-center mt-1">
        <span class="badge bg-light text-dark border font-monospace" style="font-size:0.7rem;">
          <i class="bi bi-arrows-expand me-1 text-primary"></i>${formatDistance(p.distance)}
        </span>
        <button class="btn btn-sm btn-link p-0 text-decoration-none small text-primary">
          <i class="bi bi-geo-alt me-1"></i>Zoom
        </button>
      </div>
    `;

    item.addEventListener('click', () => {
      map.flyTo([coords[1], coords[0]], 15, { duration: 0.8 });
    });

    listEl.appendChild(item);
  });

  panel.classList.remove('d-none');
}

function clearQuery() {
  activeQuery = null;
  queryVisualsLayer.clearLayers();
  document.getElementById('query-results-panel').classList.add('d-none');
  document.getElementById('btn-clear-query').classList.add('d-none');
  refreshPins();
}

/* --- Modal & Drop Pin Flow --- */

const dropPinModal = new bootstrap.Modal(
  document.getElementById('dropPinModal'),
  { backdrop: 'static' }
);

/** Coordinates stored when user clicks the map */
let pendingLatLng = null;

/** Temporary marker shown while the modal is open */
let tempMarker = null;

/**
 * Handle map click: evaluate current mode.
 * @param {L.MouseEvent} e
 */
map.on('click', (e) => {
  if (currentMode === 'nearest') {
    executeNearestQuery(e.latlng.lat, e.latlng.lng, 'Map Location');
    return;
  }
  if (currentMode === 'radius') {
    executeRadiusQuery(e.latlng.lat, e.latlng.lng, 'Map Location');
    return;
  }

  // Otherwise 'drop' mode:
  pendingLatLng = e.latlng;

  document.getElementById('modal-lat').textContent = e.latlng.lat.toFixed(6);
  document.getElementById('modal-lng').textContent = e.latlng.lng.toFixed(6);

  if (tempMarker) map.removeLayer(tempMarker);
  tempMarker = L.circleMarker(e.latlng, {
    radius:      9,
    fillColor:   '#888',
    color:       '#fff',
    weight:      2,
    opacity:     0.8,
    fillOpacity: 0.6,
  }).addTo(map);

  resetForm();
  dropPinModal.show();
});

document.getElementById('dropPinModal').addEventListener('hidden.bs.modal', () => {
  if (tempMarker) {
    map.removeLayer(tempMarker);
    tempMarker = null;
  }
  pendingLatLng = null;
});

document.getElementById('submit-pin-btn').addEventListener('click', async () => {
  const form = document.getElementById('drop-pin-form');

  form.classList.add('was-validated');
  if (!form.checkValidity()) return;

  if (!pendingLatLng) return;

  const category    = form.querySelector('input[name="category"]:checked').value;
  const title       = document.getElementById('pin-title').value.trim();
  const description = document.getElementById('pin-description').value.trim();

  setSubmitting(true);
  hideFormAlert();

  try {
    const csrfToken = getCsrfToken();
    const response = await fetch(API_PINS_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken':  csrfToken,
      },
      body: JSON.stringify({
        title,
        description,
        category,
        latitude:  pendingLatLng.lat,
        longitude: pendingLatLng.lng,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      const messages = Object.entries(data)
        .map(([key, val]) => `<strong>${key}:</strong> ${[].concat(val).join(', ')}`)
        .join('<br>');
      showFormAlert('danger', messages || 'Failed to create pin. Please try again.');
      return;
    }

    dropPinModal.hide();
    await refreshPins();

  } catch (err) {
    console.error('POST /api/v1/pins/ failed:', err);
    showFormAlert('danger', 'Network error. Please check your connection and try again.');
  } finally {
    setSubmitting(false);
  }
});

async function deletePin(pinId) {
  try {
    const response = await fetch(`${API_PINS_URL}${pinId}/`, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': getCsrfToken() },
    });
    return response.ok || response.status === 204;
  } catch (err) {
    console.error('DELETE failed:', err);
    return false;
  }
}

function getCsrfToken() {
  const name   = 'csrftoken';
  const cookie = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith(name + '='));
  if (cookie) {
    return decodeURIComponent(cookie.split('=')[1]);
  }
  const input = document.querySelector('[name=csrfmiddlewaretoken]');
  return input ? input.value : '';
}

function setSubmitting(isSubmitting) {
  const btn     = document.getElementById('submit-pin-btn');
  const spinner = document.getElementById('submit-spinner');
  const icon    = document.getElementById('submit-icon');
  btn.disabled        = isSubmitting;
  spinner.classList.toggle('d-none', !isSubmitting);
  icon.classList.toggle('d-none', isSubmitting);
}

function showFormAlert(type, html) {
  const el = document.getElementById('form-alert');
  el.className = `alert alert-${type}`;
  el.innerHTML = html;
  el.classList.remove('d-none');
}

function hideFormAlert() {
  const el = document.getElementById('form-alert');
  el.classList.add('d-none');
  el.innerHTML = '';
}

function resetForm() {
  const form = document.getElementById('drop-pin-form');
  form.classList.remove('was-validated');
  document.getElementById('pin-title').value       = '';
  document.getElementById('pin-description').value = '';
  document.getElementById('cat-peaceful').checked  = true;
  hideFormAlert();
  setSubmitting(false);
}

/* --- UI Controls & Event Listeners --- */

// Mode toggle buttons
document.querySelectorAll('input[name="map-mode"]').forEach((radio) => {
  radio.addEventListener('change', (e) => {
    currentMode = e.target.value;
    document.getElementById('subpanel-drop').classList.toggle('d-none', currentMode !== 'drop');
    document.getElementById('subpanel-nearest').classList.toggle('d-none', currentMode !== 'nearest');
    document.getElementById('subpanel-radius').classList.toggle('d-none', currentMode !== 'radius');

    const mapEl = document.getElementById('map');
    mapEl.style.cursor = currentMode === 'drop' ? 'crosshair' : 'pointer';
  });
});

// Category filter
document.getElementById('filter-category').addEventListener('change', (e) => {
  currentCategoryFilter = e.target.value;
  if (activeQuery) {
    if (activeQuery.type === 'nearest') {
      executeNearestQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
    } else if (activeQuery.type === 'radius') {
      executeRadiusQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
    }
  } else {
    refreshPins();
  }
});

// City Jump buttons
document.getElementById('btn-jump-dublin').addEventListener('click', () => {
  map.flyTo(DUBLIN_CENTRE, 13);
});
document.getElementById('btn-jump-paris').addEventListener('click', () => {
  map.flyTo(PARIS_CENTRE, 13);
});

// Boundaries toggle
document.getElementById('toggle-boundaries').addEventListener('change', (e) => {
  if (e.target.checked) {
    boundariesLayer.addTo(map);
  } else {
    map.removeLayer(boundariesLayer);
  }
});

// Radius slider
const radiusSlider = document.getElementById('radius-slider');
const radiusVal    = document.getElementById('radius-val');
radiusSlider.addEventListener('input', (e) => {
  radiusMeters = parseInt(e.target.value, 10);
  radiusVal.textContent = formatDistance(radiusMeters);
  if (activeQuery && activeQuery.type === 'radius') {
    executeRadiusQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
  }
});

// Nearest limit
document.getElementById('nearest-limit').addEventListener('change', (e) => {
  nearestLimit = parseInt(e.target.value, 10);
  if (activeQuery && activeQuery.type === 'nearest') {
    executeNearestQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
  }
});

// Reset and close results panel
document.getElementById('btn-clear-query').addEventListener('click', clearQuery);
document.getElementById('btn-close-results').addEventListener('click', () => {
  document.getElementById('query-results-panel').classList.add('d-none');
});

/* --- Initialization --- */
document.addEventListener('DOMContentLoaded', () => {
  loadBoundaries();
  refreshPins();
});
