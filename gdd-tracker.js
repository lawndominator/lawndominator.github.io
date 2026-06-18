// GDD calculator page logic — requires tools.js

var currentGrassType = 'bermuda';
var currentTotal = 0;
var currentDaily = null;
var currentPgrDaily = null;
var currentWeatherData = null;

// GDD milestone labels are approximate trend indicators only.
// Pre-emergent timing should be confirmed with 2-inch soil temperature (50-55°F per UMN/Penn State).
// Greenup timing should be confirmed with soil temperature and visual observation (TAMU: 65°F for bermuda).
var GRASS_MILESTONES = {
  bermuda: [
    { gdd: 50,  label: 'Watch soil temp — pre-emergent window may be near' },
    { gdd: 200, label: 'Spring heat accumulating — check soil temp and visual greenup' },
    { gdd: 500, label: 'Full growth season likely underway' }
  ],
  zoysia: [
    { gdd: 100, label: 'Watch soil temp — pre-emergent window may be near' },
    { gdd: 300, label: 'Spring heat accumulating — confirm visual greenup' }
  ],
  'st-augustine': [
    { gdd: 50,  label: 'Watch soil temp — pre-emergent window may be near' },
    { gdd: 200, label: 'Spring heat accumulating — confirm visual greenup' }
  ],
  'cool-season': [
    { gdd: 50, label: 'Watch soil temp — spring pre-emergent window' }
  ]
};

// Max possible daily GDD (base 50, cap 86): (86+50)/2 - 50 = 18
var MAX_DAILY_GDD = 18;

function getPgrBaseC(grassType) {
  return grassType === 'cool-season' ? 0 : 10;
}

function fahrenheitToCelsius(value) {
  return (value - 32) * 5 / 9;
}

function getLocalDateString() {
  var now = new Date();
  var year = now.getFullYear();
  var month = String(now.getMonth() + 1).padStart(2, '0');
  var day = String(now.getDate()).padStart(2, '0');
  return year + '-' + month + '-' + day;
}

function getPreviousDateString(dateStr) {
  var dt = new Date(dateStr + 'T12:00:00');
  dt.setDate(dt.getDate() - 1);
  var year = dt.getFullYear();
  var month = String(dt.getMonth() + 1).padStart(2, '0');
  var day = String(dt.getDate()).padStart(2, '0');
  return year + '-' + month + '-' + day;
}

async function fetchHistoricalData(lat, lon) {
  var year = new Date().getFullYear();
  var today = getLocalDateString();
  var url = 'https://archive-api.open-meteo.com/v1/archive' +
    '?latitude=' + lat + '&longitude=' + lon +
    '&start_date=' + year + '-01-01&end_date=' + today +
    '&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&timezone=auto';
  var res = await fetch(url);
  if (!res.ok) throw new Error('Weather data unavailable. Try again in a moment.');
  return res.json();
}

function calculateGDD(data, options) {
  options = options || {};
  var times  = data.daily.time;
  var maxArr = data.daily.temperature_2m_max;
  var minArr = data.daily.temperature_2m_min;
  var tBase = options.baseTemp || 50;
  var maxCap = options.maxCap;
  var cumulative = 0;
  var daily = [];
  for (var i = 0; i < times.length; i++) {
    var tMax = maxArr[i] !== null ? maxArr[i] : tBase;
    var tMin = minArr[i] !== null ? minArr[i] : tBase;
    if (typeof maxCap === 'number') tMax = Math.min(tMax, maxCap);
    tMin = Math.max(tMin, tBase);
    var gdd  = Math.max(0, (tMax + tMin) / 2 - tBase);
    cumulative += gdd;
    daily.push({
      date: times[i],
      gdd: Math.round(gdd * 10) / 10,
      cumulative: Math.round(cumulative * 10) / 10
    });
  }
  return { daily: daily, total: Math.round(cumulative) };
}

function calculatePgrGDDC(data, grassType) {
  var times  = data.daily.time;
  var maxArr = data.daily.temperature_2m_max;
  var minArr = data.daily.temperature_2m_min;
  var baseC = getPgrBaseC(grassType);
  var cumulative = 0;
  var daily = [];
  for (var i = 0; i < times.length; i++) {
    var tMaxF = maxArr[i] !== null ? maxArr[i] : 32 + baseC * 9 / 5;
    var tMinF = minArr[i] !== null ? minArr[i] : 32 + baseC * 9 / 5;
    var tMaxC = fahrenheitToCelsius(tMaxF);
    var tMinC = fahrenheitToCelsius(tMinF);
    var gdd = Math.max(0, (tMaxC + tMinC) / 2 - baseC);
    cumulative += gdd;
    daily.push({
      date: times[i],
      gdd: Math.round(gdd * 10) / 10,
      cumulative: Math.round(cumulative * 10) / 10
    });
  }
  return { daily: daily, total: Math.round(cumulative) };
}

function renderMilestoneStatus(total, grassType) {
  var el = document.getElementById('milestone-status');
  if (!el) return;
  var milestones = GRASS_MILESTONES[grassType] || [];
  el.innerHTML = milestones.map(function(ms) {
    var passed = total >= ms.gdd;
    return '<div class="milestone-chip milestone-chip--' + (passed ? 'passed' : 'pending') + '">' +
      '<span class="milestone-chip__label">' + ms.label + '</span>' +
      '<span class="milestone-chip__val">' +
        (passed ? '✓ Threshold passed' : 'Not yet reached') +
      '</span></div>';
  }).join('');
}

