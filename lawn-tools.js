function byId(id) {
  return document.getElementById(id);
}

function numberValue(id) {
  var el = byId(id);
  return el ? parseFloat(el.value) : NaN;
}

function formatNumber(value, digits) {
  if (!isFinite(value)) return '0';
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits == null ? 2 : digits,
    minimumFractionDigits: 0
  });
}

function initFertilizerCalculator() {
  var form = byId('fertilizer-form');
  if (!form) return;
  var result = byId('fertilizer-result');
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var area = numberValue('fert-area');
    var rate = numberValue('fert-rate');
    var nitrogen = numberValue('fert-n');
    var bagWeight = numberValue('fert-bag');
    if (!(area > 0 && rate > 0 && nitrogen > 0)) {
      result.textContent = 'Enter lawn area, target nitrogen rate, and the nitrogen percentage from the bag.';
      result.classList.add('tool-result--warn');
      return;
    }
    var productPerThousand = rate / (nitrogen / 100);
    var totalProduct = productPerThousand * (area / 1000);
    var bags = bagWeight > 0 ? totalProduct / bagWeight : null;
    var actualN = totalProduct * (nitrogen / 100);
    result.classList.remove('tool-result--warn');
    result.innerHTML =
      '<strong>' + formatNumber(totalProduct, 2) + ' lb product total</strong><br>' +
      formatNumber(productPerThousand, 2) + ' lb product per 1,000 sq ft<br>' +
      formatNumber(actualN, 2) + ' lb actual nitrogen over ' + formatNumber(area, 0) + ' sq ft' +
      (bags ? '<br>' + formatNumber(bags, 2) + ' bag(s) at ' + formatNumber(bagWeight, 1) + ' lb each' : '');
  });
}

function initTankMixCalculator() {
  var form = byId('tank-form');
  var rows = byId('tank-products');
  if (!form || !rows) return;
  var addButton = byId('tank-add-row');
  var result = byId('tank-result');

  function addRow(name, rate) {
    var row = document.createElement('div');
    row.className = 'tool-row tool-row--mix';
    row.innerHTML =
      '<input type="text" class="tank-name" placeholder="Product name" value="' + (name || '') + '" aria-label="Product name" />' +
      '<input type="number" class="tank-rate" min="0" step="0.01" placeholder="Rate / 1,000" value="' + (rate || '') + '" aria-label="Rate per 1,000 sq ft" />' +
      '<button type="button" class="btn-secondary tank-remove" aria-label="Remove product">Remove</button>';
    row.querySelector('.tank-remove').addEventListener('click', function() {
      row.remove();
    });
    rows.appendChild(row);
  }

  addButton.addEventListener('click', function() { addRow('', ''); });
  addRow('Herbicide / fertilizer / PGR', '');

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var area = numberValue('tank-area');
    var gallons = numberValue('tank-gallons');
    if (!(area > 0 && gallons > 0)) {
      result.textContent = 'Enter treated area and spray volume before calculating.';
      result.classList.add('tool-result--warn');
      return;
    }
    var multiplier = area / 1000;
    var lines = [];
    rows.querySelectorAll('.tool-row--mix').forEach(function(row) {
      var name = row.querySelector('.tank-name').value.trim() || 'Product';
      var rate = parseFloat(row.querySelector('.tank-rate').value);
      if (rate > 0) {
        lines.push('<li><strong>' + name + ':</strong> ' + formatNumber(rate * multiplier, 2) + ' total units</li>');
      }
    });
    result.classList.remove('tool-result--warn');
    result.innerHTML =
      '<strong>Mix for ' + formatNumber(area, 0) + ' sq ft in ' + formatNumber(gallons, 2) + ' gal carrier</strong>' +
      '<ul>' + (lines.length ? lines.join('') : '<li>Add at least one product rate.</li>') + '</ul>' +
      '<p>Confirm every product label, turf species, water-in requirement, PPE, and tank-mix compatibility before spraying.</p>';
  });
}

