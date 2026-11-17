/* SPDX-License-Identifier: MIT — original SiteCraft Render AI interface. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var nativeAvailable = !!(window.sketchup && window.sketchup.sitecraft_ai);
  var pageId = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 9), sequence = 0, pending = {};
  var S = { online: false, managed: true, bridge: {}, busy: '', source: null, sourceImage: null, sourceName: '', refs: [],
    annotations: [], undo: [], redo: [], draft: null, tool: 'none', jobs: [], job: null, result: null, resultIndex: 0,
    compareSource: null, compare: false, cache: new Map(), selection: 0, resultLoad: 0, resultPending: '', prepared: null, preparedKey: '',
    cancelled: new Set(), cancelling: new Set(), pendingSubmission: null, polling: false, timer: null, cameraTimer: null };
  var prefs = readPrefs(), thumbnailObserver = null, thumbnailGeneration = 0, thumbnailQueue = [], thumbnailActive = 0, thumbnailCache = new Map();
  S.lastCapture = prefs.lastCapture || null; S.sourceKind = ''; S.initialCaptureDone = false; S.frameSupported = false; S.customCompare = null; S.pan = null; S.refPrepared = new Map(); S.editorDrafts=new Map();
  var MAX_FILE = 20 * 1024 * 1024, MAX_PIXELS = 20_000_000, MAX_REGIONS = 12;
  var labels = { queued: 'Trong hàng đợi', claimed: 'Chrome đã nhận', running: 'Đang thực hiện trên Flow', waiting_user: 'Cần bạn thao tác',
    complete: 'Hoàn thành', error: 'Gặp lỗi', cancelled: 'Đã hủy' };
  var operationNames = { render: 'Tạo ảnh', edit: 'Chỉnh ảnh', upscale: 'Flow 2K' };
  var presets = { architecture: 'Ảnh ngoại thất kiến trúc với tỷ lệ và vật liệu hợp lý, phối cảnh chân thực.',
    interior: 'Ảnh nội thất chân thực, ánh sáng trong phòng tự nhiên và vật liệu có chiều sâu.',
    landscape: 'Ảnh cảnh quan chân thực, cây cối và mặt đất có tỷ lệ phù hợp với kiến trúc.',
    aerial: 'Ảnh kiến trúc từ trên cao, giữ tổ chức không gian và tỷ lệ công trình.', custom: '' };
  var lights = { original: '', daylight: 'Ánh sáng ban ngày dịu, cân bằng và bóng đổ tự nhiên.',
    golden: 'Ánh sáng nắng chiều ấm, có hướng và bóng đổ mềm.', blue: 'Ánh sáng chạng vạng với bầu trời dịu và đèn kiến trúc hợp lý.',
    night: 'Khung cảnh ban đêm với chiếu sáng kiến trúc tự nhiên, tránh vùng cháy sáng.' };

  function tell(message, success) {
    $('notice').textContent = message; $('notice').className = success ? 'success' : ''; $('notice').hidden = false;
    clearTimeout(tell.timer); tell.timer = setTimeout(function () { $('notice').hidden = true; }, success ? 6000 : 16000);
  }
  function native(action, args) {
    return new Promise(function (resolve, reject) {
      if (!nativeAvailable) { reject(new Error('Mở Render AI từ SiteCraft trong SketchUp để sử dụng.')); return; }
      var id = pageId + '-' + (++sequence), timer = setTimeout(function () {
        if (!pending[id]) return; delete pending[id]; var error = new Error('Bộ xử lý chưa phản hồi. Kiểm tra SiteCraft rồi thử kết nối lại.'); error.status = 0; reject(error);
      }, 90000);
      pending[id] = { resolve: resolve, reject: reject, timer: timer };
      try { window.sketchup.sitecraft_ai(JSON.stringify({ id: id, action: action, args: args || {} })); }
      catch (error) { clearTimeout(timer); delete pending[id]; reject(error); }
    });
  }
  window.SiteCraftAI = {
    receive: function (id, value) {
      var request = pending[id]; if (!request) return;
      clearTimeout(request.timer); delete pending[id];
      if (value.ok) request.resolve(value.data);
      else { var error = new Error(value.error || 'Không thực hiện được thao tác.'); error.status = value.status; request.reject(error); }
    },
    cameraChanged: function () {
      clearTimeout(S.cameraTimer);
      if (!$('camera-watch').checked) return;
      if (S.annotations.length || S.draft) { $('busy-message').textContent = 'Camera đã đổi; ảnh có đánh dấu được giữ lại. Bấm Chụp SketchUp để cập nhật.'; return; }
      S.cameraTimer = setTimeout(function () { if (!S.busy && $('camera-watch').checked) capture(true); }, Math.max(200, Math.min(10000, Number($('camera-debounce').value) * 1000 || 600)));
    }
  };
  function api(method, suffix, body) { return native('api', { method: method, path: '/api/ai/' + suffix, body: body || null }); }
  function validId(value) { return typeof value === 'string' && /^[a-f0-9]{32}$/.test(value); }
  function button(id, action) { $(id).onclick = function (event) { if (event) event.preventDefault(); Promise.resolve().then(action).catch(function (error) { tell(error.message); }); }; }
  function terminal(job) { return job && ['complete', 'error', 'cancelled'].indexOf(job.state) >= 0; }
  function requestId() {
    var bytes = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes);
    else for (var i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    return Array.from(bytes).map(function (byte) { return byte.toString(16).padStart(2, '0'); }).join('');
  }
  function readPrefs() { try { return JSON.parse(localStorage.getItem('SiteCraftAI.ui.v1') || '{}') || {}; } catch (_error) { return {}; } }
  function savePrefs() {
    ['capture-width','capture-size-mode','hide-helpers','auto-recapture','upload-max','upload-format','jpeg-quality','camera-debounce','history-size','history-fit','allow-queue'].forEach(function (id) { prefs[id] = $(id).type === 'checkbox' ? $(id).checked : $(id).value; });
    prefs.lastCapture = S.lastCapture; prefs.draftPrompt=$('prompt').value;
    try { localStorage.setItem('SiteCraftAI.ui.v1', JSON.stringify(prefs)); } catch (_error) {}
  }
  function regionItems() { return S.annotations.filter(function (item) { return item.tool !== 'eraser'; }); }
  function promptLibrary() { return window.SiteCraftAIReferencePrompts || window.SiteCraftAIPresets; }
  function roleLabel(role) { var library = promptLibrary(), value = library && library.getOptions('referenceRoles').find(function (item) { return item.id === role; }); return value ? value.label : 'Tham chiếu'; }
  function basePrompt() {
    var parts = [$('prompt').value.trim()], library = promptLibrary();
    if (!S.restoredPrompt) {
      if (library) parts.push(library.compose({ scene:$('preset').value, style:$('photo-style').value, context:$('context').value, lighting:$('lighting').value,styleCustom:$('custom-style').value,contextCustom:$('custom-context').value,lightingCustom:$('custom-lighting').value,
        extras:Array.from(document.querySelectorAll('[data-extra]:checked')).map(function (input) { return input.dataset.extra; }),
        references:S.refs.map(function (ref,index) { return {index:index+1,role:ref.role || 'other'}; }) }));
      else parts.push(presets[$('preset').value] || '', lights[$('lighting').value] || '');
      ['style','context','lighting'].forEach(function (group) { var control = group === 'style' ? $('photo-style') : $(group); if (control.value === 'custom') parts.push($('custom-'+group).value.trim()); });
    }
    return parts.filter(Boolean).join('\n');
  }
  function currentAnnotationNotes() {
    if (!S.source) return '';
    var crop = cropBox(), notes = [];
    regionItems().forEach(function (item, index) {
      var bounds = shapeBounds(item);
      if (bounds.right < crop.x || bounds.left > crop.x + crop.width || bounds.bottom < crop.y || bounds.top > crop.y + crop.height) return;
      var left = Math.max(0, (bounds.left - crop.x) / crop.width), top = Math.max(0, (bounds.top - crop.y) / crop.height);
      var right = Math.min(1, (bounds.right - crop.x) / crop.width), bottom = Math.min(1, (bounds.bottom - crop.y) / crop.height);
      var references = (item.reference_ids || []).map(function (id) { var i = S.refs.findIndex(function (ref) { return ref.id === id; }); return i < 0 ? '' : 'Ảnh tham chiếu ' + (i+1) + ' (' + roleLabel(S.refs[i].role) + ') áp dụng cho vùng này.'; }).filter(Boolean).join(' ');
      notes.push('Vùng ' + (index + 1) + ' (' + item.color + ', ' + [left, top, right, bottom].map(function (v) { return Math.round(v * 100) + '%'; }).join(', ') + '): ' + (item.note.trim() || 'Thực hiện yêu cầu mô tả tại vùng được đánh dấu.') + (references ? ' ' + references : ''));
    });
    return notes.length ? 'Ảnh nguồn có nét đánh dấu để chỉ vùng cần chú ý; đây không phải mặt nạ khóa điểm ảnh.\n' + notes.join('\n') : '';
  }
  function annotationNotes() { return [S.restoredNotes || '',currentAnnotationNotes()].filter(Boolean).join('\n'); }
  function fullPrompt() {
    var operation=S.promptOperation || 'render'; if (operation==='upscale') return '';
    var reference=window.SiteCraftAIReferencePrompts;
    if (reference && typeof reference.composeFull==='function') {
      if (S.restoredPrompt) return [basePrompt(),currentAnnotationNotes() ? (reference.composeAnnotationNotes ? reference.composeAnnotationNotes(currentAnnotationNotes()) : currentAnnotationNotes()+'\nBỏ các nét màu đánh dấu khỏi ảnh kết quả.') : ''].filter(Boolean).join('\n');
      var userText=$('prompt').value.trim(), notes=annotationNotes(), colors=Array.from(new Set(regionItems().map(function (item) { return item.color; }).concat((S.restoredNotes || '').match(/#[0-9a-f]{6}/gi) || []))).slice(0,12);
      var materialRefs=S.refs.filter(function (ref) { return ref.role==='material'; });
      if (operation==='edit' && reference.composeRegionEdit && (colors.length || materialRefs.length)) userText=reference.composeRegionEdit({userText:userText,colors:colors,textureLabels:materialRefs.length===S.refs.length?materialRefs.map(function (ref) { return ref.name || 'Vật liệu'; }):[]});
      return reference.composeFull({operation:operation,basePrompt:'',userText:userText,scene:$('preset').value,style:$('photo-style').value,context:$('context').value,lighting:$('lighting').value,styleCustom:$('custom-style').value,contextCustom:$('custom-context').value,lightingCustom:$('custom-lighting').value,
        extras:Array.from(document.querySelectorAll('[data-extra]:checked')).map(function (input) { return input.dataset.extra; }),references:S.refs.map(function (ref,index) { return {index:index+1,role:ref.role || 'general'}; }),
        keepDesign:$('keep-design').checked,keepCamera:$('keep-camera').checked,aspect:aspectValue(),annotationNotes:notes});
    }
    var parts=[basePrompt()];
    if (!S.restoredPrompt) {
      if ($('keep-design').checked) parts.push('Giữ hình khối, bố cục kiến trúc, tỷ lệ và thiết kế của ảnh nguồn.');
      if ($('keep-camera').checked) parts.push('Giữ vị trí máy ảnh, hướng nhìn, phối cảnh và khung hình của ảnh nguồn.');
      if (aspectValue()!=='original') parts.push('Tạo ảnh theo khung tỷ lệ '+aspectValue()+', bám sát phần nguồn đã cắt.');
    }
    if (!S.restoredPrompt && S.restoredNotes) parts.push(S.restoredNotes);
    if (currentAnnotationNotes()) parts.push(currentAnnotationNotes());
    if (currentAnnotationNotes() || !S.restoredPrompt && S.restoredNotes) parts.push('Các nét màu chỉ để chỉ vùng cần chỉnh; bỏ toàn bộ nét, khung và ký hiệu đánh dấu khỏi ảnh kết quả.');
    return parts.filter(Boolean).join('\n');
  }
  function updatePrompt() { $('prompt-preview').value=fullPrompt(); sync(); }
  function sync() {
    var ready = S.online && S.managed && !S.busy && !S.draft && !S.pan, connected = !!(S.bridge.paired && S.bridge.connected);
    $('render').disabled = $('edit').disabled = !ready || !connected || !!S.pendingSubmission || !S.source || !basePrompt().trim();
    $('manual-handoff').disabled = !ready || !!S.pendingSubmission || !S.source || !basePrompt().trim();
    $('upscale').disabled = !ready || !connected || !!S.pendingSubmission || !(S.result || S.source);
    ['capture', 'upload-source', 'source-file', 'add-reference', 'reference-file'].forEach(function (id) { $(id).disabled = !ready; });
    $('add-reference').disabled = !ready || S.refs.length >= 4;
    $('save-result').disabled = $('open-result').disabled = !ready || !S.result;
    $('return-capture').disabled = !ready || !S.lastCapture;
    $('compare-file-open').disabled = !ready;
    $('compare-reset').hidden = !S.customCompare;
    $('viewport-frame').disabled = !S.frameSupported || !!S.busy;
    $('restored-notes').hidden=!S.restoredNotes; $('restored-notes-text').value=S.restoredNotes || '';
    $('custom-aspect').hidden = $('aspect').value !== 'custom';
    $('jpeg-quality').disabled = !!S.busy || $('upload-format').value !== 'jpeg';
    $('save-source').disabled = !ready || !S.source;
    $('reuse-result').disabled = $('reference-result').disabled = !ready || !S.result;
    $('reference-result').disabled = !ready || !S.result || S.refs.length >= 4;
    $('restore-job').disabled = !ready || !S.job;
    $('compare-toggle').disabled = !S.result || !(S.customCompare || S.compareSource);
    $('previous-result').disabled = !S.job || !S.job.result_ids || S.resultIndex <= 0;
    $('next-result').disabled = !S.job || !S.job.result_ids || S.resultIndex >= S.job.result_ids.length - 1;
    $('cancel-job').disabled = !S.online || !S.job || terminal(S.job) || S.cancelling.has(S.job.id) || !!S.busy;
    $('manual-stop-watch').hidden=!S.watchJob || !S.job || S.job.id!==S.watchJob;
    $('manual-result-open').disabled = !ready || !S.job || ['waiting_user', 'error'].indexOf(S.job.state) < 0;
    $('annotation-undo').disabled = !S.source || !S.undo.length || !!S.busy;
    $('annotation-redo').disabled = !S.source || !S.redo.length || !!S.busy;
    $('annotation-clear').disabled = !S.annotations.length || !!S.busy;
    $('aspect').disabled = !S.source || !!S.busy;
    ['prompt','prompt-template', 'preset', 'lighting', 'keep-design', 'keep-camera', 'crop-reset', 'annotation-color', 'annotation-size','crop-zoom','aspect-width','aspect-height','photo-style','context','custom-style','custom-context','custom-lighting','upload-max','upload-format','capture-width','capture-size-mode','hide-helpers','auto-recapture','camera-debounce'].forEach(function (id) { $(id).disabled = !!S.busy; });
    $('prompt-template').disabled=!!S.busy || !window.SiteCraftAIReferencePrompts;
    $('capture-size-mode').disabled=!S.captureLongEdge || !!S.busy; $('hide-helpers').disabled=!S.captureHelpers || !!S.busy;
    document.querySelectorAll('[data-tool], #region-list textarea, #region-list select, #region-list button, [data-extra], .reference-thumb select').forEach(function (element) { element.disabled = !!S.busy || !S.source; });
    document.querySelectorAll('.region-attach').forEach(function (element) { element.disabled=!!S.busy || S.refs.length>=4; });
    document.querySelectorAll('.queue-item').forEach(function (element) { element.disabled = !!S.busy; });
    var crop = S.sourceImage ? cropBox() : null;
    $('crop-x').disabled = !!S.busy || !crop || crop.width === S.sourceImage.naturalWidth;
    $('crop-y').disabled = !!S.busy || !crop || crop.height === S.sourceImage.naturalHeight;
    $('retry-submit').hidden = !S.pendingSubmission;
    $('retry-submit').disabled = !ready || !connected && !(S.pendingSubmission && S.pendingSubmission.options.manual_handoff);
    $('busy-message').textContent = S.busy || 'Nguồn và kết quả trong cùng cửa sổ';
    $('reference-count').textContent = S.refs.length + ' / 4';
    $('crop-zoom-value').textContent = Number($('crop-zoom').value).toFixed(2).replace(/0+$/, '').replace(/\.$/, '') + '×';
    $('jpeg-quality-value').textContent = $('jpeg-quality').value + '%';
    ['style','context','lighting'].forEach(function (group) { $('custom-'+group).hidden = (group === 'style' ? $('photo-style') : $(group)).value !== 'custom'; });
  }
  async function task(label, action) {
    if (S.busy || S.draft || S.pan) return;
    S.busy = label; sync();
    try { return await action(); }
    catch (error) { tell(error.message); }
    finally { S.busy = ''; sync(); }
  }
  async function imageFrom(dataURL) {
    return new Promise(function (resolve, reject) {
      var image = new Image();
      image.onload = function () {
        if (image.naturalWidth * image.naturalHeight > MAX_PIXELS) { reject(new Error('Ảnh quá lớn để chỉnh trong bảng này. Chọn ảnh dưới 20 triệu điểm ảnh.')); return; }
        resolve(image);
      };
      image.onerror = function () { reject(new Error('Không đọc được ảnh. Chọn PNG, JPEG hoặc WebP hợp lệ.')); };
      image.src = dataURL;
    });
  }
  async function asset(id, known) {
    if (!validId(id)) throw new Error('Mã ảnh không hợp lệ.');
    if (known && known.data_url) S.cache.set(id, known);
    if (!S.cache.has(id)) S.cache.set(id, await api('GET', 'assets/' + id));
    var value = S.cache.get(id);
    if (!value || !/^data:image\/(?:png|jpeg|webp);base64,/i.test(value.data_url || '')) { S.cache.delete(id); throw new Error('Bộ xử lý chưa trả dữ liệu ảnh hợp lệ.'); }
    S.cache.delete(id); S.cache.set(id, value);
    while (S.cache.size > 4) S.cache.delete(S.cache.keys().next().value);
    return value;
  }
  function readFile(file) {
    return new Promise(function (resolve, reject) {
      if (!file || file.size > MAX_FILE || (file.type && !/^image\/(?:png|jpeg|webp)$/.test(file.type))) { reject(new Error('Chọn ảnh PNG, JPEG hoặc WebP không quá 20 MB.')); return; }
      var reader = new FileReader(); reader.onload = function () { resolve(reader.result); }; reader.onerror = function () { reject(new Error('Không mở được tệp ảnh.')); }; reader.readAsDataURL(file);
    });
  }
  async function upload(dataURL, name, role) {
    if (typeof dataURL !== 'string' || dataURL.length > 60_000_000) throw new Error('Ảnh vượt giới hạn tải. Chọn khung cắt hoặc ảnh có kích thước nhỏ hơn.');
    var meta = await api('POST', 'assets', { data_url: dataURL, name: (name || 'Ảnh').slice(0, 120), role: role });
    return asset(meta.id);
  }
  async function setSource(value, label, kind) {
    var image = await imageFrom(value.data_url);
    S.source = value; S.sourceImage = image; S.sourceName = label || value.name || 'Ảnh nguồn'; S.sourceKind = kind;
    S.promptOperation='render'; S.restoredPrompt = false; S.restoredNotes=''; S.cleanSourceImage=null; S.bakedComparison=null;
    S.annotations = []; S.undo = []; S.redo = []; S.draft = null; S.prepared = null; S.preparedKey = '';
    $('aspect').value = 'original'; $('crop-zoom').value = '1'; $('crop-x').value = $('crop-y').value = '50';
    $('source-empty').hidden = true; $('annotation-canvas').hidden = false;
    if (kind !== 'capture' && $('camera-watch').checked) { $('camera-watch').checked = false; native('camera_watch', { enabled: false }).catch(function () {}); }
    renderRegions(); drawSource(); updatePrompt(); sync();
  }
  function capture(automatic) {
    return task('Đang chụp góc nhìn SketchUp…', async function () {
      if (S.annotations.length && !automatic && !window.confirm('Chụp lại sẽ thay ảnh nguồn và các nét đánh dấu hiện tại. Tiếp tục?')) return;
      var value = await native('capture',captureArgs());
      var captured = await asset(value.id, value); rememberCapture(captured);
      await setSource(captured, 'Góc nhìn SketchUp', 'capture');
    });
  }
  function captureArgs() { return {width:Number($('capture-width').value),size_mode:S.captureLongEdge?$('capture-size-mode').value:'width',hide_helpers:!!S.captureHelpers && $('hide-helpers').checked}; }
  function rememberCapture(value) { S.lastCapture = {id:value.id, camera_stamp:value.camera_stamp, model_context:value.model_context, name:'Góc nhìn SketchUp'}; savePrefs(); }
  async function recaptureForRender() {
    var captured = await native('capture',captureArgs()), value = await asset(captured.id,captured);
    var image = await imageFrom(value.data_url), unchanged = value.camera_stamp && S.source.camera_stamp && value.camera_stamp === S.source.camera_stamp;
    if (S.annotations.length && !unchanged && !window.confirm('Camera hoặc khung nhìn SketchUp đã đổi. Chụp góc hiện tại sẽ xóa các nét và ghi chú vùng cũ để tránh đặt sai vị trí. Tiếp tục?')) return false;
    if (!unchanged && S.annotations.length) { S.annotations=[]; S.undo=[]; S.redo=[]; renderRegions(); }
    S.source=value; S.sourceImage=image; S.sourceName='Góc nhìn SketchUp'; S.sourceKind='capture'; rememberCapture(value); drawSource(); updatePrompt(); return true;
  }
  function openSourceFile(file) {
    return task('Đang nhập ảnh nguồn…', async function () { await setSource(await upload(await readFile(file), file.name, 'source'), file.name, 'file'); });
  }
  async function addReferences(files) {
    return task('Đang nhập ảnh tham chiếu…', async function () {
      var available = 4 - S.refs.length, list = Array.from(files || []);
      for (var i = 0; i < Math.min(available, list.length); i++) {
        var value = await upload(await readFile(list[i]), list[i].name, 'reference');
        if (!S.refs.some(function (v) { return v.id === value.id; })) S.refs.push(await referenceValue(value));
      }
      renderReferences();
      if (list.length > available) tell('Chỉ dùng tối đa 4 ảnh tham chiếu cho một tác vụ.');
    });
  }
  async function referenceValue(value) {
    var image = await imageFrom(value.data_url), canvas = document.createElement('canvas');
    var scale = Math.min(1, 160 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    return { id: value.id, name: value.name, width: value.width, height: value.height, mime: value.mime, role:'general', thumbnail: canvas.toDataURL('image/png') };
  }
  function renderReferences() {
    $('reference-list').replaceChildren();
    S.refs.forEach(function (value) {
      var frame=document.createElement('div'), image=document.createElement('img'), remove=document.createElement('button'), role=document.createElement('select');
      frame.className='reference-thumb'; image.src=value.thumbnail || value.data_url; image.alt=value.name || 'Ảnh tham chiếu'; remove.textContent='×'; remove.title='Bỏ ảnh tham chiếu';
      var options=promptLibrary() ? promptLibrary().getOptions('referenceRoles') : [{id:'other',label:'Tham chiếu'}];
      options.forEach(function (item) { role.add(new Option(item.label,item.id)); }); role.value=value.role==='other'?'general':value.role || 'general'; role.setAttribute('aria-label','Vai trò '+(value.name || 'ảnh tham chiếu'));
      role.onchange=function () { value.role=role.value; S.restoredPrompt=false; updatePrompt(); };
      remove.onclick=function () { if (S.busy) return; S.refs=S.refs.filter(function (v) { return v.id!==value.id; }); S.annotations.forEach(function (item) { item.reference_ids=(item.reference_ids || []).filter(function (id) { return id!==value.id; }); }); renderReferences(); renderRegions(); updatePrompt(); };
      frame.append(image,remove,role); $('reference-list').append(frame);
    });
    updatePrompt(); sync();
  }
  function aspectValue() {
    if ($('aspect').value!=='custom') return $('aspect').value;
    var width=Math.round(Number($('aspect-width').value)), height=Math.round(Number($('aspect-height').value));
    if (!(width>=1&&width<=9999&&height>=1&&height<=9999&&width/height>=0.05&&width/height<=20)) return '16:9';
    return width+':'+height;
  }
  function cropBox() {
    if (!S.sourceImage) return null;
    var width=S.sourceImage.naturalWidth, height=S.sourceImage.naturalHeight, ratio=aspectValue(), w=width, h=height;
    if (ratio!=='original') { var parts=ratio.split(':').map(Number), target=parts[0]/parts[1]; if (width/height>target) w=height*target; else h=width/target; }
    var zoom=Math.max(1,Number($('crop-zoom').value)||1); w=Math.max(1,Math.round(w/zoom)); h=Math.max(1,Math.round(h/zoom));
    return {x:Math.round((width-w)*Number($('crop-x').value)/100),y:Math.round((height-h)*Number($('crop-y').value)/100),width:w,height:h};
  }
  function updateFrame() {
    clearTimeout(updateFrame.timer);
    if (!$('viewport-frame').checked || !S.frameSupported) return;
    updateFrame.timer=setTimeout(function () {
      var args={enabled:true,aspect:aspectValue()}, crop=cropBox();
      if (crop && ['capture','last_capture'].indexOf(S.sourceKind)>=0) args.crop={x:crop.x/S.sourceImage.naturalWidth,y:crop.y/S.sourceImage.naturalHeight,width:crop.width/S.sourceImage.naturalWidth,height:crop.height/S.sourceImage.naturalHeight};
      native('frame_overlay',args).catch(function (error) { $('viewport-frame').checked=false; tell(error.message); });
    },120);
  }
  function shapeBounds(item) {
    var xs = item.points.map(function (p) { return p.x * S.sourceImage.naturalWidth; });
    var ys = item.points.map(function (p) { return p.y * S.sourceImage.naturalHeight; });
    return { left: Math.min.apply(null, xs), right: Math.max.apply(null, xs), top: Math.min.apply(null, ys), bottom: Math.max.apply(null, ys) };
  }
  function stroke(context, item) {
    if (!item.points.length) return;
    var width = S.sourceImage.naturalWidth, height = S.sourceImage.naturalHeight;
    context.globalCompositeOperation = item.tool === 'eraser' ? 'destination-out' : 'source-over'; context.strokeStyle = item.color; context.fillStyle = item.color; context.lineWidth = item.width * Math.min(width, height); context.lineCap = context.lineJoin = 'round';
    var first = item.points[0], last = item.points[item.points.length - 1]; context.beginPath();
    if (item.tool === 'pen' || item.tool === 'eraser') {
      context.moveTo(first.x * width, first.y * height);
      item.points.slice(1).forEach(function (p) { context.lineTo(p.x * width, p.y * height); });
      if (item.points.length === 1) { context.arc(first.x * width, first.y * height, context.lineWidth / 2, 0, Math.PI * 2); context.fill(); }
    } else if (item.tool === 'rectangle') context.rect(Math.min(first.x, last.x) * width, Math.min(first.y, last.y) * height, Math.abs(first.x - last.x) * width, Math.abs(first.y - last.y) * height);
    else context.ellipse((first.x + last.x) * width / 2, (first.y + last.y) * height / 2, Math.abs(first.x - last.x) * width / 2, Math.abs(first.y - last.y) * height / 2, 0, 0, Math.PI * 2);
    context.stroke();
  }
  function paintSource(canvas, preview, clean) {
    var crop=cropBox(), scale=preview ? Math.min(1,1600/Math.max(crop.width,crop.height)) : 1;
    var width=Math.max(1,Math.round(crop.width*scale)), height=Math.max(1,Math.round(crop.height*scale));
    if (canvas.width!==width) canvas.width=width; if (canvas.height!==height) canvas.height=height;
    var context=canvas.getContext('2d'); context.clearRect(0,0,width,height); context.drawImage(clean && S.cleanSourceImage ? S.cleanSourceImage : S.sourceImage,crop.x,crop.y,crop.width,crop.height,0,0,width,height);
    if (!clean && (S.annotations.length || S.draft)) {
      var ink=S.inkCanvas || (S.inkCanvas=document.createElement('canvas')); if (ink.width!==width) ink.width=width; if (ink.height!==height) ink.height=height;
      var layer=ink.getContext('2d'); layer.clearRect(0,0,width,height); layer.save(); layer.scale(width/crop.width,height/crop.height); layer.translate(-crop.x,-crop.y);
      S.annotations.forEach(function (item) { stroke(layer,item); }); if (S.draft) stroke(layer,S.draft); layer.restore(); context.drawImage(ink,0,0);
    }
    return canvas;
  }
  function composeSource(clean) { return paintSource(document.createElement('canvas'),false,clean); }
  function fitSource() {
    if (!S.sourceImage) return;
    var crop = cropBox(), stage = $('source-stage'), scale = Math.min((stage.clientWidth - 12) / crop.width, (stage.clientHeight - 12) / crop.height);
    $('annotation-canvas').style.width = Math.max(1, Math.floor(crop.width * scale)) + 'px'; $('annotation-canvas').style.height = Math.max(1, Math.floor(crop.height * scale)) + 'px';
  }
  function drawSource() {
    if (!S.sourceImage) return;
    paintSource($('annotation-canvas'), true);
    var crop = cropBox(); $('source-info').textContent = S.sourceName + ' · ' + crop.width + ' × ' + crop.height;
    $('crop-x').disabled = crop.width === S.sourceImage.naturalWidth; $('crop-y').disabled = crop.height === S.sourceImage.naturalHeight;
    S.prepared = null; S.preparedKey = ''; fitSource(); sync(); updateFrame();
  }
  function sourcePoint(event) {
    var rect = $('annotation-canvas').getBoundingClientRect(), crop = cropBox();
    return { x: Math.max(0, Math.min(1, (crop.x + (event.clientX - rect.left) / rect.width * crop.width) / S.sourceImage.naturalWidth)),
      y: Math.max(0, Math.min(1, (crop.y + (event.clientY - rect.top) / rect.height * crop.height) / S.sourceImage.naturalHeight)) };
  }
  function remember() { S.undo.push(JSON.parse(JSON.stringify(S.annotations))); if (S.undo.length > 40) S.undo.shift(); S.redo = []; }
  function renderRegions() {
    $('region-list').replaceChildren();
    regionItems().forEach(function (item,index) {
      var row=document.createElement('div'), number=document.createElement('span'), note=document.createElement('textarea'), remove=document.createElement('button'), controls=document.createElement('div'), choice=document.createElement('select'), attach=document.createElement('button'), file=document.createElement('input');
      row.className='region-note'; number.textContent=String(index+1); number.style.color=item.color; note.value=item.note; note.maxLength=200; note.placeholder='Yêu cầu cho vùng '+(index+1); note.setAttribute('aria-label','Ghi chú vùng '+(index+1)); note.oninput=function () { item.note=note.value; updatePrompt(); };
      remove.textContent='×'; remove.title='Xóa vùng '+(index+1); remove.onclick=function () { if (S.busy) return; remember(); S.annotations=S.annotations.filter(function (v) { return v!==item; }); renderRegions(); drawSource(); updatePrompt(); };
      choice.add(new Option('Chưa gắn ảnh vùng','')); S.refs.forEach(function (ref,i) { choice.add(new Option('Ảnh '+(i+1)+' · '+(ref.name || roleLabel(ref.role)),ref.id)); }); choice.value=(item.reference_ids || [])[0] || ''; choice.setAttribute('aria-label','Ảnh tham chiếu vùng '+(index+1));
      choice.onchange=function () { item.reference_ids=choice.value?[choice.value]:[]; updatePrompt(); };
      attach.textContent='+ Ảnh vùng'; attach.className='region-attach'; attach.disabled=S.refs.length>=4; attach.title='Tối đa 4 ảnh chung cho cả tác vụ'; file.type='file'; file.accept='image/png,image/jpeg,image/webp'; file.hidden=true;
      attach.onclick=function () { file.click(); }; file.onchange=function () { var selected=file.files[0]; file.value=''; if (!selected) return; task('Đang thêm ảnh cho vùng…',async function () { if (S.refs.length>=4) throw new Error('Đã đủ 4 ảnh tham chiếu. Bỏ một ảnh trước khi thêm.'); var value=await referenceValue(await upload(await readFile(selected),selected.name,'reference')); value.role='material'; S.refs.push(value); item.reference_ids=[value.id]; S.restoredPrompt=false; renderReferences(); renderRegions(); updatePrompt(); }); };
      var quick=document.createElement('select'); quick.className='region-quick'; quick.setAttribute('aria-label','Câu mẫu vùng '+(index+1)); quick.add(new Option('Câu mẫu cho vùng…','')); if (promptLibrary()) promptLibrary().getOptions('regionQuickActions').forEach(function (action) { quick.add(new Option(action.label,action.id)); }); quick.onchange=function () { var action=promptLibrary().getOptions('regionQuickActions').find(function (value) { return value.id===quick.value; }); if (action) { item.note=action.prompt; note.value=item.note; updatePrompt(); } quick.value=''; };
      controls.className='region-reference'; controls.append(choice,attach,file,quick); row.append(number,note,remove,controls); $('region-list').append(row);
    }); sync();
  }
  $('annotation-canvas').onpointerdown=function (event) {
    if (!S.source || S.busy) return;
    if (S.tool==='none') { var crop=cropBox(); S.pan={x:event.clientX,y:event.clientY,crop:crop,rect:$('annotation-canvas').getBoundingClientRect()}; $('annotation-canvas').setPointerCapture(event.pointerId); event.preventDefault(); sync(); return; }
    if (S.tool!=='eraser' && regionItems().length>=MAX_REGIONS) { tell('Dùng tối đa 12 vùng đánh dấu cho một lần gửi.'); return; }
    if (S.tool==='eraser' && S.annotations.filter(function (item) { return item.tool==='eraser'; }).length>=50) { tell('Đã đủ 50 nét tẩy. Hoàn tác hoặc xóa nét trước khi tiếp tục.'); return; }
    event.preventDefault(); S.draft={tool:S.tool,color:$('annotation-color').value,width:Number($('annotation-size').value)/Math.min(S.sourceImage.naturalWidth,S.sourceImage.naturalHeight),points:[sourcePoint(event)],note:'',reference_ids:[]}; $('annotation-canvas').setPointerCapture(event.pointerId); drawSource();
  };
  $('annotation-canvas').onpointermove=function (event) {
    if (S.pan) {
      var pan=S.pan, maxX=S.sourceImage.naturalWidth-pan.crop.width, maxY=S.sourceImage.naturalHeight-pan.crop.height;
      if (maxX>0) $('crop-x').value=Math.max(0,Math.min(100,(pan.crop.x-(event.clientX-pan.x)/pan.rect.width*pan.crop.width)/maxX*100));
      if (maxY>0) $('crop-y').value=Math.max(0,Math.min(100,(pan.crop.y-(event.clientY-pan.y)/pan.rect.height*pan.crop.height)/maxY*100)); drawSource(); return;
    }
    if (!S.draft) return; var point=sourcePoint(event);
    if (S.draft.tool==='pen' || S.draft.tool==='eraser') { if (S.draft.points.length<1500) S.draft.points.push(point); } else S.draft.points[1]=point; drawSource();
  };
  $('annotation-canvas').addEventListener('wheel',function (event) { if (!S.source || S.busy || S.tool!=='none') return; event.preventDefault(); $('crop-zoom').value=Math.max(1,Math.min(4,Number($('crop-zoom').value)*(event.deltaY<0?1.1:1/1.1))); drawSource(); updatePrompt(); },{passive:false});
  function finishStroke(event) {
    if (S.pan) { S.pan=null; if (event && $('annotation-canvas').hasPointerCapture(event.pointerId)) $('annotation-canvas').releasePointerCapture(event.pointerId); updatePrompt(); return; }
    if (!S.draft) return;
    var item = S.draft; S.draft = null;
    if (item.tool === 'pen' || item.tool === 'eraser' || item.points.length > 1) { remember(); S.annotations.push(item); }
    if (event && $('annotation-canvas').hasPointerCapture(event.pointerId)) $('annotation-canvas').releasePointerCapture(event.pointerId);
    renderRegions(); drawSource(); updatePrompt();
  }
  $('annotation-canvas').onpointerup = finishStroke; $('annotation-canvas').onpointercancel = finishStroke;
  document.querySelectorAll('[data-tool]').forEach(function (element) {
    element.onclick = function () { S.tool = element.dataset.tool; document.querySelectorAll('[data-tool]').forEach(function (b) { b.classList.toggle('selected', b === element); }); $('annotation-canvas').style.cursor = S.tool === 'none' ? 'grab' : 'crosshair'; };
  });
  button('annotation-undo', function () { if (!S.undo.length || S.busy) return; S.redo.push(S.annotations); S.annotations = S.undo.pop(); renderRegions(); drawSource(); updatePrompt(); });
  button('annotation-redo', function () { if (!S.redo.length || S.busy) return; S.undo.push(S.annotations); S.annotations = S.redo.pop(); renderRegions(); drawSource(); updatePrompt(); });
  button('annotation-clear', function () { if (!S.annotations.length || S.busy) return; remember(); S.annotations = []; renderRegions(); drawSource(); updatePrompt(); });

  function uploadSettings() { return {max:Number($('upload-max').value)||0,format:$('upload-format').value,quality:Number($('jpeg-quality').value)/100}; }
  function resizedCanvas(canvas, max) {
    if (!max || Math.max(canvas.width,canvas.height)<=max) return canvas;
    var scale=max/Math.max(canvas.width,canvas.height), output=document.createElement('canvas'); output.width=Math.max(1,Math.round(canvas.width*scale)); output.height=Math.max(1,Math.round(canvas.height*scale)); output.getContext('2d').drawImage(canvas,0,0,output.width,output.height); return output;
  }
  function canvasData(canvas, settings) {
    if (settings.format!=='jpeg') return canvas.toDataURL('image/png');
    var white=document.createElement('canvas'); white.width=canvas.width; white.height=canvas.height; var context=white.getContext('2d'); context.fillStyle='#fff'; context.fillRect(0,0,white.width,white.height); context.drawImage(canvas,0,0); return white.toDataURL('image/jpeg',settings.quality);
  }
  async function preparedSource() {
    if (!S.source) throw new Error('Chụp hoặc mở ảnh nguồn trước.');
    var crop=cropBox(), settings=uploadSettings(), changed=S.annotations.length || crop.x || crop.y || crop.width!==S.sourceImage.naturalWidth || crop.height!==S.sourceImage.naturalHeight;
    var convert=settings.format!=='original' || settings.max && Math.max(crop.width,crop.height)>settings.max;
    var key=JSON.stringify([S.source.id,crop,S.annotations,settings]); if (S.prepared && S.preparedKey===key) return S.prepared;
    var value=S.source, clean;
    if (changed || convert) value=await upload(canvasData(resizedCanvas(composeSource(false),settings.max),settings),'SiteCraft_nguon_gui.'+(settings.format==='jpeg'?'jpg':'png'),regionItems().length?'annotation':'source');
    if (!changed && !convert && S.bakedComparison) clean=S.bakedComparison;
    else if (!changed && !convert && S.source.mime==='image/png') clean=S.source;
    else clean=await upload(resizedCanvas(composeSource(true),settings.max).toDataURL('image/png'),'SiteCraft_nguon_sach.png','source');
    S.preparedKey=key; S.prepared=value; S.preparedCompare=clean; if (S.inkCanvas) { S.inkCanvas.width=1; S.inkCanvas.height=1; } return value;
  }
  async function preparedReferences() {
    var settings=uploadSettings(), ids=[];
    for (var ref of S.refs) {
      if (settings.format==='original' && (!settings.max || Math.max(ref.width,ref.height)<=settings.max)) { ids.push(ref.id); continue; }
      var key=JSON.stringify([ref.id,settings]), cached=S.refPrepared.get(key);
      if (cached) { ids.push(cached); continue; }
      var value=await asset(ref.id), image=await imageFrom(value.data_url), canvas=document.createElement('canvas'); canvas.width=image.naturalWidth; canvas.height=image.naturalHeight; canvas.getContext('2d').drawImage(image,0,0);
      var prepared=await upload(canvasData(resizedCanvas(canvas,settings.max),settings),ref.name || 'Tham chiếu','reference'); S.refPrepared.set(key,prepared.id); while (S.refPrepared.size>12) S.refPrepared.delete(S.refPrepared.keys().next().value); ids.push(prepared.id);
    } return ids;
  }
  function clearResult() {
    S.downloadCandidate=null; $('download-candidate').hidden=true; $('download-candidate-image').removeAttribute('src');
    S.resultLoad++; S.resultPending = ''; S.result = null; S.compareSource = null; S.compare = false; $('result-image').hidden = true; $('result-empty').hidden = false;
    ['result-image', 'compare-after', 'compare-before'].forEach(function (id) { $(id).removeAttribute('src'); });
    $('compare-view').hidden = $('compare-control').hidden = true; $('result-index').textContent = '—'; $('result-info').textContent = 'Chưa có kết quả'; sync();
  }
  function updateCompare() {
    var enabled = S.compare && S.result && (S.customCompare || S.compareSource);
    $('compare-view').hidden = $('compare-control').hidden = !enabled; $('result-image').hidden = !!enabled || !S.result;
    $('compare-toggle').classList.toggle('selected', !!enabled);
    if (enabled) {
      $('compare-after').src = S.result.data_url; $('compare-before').src = (S.customCompare || S.compareSource).data_url; $('compare-source-label').textContent = S.customCompare ? S.customCompare.name || 'Ảnh bạn chọn' : 'Nguồn sạch';
      var position = Number($('compare-range').value); $('compare-before-clip').style.clipPath = 'inset(0 ' + (100 - position) + '% 0 0)'; $('compare-line').style.left = position + '%';
    }
  }
  async function showResult(job, index, selection) {
    var ids = job.result_ids || [];
    if (!ids.length) { clearResult(); return; }
    index = Math.max(0, Math.min(ids.length - 1, index));
    var key = [selection, job.id, ids[index], job.comparison_source_id || job.source_id].join(':');
    if (S.resultPending === key) return;
    if (S.result && S.result.id === ids[index] && S.compareSource && S.compareSource.id === (job.comparison_source_id || job.source_id)) {
      S.resultLoad++; S.resultPending = ''; S.resultIndex = index; sync(); return;
    }
    var revision = ++S.resultLoad; S.resultPending = key; S.resultIndex = index; sync();
    var value, before;
    try { value = await asset(ids[index]); before = (job.comparison_source_id || job.source_id) ? await asset(job.comparison_source_id || job.source_id) : null; }
    finally { if (S.resultPending === key) S.resultPending = ''; }
    if (revision !== S.resultLoad || selection !== S.selection || !S.job || S.job.id !== job.id || S.cancelled.has(job.id) || S.cancelling.has(job.id)) return;
    S.result = value; S.compareSource = before; S.resultIndex = index;
    $('result-image').src = value.data_url; $('result-image').hidden = false; $('result-empty').hidden = true;
    $('result-index').textContent = (index + 1) + ' / ' + ids.length;
    $('result-info').textContent = value.width + ' × ' + value.height + ' · ' + (value.mime || '').replace('image/', '').toUpperCase() + (job.manual_import ? ' · Bạn nhập thủ công' : '');
    $('result-title').textContent = job.operation === 'upscale' ? 'Kết quả tải Flow 2K' : 'Ảnh từ Flow'; updateCompare(); sync();
  }
  function mergeJobs(jobs) {
    var map = new Map(S.jobs.map(function (job) { return [job.id, job]; }));
    (jobs || []).forEach(function (job) {
      if (!validId(job.id)) return;
      if (S.cancelled.has(job.id)) job = Object.assign({}, job, { state: 'cancelled', result_ids: [], message: 'Đã hủy tác vụ AI.' });
      map.set(job.id, job);
    });
    S.jobs = Array.from(map.values()).sort(function (a, b) { return Number(b.created || 0) - Number(a.created || 0); });
    renderQueue();
  }
  function renderQueue() {
    $('queue-list').replaceChildren();
    S.jobs.filter(function (job) { return !terminal(job) || S.job && job.id === S.job.id; }).slice(0, 8).forEach(function (job) {
      var item = document.createElement('button'), title = document.createElement('span'), state = document.createElement('span');
      item.className = 'queue-item' + (S.job && job.id === S.job.id ? ' selected' : ''); title.textContent = operationNames[job.operation] || 'Tác vụ';
      state.textContent = labels[job.state] || job.state; item.append(title, state); item.disabled = !!S.busy; item.onclick = function () { if (!S.busy) loadJob(job.id, false).catch(function (error) { tell(error.message); }); }; $('queue-list').append(item);
    });
  }
  function renderJob() {
    var job = S.job;
    $('job-state').textContent = job && S.cancelling.has(job.id) ? 'Đang yêu cầu hủy…' : job ? labels[job.state] || job.state : 'Chưa có tác vụ';
    $('job-state').className = 'state-chip ' + (job ? job.state : '');
    $('job-message').textContent = job ? job.message || labels[job.state] || '' : 'Ảnh chỉ được gửi khi bạn bấm Tạo ảnh, Chỉnh nguồn hoặc Flow 2K.';
    $('job-progress').hidden = !job || terminal(job);
    if (job && typeof job.progress === 'number' && isFinite(job.progress) && job.progress >= 0 && job.progress <= 100) $('job-progress').value = job.progress;
    else $('job-progress').removeAttribute('value');
    $('manual-fallback').hidden = !job || ['waiting_user', 'error'].indexOf(job.state) < 0 || S.cancelled.has(job.id) || S.cancelling.has(job.id);
    $('manual-message').textContent = job && job.message ? job.message + ' Hoàn tất trong Flow, tải đúng ảnh kết quả rồi nhập lại.' : 'Hoàn tất thao tác trong Flow rồi nhập đúng ảnh kết quả.';
    if (job && S.watchStatusJob===job.id && S.watchMessage) $('manual-message').textContent+=' '+S.watchMessage;
    renderQueue(); sync();
  }
  async function loadJob(id, restore, refreshing) {
    if (!validId(id)) return;
    var selection = refreshing ? S.selection : ++S.selection, job = await api('GET', 'jobs/' + id);
    if (selection !== S.selection || (refreshing && (!S.job || S.job.id !== id))) return;
    if (S.cancelled.has(id)) job = Object.assign({}, job, { state: 'cancelled', result_ids: [], message: 'Đã hủy tác vụ AI.' });
    else if (S.cancelling.has(id)) job = Object.assign({}, job, { message: 'Đang yêu cầu hủy tác vụ AI…' });
    var previous = S.job; S.job = job;
    if (!previous || previous.id !== job.id) clearResult();
    mergeJobs([job]); renderJob();
    if (restore) await restoreJob(job);
    if (selection === S.selection && job.state === 'complete' && (job.result_ids || []).length) await showResult(job, Math.min(S.resultIndex, job.result_ids.length - 1), selection);
  }
  function editorSnapshot() {
    var fields={}; ['prompt','preset','lighting','photo-style','context','custom-style','custom-context','custom-lighting','aspect','aspect-width','aspect-height'].forEach(function (id) { fields[id]=$(id).value; });
    return {fields:fields,keep_design:$('keep-design').checked,keep_camera:$('keep-camera').checked,extras:Array.from(document.querySelectorAll('[data-extra]:checked')).map(function (input) { return input.dataset.extra; }),roles:S.refs.map(function (ref) { return ref.role || 'general'; })};
  }
  async function restoreJob(job) {
    if (!job || !job.source_id) return;
    await setSource(await asset(job.source_id),'Nguồn của tác vụ đã lưu','history');
    S.restoredNotes=job.annotation_notes || '';
    if (job.comparison_source_id && job.comparison_source_id!==job.source_id) { S.bakedComparison=await asset(job.comparison_source_id); S.cleanSourceImage=await imageFrom(S.bakedComparison.data_url); }
    S.promptOperation=job.operation || 'render';
    var saved=prefs.jobEditors && prefs.jobEditors[job.id];
    $('prompt').value=job.prompt || ''; $('preset').value=window.SiteCraftAIReferencePrompts?'auto':'custom'; $('lighting').value='original'; $('photo-style').value='original'; $('context').value='original'; S.restoredPrompt=!!(job.options || {}).prompt_is_complete;
    document.querySelectorAll('[data-extra]').forEach(function (input) { input.checked=false; });
    $('keep-design').checked=(job.options || {}).keep_design!==false; $('keep-camera').checked=(job.options || {}).keep_camera!==false;
    if (saved && saved.fields) { Object.keys(saved.fields).forEach(function (id) { if ($(id)) $(id).value=saved.fields[id]; }); $('keep-design').checked=saved.keep_design!==false; $('keep-camera').checked=saved.keep_camera!==false; document.querySelectorAll('[data-extra]').forEach(function (input) { input.checked=(saved.extras || []).indexOf(input.dataset.extra)>=0; }); S.restoredPrompt=false; }
    // The job source is already cropped. Matching its ratio does not repeat zoom or offset.
    $('crop-zoom').value='1'; $('crop-x').value=$('crop-y').value='50'; S.refs=[];
    for (var id of (job.reference_ids || []).slice(0,4)) { var ref=await referenceValue(await asset(id)); if (saved && saved.roles && saved.roles[S.refs.length]) ref.role=saved.roles[S.refs.length]; S.refs.push(ref); }
    renderReferences(); drawSource(); updatePrompt(); closeDrawers();
  }
  function connectionStatus() {
    var connected = S.online && S.bridge.paired && S.bridge.connected;
    $('connection').classList.toggle('connected', !!connected);
    $('connection-label').textContent = !S.online ? 'Chưa nối bộ xử lý' : connected ? 'Chrome đã nối' : S.bridge.paired ? 'Chờ Chrome / Flow' : 'Chưa ghép Chrome';
    $('bridge-help').classList.toggle('ready', !!connected);
    $('bridge-help-title').textContent = connected ? 'Sẵn sàng gửi sang Flow' : S.online ? 'Kết nối Google Flow' : 'Chưa kết nối SiteCraft';
    $('bridge-help-text').textContent = !nativeAvailable ? 'Mở Render AI từ menu hoặc nút SiteCraft trong SketchUp; trình duyệt riêng không giả lập kết quả.' :
      !S.managed ? 'Render AI hiện dùng bộ xử lý cục bộ. Chọn chế độ chạy trên máy trong SiteCraft rồi mở lại bảng này.' :
      !S.online ? 'Bộ xử lý đang khởi động hoặc chưa phản hồi. Bảng sẽ kiểm tra lại kết nối.' :
      !S.bridge.paired ? 'Ghép tiện ích SiteCraft Flow Bridge, mở Flow và đăng nhập Google trong Chrome.' :
      !S.bridge.connected ? 'Mở tiện ích Chrome, chọn đúng tab / dự án Flow và bấm kết nối.' : 'Tác vụ sẽ chạy trên phiên Flow bạn đã chọn trong Chrome.';
    $('connect-shortcut').hidden = connected || !nativeAvailable;
    $('settings-connection').textContent = $('connection-label').textContent + (S.bridge.port ? ' · Cổng ' + S.bridge.port : '');
    $('unpair').disabled = !S.online || !S.bridge.paired; $('pair').disabled = !S.online || !!S.busy;
    sync();
  }
  async function refreshStatus() {
    if (S.polling || !nativeAvailable) return;
    S.polling = true;
    try {
      var config = await native('config'); S.managed = config.managed !== false;
      S.frameSupported=!!config.supports_frame; S.captureLongEdge=!!config.capture_long_edge; S.captureHelpers=!!config.capture_helpers;
      $('panel-version').textContent = 'SiteCraft ' + (config.version || '') + ' · Render AI beta';
      if (!S.managed) { S.online = false; return; }
      var info = await api('GET', 'status');
      if (info.protocol !== 1) throw new Error('Phiên bản cầu nối chưa tương thích. Cập nhật bộ cài SiteCraft và tiện ích Chrome cùng nhau.');
      S.online = true; S.bridge = info.bridge || {}; mergeJobs(info.jobs || []);
      if (!S.initialCaptureDone && !S.source && !S.busy) { S.initialCaptureDone=true; await capture(true); }
      if (S.job) {
        var selectedId = S.job.id;
        try { await loadJob(selectedId, false, true); }
        catch (error) {
          if (error.status !== 404) throw error;
          S.jobs = S.jobs.filter(function (job) { return job.id !== selectedId; });
          if (S.job && S.job.id === selectedId) { S.job = null; S.selection++; clearResult(); renderJob(); }
          tell('Tác vụ đã được xóa khỏi lịch sử trên máy. Bạn có thể tiếp tục với ảnh nguồn hiện tại.');
        }
      }
      if (S.watchJob) { try { var watch=await native('downloads_status'); S.watchMessage=watch.message || ''; S.watchStatusJob=S.watchJob; if (!watch.watching) S.watchJob=null; renderJob(); } catch (watchError) { S.watchMessage=watchError.message; } }
      if (!$('history-drawer').hidden) renderHistory();
    } catch (error) {
      S.online = false;
      if (!S.busy) $('busy-message').textContent = error.message;
    } finally {
      S.polling = false; connectionStatus(); clearTimeout(S.timer); S.timer = setTimeout(refreshStatus, S.online ? 2500 : 4000);
    }
  }
  function submit(operation, manual) {
    return task('Đang chuẩn bị ảnh gửi…', async function () {
      if (S.pendingSubmission) throw new Error('Có yêu cầu chưa xác nhận. Kiểm tra lại yêu cầu đó với cùng mã trước khi tạo một tác vụ khác.');
      if (!S.online || !manual && (!S.bridge.paired || !S.bridge.connected)) throw new Error('Ghép và kết nối tiện ích Chrome với đúng tab Flow trước khi gửi.');
      if ($('aspect').value==='custom') { var aw=Number($('aspect-width').value), ah=Number($('aspect-height').value); if (!Number.isInteger(aw)||!Number.isInteger(ah)||aw<1||ah<1||aw>9999||ah>9999||aw/ah<0.05||aw/ah>20) throw new Error('Tỷ lệ W:H cần số nguyên1–9999 và nằm trong1:20 đến20:1.'); }
      var active=S.jobs.filter(function (job) { return ['queued','claimed','running'].indexOf(job.state)>=0; });
      if (active.length && !$('allow-queue').checked) { var choice=await chooseActive(); if (choice==='dismiss') return; if (choice==='replace') for (var old of active) { var cancelled=await api('DELETE','jobs/'+old.id); if (cancelled.job) { mergeJobs([cancelled.job]); if (cancelled.job.state==='cancelled') S.cancelled.add(old.id); } } }
      if (operation==='render' && $('auto-recapture').checked && ['capture','last_capture'].indexOf(S.sourceKind)>=0 && !await recaptureForRender()) return;
      S.promptOperation=operation; updatePrompt();
      var source = operation === 'upscale' && S.result ? S.result : await preparedSource();
      var prompt = operation === 'upscale' ? '' : fullPrompt(), notes = operation === 'upscale' ? '' : annotationNotes();
      if (!prompt.trim() && operation !== 'upscale') throw new Error('Nhập mô tả hoặc chọn một kiểu ảnh trước khi gửi.');
      if (prompt.length > 8000 || notes.length > 4000) throw new Error('Nội dung quá dài. Rút gọn mô tả hoặc ghi chú vùng trước khi gửi.');
      var body = { client_request_id: requestId(), operation: operation, source_id: source.id, comparison_source_id: operation==='upscale' ? source.id : S.preparedCompare.id, reference_ids: operation === 'upscale' ? [] : await preparedReferences(),
        prompt: prompt, options: { keep_design: $('keep-design').checked, keep_camera: $('keep-camera').checked, aspect: aspectValue(), preset: $('preset').value, prompt_is_complete:true, manual_handoff:!!manual }, annotation_notes: notes };
      S.editorDrafts.set(body.client_request_id,editorSnapshot()); while (S.editorDrafts.size>80) S.editorDrafts.delete(S.editorDrafts.keys().next().value);
      S.pendingSubmission = body;
      await sendSubmission(body);
    });
  }
  async function sendSubmission(body) {
    var summary;
    try {
      summary = await api('POST', 'jobs', body);
    } catch (error) {
      if (error.status >= 400 && error.status < 500) S.pendingSubmission = null;
      else error.message = 'Chưa xác nhận được yêu cầu đã được nhận hay chưa. Không tự tạo lại ảnh; dùng “Kiểm tra lại yêu cầu vừa gửi” với cùng mã. ' + error.message;
      throw error;
    } finally { sync(); }
    S.pendingSubmission = null;
    if (S.editorDrafts.has(body.client_request_id)) { prefs.jobEditors=prefs.jobEditors || {}; prefs.jobEditors[summary.id]=S.editorDrafts.get(body.client_request_id); var savedIds=Object.keys(prefs.jobEditors); while (savedIds.length>80) delete prefs.jobEditors[savedIds.shift()]; savePrefs(); }
    S.job = Object.assign({}, body, summary); S.resultIndex = 0; clearResult(); mergeJobs([S.job]); renderJob();
    // An acknowledged job remains acknowledged even if fetching its details fails.
    await loadJob(summary.id, false);
  }

  function chooseActive() { return new Promise(function (resolve) { $('active-job-dialog').hidden=false; chooseActive.resolve=function (value) { $('active-job-dialog').hidden=true; chooseActive.resolve=null; resolve(value); }; $('replace-active').focus(); }); }
  function closeDrawers() { $('history-drawer').hidden = $('settings-drawer').hidden = $('drawer-backdrop').hidden = true; }
  function openDrawer(id) { closeDrawers(); $(id).hidden = false; $('drawer-backdrop').hidden = false; }
  function formatDate(value) {
    var date = new Date(typeof value === 'number' ? value * 1000 : value);
    return isNaN(date.getTime()) ? '' : date.toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
  function drainThumbnails() {
    while (thumbnailActive<3 && thumbnailQueue.length) {
      var next=thumbnailQueue.shift(); thumbnailActive++;
      (function (request) { api('GET','assets/'+request.id+'/thumbnail').then(function (value) {
        if (!value || !/^data:image\/(?:png|jpeg|webp);base64,/i.test(value.data_url || '')) throw new Error('Ảnh thu nhỏ chưa sẵn sàng.');
        thumbnailCache.set(request.id,value.data_url); while (thumbnailCache.size>80) thumbnailCache.delete(thumbnailCache.keys().next().value);
        if (request.generation===thumbnailGeneration && request.image.isConnected) { request.image.src=value.data_url; request.image.alt='Ảnh thu nhỏ của tác vụ'; }
      }).catch(function () { if (request.image.isConnected) request.image.alt='Không còn ảnh thu nhỏ'; }).finally(function () { thumbnailActive--; drainThumbnails(); }); })(next);
    }
  }
  function queueThumbnail(image,id,generation) {
    if (thumbnailCache.has(id)) { image.src=thumbnailCache.get(id); return; }
    thumbnailQueue.push({image:image,id:id,generation:generation}); drainThumbnails();
  }
  function renderHistory() {
    var signature=JSON.stringify([S.jobs.map(function (job) { return [job.id,job.state,job.updated,job.message,job.result_ids]; }),$('history-size').value,$('history-fit').value]);
    if (renderHistory.signature===signature && $('history-list').childElementCount) return; renderHistory.signature=signature;
    thumbnailGeneration++; var generation=thumbnailGeneration; thumbnailQueue=[]; if (thumbnailObserver) thumbnailObserver.disconnect();
    if (window.IntersectionObserver) thumbnailObserver=new IntersectionObserver(function (entries) { entries.forEach(function (entry) { if (entry.isIntersecting) { thumbnailObserver.unobserve(entry.target); queueThumbnail(entry.target,entry.target.dataset.assetId,generation); } }); },{root:$('history-drawer'),rootMargin:'120px'});
    $('history-list').replaceChildren(); $('history-list').style.setProperty('--thumb-size',$('history-size').value+'px'); $('history-list').style.setProperty('--thumb-fit',$('history-fit').value);
    if (!S.jobs.length) { var empty=document.createElement('p'); empty.className='history-empty'; empty.textContent='Chưa có tác vụ đã lưu. Lịch sử trên máy sẽ xuất hiện ở đây sau khi bạn gửi ảnh.'; $('history-list').append(empty); return; }
    S.jobs.slice(0,80).forEach(function (job) {
      var card=document.createElement('article'), heading=document.createElement('div'), title=document.createElement('strong'), date=document.createElement('span'), message=document.createElement('p'), actions=document.createElement('div');
      card.className='history-card'; card.dataset.jobId=job.id; heading.className='history-card-header'; title.textContent=(operationNames[job.operation] || 'Tác vụ')+' · '+(labels[job.state] || job.state); date.textContent=formatDate(job.created); heading.append(title,date); message.textContent=job.message || ''; actions.className='history-actions';
      var image=document.createElement('img'), imageId=(job.result_ids || [])[0] || job.comparison_source_id || job.source_id; image.className='history-thumbnail'; image.alt='Đang tải ảnh thu nhỏ'; image.onload=function () { image.style.opacity='1'; }; image.style.opacity='0'; if (validId(imageId)) { image.dataset.assetId=imageId; if (thumbnailCache.has(imageId)) image.src=thumbnailCache.get(imageId); else if (thumbnailObserver) thumbnailObserver.observe(image); else queueThumbnail(image,imageId,generation); }
      var view=document.createElement('button'); view.textContent='Xem'; view.onclick=function () { task('Đang mở tác vụ…',async function () { closeDrawers(); await loadJob(job.id,false); }); }; image.onclick=view.onclick;
      var reuse=document.createElement('button'); reuse.textContent='Dùng thiết lập'; reuse.onclick=function () { task('Đang lấy lại thiết lập…',async function () { await loadJob(job.id,true); }); };
      var remove=document.createElement('button'); remove.textContent='Xóa lịch sử'; remove.disabled=!terminal(job); remove.onclick=function () { task('Đang xóa lịch sử…',async function () { if (!window.confirm('Xóa tác vụ và ảnh chỉ thuộc lịch sử này trên máy? Tệp bạn đã lưu ra ngoài không bị xóa.')) return; await api('DELETE','history/'+job.id); S.jobs=S.jobs.filter(function (v) { return v.id!==job.id; }); if (S.job && S.job.id===job.id) { S.job=null; S.selection++; clearResult(); renderJob(); } renderHistory(); }); };
      actions.append(view,reuse,remove); card.append(image,heading,message,actions); $('history-list').append(card);
    });
  }
  async function historyRefresh() { var info = await api('GET', 'jobs'); S.jobs = []; mergeJobs(info.jobs || []); renderHistory(); }
  async function copyText(value) {
    try { if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(value); return; } } catch (_error) {}
    var area = document.createElement('textarea'); area.value = value; document.body.append(area); area.select();
    var copied = document.execCommand('copy'); area.remove(); if (!copied) throw new Error('Không sao chép được. Chọn nội dung rồi nhấn Ctrl+C.');
  }
  ['replace-active','queue-new','dismiss-job-choice'].forEach(function (id,index) { button(id,function () { if (chooseActive.resolve) chooseActive.resolve(['replace','queue','dismiss'][index]); }); });
  button('manual-handoff',function () { return submit('render',true); });
  button('capture', function () { return capture(false); });
  button('return-capture',function () { return task('Đang lấy ảnh SketchUp đã chụp…',async function () { if (!S.lastCapture) return; var value=await asset(S.lastCapture.id); value.camera_stamp=S.lastCapture.camera_stamp; value.model_context=S.lastCapture.model_context; await setSource(value,'Ảnh SketchUp đã chụp','last_capture'); }); });
  button('open-result',function () { if (S.result) return native('open_image',{asset_id:S.result.id}); });
  button('cleanup-open',function () { return native('open_cleanup'); });
  button('compare-file-open',function () { $('compare-file').click(); });
  $('compare-file').onchange=function () { var file=$('compare-file').files[0]; $('compare-file').value=''; if (!file) return; task('Đang mở ảnh so sánh…',async function () { S.customCompare=await upload(await readFile(file),file.name,'reference'); S.compare=true; updateCompare(); sync(); }); };
  button('compare-reset',function () { S.customCompare=null; updateCompare(); sync(); });
  $('viewport-frame').onchange=async function () { try { if ($('viewport-frame').checked) updateFrame(); else await native('frame_overlay',{enabled:false,aspect:aspectValue()}); } catch (error) { $('viewport-frame').checked=false; tell(error.message); } };
  button('upload-source', function () { $('source-file').click(); });
  $('source-file').onchange = function () { var file = $('source-file').files[0]; $('source-file').value = ''; if (file) openSourceFile(file); };
  button('add-reference', function () { $('reference-file').click(); });
  $('reference-file').onchange = function () { var files = Array.from($('reference-file').files); $('reference-file').value = ''; addReferences(files); };
  button('render', function () { return submit('render'); }); button('edit', function () { return submit('edit'); }); button('upscale', function () { return submit('upscale'); });
  button('retry-submit', function () { if (S.pendingSubmission) return task('Đang kiểm tra yêu cầu cũ…', function () { return sendSubmission(S.pendingSubmission); }); });
  button('save-source', function () { return task('Đang chuẩn bị ảnh nguồn…', async function () { var value = await preparedSource(); await native('save_image', { asset_id: value.id }); }); });
  button('save-result', function () { if (S.result) return task('Đang lưu ảnh kết quả…', function () { return native('save_image', { asset_id: S.result.id }); }); });
  button('reuse-result', function () { if (S.result) return task('Đang dùng kết quả làm nguồn…', function () { return setSource(S.result, 'Nguồn từ kết quả Flow', 'result'); }); });
  button('reference-result', function () { return task('Đang thêm ảnh tham chiếu…', async function () { if (S.result && S.refs.length < 4 && !S.refs.some(function (v) { return v.id === S.result.id; })) { S.refs.push(await referenceValue(S.result)); renderReferences(); } }); });
  button('restore-job', function () { if (S.job) return task('Đang lấy lại thiết lập…', function () { return restoreJob(S.job); }); });
  button('compare-toggle', function () { S.compare = !S.compare; updateCompare(); });
  $('compare-range').oninput = updateCompare;
  button('previous-result', function () { if (S.job) return showResult(S.job, S.resultIndex - 1, S.selection); });
  button('next-result', function () { if (S.job) return showResult(S.job, S.resultIndex + 1, S.selection); });
  button('cancel-job', async function () {
    if (!S.job || terminal(S.job)) return;
    var selectedJob = S.job, id = selectedJob.id; S.cancelling.add(id); renderJob();
    try {
      var result = await api('DELETE', 'jobs/' + id);
      if (result.job && result.job.state === 'complete') {
        S.cancelling.delete(id); mergeJobs([result.job]);
        if (S.job && S.job.id === id) await loadJob(id, false);
        tell('Tác vụ đã hoàn thành trước khi được hủy. Ảnh kết quả vẫn được giữ lại.', true);
        return;
      }
      S.cancelled.add(id); mergeJobs([Object.assign({}, selectedJob, result.job || {}, { id: id, state: 'cancelled', result_ids: [], message: 'Đã hủy tác vụ AI.' })]);
      if (S.job && S.job.id === id) { S.job = S.jobs.find(function (v) { return v.id === id; }); S.selection++; clearResult(); renderJob(); }
    } catch (error) { tell(error.message); } finally { S.cancelling.delete(id); renderJob(); }
  });
  button('manual-save-source',function () { if (S.job) return native('save_image',{asset_id:S.job.source_id}); });
  button('manual-copy-prompt',async function () { if (S.job) { await copyText(S.job.prompt || ''); tell('Đã sao chép đúng mô tả của tác vụ.',true); } });
  button('manual-watch',function () { if (S.job) return task('Đang chọn thư mục tải về…',async function () { var id=S.job.id; var watch=await native('watch_downloads',{job_id:id}); S.watchJob=watch.watching?id:null; S.watchStatusJob=id; S.watchMessage=watch.message || ''; $('manual-stop-watch').hidden=!S.watchJob; tell(watch.watching?'Chỉ xem trước ảnh mới tải về; bạn sẽ xác nhận ảnh trước khi nhập.':'Chưa bật theo dõi thư mục.',!!watch.watching); }); });
  button('manual-stop-watch',async function () { await native('stop_downloads'); S.watchJob=null; $('manual-stop-watch').hidden=true; });
  window.SiteCraftAI.downloadCandidate=function (value,jobId) { var selected=S.selection; if (!value || !validId(value.id) || !S.job || S.job.id!==jobId || ['waiting_user','error'].indexOf(S.job.state)<0) return; asset(value.id,value).then(function (candidate) { if (selected!==S.selection || !S.job || S.job.id!==jobId || ['waiting_user','error'].indexOf(S.job.state)<0) return; S.downloadCandidate={job_id:jobId,asset:candidate}; $('download-candidate-image').src=candidate.data_url; $('download-candidate').hidden=false; }).catch(function (error) { tell(error.message); }); };
  button('download-dismiss',function () { S.downloadCandidate=null; $('download-candidate').hidden=true; $('download-candidate-image').removeAttribute('src'); });
  button('download-accept',function () { return task('Đang xác nhận ảnh tải về…',async function () { var candidate=S.downloadCandidate; if (!candidate || !S.job || S.job.id!==candidate.job_id || ['waiting_user','error'].indexOf(S.job.state)<0) throw new Error('Tác vụ đã đổi; chọn lại đúng ảnh kết quả.'); await api('POST','jobs/'+candidate.job_id+'/import',{asset_id:candidate.asset.id}); S.downloadCandidate=null; $('download-candidate').hidden=true; $('download-candidate-image').removeAttribute('src'); await loadJob(candidate.job_id,false); }); });
  button('manual-result-open', function () { $('manual-result-file').click(); });
  $('manual-result-file').onchange = function () {
    var file = $('manual-result-file').files[0], job = S.job; $('manual-result-file').value = '';
    if (!file || !job) return;
    task('Đang nhập kết quả bạn chọn…', async function () {
      if (S.cancelled.has(job.id) || ['waiting_user', 'error'].indexOf(job.state) < 0) throw new Error('Tác vụ này không còn chờ nhập kết quả.');
      var value = await upload(await readFile(file), file.name, 'manual_result');
      if (S.cancelled.has(job.id) || S.cancelling.has(job.id)) throw new Error('Tác vụ đã được hủy.');
      await api('POST', 'jobs/' + job.id + '/import', { asset_id: value.id }); await loadJob(job.id, false); tell('Đã nhập ảnh do bạn chọn làm kết quả.', true);
    });
  };
  ['open-flow', 'manual-open-flow', 'settings-open-flow'].forEach(function (id) { button(id, function () { return native('open_flow'); }); });
  button('open-folder', function () { return native('open_folder'); }); button('history-folder', function () { return native('open_folder'); });
  button('open-bridge-folder', function () { return native('open_bridge_folder'); });
  ['settings-open', 'connection', 'connect-shortcut'].forEach(function (id) { button(id, function () { openDrawer('settings-drawer'); }); });
  button('history-open', async function () { openDrawer('history-drawer'); if (S.online) await historyRefresh(); else renderHistory(); });
  button('history-refresh', function () { return task('Đang đọc lịch sử…', historyRefresh); });
  document.querySelectorAll('[data-close-drawer]').forEach(function (element) { element.onclick = closeDrawers; }); $('drawer-backdrop').onclick = closeDrawers;
  button('pair', function () { return task('Đang tạo mã ghép…', async function () {
    var result = await api('POST', 'pair', {}); $('pair-code').textContent = result.code; $('pair-details').hidden = false;
    $('pair-info').textContent = 'Cổng ' + result.port + ' · hiệu lực ' + Math.round(result.expires_in / 60) + ' phút. Nhập mã và cổng trong tiện ích Chrome.';
  }); });
  button('copy-pair', async function () { await copyText($('pair-code').textContent); tell('Đã sao chép mã ghép.', true); });
  button('copy-prompt', async function () { await copyText($('prompt-preview').value); tell('Đã sao chép nội dung.', true); });
  button('unpair', function () { return task('Đang ngắt ghép Chrome…', async function () {
    if (S.jobs.some(function (j) { return ['claimed', 'running'].indexOf(j.state) >= 0; }) && !window.confirm('Ngắt ghép khi có tác vụ đang chạy? Hãy kiểm tra lại Flow trước khi gửi tác vụ khác.')) return;
    await api('POST', 'unpair', {}); await refreshStatus();
  }); });
  $('camera-watch').onchange = async function () {
    try { await native('camera_watch', { enabled: $('camera-watch').checked }); }
    catch (error) { $('camera-watch').checked = false; tell(error.message); }
  };
  $('prompt-template').onchange=function () { var reference=window.SiteCraftAIReferencePrompts, template=reference && reference.basePreviewFixture && reference.basePreviewFixture[$('prompt-template').value]; if (typeof template==='string') { $('prompt').value=template; S.promptOperation=$('prompt-template').value; S.restoredPrompt=false; savePrefs(); updatePrompt(); } $('prompt-template').value=''; };
  ['prompt','preset','lighting','photo-style','context','custom-style','custom-context','custom-lighting','keep-design','keep-camera'].forEach(function (id) { $(id).oninput=function () { S.promptOperation='render'; if (id==='prompt') savePrefs(); if (['preset','lighting','photo-style','context'].indexOf(id)>=0) S.restoredPrompt=false; updatePrompt(); }; $(id).onchange=$(id).oninput; });
  ['aspect','crop-x','crop-y','crop-zoom','aspect-width','aspect-height'].forEach(function (id) { $(id).oninput = function () { drawSource(); updatePrompt(); }; $(id).onchange = function () { drawSource(); updatePrompt(); }; });
  button('crop-reset', function () { $('crop-zoom').value='1'; $('aspect').value = 'original'; $('crop-x').value = $('crop-y').value = '50'; drawSource(); updatePrompt(); });
  function dropZone(element, callback) {
    element.addEventListener('dragover', function (event) { if (!event.dataTransfer.types.includes('Files')) return; event.preventDefault(); element.classList.add('drag-over'); });
    element.addEventListener('dragleave', function () { element.classList.remove('drag-over'); });
    element.addEventListener('drop', function (event) { event.preventDefault(); event.stopPropagation(); element.classList.remove('drag-over'); callback(Array.from(event.dataTransfer.files).filter(function (f) { return !f.type || f.type.indexOf('image/') === 0; })); });
  }
  dropZone($('source-stage'), function (files) { if (files[0]) openSourceFile(files[0]); });
  dropZone($('references'), addReferences);
  var pasteTarget = 'source';
  $('references').addEventListener('focusin', function () { pasteTarget = 'reference'; }); $('references').addEventListener('pointerdown', function () { pasteTarget = 'reference'; });
  $('source-stage').addEventListener('focusin', function () { pasteTarget = 'source'; }); $('source-stage').addEventListener('pointerdown', function () { pasteTarget = 'source'; });
  document.addEventListener('paste', function (event) {
    var files = Array.from(event.clipboardData && event.clipboardData.files || []).filter(function (f) { return f.type.indexOf('image/') === 0; });
    if (!files.length) return; event.preventDefault(); if (pasteTarget === 'reference') addReferences(files); else openSourceFile(files[0]);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { closeDrawers(); if (chooseActive.resolve) chooseActive.resolve('dismiss'); }
    if (event.ctrlKey && event.key === 'Enter' && !$('render').disabled) { event.preventDefault(); submit('render'); }
    if (event.key.toLowerCase() === 'r' && !event.ctrlKey && !event.metaKey && !/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) { event.preventDefault(); capture(false); }
  });
  if (window.ResizeObserver) new ResizeObserver(fitSource).observe($('source-stage')); else window.addEventListener('resize', fitSource);
  var library=promptLibrary();
  if (library) {
    [['preset','scene',window.SiteCraftAIReferencePrompts?'auto':'architecture'],['lighting','lighting','original'],['photo-style','style','original'],['context','context','original']].forEach(function (entry) { var select=$(entry[0]); select.replaceChildren(); library.getOptions(entry[1]).forEach(function (item) { select.add(new Option(item.label,item.id)); }); select.value=entry[2]; if (!select.value && select.options.length) select.selectedIndex=0; });
    library.getOptions('extras').forEach(function (item) { var label=document.createElement('label'), input=document.createElement('input'); input.type='checkbox'; input.dataset.extra=item.id; input.onchange=function () { S.promptOperation='render'; S.restoredPrompt=false; updatePrompt(); }; label.append(input,document.createTextNode(' '+item.label)); $('preset-extras').append(label); });
  }
  ['capture-width','capture-size-mode','hide-helpers','auto-recapture','upload-max','upload-format','jpeg-quality','camera-debounce','history-size','history-fit','allow-queue'].forEach(function (id) { if (prefs[id]!==undefined) { if ($(id).type==='checkbox') $(id).checked=!!prefs[id]; else $(id).value=prefs[id]; } $(id).oninput=function () { savePrefs(); S.prepared=null; if (id.indexOf('history-')===0) renderHistory(); sync(); }; $(id).onchange=$(id).oninput; });
  var reference=window.SiteCraftAIReferencePrompts; if (Object.prototype.hasOwnProperty.call(prefs,'draftPrompt')) $('prompt').value=prefs.draftPrompt; else if (reference && reference.basePreviewFixture && typeof reference.basePreviewFixture.render==='string') $('prompt').value=reference.basePreviewFixture.render; $('prompt-template').disabled=!reference;
  $('region-list').classList.add('region-list'); $('prompt').maxLength=7000;
  updatePrompt(); sync(); connectionStatus();
  if (nativeAvailable) refreshStatus();
}());
