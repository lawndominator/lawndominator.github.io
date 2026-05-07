// GDD calculator page logic — requires tools.js and Chart.js

var currentGrassType = 'bermuda';
var currentTotal = 0;
var gddChart = null;
var currentDaily = null;

var GRASS_MILESTONES = {
  bermuda: [
    { gdd: 50,  label: 'Pre-emergent opens' },
    { gdd: 200, label: 'Greenup approaching' },
    { gdd: 500, label: 'Full active growth' }
  ],
  zoysia: [
    { gdd: 100, label: 'Pre-emergent window' },
    { gdd: 300, label: 'Greenup approaching' }
  ],
  'st-augustine': [
    { gdd: 50,  label: 'Pre-emergent window' },
    { gdd: 200, label: 'First green push' }
  ],
  'cool-season': [
    { gdd: 50, label: 'Spring pre-em window' }
  ]
};

async function fetchHistoricalData(lat, lon) {
  var year = new Date().getFullYear();
  var today = new Date().toISOString().slice(0, 10);
  var url = 'https://archive-api.open-meteo.com/v1/archive' +
    '?latitude=' + lat + '&longitude=' + lon +
    '&start_date=' + year + '-01-01&end_date=' + today +
    '&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&timezone=auto';
  var res = await fetch(url);
  if (!res.ok) throw new Error('Weather data unavailable. Try again in a moment.');
  return res.json();
}

function calculateGDD(data) {
  var times   = data.daily.time;
  var maxArr  = data.daily.temperature_2m_max;
  var minArr  = data.daily.temperature_2m_min;
  var T_BASE  = 50;
  var cumulative = 0;
  var daily = [];
  for (var i = 0; i < times.length; i++) {
    var tMax = maxArr[i] !== null ? Math.min(maxArr[i], 86) : T_BASE;
    var tMin = minArr[i] !== null ? Math.max(minArr[i], T_BASE) : T_BASE;
    var gdd  = Math.max(0, (tMax + tMin) / 2 - T_BASE);
    cumulative += gdd;
    daily.push({ date: times[i], gdd: Math.round(gdd * 10) / 10, cumulative: Math.round(cumulative * 10) / 10 });
  }
  return { daily: daily, total: Math.round(cumulative) };
}

function renderMilestoneStatus(total, grassType) {
  var milestones = GRASS_MILESTONES[grassType] || [];
  var el = document.getElementById('milestone-status');
  if (!el) return;
  el.innerHTML = milestones.map(function(ms) {
    var passed = total >= ms.gdd;
    var remaining = ms.gdd - total;
    return '<div class="milestone-chip milestone-chip--' + (passed ? 'passed' : 'pending') + '">' +
      '<span class="milestone-chip__label">' + ms.label + '</span>' +
      '<span class="milestone-chip__val">' +
        (passed ? '✓ ' + ms.gdd + ' GDD reached' : remaining + ' GDD away') +
      '</span>' +
    '</div>';
  }).join('');
}

function renderGDDChart(daily) {
  var recent = daily.slice(-30);
  var labels = recent.map(function(d) {
    var dt = new Date(d.date + 'T12:00:00');
    var day = dt.getDate();
    if (day === 1) return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (day % 5 === 0) return String(day);
    return '';
  });
  var barData = recent.map(function(d) { return d.gdd; });

  if (gddChart) gddChart.destroy();

  gddChart = new Chart(document.getElementById('gdd-chart'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Daily GDD',
        data: barData,
        backgroundColor: recent.map(function(d) {
          return d.gdd >= 15 ? 'rgba(114, 196, 75, 0.75)' :
                 d.gdd >= 8  ? 'rgba(196, 200, 75, 0.7)'  :
                               'rgba(130, 150, 120, 0.45)';
        }),
        borderColor: 'transparent',
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(ctx) { return recent[ctx[0].dataIndex] ? recent[ctx[0].dataIndex].date : ''; },
            label: function(ctx) { return ctx.raw + ' GDD'; }
          }
        }
      },
      scales: {
        x: {
          ticks: {
            autoSkip: false,
            color: 'rgba(200, 210, 190, 0.6)',
            font: { size: 11 },
            maxRotation: 0
          },
          grid: { display: false }
        },
        y: {
          ticks: { color: 'rgba(200, 210, 190, 0.6)', font: { size: 12 } },
          grid: { color: 'rgba(120, 140, 100, 0.15)' }
        }
      }
    }
  });
}

async function loadData(lat, lon, displayName) {
  var errEl     = document.getElementById('location-error');
  var loadEl    = document.getElementById('loading');
  var resultsEl = document.getElementById('results');

  errEl.hidden  = true;
  loadEl.hidden = false;
  resultsEl.hidden = true;

  try {
    var data   = await fetchHistoricalData(lat, lon);
    var result = calculateGDD(data);
    currentDaily = result.daily;
    currentTotal = result.total;

    resultsEl.hidden = false;
    loadEl.hidden    = true;

    document.getElementById('location-label').textContent = '📍 ' + displayName;
    document.getElementById('gdd-number').textContent = result.total.toLocaleString();
    document.getElementById('gdd-sublabel').textContent =
      'Base 50°F · ' + displayName + ' · Jan 1–today';

    renderMilestoneStatus(currentTotal, currentGrassType);
    renderGDDChart(currentDaily);
  } catch (err) {
    loadEl.hidden = true;
    errEl.hidden  = false;
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
    if (currentDaily) renderMilestoneStatus(currentTotal, currentGrassType);
  });
});

initAutocomplete(
  document.getElementById('location-input'),
  function(lat, lon, displayName) { loadData(lat, lon, displayName); }
);
