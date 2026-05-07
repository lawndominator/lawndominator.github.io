// Soil temperature page logic — requires tools.js, Leaflet, Chart.js

var currentGrassType = 'bermuda';
var currentTemp2in = null;
var soilMap = null;
var soilMarker = null;
var soilChart = null;

var INTERPRETATIONS = {
  bermuda: [
    { max: 50, text: "Bermuda is dormant. Hold all fertilizer, herbicide, and PGR applications. Resume when soil consistently reaches 50°F." },
    { max: 55, text: "Bermuda is at the pre-emergent window. Apply crabgrass pre-emergent now if you haven't already — the window closes as soil warms past 55°F." },
    { max: 65, text: "Bermuda is breaking dormancy. Light nitrogen is OK — wait for a visible flush of green before resuming a full program." },
    { max: 80, text: "Bermuda is in active growth. Your full fertilizer, herbicide, and PGR program is appropriate." },
    { max: Infinity, text: "Soil is hot. Avoid elemental sulfur and any heat-stress products. Maintain irrigation to prevent drought dormancy." }
  ],
  zoysia: [
    { max: 55, text: "Zoysia is dormant or just beginning to stir. Hold all fertilizer and PGR until soil temps are consistently above 55°F." },
    { max: 65, text: "Zoysia is at the pre-emergent window. Apply crabgrass pre-emergent before soil reaches 65°F." },
    { max: 80, text: "Zoysia is in active growth. Full program is appropriate — confirm visual greenup before applying nitrogen, as zoysia breaks later than bermuda." },
    { max: Infinity, text: "Soil is hot. Monitor for brown patch pressure and keep irrigation consistent." }
  ],
  'st-augustine': [
    { max: 60, text: "St. Augustine is dormant or recovering. Hold nitrogen until soil temps are consistently above 60°F." },
    { max: 70, text: "St. Augustine is waking up. Pre-emergent timing is active. Most St. Augustine programs don't include PGR." },
    { max: 85, text: "St. Augustine is in active growth. Full fertilizer program is appropriate. Watch for chinch bugs as temps climb." },
    { max: Infinity, text: "Extreme heat. St. Augustine is heat-stressed. Limit applications and prioritize irrigation." }
  ],
  'cool-season': [
    { max: 45, text: "Too cold for active growth. Cool-season grass is in winter dormancy." },
    { max: 65, text: "Ideal range for cool-season growth. Spring program is appropriate — fertilize lightly and watch for disease pressure." },
    { max: 75, text: "Warming toward summer stress threshold. Reduce nitrogen and prepare for potential summer dormancy." },
    { max: Infinity, text: "Cool-season grass is likely heat-stressed or dormant. Hold fertilizer, maintain irrigation, and wait for fall." }
  ]
};

function getInterpretation(grassType, temp) {
  var thresholds = INTERPRETATIONS[grassType] || INTERPRETATIONS.bermuda;
  for (var i = 0; i < thresholds.length; i++) {
    if (temp < thresholds[i].max) return thresholds[i].text;
  }
  return thresholds[thresholds.length - 1].text;
}

function getBadge(temp) {
  if (temp < 50) return { label: 'Cold', cls: 'blue' };
  if (temp < 65) return { label: 'Cool', cls: 'yellow' };
  if (temp <= 80) return { label: 'Active', cls: 'green' };
  return { label: 'Hot', cls: 'red' };
}

function round1(v) { return Math.round(v * 10) / 10; }

async function fetchSoilData(lat, lon) {
  var url = 'https://api.open-meteo.com/v1/forecast' +
    '?latitude=' + lat + '&longitude=' + lon +
    '&hourly=soil_temperature_0cm,soil_temperature_6cm,soil_temperature_18cm' +
    '&temperature_unit=fahrenheit&timezone=auto&past_days=6&forecast_days=1';
  var res = await fetch(url);
  if (!res.ok) throw new Error('Weather data unavailable. Try again in a moment.');
  return res.json();
}

function getLatestValue(times, values) {
  var nowStr = new Date().toISOString().slice(0, 13);
  var latest = null;
  for (var i = 0; i < times.length; i++) {
    if (times[i].slice(0, 13) <= nowStr && values[i] !== null) {
      latest = values[i];
    }
  }
  return latest !== null ? round1(latest) : null;
}

function aggregateDaily(times, values) {
  var days = {};
  for (var i = 0; i < times.length; i++) {
    var date = times[i].slice(0, 10);
    if (!days[date]) days[date] = [];
    if (values[i] !== null) days[date].push(values[i]);
  }
  return Object.keys(days).sort().map(function(date) {
    var vals = days[date];
    return {
      date: date,
      avg: vals.length ? round1(vals.reduce(function(a, b) { return a + b; }, 0) / vals.length) : null
    };
  });
}

function renderDepthCard(tempId, badgeId, temp) {
  var tempEl = document.getElementById(tempId);
  var badgeEl = document.getElementById(badgeId);
  if (temp === null) {
    tempEl.textContent = '—';
    badgeEl.textContent = '';
    badgeEl.className = 'depth-card__badge';
    return;
  }
  tempEl.textContent = temp + '°F';
  var b = getBadge(temp);
  badgeEl.textContent = b.label;
  badgeEl.className = 'depth-card__badge depth-card__badge--' + b.cls;
}

