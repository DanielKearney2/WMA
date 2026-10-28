const PEACEFUL_COLOUR = '#0072B2';  // Blue  (colour-blind-safe)
const VIOLENT_COLOUR  = '#D55E00';  // Red   (colour-blind-safe)

const MAP_CENTRE = [51.1032, -1.9541];
const MAP_ZOOM   = 6;

const API_PINS_URL = '/api/v1/pins/';

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

/** Markers layer – circle markers for each pin */
const markersLayer = L.layerGroup().addTo(map);

/** Buffers layer – 100 m polygon overlays (rendered below markers) */
const buffersLayer = L.layerGroup().addTo(map);

// Ensure buffers render underneath markers in the z-order
map.removeLayer(buffersLayer);
map.removeLayer(markersLayer);
buffersLayer.addTo(map);   // added first → lower z-index
markersLayer.addTo(map);   // added second → higher z-index

function colourForCategory(category) {
  return category === 'VIOLENT' ? VIOLENT_COLOUR : PEACEFUL_COLOUR;
}

function buildPopupHtml(feature) {
  const p       = feature.properties;
  const cat     = p.category || 'PEACEFUL';
  const colour  = colourForCategory(cat);
  const label   = cat === 'VIOLENT' ? 'Violent Incident' : 'Peaceful Protest';
  const icon    = cat === 'VIOLENT'
    ? '<i class="bi bi-exclamation-triangle-fill"></i>'
    : '<i class="bi bi-peace"></i>';
  const created = p.created_at
    ? new Date(p.created_at).toLocaleString()
    : '—';

  return `
    <div class="pin-popup" style="min-width:210px;">
      <h6 class="fw-semibold mb-1" style="color:${colour};">
        ${icon} ${p.title || 'Unnamed Pin'}
      </h6>
      <span class="badge mb-2" style="background-color:${colour};">${label}</span>
      ${p.description ? `<p class="mb-1">${p.description}</p>` : ''}
      <p class="text-muted" style="font-size:0.72rem;">Added: ${created}</p>
      <button
        class="btn btn-sm btn-outline-danger mt-1 w-100 delete-pin-btn"
        data-pin-id="${p.id}"
      >
        <i class="bi bi-trash me-1"></i>Delete Pin
      </button>
    </div>`;
}

function addPinToMap(feature) {
  const p      = feature.properties;
  const coords = feature.geometry.coordinates;  // [lng, lat]
  const lat    = coords[1];
  const lng    = coords[0];
  const colour = colourForCategory(p.category);

  /* --- Circle marker --- */
  const marker = L.circleMarker([lat, lng], {
    radius:      9,
    fillColor:   colour,
    color:       '#ffffff',
    weight:      2,
    opacity:     1,
    fillOpacity: 0.95,
  });

  const popup = L.popup({ maxWidth: 280 }).setContent(buildPopupHtml(feature));
  marker.bindPopup(popup);

  // Wire up delete button inside the popup
  marker.on('popupopen', () => {
    document.querySelectorAll('.delete-pin-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const pinId = btn.dataset.pinId;
        if (await deletePin(pinId)) {
          marker.closePopup();
          await refreshPins();
        }
      });
    });
  });

  markersLayer.addLayer(marker);

  /* --- 100 m buffer polygon --- */
  if (p.buffer_geom && p.buffer_geom.coordinates) {
    const bufferLayer = L.geoJSON(p.buffer_geom, {
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

async function refreshPins() {
  try {
    const response = await fetch(API_PINS_URL);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const geojson = await response.json();  // GeoJSON FeatureCollection

    // Clear existing layers
    markersLayer.clearLayers();
    buffersLayer.clearLayers();

    const features = geojson.features || [];
    features.forEach(addPinToMap);

    // Update badge count
    document.getElementById('pin-count').textContent = features.length;
  } catch (err) {
    console.error('Failed to load pins:', err);
  }
}

const dropPinModal = new bootstrap.Modal(
  document.getElementById('dropPinModal'),
  { backdrop: 'static' }
);

/** Coordinates stored when user clicks the map */
let pendingLatLng = null;

/** Temporary marker shown while the modal is open */
let tempMarker = null;

/**
 * Handle map click: store coordinates, update modal UI, open modal.
 * @param {L.MouseEvent} e
 */
map.on('click', (e) => {
  pendingLatLng = e.latlng;

  // Update coordinate display in modal
  document.getElementById('modal-lat').textContent = e.latlng.lat.toFixed(6);
  document.getElementById('modal-lng').textContent = e.latlng.lng.toFixed(6);

  // Drop a temporary grey placeholder marker
  if (tempMarker) map.removeLayer(tempMarker);
  tempMarker = L.circleMarker(e.latlng, {
    radius:      9,
    fillColor:   '#888',
    color:       '#fff',
    weight:      2,
    opacity:     0.8,
    fillOpacity: 0.6,
  }).addTo(map);

  // Reset form state
  resetForm();

  dropPinModal.show();
});

/** Remove the temporary marker when the modal is dismissed without submitting. */
document.getElementById('dropPinModal').addEventListener('hidden.bs.modal', () => {
  if (tempMarker) {
    map.removeLayer(tempMarker);
    tempMarker = null;
  }
  pendingLatLng = null;
});

document.getElementById('submit-pin-btn').addEventListener('click', async () => {
  const form = document.getElementById('drop-pin-form');

  // Simple Bootstrap validation
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
      // Show API validation errors
      const messages = Object.entries(data)
        .map(([key, val]) => `<strong>${key}:</strong> ${[].concat(val).join(', ')}`)
        .join('<br>');
      showFormAlert('danger', messages || 'Failed to create pin. Please try again.');
      return;
    }

    // Success – close modal and refresh map
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
  return cookie ? decodeURIComponent(cookie.split('=')[1]) : '';
}

/** Toggle the submit button between normal and loading states. */
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

/** Reset the pin form back to its default state. */
function resetForm() {
  const form = document.getElementById('drop-pin-form');
  form.classList.remove('was-validated');
  document.getElementById('pin-title').value       = '';
  document.getElementById('pin-description').value = '';
  document.getElementById('cat-peaceful').checked  = true;
  hideFormAlert();
  setSubmitting(false);
}

document.addEventListener('DOMContentLoaded', () => {
  refreshPins();
});