function initSprayRateCalculator() {
  var form = byId('spray-rate-form');
  if (!form) return;
  var result = byId('spray-rate-result');
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var area = numberValue('spray-area');
    var rate = numberValue('spray-rate');
    var carrierRate = numberValue('spray-carrier-rate');
    var tankSize = numberValue('spray-tank-size');
    var unitEl = byId('spray-unit');
    var unit = unitEl ? unitEl.value : 'units';
    if (!(area > 0 && rate > 0 && carrierRate > 0)) {
      result.textContent = 'Enter treated area, label rate per 1,000 sq ft, and carrier gallons per 1,000 sq ft.';
      result.classList.add('tool-result--warn');
      return;
    }
    var multiplier = area / 1000;
    var productTotal = rate * multiplier;
    var carrierTotal = carrierRate * multiplier;
    var tanks = tankSize > 0 ? carrierTotal / tankSize : null;
    result.classList.remove('tool-result--warn');
    result.innerHTML =
      '<strong>' + formatNumber(productTotal, 2) + ' ' + unit + ' product total</strong><br>' +
      formatNumber(carrierTotal, 2) + ' gal carrier total for ' + formatNumber(area, 0) + ' sq ft' +
      (tanks ? '<br>' + formatNumber(tanks, 2) + ' tank(s) at ' + formatNumber(tankSize, 2) + ' gal each' : '') +
      '<p>Confirm the label rate, turf species, PPE, water-in or rainfast window, re-entry interval, and annual maximum before spraying.</p>';
  });
}

function initSeedCalculator() {
  var form = byId('seed-form');
  if (!form) return;
  var result = byId('seed-result');
  var grass = byId('seed-grass');
  var purpose = byId('seed-purpose');
  var customRate = byId('seed-custom-rate');

  var seedRates = {
    tall_fescue: { newRate: 6, overseedRate: 3, note: 'NC State lists tall fescue establishment at 6 lb per 1,000 sq ft.' },
    kentucky_bluegrass: { newRate: 2, overseedRate: 1, note: 'Kentucky bluegrass is normally seeded lighter than tall fescue and establishes more slowly.' },
    perennial_ryegrass: { newRate: 8, overseedRate: 4, note: 'Perennial ryegrass establishes quickly but still needs seed-to-soil contact and moisture.' },
    bermuda_common: { newRate: 1, overseedRate: 0.5, note: 'Common bermuda can be seeded; many hybrid bermuda lawns are established vegetatively.' },
    zoysia: { newRate: 2, overseedRate: 1, note: 'Zoysia is slow from seed; many zoysia and St. Augustine lawns use sod, plugs, or sprigs.' }
  };

  function updateDefaultRate() {
    var item = seedRates[grass.value];
    var rate = item ? (purpose.value === 'overseed' ? item.overseedRate : item.newRate) : NaN;
    customRate.placeholder = isFinite(rate) ? String(rate) : 'Optional custom rate';
  }

  grass.addEventListener('change', updateDefaultRate);
  purpose.addEventListener('change', updateDefaultRate);
  updateDefaultRate();

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var area = numberValue('seed-area');
    var bagWeight = numberValue('seed-bag');
    var custom = numberValue('seed-custom-rate');
    var item = seedRates[grass.value];
    var rate = custom > 0 ? custom : item[purpose.value === 'overseed' ? 'overseedRate' : 'newRate'];
    if (!(area > 0 && rate > 0)) {
      result.textContent = 'Enter lawn area and choose a grass type, or enter a custom seed rate.';
      result.classList.add('tool-result--warn');
      return;
    }
    var pounds = rate * (area / 1000);
    var bags = bagWeight > 0 ? pounds / bagWeight : null;
    result.classList.remove('tool-result--warn');
    result.innerHTML =
      '<strong>' + formatNumber(pounds, 2) + ' lb seed needed</strong><br>' +
      formatNumber(rate, 2) + ' lb seed per 1,000 sq ft x ' + formatNumber(area / 1000, 2) + ' thousand sq ft' +
      (bags ? '<br>' + formatNumber(bags, 2) + ' bag(s) at ' + formatNumber(bagWeight, 1) + ' lb each' : '') +
      '<p>' + item.note + ' Check the seed tag, cultivar recommendation, local planting window, and label rate before buying.</p>';
  });
}

