/* SPDX-License-Identifier: MIT */
(function () {
  'use strict';
  var pending = {}, sequence = 0, session = null, refreshPromise = null, job = null;
  var bridgePage = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  var jobTimer = null, googleTimer = null, active = false, noticeTimer = null;
  var modelAnchor = null, lastTile = null, viewMode = '2d', previewJob = null;
  var runtimeMode = 'bundled', runtimeReady = false;
  var suggestTimer = null, suggestSequence = 0, suggestItems = [], suggestIndex = -1;
  var $ = function (id) { return document.getElementById(id); };
  $('workspace').appendChild($('search-form'));
  $('workspace').appendChild($('search-results'));
  function tell(message, success) {
    clearTimeout(noticeTimer); $('notice').textContent = message; $('notice').hidden = false;
    $('notice').className = success ? 'success' : '';
    noticeTimer = setTimeout(function () { $('notice').hidden = true; }, success ? 7000 : 18000);
  }
  function native(action, args) {
    return new Promise(function (resolve, reject) {
      if (!window.sketchup || !window.sketchup.openmap) { reject(new Error('Mở extension trong SketchUp để sử dụng.')); return; }
      var id = bridgePage + '-r' + (++sequence), timeout = setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error('Yêu cầu mất quá nhiều thời gian.')); }
      }, 180000);
      pending[id] = { resolve: resolve, reject: reject, timer: timeout };
      window.sketchup.openmap(JSON.stringify({ id: id, action: action, args: args || {} }));
    });
  }
  window.OpenMap = { receive: function (id, result) {
    var item = pending[id]; if (!item) return;
    clearTimeout(item.timer); delete pending[id];
    if (result.ok) item.resolve(result.data);
    else { var error = new Error(result.error || 'Không xử lý được yêu cầu.'); error.status = result.status; item.reject(error); }
  } };
  function api(method, path, body, headers, retry) {
    return native('api', { method: method, path: path, body: body || null, headers: headers || {} }).catch(function (error) {
      if (error.status === 401 && session && session.refresh_token && retry !== false && path.indexOf('/api/auth/') !== 0) {
        if (!refreshPromise) {
          refreshPromise = api('POST', '/api/auth/refresh', { refresh_token: session.refresh_token }, {}, false).then(function (value) {
            session = value; return native('session', value);
          }).finally(function () { refreshPromise = null; });
        }
        return refreshPromise.then(function () { return api(method, path, body, headers, false); });
      }
      throw error;
    });
  }
  function guard(action) { return function (event) { if (event) event.preventDefault(); Promise.resolve().then(action).catch(function (e) { tell(e.message); }); }; }
  function updateAnchor() {
    return native('config').then(function (config) {
      var a = config.anchor;
      modelAnchor = a;
      lastTile = config.last_tile || null;
      $('anchor-panel').hidden = !a;
      document.querySelectorAll('[data-direction]').forEach(function (button) { button.disabled = !lastTile; });
      $('anchor').textContent = a ? a.lat.toFixed(6) + ', ' + a.lon.toFixed(6) + ' · Cao độ mốc ' + a.elevation.toFixed(2) + ' m' : 'Mốc sẽ được đặt khi nạp mảnh đầu tiên.';
      terrainModeUI();
    });
  }
  window.OpenMap.refreshAnchor = updateAnchor;
  function loggedIn(value) {
    return native('session', value).then(function () {
      session = value; return api('GET', '/api/me');
    }).then(enterWorkspace).catch(function (error) { session = null; native('session', { access_token: null }); throw error; });
  }
  function enterWorkspace(me) {
    $('control-panel').insertBefore($('app-header'), $('control-panel').firstChild);
    $('password').value = ''; $('login').hidden = true; $('workspace').hidden = false;
    document.body.classList.add('workspace-open');
    document.body.classList.toggle('has-account', runtimeMode === 'remote');
    $('account-email').textContent = me.email || me.id;
    $('logout').hidden = runtimeMode === 'bundled';
    renderMap(); return updateAnchor();
  }
  function clearLogin() {
    document.body.insertBefore($('app-header'), document.body.firstChild);
    session = null; clearTimeout(googleTimer); clearTimeout(jobTimer); active = false;
    job = null; $('build').disabled = false; $('import').disabled = $('export').disabled = $('export-glb').disabled = $('cancel').disabled = true;
    $('job-message').textContent = 'Chọn một vùng, rồi bấm Dựng bản đồ.';
    $('progress').value = 0; $('job-detail').textContent = '';
    $('login').hidden = false; $('workspace').hidden = true;
    document.body.classList.remove('workspace-open');
    document.body.classList.remove('has-account');
    previewJob = null;
    if (window.OpenMapViewer) window.OpenMapViewer.clear();
    switchView('2d');
    return native('session', { access_token: null });
  }
  function loginEnabled(value) { ['login-button','google','signup'].forEach(function (id) { $(id).disabled = !value; }); }
  function openSettings() {
    $('setup-overlay').hidden = false;
    $('setup-message').textContent = '';
    native('ack_settings').catch(function () {});
    return native('config').then(function (config) {
      runtimeMode = config.mode || 'remote'; $('setup-mode').value = runtimeMode;
      $('setup-server').value = config.server || 'http://127.0.0.1:8877';
      updateSetupMode();
      return native('runtime_status');
    }).then(function (state) {
      $('setup-runtime').textContent = state.message || 'Bộ xử lý đã sẵn sàng';
    }).catch(function (error) { $('setup-message').textContent = error.message; });
  }
  window.OpenMap.openSettings = openSettings;
  function updateSetupMode() {
    var local = $('setup-mode').value === 'bundled';
    $('setup-remote').hidden = local; $('setup-local-info').hidden = !local;
    $('setup-restart').hidden = !local;
  }
  $('setup-mode').onchange = updateSetupMode;
  $('setup-close').onclick = function () { $('setup-overlay').hidden = true; };
  $('settings').onclick = guard(openSettings);
  $('setup-use-local').onclick = guard(function () {
    return native('set_mode', { mode: 'bundled' }).then(function () { window.location.reload(); });
  });
  $('setup-apply-mode').onclick = guard(function () {
    return native('set_mode', { mode: $('setup-mode').value, server: $('setup-server').value }).then(function () { window.location.reload(); });
  });
  function restartRuntime() {
    if (active && !window.confirm('Khởi động lại sẽ dừng tác vụ đang dựng. Tiếp tục?')) return;
    $('setup-overlay').hidden = true;
    loginEnabled(false);
    return clearLogin().then(function () { return native('runtime_restart'); }).then(bootRuntime);
  }
  $('runtime-retry').onclick = guard(restartRuntime); $('setup-restart').onclick = guard(restartRuntime);
  $('setup-logs').onclick = guard(function () { return native('open_runtime_folder'); });
  $('login-form').onsubmit = guard(function () {
    $('login-button').disabled = true;
    return api('POST', '/api/auth/login', { email: $('email').value, password: $('password').value }).then(loggedIn).finally(function () { $('login-button').disabled = false; });
  });
  $('signup').onclick = guard(function () {
    return api('POST', '/api/auth/signup', { email: $('email').value, password: $('password').value }).then(function (result) { tell(result.message, true); });
  });
  $('google').onclick = guard(function () {
    $('google').disabled = true;
    return api('POST', '/api/auth/google/start', {}).then(function (flow) {
      return native('open_url', { url: flow.authorize_url }).then(function () {
        tell('Hoàn tất đăng nhập trong trình duyệt, rồi quay lại SketchUp.', true);
        var started = Date.now();
        function pollGoogle() {
          if (Date.now() - started > 600000) { $('google').disabled = false; tell('Yêu cầu Google đã hết hạn. Bấm đăng nhập lại.'); return; }
          api('GET', '/api/auth/google/status?flow_id=' + encodeURIComponent(flow.flow_id), null, { 'X-Flow-Secret': flow.poll_secret }, false).then(function (result) {
            if (result.state === 'ready') { $('google').disabled = false; return loggedIn(result.session); }
            googleTimer = setTimeout(pollGoogle, 1600);
          }).catch(function (error) { $('google').disabled = false; tell(error.message); });
        }
        pollGoogle();
      });
    }).catch(function (error) { $('google').disabled = false; throw error; });
  });
  $('logout').onclick = guard(function () { return api('POST', '/api/auth/logout', {}).catch(function () {}).then(clearLogin); });
  function numeric(id) { var input = $(id); if (!input.checkValidity() || !input.value.trim()) throw new Error('Kiểm tra giá trị ' + id + '.'); return Number(input.value); }
  function buildParams() {
    return { lat: numeric('lat'), lon: numeric('lon'), width: numeric('width'), height: numeric('height'), grid: numeric('grid'), image_size: numeric('image_size'), imagery: $('imagery').value, terrain: $('terrain').checked, exaggeration: numeric('exaggeration'), roads: $('roads-main').checked || $('roads-local').checked, buildings: $('buildings').checked,
      roads_main: $('roads-main').checked, roads_local: $('roads-local').checked, water: $('water').checked, trees: $('trees').checked, project_name: $('project-name').value,
      default_floors: numeric('default-floors'), building_style: $('building-style').value, roof_style: $('roof-style').value };
  }
  function finishJob(message) {
    active = false; $('build').disabled = false; $('cancel').disabled = true; $('job-message').textContent = message;
  }
  function pollJob() {
    if (!job || !active) return;
    var id = job.id;
    api('GET', '/api/jobs/' + id).then(function (status) {
      if (!job || job.id !== id || !active) return;
      $('progress').value = status.progress; $('job-message').textContent = status.message;
      if (status.state === 'complete') {
        job.partial = !!status.partial; job.warnings = status.warnings || []; job.missing_layers = status.missing_layers || [];
        $('job-warning').hidden = !job.partial && !job.warnings.length;
        $('job-warning').textContent = job.warnings.join(' ') + (job.partial ? ' Chưa tự nạp. Bạn có thể bấm Nạp nền/địa hình hoặc dựng lại vùng này để thử tải lớp OSM.' : '');
        $('import').textContent = job.partial ? 'Nạp nền/địa hình' : 'Nạp SU';
        job.state = 'complete'; finishJob(status.message); $('import').disabled = $('export').disabled = $('export-glb').disabled = false;
        if ($('auto-import').checked && !job.partial) return jobAction('import')();
      }
      else if (status.state === 'error' || status.state === 'cancelled') { $('progress').value = 0; finishJob(status.message); }
      else jobTimer = setTimeout(pollJob, 1700);
    }).catch(function (error) { finishJob(error.message); tell(error.message); });
  }
  $('build').onclick = guard(function () {
    var params = buildParams(); $('build').disabled = true; $('import').disabled = $('export').disabled = $('export-glb').disabled = true;
    previewJob = null;
    $('job-warning').hidden = true; $('import').textContent = 'Nạp SU';
    $('progress').value = 0; $('job-detail').textContent = ''; $('job-message').textContent = 'Đang gửi vùng chọn…';
    $('job-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    return api('POST', '/api/jobs', params).then(function (value) {
      job = value; active = true; $('cancel').disabled = false; pollJob();
    }).catch(function (error) { finishJob(error.message); throw error; });
  });
  $('cancel').onclick = guard(function () {
    if (!job) return;
    return api('DELETE', '/api/jobs/' + job.id).then(function () { clearTimeout(jobTimer); finishJob('Đã hủy tác vụ.'); });
  });
  function jobAction(action) {
    return function () {
      if (!job || job.state !== 'complete') throw new Error('Dựng xong bản đồ trước khi nạp hoặc xuất.');
      var button = $(action === 'export_glb' ? 'export-glb' : action);
      button.disabled = true; $('build').disabled = true;
      return api('GET', '/api/me').then(function () { return native(action, { job_id: job.id }); }).then(function (result) {
        if (action === 'import') {
          $('job-detail').textContent = 'Đã nạp ' + result.name + ' · ' + result.triangles.toLocaleString() + ' tam giác. ' + (result.warnings || []).join(' ');
          tell(job.partial ? 'Đã nạp nền/địa hình. Các lớp OSM được cảnh báo vẫn còn thiếu.' : 'Đã nạp bản đồ vào SketchUp.', !job.partial); return updateAnchor();
        }
        if (result.saved) tell(action === 'export_glb' ? 'Đã lưu mô hình GLB.' : 'Đã lưu gói OBJ, vật liệu, ảnh và metadata.', true);
      }).finally(function () { button.disabled = !job || job.state !== 'complete'; $('build').disabled = active; });
    };
  }
  $('import').onclick = guard(jobAction('import')); $('export').onclick = guard(jobAction('export'));
  $('export-glb').onclick = guard(jobAction('export_glb'));
  $('save-skp').onclick = guard(function () { return native('save_skp').then(function (r) { if (r.saved) tell('Đã lưu mảnh SKP.', true); }); });
  $('reset-anchor').onclick = guard(function () { return native('reset_anchor').then(updateAnchor); });
  $('undo').onclick = guard(function () { return native('undo').then(updateAnchor); });
  $('sync-shadow').onclick = guard(function () { return native('sync_shadow', { lat: numeric('lat'), lon: numeric('lon') }).then(function () { tell('Đã đồng bộ tọa độ bóng nắng.', true); }); });
  $('open-folder').onclick = guard(function () { return native('open_folder'); });
  function coordinatesFromText(text) {
    var result = String(text).match(/(?:@|[?&]q=|[?&]query=|^\s*)([-+]?\d{1,2}(?:\.\d+)?)\s*[,;]\s*([-+]?\d{1,3}(?:\.\d+)?)/i);
    if (!result) result = String(text).match(/!3d([-+\d.]+)!4d([-+\d.]+)/);
    if (result && Math.abs(Number(result[1])) <= 80 && Math.abs(Number(result[2])) <= 180) return [Number(result[1]), Number(result[2])];
    var re = /(\d{1,3})\s*[°º]\s*(\d{1,2})\s*['′’]\s*(\d+(?:\.\d+)?)\s*["″”]?\s*([NSEW])/gi, item, values = {};
    while ((item = re.exec(text))) { var value = Number(item[1]) + Number(item[2]) / 60 + Number(item[3]) / 3600, direction = item[4].toUpperCase(); values[direction === 'N' || direction === 'S' ? 'lat' : 'lon'] = (direction === 'S' || direction === 'W' ? -1 : 1) * value; }
    if (isFinite(values.lat) && isFinite(values.lon) && Math.abs(values.lat) <= 80 && Math.abs(values.lon) <= 180) return [values.lat, values.lon];
    return null;
  }
  function closeSuggestions() {
    suggestItems = []; suggestIndex = -1; $('search-results').textContent = ''; $('search-results').hidden = true;
    $('address').setAttribute('aria-expanded', 'false'); $('address').removeAttribute('aria-activedescendant');
  }
  function choosePlace(entry) {
    clearTimeout(suggestTimer); suggestSequence++; closeSuggestions(); $('preset-list').hidden = true;
    zoom = entry.kind === 'coords' || entry.source === 'coordinates' ? 17 : 16;
    setCenter(Number(entry.lat), Number(entry.lon)); switchView('2d');
    if (entry.kind !== 'coords' && entry.source !== 'coordinates') $('address').value = entry.title || entry.label || entry.display_name || $('address').value;
    $('clear-search').hidden = !$('address').value;
    $('search-submit').disabled = false; $('search-submit').textContent = 'Tìm';
    tell(entry.label || entry.display_name || 'Đã chuyển tới địa điểm.', true);
  }
  function showSuggestions(items, selected) {
    closeSuggestions(); suggestItems = items || []; suggestIndex = selected == null ? -1 : selected;
    if (!suggestItems.length) return;
    $('preset-list').hidden = true; $('search-results').hidden = false; $('address').setAttribute('aria-expanded', 'true');
    suggestItems.forEach(function (entry, index) {
      var button = document.createElement('button'); button.type = 'button'; button.id = 'suggest-' + index; button.setAttribute('role', 'option');
      button.classList.toggle('active', index === suggestIndex); button.setAttribute('aria-selected', index === suggestIndex ? 'true' : 'false');
      var title = document.createElement('span'), detail = document.createElement('span');
      title.className = 'suggest-title'; title.textContent = entry.title || entry.label || entry.display_name;
      detail.className = 'suggest-sub'; detail.textContent = entry.subtitle || Number(entry.lat).toFixed(5) + ', ' + Number(entry.lon).toFixed(5);
      button.appendChild(title); button.appendChild(detail); button.onclick = function () { choosePlace(entry); };
      $('search-results').appendChild(button);
    });
    if (suggestIndex >= 0) $('address').setAttribute('aria-activedescendant', 'suggest-' + suggestIndex);
  }
  function scheduleSuggestions() {
    var text = $('address').value.trim(), generation = ++suggestSequence;
    $('search-submit').textContent = 'Tìm';
    clearTimeout(suggestTimer); closeSuggestions(); $('clear-search').hidden = !text;
    var pair = coordinatesFromText(text);
    if (pair) { showSuggestions([{ title: 'Tới tọa độ ' + pair[0].toFixed(6) + ', ' + pair[1].toFixed(6), subtitle: 'Bấm Enter để chuyển ngay', kind: 'coords', lat: pair[0], lon: pair[1] }], 0); return; }
    if (text.length < 2 || !runtimeReady) return;
    suggestTimer = setTimeout(function () {
      api('POST', '/api/search_suggest', { query: text, lat: Number($('lat').value), lon: Number($('lon').value), limit: 6 }).then(function (value) {
        if (generation === suggestSequence && $('address').value.trim() === text) showSuggestions(value.results || []);
      }).catch(function () { if (generation === suggestSequence) closeSuggestions(); });
    }, 180);
  }
  $('address').oninput = scheduleSuggestions;
  $('address').onkeydown = function (event) {
    if (event.key === 'Escape') { suggestSequence++; clearTimeout(suggestTimer); closeSuggestions(); return; }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && suggestItems.length) {
      event.preventDefault(); var items = suggestItems.slice();
      var next = event.key === 'ArrowDown' ? (suggestIndex + 1) % items.length : (suggestIndex <= 0 ? items.length - 1 : suggestIndex - 1);
      showSuggestions(items, next);
    }
  };
  $('clear-search').onclick = function () { $('address').value = ''; suggestSequence++; clearTimeout(suggestTimer); closeSuggestions(); $('clear-search').hidden = true; $('address').focus(); };
  document.addEventListener('pointerdown', function (event) {
    if (!$('search-form').contains(event.target) && !$('search-results').contains(event.target)) { suggestSequence++; clearTimeout(suggestTimer); closeSuggestions(); }
  });
  $('search-form').onsubmit = guard(function () {
    var text = $('address').value.trim(), coordinates = coordinatesFromText(text);
    clearTimeout(suggestTimer);
    if (suggestItems.length) { choosePlace(suggestItems[suggestIndex >= 0 ? suggestIndex : 0]); return; }
    if (coordinates) { choosePlace({ kind: 'coords', lat: coordinates[0], lon: coordinates[1] }); return; }
    if (text.length < 2) { tell('Nhập địa điểm hoặc dán tọa độ / link Google Maps.'); return; }
    var generation = ++suggestSequence; closeSuggestions(); $('search-submit').textContent = '…';
    return api('POST', '/api/geocode', { query: text, lat: Number($('lat').value), lon: Number($('lon').value), limit: 6 }).then(function (value) {
      if (generation !== suggestSequence || $('address').value.trim() !== text) return;
      if (!value.results || !value.results.length) throw new Error('Không tìm thấy địa điểm. Thử ghi thêm quận/tỉnh hoặc dán tọa độ.');
      choosePlace(value.results[0]);
    }).catch(function (error) {
      if (generation === suggestSequence) throw error;
    }).finally(function () { if (generation === suggestSequence) $('search-submit').textContent = 'Tìm'; });
  });
  var zoom = 16, drag = null, loadedTiles = {};
  function mapTile(style, z, x, y) {
    if (style === 'esri_sat') return 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/' + z + '/' + y + '/' + x;
    if (style.indexOf('google_') === 0) return 'https://mt' + ((x + y) % 4) + '.google.com/vt/lyrs=' + ({ google_sat: 's', google_hybrid: 'y', google_street: 'm' })[style] + '&hl=vi&x=' + x + '&y=' + y + '&z=' + z;
    return 'https://tile.openstreetmap.org/' + z + '/' + x + '/' + y + '.png';
  }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function mercator(lat, lon, z) {
    var scale = 256 * Math.pow(2, z), rad = clamp(lat, -80, 80) * Math.PI / 180;
    return { x: (lon + 180) / 360 * scale, y: (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * scale };
  }
  function inverse(x, y, z) {
    var scale = 256 * Math.pow(2, z), value = Math.PI * (1 - 2 * y / scale);
    return { lat: Math.atan((Math.exp(value) - Math.exp(-value)) / 2) * 180 / Math.PI, lon: x / scale * 360 - 180 };
  }
  function setCenter(lat, lon) {
    $('lat').value = clamp(lat, -79.9, 79.9).toFixed(6); $('lon').value = clamp(lon, -179.9, 179.9).toFixed(6); renderMap();
  }
  function renderMap() {
    if ($('workspace').hidden || viewMode !== '2d') return;
    var frame = $('map'), w = frame.clientWidth, h = frame.clientHeight, lat = Number($('lat').value), lon = Number($('lon').value);
    if (!isFinite(lat) || !isFinite(lon)) return;
    var center = mercator(lat, lon, zoom), left = center.x - w / 2, top = center.y - h / 2, n = Math.pow(2, zoom), wanted = {};
    for (var y = Math.floor(top / 256); y <= Math.floor((top + h) / 256); y++) {
      for (var x = Math.floor(left / 256); x <= Math.floor((left + w) / 256); x++) {
        if (y < 0 || y >= n) continue;
        var style = $('map-style').value, key = style + '/' + zoom + '/' + x + '/' + y, tile = loadedTiles[key]; wanted[key] = true;
        if (!tile) { tile = document.createElement('img'); tile.alt = ''; tile.draggable = false; tile.src = mapTile(style, zoom, ((x % n + n) % n), y); $('tiles').appendChild(tile); loadedTiles[key] = tile; }
        tile.style.left = (x * 256 - left) + 'px'; tile.style.top = (y * 256 - top) + 'px';
      }
    }
    Object.keys(loadedTiles).forEach(function (key) { if (!wanted[key]) { loadedTiles[key].remove(); delete loadedTiles[key]; } });
    var metersPixel = 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom);
    $('selection-box').style.width = (Number($('width').value) / metersPixel) + 'px';
    $('selection-box').style.height = (Number($('height').value) / metersPixel) + 'px';
    $('selection-size').textContent = $('width').value + ' × ' + $('height').value + ' m';
    $('center-coordinates').textContent = lat.toFixed(5) + ', ' + lon.toFixed(5);
    $('map-credit').textContent = $('map-style').value === 'osm_clean' ? '© OpenStreetMap contributors' : ($('map-style').value === 'esri_sat' ? 'Tiles © Esri and providers' : '© Google and data providers');
  }
  ['lat', 'lon', 'width', 'height'].forEach(function (id) { $(id).onchange = renderMap; });
  function updateImageryNote() {
    $('imagery-note').textContent = $('map-style').value === 'osm_clean' ? 'OSM dùng để xem 2D. Ảnh xuất đang dùng: ' + $('imagery').selectedOptions[0].textContent + '.' : 'Ảnh xuất dùng cùng nguồn với bản đồ đang xem.';
  }
  $('map-style').onchange = function () {
    var style = $('map-style').value;
    if (style !== 'osm_clean') $('imagery').value = style === 'esri_sat' ? 'satellite' : style;
    updateImageryNote(); renderMap();
  };
  $('imagery').onchange = function () {
    if ($('imagery').value !== 'none') $('map-style').value = $('imagery').value === 'satellite' ? 'esri_sat' : $('imagery').value;
    updateImageryNote(); renderMap();
  };
  $('zoom-in').onclick = function () { zoom = Math.min(19, zoom + 1); renderMap(); };
  $('zoom-out').onclick = function () { zoom = Math.max(3, zoom - 1); renderMap(); };
  $('map').addEventListener('wheel', function (event) { event.preventDefault(); zoom = clamp(zoom + (event.deltaY < 0 ? 1 : -1), 3, 19); renderMap(); }, { passive: false });
  $('map').onpointerdown = function (event) {
    if (event.target.closest('button')) return;
    drag = { resize: event.target.classList.contains('resize-grip'), x: event.clientX, y: event.clientY, center: mercator(Number($('lat').value), Number($('lon').value), zoom) };
    $('map').setPointerCapture(event.pointerId); $('map').classList.add('dragging');
  };
  $('map').onpointermove = function (event) {
    if (!drag) return;
    if (drag.resize) {
      var frame = $('map').getBoundingClientRect(), scale = 156543.03392 * Math.cos(Number($('lat').value) * Math.PI / 180) / Math.pow(2, zoom);
      $('width').value = clamp(Math.round(Math.abs(event.clientX - frame.left - frame.width / 2) * 2 * scale), 10, 10000);
      $('height').value = clamp(Math.round(Math.abs(event.clientY - frame.top - frame.height / 2) * 2 * scale), 10, 10000); renderMap();
    } else { var center = inverse(drag.center.x - (event.clientX - drag.x), drag.center.y - (event.clientY - drag.y), zoom); setCenter(center.lat, center.lon); }
  };
  $('map').onpointerup = $('map').onpointercancel = function () { drag = null; $('map').classList.remove('dragging'); };
  document.querySelectorAll('[data-direction]').forEach(function (button) {
    button.onclick = function () {
      if (!lastTile) return;
      var lat = lastTile.center.lat, lon = lastTile.center.lon;
      $('width').value = lastTile.width; $('height').value = lastTile.height;
      var direction = button.getAttribute('data-direction');
      if (direction === 'north' || direction === 'south') lat += (lastTile.bbox.north - lastTile.bbox.south) * (direction === 'north' ? 1 : -1);
      else lon += (lastTile.bbox.east - lastTile.bbox.west) * (direction === 'east' ? 1 : -1);
      setCenter(lat, lon);
    };
  });
  window.addEventListener('resize', renderMap);
  function terrainModeUI() {
    var enabled = $('terrain').checked, patch = enabled && modelAnchor && modelAnchor.terrain_mode === 'flat';
    $('mode-flat').classList.toggle('selected', !enabled); $('mode-terrain').classList.toggle('selected', enabled);
    $('mode-terrain').textContent = modelAnchor && modelAnchor.terrain_mode === 'flat' ? '⛰ Trám đồi 3D' : '⛰ Địa hình 3D';
    $('hill-hint').hidden = !patch;
    $('grid').disabled = $('exaggeration').disabled = !enabled;
    $('build').textContent = patch ? 'Trám đồi 3D vào map phẳng' : 'Đưa vào SketchUp';
  }
  $('mode-flat').onclick = function () { $('terrain').checked = false; terrainModeUI(); };
  $('mode-terrain').onclick = function () { $('terrain').checked = true; terrainModeUI(); };
  $('terrain').onchange = terrainModeUI;
  $('advanced-toggle').onclick = function () { $('advanced').hidden = !$('advanced').hidden; $('advanced-toggle').textContent = $('advanced').hidden ? 'Tùy chỉnh chi tiết ▾' : 'Thu gọn chi tiết ▴'; };
  document.querySelectorAll('[data-size]').forEach(function (button) { button.onclick = function () { $('width').value = $('height').value = button.getAttribute('data-size'); renderMap(); }; });
  document.querySelectorAll('[data-building]').forEach(function (button) { button.onclick = function () { $('building-style').value = button.getAttribute('data-building'); document.querySelectorAll('[data-building]').forEach(function (b) { b.classList.toggle('selected', b === button); }); }; });
  $('building-style').onchange = function () { document.querySelectorAll('[data-building]').forEach(function (b) { b.classList.toggle('selected', b.getAttribute('data-building') === $('building-style').value); }); };
  $('theme').onclick = function () { document.body.classList.toggle('dark'); try { localStorage.setItem('openmap-theme', document.body.classList.contains('dark') ? 'dark' : 'light'); } catch (_e) {} };
  try { document.body.classList.toggle('dark', localStorage.getItem('openmap-theme') === 'dark'); } catch (_e) {}
  [['Hà Nội',21.028511,105.854444],['TP. Hồ Chí Minh',10.776889,106.700806],['Đà Nẵng',16.0544,108.2022],['Đà Lạt',11.9404,108.4583],['Hải Phòng',20.8449,106.6881],['Cần Thơ',10.0452,105.7469]].forEach(function (place) { var button = document.createElement('button'); button.type = 'button'; button.textContent = place[0]; button.onclick = function () { choosePlace({ title: place[0], label: place[0], lat: place[1], lon: place[2] }); }; $('preset-list').appendChild(button); });
  $('presets').onclick = function () { suggestSequence++; clearTimeout(suggestTimer); closeSuggestions(); $('preset-list').hidden = !$('preset-list').hidden; };
  function ocrFile(file) {
    if (!file || file.size > 6000000) { tell('Chọn ảnh tọa độ nhỏ hơn 6 MB.'); return; }
    tell('Đang đọc tọa độ trong ảnh…', true);
    var reader = new FileReader(); reader.onload = function () {
      api('POST', '/api/ocr', { image: reader.result.split(',')[1] }).then(function (result) {
        var pair = coordinatesFromText(result.text);
        if (!pair) throw new Error('Chưa nhận ra cặp tọa độ. Hãy cắt riêng vùng chữ hoặc dán tọa độ dạng văn bản.');
        choosePlace({ kind: 'coords', lat: pair[0], lon: pair[1] }); tell('Đã lấy tọa độ từ ảnh.', true);
      }).catch(function (error) { tell(error.message); });
    }; reader.readAsDataURL(file);
  }
  $('ocr').onclick = function () { $('ocr-file').click(); };
  $('ocr-file').onchange = function () { ocrFile($('ocr-file').files[0]); $('ocr-file').value = ''; };
  document.addEventListener('paste', function (event) {
    if ($('workspace').hidden) return;
    var items = event.clipboardData && event.clipboardData.items;
    if (items) for (var i = 0; i < items.length; i++) if (items[i].type.indexOf('image/') === 0) { event.preventDefault(); ocrFile(items[i].getAsFile()); break; }
  });
  function switchView(mode) {
    viewMode = mode; $('map').hidden = mode !== '2d'; $('preview3d').hidden = mode !== '3d';
    $('view2d').classList.toggle('selected', mode === '2d'); $('view3d').classList.toggle('selected', mode === '3d');
    $('reset-camera').hidden = $('wireframe').hidden = mode !== '3d';
    if (mode === '2d') renderMap(); else window.OpenMapViewer.render();
  }
  $('view2d').onclick = function () { switchView('2d'); };
  $('view3d').onclick = guard(function () {
    if (!job || job.state !== 'complete') throw new Error('Dựng bản đồ xong để xem mô hình 3D.');
    if (previewJob === job.id) { switchView('3d'); return; }
    var id = job.id; $('view3d').disabled = true;
    return api('GET', '/api/me').then(function () { return native('preview', { job_id: id }); }).then(function (mesh) {
      if (!job || job.id !== id) return;
      switchView('3d'); return window.OpenMapViewer.load(mesh).then(function () { if (job && job.id === id) previewJob = id; });
    }).finally(function () { $('view3d').disabled = false; });
  });
  $('wireframe').onclick = function () { window.OpenMapViewer.wireframe = !window.OpenMapViewer.wireframe; window.OpenMapViewer.render(); };
  $('reset-camera').onclick = function () { window.OpenMapViewer.reset(); };
  function bootRuntime() {
    loginEnabled(false); runtimeReady = false; $('runtime-retry').hidden = true; $('runtime-progress').hidden = false;
    $('login-options').hidden = true;
    $('signin-title').textContent = 'Đang mở bản đồ';
    $('signin-description').textContent = 'Đang kết nối bộ xử lý bản đồ…';
    var started = Date.now(), config;
    function poll() {
      return native('runtime_status').then(function (state) {
        runtimeMode = state.mode || config.mode || 'remote';
        $('runtime-progress').value = state.progress || 0; $('connection').textContent = state.message || 'Đang khởi động…';
        if (state.state === 'error') throw new Error(state.message);
        if (state.state === 'ready') return;
        if (Date.now() - started > 180000) throw new Error('Bộ xử lý chưa khởi động xong. Bấm Thử lại hoặc mở Cấu hình để xem log.');
        return new Promise(function (resolve) { setTimeout(resolve, 500); }).then(poll);
      });
    }
    return native('config').then(function (value) { config = value; return poll(); }).then(function () {
      runtimeReady = true; $('runtime-progress').hidden = true;
      return api('GET', '/health');
    }).then(function (info) {
      $('ocr').title = info.ocr_available ? 'OCR đã có sẵn trong bộ xử lý' : 'Máy chủ chưa có bộ OCR';
      if (info.auth_mode === 'local') {
        session = null;
        return native('session', { access_token: null }).then(function () { return api('GET', '/api/me'); }).then(enterWorkspace).then(function () {
          if (config.open_settings) return openSettings();
        });
      }
      $('login-options').hidden = false; $('signin-title').textContent = 'Đăng nhập máy chủ riêng';
      $('signin-description').textContent = 'Đăng nhập Email hoặc Google của máy chủ bạn đã cấu hình.';
      loginEnabled(info.auth_configured);
      $('connection').textContent = info.auth_configured ? 'Bộ xử lý sẵn sàng · OpenMap ' + info.version : 'Mở Cấu hình để nhập Project URL và public key Supabase.';
      if (config.open_settings) return openSettings();
      if (info.auth_configured && config.session) return loggedIn(config.session);
    }).catch(function (error) {
      runtimeReady = false; loginEnabled(false);
      $('connection').textContent = error.message; $('runtime-progress').hidden = true;
      $('runtime-retry').hidden = runtimeMode !== 'bundled';
      return openSettings();
    });
  }
  bootRuntime();
}());
