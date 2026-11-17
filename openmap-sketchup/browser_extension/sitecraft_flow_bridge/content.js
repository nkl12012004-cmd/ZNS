/* Runs only in the explicitly connected Flow tab; no bearer token is received. */
(function (scope) {
  'use strict';
  if (scope.__sitecraftFlowContent) return;
  scope.__sitecraftFlowContent = true;
  const C = scope.SiteCraftBridgeCore, D = scope.SiteCraftFlowDOM;
  if (!C || !D || !C.flowURL(location.href)) return;
  const dom = new D.FlowDOM();
  let session = '', enabled = false, active = null, polling = null, failures = 0;
  let badge = null;
  function show(message) {
    if (!badge) {
      badge = document.createElement('div'); badge.id = 'sitecraft-flow-status';
      Object.assign(badge.style, {position: 'fixed', right: '16px', bottom: '16px', zIndex: '2147483646',
        background: '#173f35', color: '#fff', padding: '12px 15px', borderRadius: '12px',
        font: '13px/1.5 system-ui,sans-serif', maxWidth: '340px', boxShadow: '0 4px 24px #0003', pointerEvents: 'none'});
      document.documentElement.appendChild(badge);
    }
    badge.textContent = 'SiteCraft · ' + message;
  }
  async function message(type, args = {}) {
    const response = await chrome.runtime.sendMessage({sitecraft: 1, session, type, ...args});
    if (!response?.ok) throw new Error(response?.error || 'Mất kết nối tiện ích SiteCraft.');
    return response.data;
  }
  function marker(jobId) { return 'sitecraft_flow_job_' + jobId; }
  function persist(job, phase, extra = {}) {
    try { sessionStorage.setItem(marker(job.id), JSON.stringify({id: job.id, phase, at: Date.now(), ...extra})); }
    catch { throw new D.WaitingUser('Không lưu được dấu lượt đã gửi. Cho phép lưu trữ của Flow rồi kết nối lại; chưa tự gửi ảnh.'); }
  }
  async function execute(job) {
    const operation = {job, cancelled: false, phase: 'starting', message: 'Đang chuẩn bị Flow.', lastLease: 0,
      deadline: Date.now() + 600000, downloadNonce: '', downloads: [], interfered: false, submittedAt: 0};
    operation.clicks = new Map(); operation.expectedClick = null;
    active = operation;
    const send = async (type, args = {}) => {
      if (operation.cancelled || active !== operation) throw new D.Cancelled('Đã dừng lượt.');
      const result = await message(type, {jobId: job.id, ...args});
      if (!result?.ok) {
        if (result?.cancelled) { operation.cancelled = true; throw new D.Cancelled('Lượt đã bị huỷ hoặc hết phiên.'); }
        throw new Error(result?.error || 'SiteCraft chưa xác nhận được phiên xử lý.');
      }
      return result;
    };
    const context = {
      check: async force => {
        if (operation.cancelled || active !== operation || !enabled) throw new D.Cancelled('Đã dừng lượt.');
        if (operation.interfered) throw new D.WaitingUser('Bạn đã thao tác trên Flow trong lúc chờ lượt này. Kiểm tra đúng kết quả và nhập ảnh thủ công; SiteCraft không tự gán ảnh mới.');
        if (Date.now() >= operation.deadline) throw new D.WaitingUser('Đã chờ quá 10 phút. Kiểm tra Flow và nhập kết quả thủ công.');
        if (force || Date.now() - operation.lastLease >= 2000) {
          await send('CHECK_LEASE', {phase: operation.phase, message: operation.message});
          operation.lastLease = Date.now();
        }
      },
      report: async (phase, text) => {
        operation.phase = phase; operation.message = text; show(text);
        if (phase === 'submitted') operation.submittedAt = Date.now();
        persist(job, phase); await send('PROGRESS', {phase, message: text}); operation.lastLease = Date.now();
      },
      intent: async baseline => {
        persist(job, 'submission_intent', {page: baseline.page, baseline: Array.from(baseline.keys).filter(key => /^[\w-]{1,160}$/.test(key)), historyCount: baseline.historyCount});
      },
      click: async (element, semantic) => {
        await context.check(true);
        const rectangle = element.getBoundingClientRect(), nonce = C.randomID();
        const rect = {x: rectangle.left, y: rectangle.top, width: rectangle.width, height: rectangle.height,
          viewportWidth: window.innerWidth, viewportHeight: window.innerHeight};
        C.clickPoint(rect);
        const expected = {nonce, element, semantic, rect, expires: Date.now() + 12000, armedUntil: 0, pointerSeen: false, domClick: false, prompt: dom.prompt()};
        operation.clicks.set(nonce, expected);
        const result = await message('CLICK', {jobId: job.id, nonce, semantic, rect});
        if (!result?.ok) {
          if (result?.cancelled) throw new D.Cancelled('Lượt đã kết thúc.');
          throw new D.WaitingUser(result?.error || 'Không xác nhận được cú bấm Flow. Kiểm tra trang trước khi tiếp tục.');
        }
        if (result.mode === 'dom') {
          expected.armedUntil = Date.now() + 500; expected.domClick = true; operation.expectedClick = expected;
          element.click();
        }
      },
      fetchImage: async url => (await send('FETCH_IMAGE', {url})).data_url,
      armDownload: async mediaId => {
        operation.downloadNonce = C.randomID(); operation.downloads = [];
        await send('ARM_DOWNLOAD', {nonce: operation.downloadNonce, mediaId});
      },
      takeDownload: () => operation.downloads.shift() || null
    };
    try {
      const output = await dom.run(job, context);
      await context.check(true);
      let completed = false;
      for (let attempt = 0; attempt < 3 && !completed; attempt++) {
        try { await send('COMPLETE', output); completed = true; }
        catch (error) {
          if (error instanceof D.Cancelled || attempt === 2) throw error;
          await dom.sleep(1000 * (attempt + 1));
        }
      }
      persist(job, 'complete'); show('Đã gửi ảnh về SiteCraft.');
    } catch (error) {
      if (error instanceof D.Cancelled) { persist(job, 'cancelled'); show('Đã dừng. Lượt đã gửi trên Google có thể vẫn tiếp tục ở Flow.'); }
      else {
        const text = error instanceof D.WaitingUser ? error.message : 'Mất kết nối hoặc không xác nhận được thao tác. Kiểm tra Flow; dùng Nhập ảnh trong SiteCraft. Không tự gửi lại.';
        persist(job, 'waiting_user'); show(text);
        try { await message('WAITING_USER', {jobId: job.id, message: text}); } catch {}
      }
    } finally { if (active === operation) active = null; }
  }
  window.addEventListener('message', event => {
    const data = event.data;
    if (!active || event.source !== window || event.origin !== location.origin || data?.source !== 'sitecraft-flow-download' || data.nonce !== active.downloadNonce) return;
    if (typeof data.name !== 'string' || data.name.length > 250 || active.downloads.length) return;
    if (typeof data.error === 'string') active.downloads.push({error: data.error.slice(0, 300), name: data.name});
    else if (data.data_url) {
      try { C.parseImage(data.data_url); } catch { return; }
      active.downloads.push({data_url: data.data_url, name: data.name});
    } else if (typeof data.url === 'string' && C.imageURL(data.url, location.origin)) active.downloads.push({url: data.url, name: data.name});
  });
  function userChanged(event) {
    if (!active || !event.isTrusted || !['submission_intent', 'submitted', 'receiving', 'upscale_download'].includes(active.phase)) return;
    const expected = active.expectedClick;
    if (expected && Date.now() <= expected.armedUntil) {
      const sameTarget = event.target === expected.element || expected.element.contains?.(event.target);
      const point = C.clickPoint(expected.rect);
      if (event.type === 'pointerdown' && sameTarget && Math.abs(event.clientX - point.x) <= 3 && Math.abs(event.clientY - point.y) <= 3 && !expected.pointerSeen) { expected.pointerSeen = true; return; }
      const samePrompt = event.target === expected.prompt || expected.prompt?.contains?.(event.target);
      if (event.type === 'input' && expected.semantic === 'generate' && samePrompt && (expected.pointerSeen || expected.domClick)) return;
    }
    active.interfered = true;
  }
  for (const type of ['pointerdown', 'keydown', 'input']) document.addEventListener(type, userChanged, true);
  async function poll() {
    clearTimeout(polling);
    if (!enabled) return;
    try { await message('TICK'); failures = 0; }
    catch { failures = Math.min(failures + 1, 4); }
    if (enabled) polling = setTimeout(poll, active ? 3000 : Math.min(30000, 5000 * 2 ** failures));
  }
  chrome.runtime.onMessage.addListener((input, sender, respond) => {
    if (sender.id !== chrome.runtime.id || input?.sitecraft !== 1) return false;
    if (input.type === 'CONFIGURE' && C.ID.test(input.session)) {
      if (active && session !== input.session) active.cancelled = true;
      session = input.session; enabled = true; show('Tab Flow đã kết nối.');
      clearTimeout(polling); polling = setTimeout(poll, 100);
      respond({ok: true}); return false;
    }
    if (!session || input.session !== session) { respond({ok: false, error: 'Phiên tab chưa được kết nối.'}); return false; }
    if (input.type === 'STATUS') {
      let blocked = false, detail = '';
      try { dom.blockers(); } catch (error) { blocked = true; detail = error.message; }
      respond({ok: true, visible: document.visibilityState === 'visible', ready: dom.ready() && Boolean(dom.prompt()),
        page_url: D.canonicalPage(location.href), generating: dom.generating(), blocked, message: detail,
        running: Boolean(active), jobId: active?.job.id || null, phase: active?.phase || 'idle'}); return false;
    }
    if (input.type === 'VERIFY_CLICK') {
      const expected = active?.clicks.get(input.nonce);
      if (!active || active.job.id !== input.jobId || active.interfered || active.cancelled || !expected || expected.semantic !== input.semantic || Date.now() > expected.expires) { respond({ok: false}); return false; }
      try {
        dom.blockers();
        const rectangle = expected.element.getBoundingClientRect();
        const rect = {x: rectangle.left, y: rectangle.top, width: rectangle.width, height: rectangle.height, viewportWidth: window.innerWidth, viewportHeight: window.innerHeight};
        const point = C.clickPoint(rect), hit = document.elementFromPoint(point.x, point.y);
        if (!dom.visible(expected.element) || expected.element.disabled || !(hit === expected.element || expected.element.contains?.(hit))) { respond({ok: false}); return false; }
        expected.rect = rect; expected.armedUntil = Date.now() + 2000; active.expectedClick = expected;
        respond({ok: true, rect});
      } catch { respond({ok: false}); }
      return false;
    }
    if (input.type === 'DISABLE') { enabled = false; if (active) active.cancelled = true; clearTimeout(polling); badge?.remove(); badge = null; respond({ok: true}); return false; }
    if (input.type === 'CANCEL') { if (active && input.jobId === active.job.id) active.cancelled = true; respond({ok: true}); return false; }
    if (input.type === 'START') {
      const job = input.job;
      if (!enabled || !job || !C.ID.test(job.id) || !job.source?.data_url || !['render', 'edit', 'upscale'].includes(job.operation)) { respond({ok: false, error: 'Lượt Flow không hợp lệ.'}); return false; }
      if (active) { respond({ok: active.job.id === job.id, error: 'Tab đang xử lý lượt khác.'}); return false; }
      if (sessionStorage.getItem(marker(job.id))) { respond({ok: false, error: 'Lượt này đã được gửi hoặc gián đoạn trên tab. Kiểm tra Flow; không tự gửi lại.'}); return false; }
      try { persist(job, 'accepted'); } catch (error) { respond({ok: false, error: error.message}); return false; }
      respond({ok: true}); execute(job); return false;
    }
    return false;
  });
})(window);
