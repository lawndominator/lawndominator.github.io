(function () {
  var SQM_TO_SQFT = 10.7639104167;
  var DEFAULT_CENTER = [39.8283, -98.5795];
  var DEFAULT_ZOOM = 4;

  var mapEl = document.getElementById('lawn-measure-map');
  if (!mapEl || !window.L || !window.L.Control || !window.L.Control.Draw) return;

  var map = L.map(mapEl, {
    center: DEFAULT_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: false
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 20,
      attribution:
        'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community'
    }
  ).addTo(map);

  var drawnItems = new L.FeatureGroup();
  map.addLayer(drawnItems);

  var drawControl = new L.Control.Draw({
    position: 'topright',
    draw: {
      marker: false,
      circle: false,
      circlemarker: false,
      polyline: false,
      rectangle: {
        shapeOptions: {
          color: '#d9f99d',
          weight: 3,
          fillColor: '#84cc16',
          fillOpacity: 0.24
        }
      },
      polygon: {
        allowIntersection: false,
        showArea: true,
        metric: false,
        shapeOptions: {
          color: '#d9f99d',
          weight: 3,
          fillColor: '#84cc16',
          fillOpacity: 0.24
        }
      }
    },
    edit: {
      featureGroup: drawnItems,
      remove: true
    }
  });
  map.addControl(drawControl);

  var addressForm = document.getElementById('measure-address-form');
  var addressInput = document.getElementById('measure-address');
  var statusEl = document.getElementById('measure-status');
  var totalEl = document.getElementById('measure-total');
  var countEl = document.getElementById('measure-count');
  var listEl = document.getElementById('measure-list');
  var copyBtn = document.getElementById('measure-copy');
  var clearBtn = document.getElementById('measure-clear');
  var locateBtn = document.getElementById('measure-locate');
  var resultsEl = document.getElementById('measure-results');

  function formatSqft(value) {
    return Math.round(value).toLocaleString('en-US') + ' sq ft';
  }

  function layerAreaSqft(layer) {
    var latLngs = layer.getLatLngs();
    var ring = Array.isArray(latLngs[0]) ? latLngs[0] : latLngs;
    if (!ring || ring.length < 3 || !L.GeometryUtil) return 0;
    return Math.abs(L.GeometryUtil.geodesicArea(ring)) * SQM_TO_SQFT;
  }

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.classList.toggle('measure-status--error', Boolean(isError));
  }

  function clearResults() {
    if (!resultsEl) return;
    resultsEl.hidden = true;
    resultsEl.innerHTML = '';
  }

  function zoomToResult(result) {
    map.setView([result.lat, result.lon], 19);
    clearResults();
    setStatus('Found it. Zoom or pan if needed, then draw the lawn edge.');
  }

  function showResults(results) {
    if (!resultsEl) return;
    resultsEl.innerHTML = '';
    if (!results.length) {
      clearResults();
      return;
    }

    var heading = document.createElement('p');
    heading.textContent = 'Choose the matching address:';
    resultsEl.appendChild(heading);

    results.forEach(function (result) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = result.label;
      button.addEventListener('click', function () {
        zoomToResult(result);
      });
      resultsEl.appendChild(button);
    });

    resultsEl.hidden = false;
  }

  function updateTotals() {
    var total = 0;
    var rows = [];
    var index = 1;

    drawnItems.eachLayer(function (layer) {
      var sqft = layerAreaSqft(layer);
      total += sqft;
      rows.push({ label: 'Area ' + index, sqft: sqft });
      index += 1;
    });

    totalEl.textContent = formatSqft(total);
    countEl.textContent = rows.length + (rows.length === 1 ? ' area' : ' areas');
    copyBtn.disabled = total <= 0;
    clearBtn.disabled = rows.length === 0;

    if (!rows.length) {
      listEl.innerHTML = '<li>Draw around the lawn to start measuring.</li>';
      return;
    }

    listEl.innerHTML = rows
      .map(function (row) {
        return '<li><span>' + row.label + '</span><strong>' + formatSqft(row.sqft) + '</strong></li>';
      })
      .join('');
  }

  function addLayer(layer) {
    drawnItems.addLayer(layer);
    updateTotals();
  }

  map.on(L.Draw.Event.CREATED, function (event) {
    addLayer(event.layer);
    setStatus('Area added. Use the edit tool to adjust points or draw another section.');
  });

  map.on(L.Draw.Event.EDITED, updateTotals);
  map.on(L.Draw.Event.DELETED, updateTotals);

  async function geocodeCensus(query) {
    var callbackName = 'ldCensusGeocode' + Date.now() + Math.floor(Math.random() * 1000);
    var params = new URLSearchParams({
      address: query,
      benchmark: 'Public_AR_Current',
      format: 'jsonp',
      callback: callbackName
    });

    return new Promise(function (resolve) {
      var script = document.createElement('script');
      var timeout = window.setTimeout(function () {
        cleanup();
        resolve([]);
      }, 8000);

      function cleanup() {
        window.clearTimeout(timeout);
        delete window[callbackName];
        if (script.parentNode) script.parentNode.removeChild(script);
      }

      window[callbackName] = function (data) {
        cleanup();
        var matches = (((data || {}).result || {}).addressMatches || []);
        resolve(matches.map(function (match) {
          return {
            lat: Number(match.coordinates.y),
            lon: Number(match.coordinates.x),
            label: match.matchedAddress || query,
            source: 'census'
          };
        }).filter(function (result) {
          return Number.isFinite(result.lat) && Number.isFinite(result.lon);
        }));
      };

      script.onerror = function () {
        cleanup();
        resolve([]);
      };
      script.src = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?' + params.toString();
      document.head.appendChild(script);
    });
  }

  async function geocodeNominatim(query) {
    var params = new URLSearchParams({
      q: query,
      format: 'json',
      limit: '5',
      countrycodes: 'us',
      addressdetails: '0'
    });
    var res = await fetch('https://nominatim.openstreetmap.org/search?' + params.toString(), {
      headers: { Accept: 'application/json' }
    });
    if (!res.ok) throw new Error('Address search failed. Try again in a minute.');
    var data = await res.json();
    return data.map(function (item) {
      return {
        lat: parseFloat(item.lat),
        lon: parseFloat(item.lon),
        label: item.display_name,
        source: 'nominatim'
      };
    }).filter(function (result) {
      return Number.isFinite(result.lat) && Number.isFinite(result.lon);
    });
  }

  async function geocode(query) {
    var censusResults = await geocodeCensus(query);
    if (censusResults.length) {
      return { source: 'census', results: censusResults };
    }

    var osmResults = await geocodeNominatim(query);
    if (!osmResults.length) {
      throw new Error('No address found. Try a full street address with city, state, and ZIP.');
    }
    return { source: 'nominatim', results: osmResults };
  }

  addressForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    var query = addressInput.value.trim();
    if (!query) {
      setStatus('Enter an address first.', true);
      return;
    }
    setStatus('Searching address...');
    clearResults();
    try {
      var response = await geocode(query);
      if (response.source === 'census' && response.results.length === 1) {
        zoomToResult(response.results[0]);
        return;
      }
      showResults(response.results);
      setStatus('Pick the matching address from the results below.');
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  locateBtn.addEventListener('click', function () {
    if (!navigator.geolocation) {
      setStatus('Your browser does not support current-location lookup.', true);
      return;
    }
    setStatus('Finding your location...');
    navigator.geolocation.getCurrentPosition(
      function (position) {
        map.setView([position.coords.latitude, position.coords.longitude], 19);
        setStatus('Location loaded. Draw the lawn edge.');
      },
      function () {
        setStatus('Location access was denied. Search by address instead.', true);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  });

  copyBtn.addEventListener('click', async function () {
    var text = 'Measured lawn area: ' + totalEl.textContent;
    try {
      await navigator.clipboard.writeText(text);
      setStatus('Copied: ' + text);
    } catch (error) {
      setStatus('Copy failed. Highlight the total and copy it manually.', true);
    }
  });

  clearBtn.addEventListener('click', function () {
    drawnItems.clearLayers();
    updateTotals();
    setStatus('Cleared. Draw a new area when ready.');
  });

  updateTotals();
})();
