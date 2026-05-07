// Shared utilities for Lawn Dominator tool pages

async function geocodeAddress(query) {
  var url = 'https://nominatim.openstreetmap.org/search?q=' +
    encodeURIComponent(query) + '&format=json&limit=1';
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
