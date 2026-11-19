const HAZARD_COLOUR = '#D55E00';

const MAP_CENTRE = [48.8566, 2.3522];
const MAP_ZOOM   = 12;

const API_PINS_URL    = '/api/v1/pins/';
const API_CITIES_URL  = '/api/v1/cities/';
const API_NEAREST_URL = '/api/v1/pins/nearest/';
const API_WITHIN_URL  = '/api/v1/pins/within/';

const map = L.map('map', {
  center: MAP_CENTRE,
  zoom: MAP_ZOOM,
  zoomControl: true,
});

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
  minZoom: 3,
}).addTo(map);

// zIndex 350 ensures buffer polygons always render underneath circle markers
map.createPane('buffersPane');
map.getPane('buffersPane').style.zIndex = 350;

const markersLayer      = L.layerGroup().addTo(map);
const buffersLayer      = L.layerGroup().addTo(map);
const boundariesLayer   = L.layerGroup().addTo(map);
const queryVisualsLayer = L.layerGroup().addTo(map);

let currentMode  = 'drop';
let nearestLimit = 5;
let radiusMeters = 1000;
let activeQuery  = null;

function getOwnerToken() {
  let token = localStorage.getItem('owner_token');
  if (!token) {
    token = crypto.randomUUID();
    localStorage.setItem('owner_token', token);
  }
  return token;
}

function getOwnedIds() {
  try {
    const raw = localStorage.getItem('owned_pin_ids');
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(arr.map(Number));
  } catch (e) {
    return new Set();
  }
}

function addOwnedId(pinId) {
  const ids = getOwnedIds();
  ids.add(Number(pinId));
  localStorage.setItem('owned_pin_ids', JSON.stringify(Array.from(ids)));
}

function removeOwnedId(pinId) {
  const ids = getOwnedIds();
  ids.delete(Number(pinId));
  localStorage.setItem('owned_pin_ids', JSON.stringify(Array.from(ids)));
}

// Stop click/scroll propagation so UI controls don't trigger map clicks
document.querySelectorAll('#map-toolbar, #query-results-panel, #legend, #pin-count-badge').forEach((el) => {
  L.DomEvent.disableClickPropagation(el);
  L.DomEvent.disableScrollPropagation(el);
});

function formatDistance(distMeters) {
  if (distMeters === undefined || distMeters === null) return '';
  if (distMeters < 1000) {
    return `${Math.round(distMeters)} m`;
  }
  return `${(distMeters / 1000).toFixed(2)} km`;
}

function formatExpiryCountdown(expiresAtStr) {
  if (!expiresAtStr) return '';
  const expiresAt = new Date(expiresAtStr);
  const now = new Date();
  const diffMs = expiresAt - now;
  if (diffMs <= 0) return 'expired';
  const diffMin = Math.ceil(diffMs / 60000);
  if (diffMin >= 60) {
    const hours = Math.floor(diffMin / 60);
    const mins = diffMin % 60;
    return `expires in ${hours}h ${mins}m`;
  }
  return `expires in ${diffMin} min`;
}

function showToast(message) {
  const toastEl = document.getElementById('app-toast');
  const msgEl = document.getElementById('toast-message');
  if (toastEl && msgEl) {
    msgEl.textContent = message;
    const toast = bootstrap.Toast.getOrCreateInstance(toastEl);
    toast.show();
  } else {
    alert(message);
  }
}