function formatDateLabel(dateStr, isToday, isYesterday) {
  var dt = new Date(dateStr + 'T12:00:00');
  var mmdd = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  if (isToday) return mmdd;
  if (isYesterday) return mmdd;
  return mmdd;
}

function renderDailyList(daily, fromDate) {
  var el = document.getElementById('gdd-daily-list');
  if (!el) return;
  var todayStr = daily.length ? daily[daily.length - 1].date : getLocalDateString();
  var yesterStr = getPreviousDateString(todayStr);
  var label = document.getElementById('gdd-list-label');

  var recent;
  if (fromDate) {
    recent = daily.filter(function(d) { return d.date >= fromDate && d.date <= todayStr; }).reverse();
    if (label) label.textContent = 'Daily GDD — ' + formatDateLabel(fromDate) + ' to Today (Base 50°F)';
  } else {
    recent = daily.slice(-21).reverse();
    if (label) label.textContent = 'Daily GDD — Last 21 Days (Base 50°F)';
  }

  el.innerHTML = recent.map(function(d) {
    var isToday = d.date === todayStr;
    var isYester = d.date === yesterStr;
    var dt = new Date(d.date + 'T12:00:00');
    var label = dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    var barPct = Math.min(100, Math.round(d.gdd / MAX_DAILY_GDD * 100));
    var valClass = d.gdd >= 12 ? 'warm' : d.gdd >= 5 ? '' : 'cool';


    return '<div class="gdd-day-row' + (isToday ? ' gdd-day-row--today' : '') + '" style="--bar:' + barPct + '%">' +
      '<span class="gdd-day-row__date">' + label +
        (isToday ? ' <span class="gdd-day-row__today-badge">today</span>' : '') +
        (isYester ? ' <span class="gdd-day-row__today-badge" style="color:var(--ink-soft);background:transparent">yesterday</span>' : '') +
      '</span>' +
      '<span class="gdd-day-row__val gdd-day-row__val--' + valClass + '">' + d.gdd + ' GDD</span>' +
    '</div>';
  }).join('');
}

function updateFromDateResult() {
  var input = document.getElementById('gdd-from-input');
  var result = document.getElementById('gdd-from-result');
  if (!input || !result || !currentDaily || !currentPgrDaily) return;
  var val = input.value;
  if (!val) {
    result.textContent = 'Pick a date — shows PGR GDD°C and turf GDD from that date';
    result.className = 'gdd-from-result gdd-from-result--empty';
    renderDailyList(currentDaily, null);
    return;
  }
  var turfSum = 0;
  var pgrSum = 0;
  var days = 0;
  var today = currentDaily.length ? currentDaily[currentDaily.length - 1].date : getLocalDateString();
  currentDaily.forEach(function(d) {
    if (d.date >= val && d.date <= today) { turfSum += d.gdd; days++; }
  });
  currentPgrDaily.forEach(function(d) {
    if (d.date >= val && d.date <= today) { pgrSum += d.gdd; }
  });
  if (days === 0) {
    result.textContent = 'No data for that date range.';
    result.className = 'gdd-from-result gdd-from-result--empty';
    renderDailyList(currentDaily, null);
    return;
  }
  var dt = new Date(val + 'T12:00:00');
  var dateLabel = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  result.textContent = Math.round(pgrSum) + ' PGR GDD°C (base ' + getPgrBaseC(currentGrassType) + '°C) · ' +
    Math.round(turfSum) + ' turf GDD (base 50°F) since ' + dateLabel +
    ' (' + days + ' day' + (days === 1 ? ')' : 's)');
  result.className = 'gdd-from-result';
  renderDailyList(currentDaily, val);
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
    var result = calculateGDD(data, { baseTemp: 50, maxCap: 86 });
    var pgrResult = calculatePgrGDDC(data, currentGrassType);
    currentWeatherData = data;
    currentDaily = result.daily;
    currentPgrDaily = pgrResult.daily;
    currentTotal = result.total;

    resultsEl.hidden = false;
    loadEl.hidden    = true;

    // Set date picker bounds
    var year = new Date().getFullYear();
    var today = currentDaily.length ? currentDaily[currentDaily.length - 1].date : getLocalDateString();
    var fromInput = document.getElementById('gdd-from-input');
    if (fromInput) {
      fromInput.min = year + '-01-01';
      fromInput.max = today;
    }

    document.getElementById('location-label').textContent = '📍 ' + displayName;
    document.getElementById('gdd-number').textContent = result.total.toLocaleString();
    document.getElementById('gdd-sublabel').textContent =
      'Base 50°F · ' + displayName + ' · Jan 1–today';

    renderMilestoneStatus(currentTotal, currentGrassType);
    renderDailyList(currentDaily);
    updateFromDateResult();
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
    if (currentWeatherData) {
      currentPgrDaily = calculatePgrGDDC(currentWeatherData, currentGrassType).daily;
      updateFromDateResult();
    }
    if (currentDaily) renderMilestoneStatus(currentTotal, currentGrassType);
  });
});

document.getElementById('gdd-from-input').addEventListener('input', updateFromDateResult);

initAutocomplete(
  document.getElementById('location-input'),
  function(lat, lon, displayName) { loadData(lat, lon, displayName); }
);
