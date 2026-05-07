// GDD calculator page logic — requires tools.js and Chart.js

var currentGrassType = 'bermuda';
var gddChart = null;
var currentDaily = null;

var GRASS_MILESTONES = {
  bermuda: [
    { gdd: 50,  label: 'Pre-emergent opens',  color: 'rgba(220, 200, 60, 0.9)' },
    { gdd: 200, label: 'Greenup approaching', color: 'rgba(114, 196, 75, 0.9)' },
    { gdd: 500, label: 'Full active growth',  color: 'rgba(80, 160, 220, 0.9)' }
  ],
  zoysia: [
    { gdd: 100, label: 'Pre-emergent window', color: 'rgba(220, 200, 60, 0.9)' },
    { gdd: 300, label: 'Greenup approaching', color: 'rgba(114, 196, 75, 0.9)' }
  ],
  'st-augustine': [
    { gdd: 50,  label: 'Pre-emergent window', color: 'rgba(220, 200, 60, 0.9)' },
    { gdd: 200, label: 'First green push',    color: 'rgba(114, 196, 75, 0.9)' }
  ],
  'cool-season': [
    { gdd: 50, label: 'Spring pre-em window', color: 'rgba(220, 200, 60, 0.9)' }
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
    daily.push({ date: times[i], gdd: gdd, cumulative: Math.round(cumulative * 10) / 10 });
  }
  return { daily: daily, total: Math.round(cumulative) };
}

// Inline Chart.js plugin: draws vertical dashed milestone lines
var milestonePlugin = {
  id: 'milestoneLines',
  afterDatasetsDraw: function(chart, _args, options) {
    var milestones = options.milestones;
    if (!milestones || !milestones.length) return;
    var ctx       = chart.ctx;
    var chartArea = chart.chartArea;
    var xScale    = chart.scales.x;
    var cumData   = chart.data.datasets[0].data;

    ctx.save();
    for (var m = 0; m < milestones.length; m++) {
      var ms  = milestones[m];
      var idx = -1;
      for (var j = 0; j < cumData.length; j++) {
        if (cumData[j] >= ms.gdd) { idx = j; break; }
      }
      if (idx === -1) continue; // threshold not yet reached this season

      var x = xScale.getPixelForIndex(idx);
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = ms.color;
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();

      ctx.setLineDash([]);
      ctx.fillStyle = ms.color;
      ctx.font      = '10px Manrope, system-ui, sans-serif';
      ctx.textAlign = 'left';
      var labelX = Math.min(x + 4, chartArea.right - 90);
      ctx.fillText(ms.label, labelX, chartArea.top + 16);
    }
    ctx.restore();
  }
};

function buildChartLabels(daily) {
  return daily.map(function(d) {
    var dt = new Date(d.date + 'T12:00:00');
    return dt.getDate() === 1 ? dt.toLocaleDateString('en-US', { month: 'short' }) : '';
  });
}

function renderGDDChart(daily, grassType) {
  var labels = buildChartLabels(daily);
  var cumData = daily.map(function(d) { return d.cumulative; });

  if (gddChart) gddChart.destroy();

  gddChart = new Chart(document.getElementById('gdd-chart'), {
    type: 'line',
    plugins: [milestonePlugin],
    data: {
      labels: labels,
      datasets: [{
        label: 'Cumulative GDD',
        data: cumData,
        borderColor: 'rgba(114, 196, 75, 0.95)',
        backgroundColor: 'rgba(114, 196, 75, 0.08)',
        borderWidth: 2.5,
        tension: 0.3,
        pointRadius: 0,
        fill: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        milestoneLines: {
          milestones: GRASS_MILESTONES[grassType] || []
        },
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(ctx) { return daily[ctx[0].dataIndex] ? daily[ctx[0].dataIndex].date : ''; },
            label: function(ctx) { return Math.round(ctx.raw) + ' GDD'; }
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
          grid: { color: 'rgba(120, 140, 100, 0.15)' }
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

    resultsEl.hidden = false;
    loadEl.hidden    = true;

    document.getElementById('location-label').textContent = '📍 ' + displayName;
    document.getElementById('gdd-number').textContent = result.total.toLocaleString();
    document.getElementById('gdd-sublabel').textContent =
      'Base 50°F · ' + displayName + ' · Jan 1–today';

    renderGDDChart(currentDaily, currentGrassType);
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
    if (gddChart && currentDaily) {
      gddChart.options.plugins.milestoneLines.milestones = GRASS_MILESTONES[currentGrassType] || [];
      gddChart.update();
    }
  });
});
