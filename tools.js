// Shared utilities for Lawn Dominator tool pages

function initAutocomplete(inputEl, onSelect) {
  var timeout = null;
  var lastFetched = '';

  var wrapper = document.createElement('div');
  wrapper.className = 'location-input-wrap';
  inputEl.parentNode.insertBefore(wrapper, inputEl);
  wrapper.appendChild(inputEl);

  var dropdown = document.createElement('ul');
  dropdown.className = 'autocomplete-dropdown';
  dropdown.hidden = true;
  wrapper.appendChild(dropdown);

  function closeDropdown() {
    dropdown.hidden = true;
    dropdown.innerHTML = '';
  }

  function showSuggestions(results) {
    dropdown.innerHTML = '';
    if (!results.length) { dropdown.hidden = true; return; }
    results.forEach(function(item) {
      var li = document.createElement('li');
      var parts = item.display_name.split(', ');
      li.textContent = parts.slice(0, 4).join(', ');
      li.addEventListener('mousedown', function(e) {
        e.preventDefault();
        var shortName = parts.slice(0, 3).join(', ');
        inputEl.value = shortName;
        closeDropdown();
        onSelect(parseFloat(item.lat), parseFloat(item.lon), shortName);
      });
      dropdown.appendChild(li);
    });
    dropdown.hidden = false;
  }

  inputEl.addEventListener('input', function() {
    var q = inputEl.value.trim();
    clearTimeout(timeout);
    if (q.length < 2) { closeDropdown(); return; }
    if (q === lastFetched) return;
    timeout = setTimeout(async function() {
      lastFetched = q;
      try {
        var url = 'https://nominatim.openstreetmap.org/search?q=' +
          encodeURIComponent(q) + '&format=json&limit=5&countrycodes=us';
        var res = await fetch(url);
        if (!res.ok) return;
        showSuggestions(await res.json());
      } catch(e) { /* ignore network errors during autocomplete */ }
    }, 300);
  });

  inputEl.addEventListener('blur', function() {
    setTimeout(closeDropdown, 150);
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeDropdown();
  });
}

async function geocodeAddress(query) {
  var url = 'https://nominatim.openstreetmap.org/search?q=' +
    encodeURIComponent(query) + '&format=json&limit=1&countrycodes=us';
  var res = await fetch(url);
  if (!res.ok) throw new Error('Geocoding request failed. Check your connection.');
  var data = await res.json();
  if (!data.length) throw new Error("Couldn't find that location. Try a city name or zip code.");
  var item = data[0];
  var parts = item.display_name.split(', ');
  var shortName = parts.slice(0, 3).join(', ');
  return { lat: parseFloat(item.lat), lon: parseFloat(item.lon), displayName: shortName };
}

async function reverseGeocode(lat, lon) {
  try {
    var url = 'https://nominatim.openstreetmap.org/reverse?lat=' + lat + '&lon=' + lon + '&format=json';
    var res = await fetch(url);
    if (!res.ok) return lat.toFixed(2) + '°, ' + lon.toFixed(2) + '°';
    var data = await res.json();
    var addr = data.address || {};
    var city = addr.city || addr.town || addr.village || addr.county || '';
    var state = addr.state || '';
    return [city, state].filter(Boolean).join(', ') ||
      lat.toFixed(2) + '°, ' + lon.toFixed(2) + '°';
  } catch (e) {
    return lat.toFixed(2) + '°, ' + lon.toFixed(2) + '°';
  }
}

function getCurrentPosition() {
  return new Promise(function(resolve, reject) {
    if (!navigator.geolocation) {
      reject(new Error('Geolocation is not supported by your browser.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      function(pos) { resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }); },
      function() { reject(new Error('Location access was denied. Enter your city or zip instead.')); },
      { timeout: 10000 }
    );
  });
}