function initIrrigationRuntimeCalculator() {
  var form = byId('irrigation-form');
  if (!form) return;
  var result = byId('irrigation-result');
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var target = numberValue('water-target');
    var caught = numberValue('water-catch');
    var minutes = numberValue('water-minutes');
    if (!(target > 0 && caught > 0 && minutes > 0)) {
      result.textContent = 'Enter target inches, average catch-can depth, and test runtime.';
      result.classList.add('tool-result--warn');
      return;
    }
    var ratePerHour = caught / minutes * 60;
    var runtime = target / ratePerHour * 60;
    result.classList.remove('tool-result--warn');
    result.innerHTML =
      '<strong>' + formatNumber(runtime, 0) + ' minutes</strong> to apply ' + formatNumber(target, 2) + ' in<br>' +
      'Measured precipitation rate: ' + formatNumber(ratePerHour, 2) + ' in/hr from ' + formatNumber(caught, 2) + ' in in ' + formatNumber(minutes, 0) + ' min' +
      '<p>If water runs off before the runtime finishes, split it into cycle-and-soak runs. Use multiple catch cans and subtract useful rainfall instead of watering by calendar alone.</p>';
  });
}

function getTreatments() {
  try {
    return JSON.parse(localStorage.getItem('ldTreatments') || '[]');
  } catch (e) {
    return [];
  }
}

function saveTreatments(items) {
  localStorage.setItem('ldTreatments', JSON.stringify(items));
}

function renderTreatments() {
  var list = byId('treatment-list');
  if (!list) return;
  var items = getTreatments();
  if (!items.length) {
    list.innerHTML = '<p class="tool-muted">No treatments saved in this browser yet.</p>';
    return;
  }
  list.innerHTML = items.map(function(item, index) {
    return '<article class="treatment-item">' +
      '<button type="button" class="treatment-delete" data-index="' + index + '">Delete</button>' +
      '<h3>' + item.date + ' · ' + item.type + '</h3>' +
      '<p><strong>' + item.product + '</strong> at ' + item.rate + '</p>' +
      '<p>' + item.notes + '</p>' +
      '</article>';
  }).join('');
  list.querySelectorAll('.treatment-delete').forEach(function(button) {
    button.addEventListener('click', function() {
      var next = getTreatments();
      next.splice(parseInt(button.dataset.index, 10), 1);
      saveTreatments(next);
      renderTreatments();
    });
  });
}

function initTreatmentLog() {
  var form = byId('treatment-form');
  if (!form) return;
  var dateEl = byId('treatment-date');
  if (dateEl && !dateEl.value) dateEl.value = new Date().toISOString().slice(0, 10);
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    var item = {
      date: byId('treatment-date').value || new Date().toISOString().slice(0, 10),
      type: byId('treatment-type').value,
      product: byId('treatment-product').value.trim() || 'Unnamed product',
      rate: byId('treatment-rate').value.trim() || 'rate not entered',
      notes: byId('treatment-notes').value.trim() || 'No notes'
    };
    var items = getTreatments();
    items.unshift(item);
    saveTreatments(items);
    form.reset();
    if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
    renderTreatments();
  });
  var exportButton = byId('treatment-export');
  if (exportButton) {
    exportButton.addEventListener('click', function() {
      var rows = [['Date', 'Type', 'Product', 'Rate', 'Notes']].concat(getTreatments().map(function(item) {
        return [item.date, item.type, item.product, item.rate, item.notes];
      }));
      var csv = rows.map(function(row) {
        return row.map(function(cell) {
          return '"' + String(cell).replace(/"/g, '""') + '"';
        }).join(',');
      }).join('\n');
      var blob = new Blob([csv], { type: 'text/csv' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'lawn-dominator-treatment-log.csv';
      a.click();
      URL.revokeObjectURL(url);
    });
  }
  renderTreatments();
}

function initCalendarChecklist() {
  var checklist = byId('calendar-checklist');
  if (!checklist) return;
  var key = 'ldCalendar-' + (checklist.dataset.calendar || location.pathname);
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { saved = {}; }
  checklist.querySelectorAll('input[type="checkbox"]').forEach(function(input) {
    if (saved[input.value]) input.checked = true;
    input.addEventListener('change', function() {
      saved[input.value] = input.checked;
      localStorage.setItem(key, JSON.stringify(saved));
    });
  });
  var reset = byId('calendar-reset');
  if (reset) {
    reset.addEventListener('click', function() {
      localStorage.removeItem(key);
      checklist.querySelectorAll('input[type="checkbox"]').forEach(function(input) {
        input.checked = false;
      });
    });
  }
}

document.addEventListener('DOMContentLoaded', function() {
  initFertilizerCalculator();
  initTankMixCalculator();
  initSprayRateCalculator();
  initSeedCalculator();
  initIrrigationRuntimeCalculator();
  initTreatmentLog();
  initCalendarChecklist();
});