function buildPopupHtml(feature) {
  const p       = feature.properties || {};
  const pinId   = feature.id ?? p.id;
  const isOwned = getOwnedIds().has(Number(pinId));

  const created = p.created_at
    ? new Date(p.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '—';

  const expiryText = formatExpiryCountdown(p.expires_at);

  const distanceHtml = p.distance !== undefined && p.distance !== null
    ? `<div class="badge bg-light text-primary border border-primary-subtle d-inline-flex align-items-center gap-1 mb-2 font-monospace" style="font-size:0.75rem;">
         <i class="bi bi-arrows-expand"></i>
         Distance: <strong>${formatDistance(p.distance)}</strong>
       </div>`
    : '';

  const actionHtml = isOwned
    ? `<button
         class="btn btn-sm btn-outline-danger mt-2 w-100 delete-pin-btn"
         data-pin-id="${pinId}"
       >
         <i class="bi bi-trash me-1"></i>Delete Pin
       </button>`
    : `<p class="text-muted small mb-0 mt-2 fst-italic">
         <i class="bi bi-person me-1"></i>Reported by another user
       </p>`;

  return `
    <div class="pin-popup" style="min-width:220px;">
      <h6 class="fw-semibold mb-1" style="color:${HAZARD_COLOUR};">
        <i class="bi bi-exclamation-triangle-fill me-1"></i>Hazard Incident
      </h6>
      <div class="d-flex align-items-center gap-1 mb-2">
        <span class="badge" style="background-color:${HAZARD_COLOUR};">Active Hazard</span>
        <span class="badge bg-secondary font-monospace">${expiryText}</span>
      </div>
      ${distanceHtml ? `<div>${distanceHtml}</div>` : ''}
      ${p.description ? `<p class="mb-1 text-secondary">${p.description}</p>` : '<p class="mb-1 text-muted fst-italic">No description provided.</p>'}
      <p class="text-muted" style="font-size:0.72rem;">Reported: ${created}</p>
      ${actionHtml}
    </div>`;
}

function addPinToMap(feature) {
  const p      = feature.properties || {};
  const coords = feature.geometry.coordinates;
  const lat    = coords[1];
  const lng    = coords[0];

  const marker = L.circleMarker([lat, lng], {
    radius:              9,
    fillColor:           HAZARD_COLOUR,
    color:               '#ffffff',
    weight:              2,
    opacity:             1,
    fillOpacity:         0.95,
    bubblingMouseEvents: false,
  });

  const popup = L.popup({ maxWidth: 290 }).setContent(buildPopupHtml(feature));
  marker.bindPopup(popup);

  marker.on('click', (e) => {
    L.DomEvent.stopPropagation(e);
    if (currentMode === 'nearest') {
      executeNearestQuery(lat, lng, p.description || 'Hazard Pin');
    } else if (currentMode === 'radius') {
      executeRadiusQuery(lat, lng, p.description || 'Hazard Pin');
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
        if (!pinId || pinId === 'undefined') return;

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Deleting...';
        const success = await deletePin(pinId);
        if (success) {
          removeOwnedId(pinId);
          marker.closePopup();
          await refreshPins();
          if (activeQuery) clearQuery();
        } else {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete Pin';
        }
      };
    }
  });

  markersLayer.addLayer(marker);

  if (p.buffer_geom && p.buffer_geom.coordinates) {
    const bufferLayer = L.geoJSON(p.buffer_geom, {
      pane:        'buffersPane',
      interactive: false,
      style: {
        fillColor:   HAZARD_COLOUR,
        fillOpacity: 0.15,
        color:       HAZARD_COLOUR,
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
    const response = await fetch(API_CITIES_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    boundariesLayer.clearLayers();
    const cityButtonsContainer = document.getElementById('city-jump-buttons');
    if (cityButtonsContainer) {
      cityButtonsContainer.innerHTML = '';
    }

    const geoJsonLayer = L.geoJSON(data, {
      style: {
        color:       '#6f42c1',
        weight:      3,
        dashArray:   '8, 4',
        fillColor:   '#6f42c1',
        fillOpacity: 0.06,
        opacity:     0.9,
      },
      onEachFeature: (feature, layer) => {
        const name = feature.properties?.name || 'Paris';
        layer.bindTooltip(
          `<strong>${name}</strong> City Boundary<br><small class="text-muted">PostGIS ST_Contains enforced</small>`,
          { sticky: true, className: 'boundary-tooltip' }
        );

        if (cityButtonsContainer) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-outline-secondary';
          btn.textContent = name;
          btn.title = `Fly to ${name}`;
          btn.addEventListener('click', () => {
            const bounds = layer.getBounds();
            if (bounds && bounds.isValid()) {
              map.fitBounds(bounds, { padding: [20, 20] });
            } else {
              map.flyTo(MAP_CENTRE, MAP_ZOOM);
            }
          });
          cityButtonsContainer.appendChild(btn);
        }
      },
    });

    geoJsonLayer.addTo(boundariesLayer);
  } catch (err) {
    console.error('Failed to load city boundaries:', err);
  }
}

async function refreshPins() {
  try {
    const response = await fetch(API_PINS_URL);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const geojson = await response.json();

    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    const features = geojson.features || [];
    features.forEach(addPinToMap);

    const countEl = document.getElementById('pin-count');
    if (countEl) countEl.textContent = features.length;
  } catch (err) {
    console.error('Failed to load pins:', err);
  }
}

async function executeNearestQuery(lat, lng, originLabel = 'Selected Point') {
  queryVisualsLayer.clearLayers();
  activeQuery = { type: 'nearest', lat, lng, originLabel };

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
    const url = `${API_NEAREST_URL}?lat=${lat}&lon=${lng}&limit=${nearestLimit}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json();
    const features = data.features || [];

    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    features.forEach((feature) => {
      addPinToMap(feature);
      const coords = feature.geometry.coordinates;
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
      title: `<i class="bi bi-crosshair text-primary me-1"></i>Nearest ${features.length} Hazard(s)`,
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
    const url = `${API_WITHIN_URL}?lat=${lat}&lon=${lng}&radius_m=${radiusMeters}`;
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
      meta:  `Found <strong>${features.length}</strong> hazard(s) within ${formatDistance(radiusMeters)} of ${originLabel}`,
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
        <i class="bi bi-inbox fs-4 d-block mb-1"></i>No hazards found matching spatial query.
      </div>`;
    panel.classList.remove('d-none');
    return;
  }

  features.forEach((f) => {
    const p          = f.properties || {};
    const coords     = f.geometry.coordinates;
    const desc       = p.description || 'Hazard Incident';
    const expiryText = formatExpiryCountdown(p.expires_at);

    const item = document.createElement('div');
    item.className = 'result-item';
    item.innerHTML = `
      <div class="d-flex justify-content-between align-items-start gap-1">
        <strong class="small text-truncate" style="max-width: 180px;" title="${desc}">
          <i class="bi bi-exclamation-triangle-fill me-1 text-danger"></i>${desc}
        </strong>
        <span class="badge bg-secondary font-monospace" style="font-size:0.65rem;">${expiryText}</span>
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

function getDropPinModal() {
  const el = document.getElementById('dropPinModal');
  if (!el || typeof bootstrap === 'undefined') return null;
  return bootstrap.Modal.getOrCreateInstance(el, { backdrop: 'static' });
}

let pendingLatLng = null;
let tempMarker    = null;

map.on('click', (e) => {
  if (currentMode === 'nearest') {
    executeNearestQuery(e.latlng.lat, e.latlng.lng, 'Map Location');
    return;
  }
  if (currentMode === 'radius') {
    executeRadiusQuery(e.latlng.lat, e.latlng.lng, 'Map Location');
    return;
  }

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
  getDropPinModal()?.show();
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

  const description = document.getElementById('pin-description').value.trim();

  setSubmitting(true);
  hideFormAlert();

  try {
    const csrfToken  = getCsrfToken();
    const ownerToken = getOwnerToken();

    const response = await fetch(API_PINS_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken':  csrfToken,
      },
      body: JSON.stringify({
        description,
        latitude:    pendingLatLng.lat,
        longitude:   pendingLatLng.lng,
        owner_token: ownerToken,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      let messages = '';
      if (data.non_field_errors) {
        messages = [].concat(data.non_field_errors).join('<br>');
      } else {
        messages = Object.entries(data)
          .map(([key, val]) => `<strong>${key}:</strong> ${[].concat(val).join(', ')}`)
          .join('<br>');
      }
      showFormAlert('danger', messages || 'Failed to report hazard. Please try again.');
      return;
    }

    const createdId = data.id ?? data.properties?.id;
    if (createdId) {
      addOwnedId(createdId);
    }

    getDropPinModal()?.hide();
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
      headers: {
        'X-CSRFToken':   getCsrfToken(),
        'X-Owner-Token': getOwnerToken(),
      },
    });

    if (response.status === 403) {
      showToast('You can only delete pins you created.');
      return false;
    }

    return response.ok || response.status === 204;
  } catch (err) {
    console.error('DELETE failed:', err);
    showToast('Failed to delete pin. Network error.');
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
  document.getElementById('pin-description').value = '';
  hideFormAlert();
  setSubmitting(false);
}

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

document.getElementById('toggle-boundaries').addEventListener('change', (e) => {
  if (e.target.checked) {
    boundariesLayer.addTo(map);
  } else {
    map.removeLayer(boundariesLayer);
  }
});

const radiusSlider = document.getElementById('radius-slider');
const radiusVal    = document.getElementById('radius-val');
radiusSlider.addEventListener('input', (e) => {
  radiusMeters = parseInt(e.target.value, 10);
  radiusVal.textContent = formatDistance(radiusMeters);
  if (activeQuery && activeQuery.type === 'radius') {
    executeRadiusQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
  }
});

document.getElementById('nearest-limit').addEventListener('change', (e) => {
  nearestLimit = parseInt(e.target.value, 10);
  if (activeQuery && activeQuery.type === 'nearest') {
    executeNearestQuery(activeQuery.lat, activeQuery.lng, activeQuery.originLabel);
  }
});

document.getElementById('btn-clear-query').addEventListener('click', clearQuery);
document.getElementById('btn-close-results').addEventListener('click', () => {
  document.getElementById('query-results-panel').classList.add('d-none');
});

setInterval(refreshPins, 30000);

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    refreshPins();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  getOwnerToken();
  loadBoundaries();
  refreshPins();
  setTimeout(() => map.invalidateSize(), 200);
});

window.addEventListener('resize', () => map.invalidateSize());