function initOrUpdateMap(lat, lon, displayName, temp2in) {
  var popup = temp2in !== null
    ? displayName + '<br><strong>' + temp2in + '°F</strong> at 2″'
    : displayName;
  if (soilMap) {
    soilMap.setView([lat, lon], 10);
    soilMarker.setLatLng([lat, lon]);
    soilMarker.getPopup().setContent(popup).openOn(soilMap);
    return;
  }
  soilMap = L.map('soil-map').setView([lat, lon], 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(soilMap);
  soilMarker = L.marker([lat, lon]).addTo(soilMap).bindPopup(popup).openPopup();
}

function renderChart(surfaceDaily, depth2Daily, depth6Daily) {
  var labels = surfaceDaily.map(function(d) {
    var dt = new Date(d.date + 'T12:00:00');
    return dt.toLocaleDateString('en-US', { weekday: 'short' });
  });
  if (soilChart) soilChart.destroy();
  soilChart = new Chart(document.getElementById('soil-chart'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Surface',
          data: surfaceDaily.map(function(d) { return d.avg; }),
          borderColor: 'rgba(196, 160, 50, 0.8)',
          backgroundColor: 'transparent',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 3
        },
        {
          label: '2″ depth',
          data: depth2Daily.map(function(d) { return d.avg; }),
          borderColor: 'rgba(114, 196, 75, 0.95)',
          backgroundColor: 'rgba(114, 196, 75, 0.08)',
          borderWidth: 2.5,
          tension: 0.4,
          pointRadius: 3,
          fill: true
        },
        {
          label: '6″ depth',
          data: depth6Daily.map(function(d) { return d.avg; }),
          borderColor: 'rgba(130, 170, 120, 0.6)',
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          tension: 0.4,
          pointRadius: 2,
          borderDash: [4, 4]
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: 'rgba(230, 235, 220, 0.7)', font: { family: 'Manrope, sans-serif', size: 12 } }
        },
        tooltip: {
          callbacks: {
            label: function(ctx) { return ctx.dataset.label + ': ' + ctx.raw + '°F'; }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: 'rgba(200, 210, 190, 0.6)', font: { size: 12 } },
          grid: { color: 'rgba(120, 140, 100, 0.15)' }
        },
        y: {
          ticks: {
            color: 'rgba(200, 210, 190, 0.6)',
            font: { size: 12 },
            callback: function(v) { return v + '°F'; }
          },
          grid: { color: 'rgba(120, 140, 100, 0.15)' }
        }
      }
    }
  });
}

function updateInterpretation() {
  var el = document.getElementById('interpretation-text');
  if (currentTemp2in === null) {
    el.textContent = 'Load your location to see soil temperature guidance.';
    return;
  }
  el.textContent = getInterpretation(currentGrassType, currentTemp2in);
}

async function loadData(lat, lon, displayName) {
  var errEl = document.getElementById('location-error');
  var loadEl = document.getElementById('loading');
  var resultsEl = document.getElementById('results');

  errEl.hidden = true;
  loadEl.hidden = false;
  resultsEl.hidden = true;

  try {
    var data = await fetchSoilData(lat, lon);
    var h = data.hourly;
    var surface = getLatestValue(h.time, h.soil_temperature_0cm);
    var temp2in = getLatestValue(h.time, h.soil_temperature_6cm);
    var temp6in = getLatestValue(h.time, h.soil_temperature_18cm);
    currentTemp2in = temp2in;

    resultsEl.hidden = false;
    loadEl.hidden = true;

    document.getElementById('location-label').textContent = '📍 ' + displayName;
    renderDepthCard('temp-surface', 'badge-surface', surface);
    renderDepthCard('temp-2in', 'badge-2in', temp2in);
    renderDepthCard('temp-6in', 'badge-6in', temp6in);

    initOrUpdateMap(lat, lon, displayName, temp2in);
    setTimeout(function() { if (soilMap) soilMap.invalidateSize(); }, 150);

    var surfaceDaily = aggregateDaily(h.time, h.soil_temperature_0cm);
    var depth2Daily  = aggregateDaily(h.time, h.soil_temperature_6cm);
    var depth6Daily  = aggregateDaily(h.time, h.soil_temperature_18cm);
    renderChart(surfaceDaily, depth2Daily, depth6Daily);
    updateInterpretation();
  } catch (err) {
    loadEl.hidden = true;
    errEl.hidden = false;
    errEl.textContent = err.message;
  }
}

document.getElementById('location-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var query = document.getElementById('location-input').value.trim();
  if (!query) return;
  var errEl = document.getElementById('location-error');
  errEl.hidden = true;
  try {
    var loc = await geocodeAddress(query);
    await loadData(loc.lat, loc.lon, loc.displayName);
  } catch (err) {
    errEl.hidden = false;
    errEl.textContent = err.message;
    document.getElementById('loading').hidden = true;
  }
});

document.getElementById('btn-geo').addEventListener('click', async function() {
  var errEl = document.getElementById('location-error');
  errEl.hidden = true;
  try {
    var pos = await getCurrentPosition();
    var displayName = await reverseGeocode(pos.lat, pos.lon);
    document.getElementById('location-input').value = displayName;
    await loadData(pos.lat, pos.lon, displayName);
  } catch (err) {
    errEl.hidden = false;
    errEl.textContent = err.message;
    document.getElementById('loading').hidden = true;
  }
});

document.querySelectorAll('.grass-pill').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.grass-pill').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    currentGrassType = btn.dataset.grass;
    updateInterpretation();
  });
});

initAutocomplete(
  document.getElementById('location-input'),
  function(lat, lon, displayName) { loadData(lat, lon, displayName); }
);
