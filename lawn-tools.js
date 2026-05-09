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
  initTreatmentLog();
  initCalendarChecklist();
});
