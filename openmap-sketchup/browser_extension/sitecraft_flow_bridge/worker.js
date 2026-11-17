/* The bearer token stays in this extension worker, never in the Flow page. */
if (typeof importScripts === 'function') importScripts('core.js');
(function (scope) {
  'use strict';
  const C = scope.SiteCraftBridgeCore || require('./core.js');
  const STORAGE = 'sitecraftFlowBridgeV1';
  class BridgeWorker {
    constructor(chromeAPI, fetcher = fetch, environment = {}) {
      this.chrome = chromeAPI; this.fetcher = fetcher; this.record = null;
      this.initializing = null; this.ticking = null; this.lastHeartbeat = 0;
      this.sleep = environment.sleep || (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)));
      this.now = environment.now || (() => Date.now());
    }
    async init() {
      if (this.record) return;
      if (this.initializing) return this.initializing;
      this.initializing = (async () => {
        if (this.chrome.storage.local.setAccessLevel) await this.chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'});
        const saved = (await this.chrome.storage.local.get(STORAGE))[STORAGE] || {};
        let selectedPort = 17865;
        try { selectedPort = C.port(saved.port || 17865); } catch {}
        this.record = {port: selectedPort, clientId: C.ID.test(saved.clientId) ? saved.clientId : C.randomID(),
          token: typeof saved.token === 'string' ? saved.token : '', enabled: Boolean(saved.enabled),
          tabId: Number.isInteger(saved.tabId) ? saved.tabId : null,
          session: C.ID.test(saved.session) ? saved.session : C.randomID(),
          pending: saved.pending || null, message: saved.message || '', trustedMode: Boolean(saved.trustedMode),
          autoOpen: Boolean(saved.autoOpen), projectUrl: ''};
        try { this.record.projectUrl = C.flowPage(saved.projectUrl); } catch {}
        await this.save();
      })();
      return this.initializing;
    }
    async save() { await this.chrome.storage.local.set({[STORAGE]: this.record}); }
    async granted(permission) {
      return Boolean(this.chrome.permissions?.contains && await this.chrome.permissions.contains({permissions: [permission]}));
    }
    call(path, body) { return C.request(this.record, path, body, this.fetcher); }
    connection() { return {...this.record}; }
    current(connection) {
      return this.record.enabled && this.record.session === connection.session && this.record.tabId === connection.tabId &&
        this.record.token === connection.token && this.record.port === connection.port;
    }
    samePending(pending) { return this.record.pending?.id === pending.id && this.record.pending?.lease === pending.lease; }
    sendTo(connection, type, args = {}) {
      return this.chrome.tabs.sendMessage(connection.tabId, {sitecraft: 1, type, session: connection.session, ...args});
    }
    async tabMessage(type, args = {}) {
      return this.sendTo(this.connection(), type, args);
    }
    async publicState() {
      await this.init();
      let tab = null;
      try { tab = await this.chrome.tabs.get(this.record.tabId); } catch {}
      return {paired: Boolean(this.record.token), port: this.record.port, enabled: this.record.enabled,
        tab: tab ? {id: tab.id, title: tab.title || 'Google Flow', supported: C.flowURL(tab.url)} : null,
        active: this.record.pending ? {id: this.record.pending.id, phase: this.record.pending.phase} : null,
        message: this.record.message, trusted_mode: this.record.trustedMode && await this.granted('debugger'),
        auto_open: this.record.autoOpen};
    }
    async pair(code, selectedPort) {
      await this.init();
      if (!/^\d{6}$/.test(String(code))) throw new C.BridgeError('Nhập mã ghép nối 6 chữ số từ SiteCraft.');
      this.record.enabled = false;
      if (this.record.pending) await this.waiting('Đã đổi kết nối bridge. Kiểm tra lượt trước trên Flow và nhập ảnh thủ công nếu đã tạo.');
      if (this.record.pending) throw new C.BridgeError('Kết nối cũ đang gián đoạn. Mở lại SiteCraft để kết thúc lượt trước khi đổi bridge.');
      const result = await C.request({port: C.port(selectedPort)}, '/pair', {code: String(code), client_id: this.record.clientId}, this.fetcher);
      if (result.protocol !== 1 || typeof result.token !== 'string' || !/^[A-Za-z0-9_-]{20,512}$/.test(result.token)) throw new C.BridgeError('Bridge không hỗ trợ giao thức 1.');
      this.record.token = result.token; this.record.port = C.port(result.port);
      this.record.message = 'Đã ghép nối. Chọn tab Flow đang mở rồi bấm Kết nối tab hiện tại.';
      await this.save(); return this.publicState();
    }
    async connect(tabId) {
      await this.init();
      if (!this.record.token) throw new C.BridgeError('Ghép mã SiteCraft trước khi kết nối Flow.');
      const tab = await this.chrome.tabs.get(tabId);
      if (!C.flowURL(tab.url)) throw new C.BridgeError('Mở Google Flow, chọn dự án rồi kết nối chính tab đó.');
      this.record.enabled = false;
      if (this.record.pending) await this.waiting('Đã đổi tab Flow. Lượt trước cần kiểm tra hoặc nhập ảnh thủ công.');
      if (this.record.pending) throw new C.BridgeError('Không xác nhận được lượt trước. Mở SiteCraft để kiểm tra trước khi đổi tab.');
      if (this.record.tabId != null) { try { await this.tabMessage('DISABLE'); } catch {} }
      this.record.tabId = tab.id; this.record.session = C.randomID(); this.record.enabled = true;
      try { this.record.projectUrl = C.flowPage(tab.url); } catch { this.record.projectUrl = ''; }
      await this.save();
      try { await this.tabMessage('CONFIGURE'); }
      catch {
        await this.chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['core.js', 'flow-dom.js', 'content.js']});
        await this.tabMessage('CONFIGURE');
      }
      this.record.message = 'Đã kết nối tab Flow. Tạo lượt Render AI trong SiteCraft.';
      await this.save(); await this.tick(); return this.publicState();
    }
    async disconnect() {
      await this.init();
      this.record.enabled = false;
      if (this.record.pending) await this.waiting('Đã ngắt tab. Kiểm tra ảnh trên Flow; dùng Nhập ảnh trong SiteCraft nếu lượt đã gửi.');
      try { await this.tabMessage('DISABLE'); } catch {}
      this.record.enabled = false; this.record.message = 'Đã ngắt tab Flow.';
      await this.save(); return this.publicState();
    }
    async waiting(message) {
      const pending = this.record.pending;
      if (!pending) return;
      const connection = this.connection();
      // Stop the content operation first; a possibly submitted generation is
      // never retried, regardless of whether the local API is reachable.
      try { await this.sendTo(connection, 'CANCEL', {jobId: pending.id}); } catch {}
      try { await C.request(connection, '/jobs/' + pending.id + '/progress', {lease: pending.lease, state: 'waiting_user', message}, this.fetcher); }
      catch (error) {
        if (![404, 409].includes(error.status)) {
          if (!this.samePending(pending)) return;
          pending.phase = 'interrupted'; this.record.message = message;
          await this.save(); return;
        }
      }
      if (!this.samePending(pending)) return;
      this.record.pending = null; this.record.message = message; await this.save();
    }
    tick() {
      if (this.ticking) return this.ticking;
      this.ticking = this.runTick().catch(async error => {
        if (this.record) { this.record.message = error.message; await this.save(); }
      }).finally(() => { this.ticking = null; });
      return this.ticking;
    }
    async runTick() {
      await this.init();
      if (!this.record.enabled || !this.record.token) return;
      let connection = this.connection();
      let tab, status;
      try { tab = await this.chrome.tabs.get(connection.tabId); }
      catch {
        if (!this.current(connection)) return;
        if (this.record.pending) await this.waiting('Tab Flow đã đóng. Lượt cũ không tự gửi lại; kiểm tra kết quả hoặc nhập thủ công.');
        if (!this.current(connection)) return;
        if (this.record.pending) return;
        if (!this.record.autoOpen || !this.record.projectUrl) return;
        const target = C.flowPage(this.record.projectUrl);
        tab = await this.chrome.tabs.create({url: target, active: false});
        if (!this.current(connection) || !this.record.autoOpen || this.record.projectUrl !== target) {
          if (this.chrome.tabs.remove) await this.chrome.tabs.remove(tab.id).catch(() => {});
          return;
        }
        this.record.tabId = tab.id; this.record.session = C.randomID(); connection = this.connection();
        await this.save();
        await this.readyPage(connection, target, null);
      }
      if (!this.current(connection)) return;
      if (!C.flowURL(tab.url)) return this.waiting('Tab đã rời Google Flow. Đăng nhập hoặc mở lại dự án rồi kết nối lại.');
      try { status = await this.sendTo(connection, 'STATUS'); }
      catch {
        if (this.record.pending) return this.waiting('Trang Flow đã tải lại. Kiểm tra lượt đã gửi; SiteCraft không tự gửi lại.');
        await this.tabMessage('CONFIGURE').catch(() => {}); return;
      }
      if (!this.current(connection)) return;
      if (this.record.pending) {
        const active = this.record.pending;
        if (active.phase === 'interrupted') return this.waiting(this.record.message);
        if (Date.now() - active.started > 600000) return this.waiting('Đã chờ quá 10 phút. Kiểm tra Flow và nhập kết quả thủ công.');
        if (status?.jobId !== active.id || !status.running) return this.waiting('Phiên xử lý đã gián đoạn. Kiểm tra Flow; không tự gửi lại để tránh tạo ảnh trùng.');
      }
      if (Date.now() - this.lastHeartbeat > 20000) {
        await C.request(connection, '/heartbeat', {client_id: connection.clientId}, this.fetcher); this.lastHeartbeat = Date.now();
      }
      if (!this.current(connection)) return;
      if (this.record.pending || status?.running || status?.generating) return;
      const claimed = await C.request(connection, '/jobs/claim', {client_id: connection.clientId}, this.fetcher);
      const job = claimed.job;
      if (!job) return;
      if (!C.ID.test(job.id) || typeof job.lease !== 'string' || job.lease.length < 16 || !['render', 'edit', 'upscale'].includes(job.operation)) throw new C.BridgeError('Tác vụ bridge không hợp lệ.');
      if (!this.current(connection)) {
        try { await C.request(connection, '/jobs/' + job.id + '/progress', {lease: job.lease, state: 'waiting_user', message: 'Tab hoặc kết nối đã đổi trong lúc nhận lượt. Kiểm tra SiteCraft; không tự gửi sang tab khác.'}, this.fetcher); } catch {}
        return;
      }
      this.record.pending = {id: job.id, lease: job.lease, tabId: tab.id, phase: 'dispatching', started: Date.now()};
      await this.save();
      if (!this.current(connection)) { await this.waiting('Kết nối tab đã thay đổi. Không tự gửi lượt này.'); return; }
      try {
        const page = job.flow?.page_url;
        let currentPage = '';
        try { currentPage = C.flowPage(tab.url); } catch {}
        if (['edit', 'upscale'].includes(job.operation) && page && currentPage !== C.flowPage(page)) {
          if (status?.generating) { await this.waiting('Flow đang tạo lượt khác. Chờ xong rồi mở lại đúng ảnh.'); return; }
          await this.navigateJob(connection, job, C.flowPage(page));
        }
        if (!this.current(connection) || !this.record.pending || this.record.pending.id !== job.id) return;
        const accepted = await this.sendTo(connection, 'START', {job});
        if (!accepted?.ok) await this.waiting(accepted?.error || 'Flow chưa sẵn sàng. Kiểm tra trang trước khi tiếp tục.');
      } catch (error) { await this.waiting(error.message || 'Không gửi được tác vụ vào tab Flow. Kiểm tra lượt trên Flow trước khi tạo lượt mới.'); }
    }
    async readyPage(connection, target, pending) {
      const deadline = this.now() + 30000; let nextLease = 0, injected = false;
      while (this.now() < deadline) {
        if (!this.current(connection) || pending && !this.samePending(pending)) throw new C.BridgeError('Phiên tab đã thay đổi trong lúc mở Flow.');
        if (pending && this.now() >= nextLease) {
          await C.request(connection, '/jobs/' + pending.id + '/progress', {lease: pending.lease, state: 'running', message: 'Đang mở lại đúng trang ảnh Flow.'}, this.fetcher);
          nextLease = this.now() + 2000;
        }
        try {
          await this.sendTo(connection, 'CONFIGURE');
          const status = await this.sendTo(connection, 'STATUS');
          if (status?.blocked) throw new C.BridgeError(status.message || 'Google Flow cần bạn xử lý đăng nhập hoặc thông báo.');
          if (status?.page_url === target && status.ready && !status.running && !status.generating) return;
        } catch (error) {
          if (error instanceof C.BridgeError) throw error;
          if (!injected) {
            const tab = await this.chrome.tabs.get(connection.tabId);
            if (!C.flowURL(tab.url)) throw new C.BridgeError('Flow chuyển sang trang đăng nhập. Tự đăng nhập rồi tạo lượt mới.');
            await this.chrome.scripting.executeScript({target: {tabId: connection.tabId}, files: ['core.js', 'flow-dom.js', 'content.js']}).catch(() => {});
            injected = true;
          }
        }
        await this.sleep(400);
      }
      throw new C.BridgeError('Flow chưa mở được đúng ảnh/dự án. Kiểm tra tab, rồi dùng Nhập ảnh; lượt không tự gửi lại.');
    }
    async navigateJob(connection, job, target) {
      const pending = this.record.pending;
      if (!pending || pending.id !== job.id || !this.current(connection)) throw new C.BridgeError('Phiên mở ảnh đã thay đổi.');
      pending.phase = 'navigation_intent'; pending.navigationUrl = target;
      await this.save(); // A restart here becomes manual, never a fresh claim.
      await C.request(connection, '/jobs/' + pending.id + '/progress', {lease: pending.lease, state: 'running', message: 'Đang mở lại đúng ảnh/dự án Flow đã lưu.'}, this.fetcher);
      if (!this.current(connection) || !this.samePending(pending)) throw new C.BridgeError('Lượt đã đổi trước khi mở Flow.');
      await this.chrome.tabs.update(connection.tabId, {url: target});
      await this.readyPage(connection, target, pending);
      if (!this.current(connection) || !this.samePending(pending)) throw new C.BridgeError('Lượt đã đổi trong lúc mở Flow.');
      this.record.projectUrl = target; pending.phase = 'dispatching'; await this.save();
    }
    async trustedClick(connection, pending, message) {
      if (!this.record.trustedMode) return {ok: true, mode: 'dom'};
      if (!await this.granted('debugger')) return {ok: false, manual: true, error: 'Quyền thao tác nền đã bị tắt. Bật lại trong tiện ích hoặc thao tác thủ công trên Flow.'};
      if (!this.current(connection) || !this.samePending(pending) || !this.record.trustedMode) return {ok: false, cancelled: true};
      const allowed = new Set(['generate', 'open_source', 'back_project', 'download', 'download_2k']);
      if (!C.ID.test(message.nonce) || !allowed.has(message.semantic)) throw new C.BridgeError('Cú bấm không hợp lệ.');
      C.clickPoint(message.rect);
      if (message.semantic === 'generate' && pending.phase !== 'submission_intent') throw new C.BridgeError('Chưa có dấu gửi lệnh tạo ảnh.');
      pending.clicks ||= {};
      if (pending.clicks[message.nonce]) return {ok: false, manual: true, error: 'Cú bấm này đã được xử lý hoặc gián đoạn. Kiểm tra Flow; không tự bấm lại.'};
      if (message.semantic === 'generate' && Object.values(pending.clicks).some(item => item.semantic === 'generate')) return {ok: false, manual: true, error: 'Lượt này đã có một lần bấm Tạo. Không bấm lại.'};
      if (Object.keys(pending.clicks).length >= 12) throw new C.BridgeError('Đã vượt số thao tác cho phép của lượt.');
      pending.clicks[message.nonce] = {semantic: message.semantic, at: Date.now(), phase: 'intent'}; await this.save();
      const target = {tabId: connection.tabId}; let attached = false;
      const bounded = promise => new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new C.BridgeError('Hết thời gian thao tác nền. Kiểm tra Flow trước khi gửi tiếp.')), 12000);
        Promise.resolve(promise).then(value => { clearTimeout(timer); resolve(value); }, error => { clearTimeout(timer); reject(error); });
      });
      try {
        const lease = await C.request(connection, '/jobs/' + pending.id + '/progress', {lease: pending.lease, state: 'running', message: 'Đang thao tác nút Flow: ' + message.semantic}, this.fetcher);
        if (lease.job?.state !== 'running' || !this.current(connection) || !this.samePending(pending)) return {ok: false, cancelled: true};
        const tab = await this.chrome.tabs.get(connection.tabId);
        if (!C.flowURL(tab.url)) throw new C.BridgeError('Tab không còn ở Google Flow.');
        if (!this.current(connection) || !this.samePending(pending) || !this.record.trustedMode) return {ok: false, cancelled: true};
        const attaching = this.chrome.debugger.attach(target, '1.3');
        try { await bounded(attaching); attached = true; }
        catch (error) {
          // attach may settle after its timeout; release that late attachment
          // rather than leaving a debugger associated with an obsolete job.
          Promise.resolve(attaching).then(() => this.chrome.debugger.detach(target)).catch(() => {});
          throw error;
        }
        const metrics = await bounded(this.chrome.debugger.sendCommand(target, 'Page.getLayoutMetrics'));
        const verified = await this.sendTo(connection, 'VERIFY_CLICK', {jobId: pending.id, nonce: message.nonce, semantic: message.semantic});
        if (!verified?.ok || !this.current(connection) || !this.samePending(pending)) throw new C.BridgeError('Nút Flow đã đổi vị trí hoặc có thao tác khác. Kiểm tra trang trước khi tiếp tục.');
        const point = C.clickPoint(verified.rect), viewport = metrics.cssVisualViewport || metrics.cssLayoutViewport || metrics.visualViewport || metrics.layoutViewport;
        if (!viewport || point.x >= viewport.clientWidth || point.y >= viewport.clientHeight) throw new C.BridgeError('Nút không nằm trong vùng trang Flow.');
        for (const [type, extra] of [['mouseMoved', {}], ['mousePressed', {button: 'left', buttons: 1, clickCount: 1}], ['mouseReleased', {button: 'left', buttons: 0, clickCount: 1}]]) {
          if (!this.current(connection) || !this.samePending(pending) || !this.record.trustedMode) throw new C.BridgeError('Phiên tab hoặc chế độ thao tác đã đổi.');
          await bounded(this.chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {type, x: point.x, y: point.y, ...extra}));
        }
        pending.clicks[message.nonce].phase = 'done'; await this.save();
        return {ok: true, mode: 'trusted'};
      } catch (error) { return {ok: false, manual: true, error: String(error.message || 'Không bấm được nút Flow.').slice(0, 350)}; }
      finally { if (attached) await bounded(this.chrome.debugger.detach(target)).catch(() => {}); }
    }
    async tabClosed(tabId) {
      await this.init();
      if (tabId !== this.record.tabId) return;
      const connection = this.connection();
      if (this.record.pending) await this.waiting('Tab Flow đã đóng. Lượt đã gửi không tự chạy lại.');
      if (this.record.tabId !== connection.tabId || this.record.session !== connection.session || this.record.token !== connection.token || this.record.port !== connection.port) return;
      this.record.tabId = null;
      if (!this.record.autoOpen) this.record.enabled = false;
      await this.save();
    }
    senderAllowed(sender, message) {
      return sender?.tab?.id === this.record.tabId && sender.id === this.chrome.runtime.id &&
        message.session === this.record.session && C.flowURL(sender.tab.url);
    }
    async content(message, sender) {
      await this.init();
      if (!this.senderAllowed(sender, message)) throw new C.BridgeError('Tab không được ghép với phiên này.', 403);
      if (message.type === 'TICK') { await this.tick(); return {ok: true}; }
      const pending = this.record.pending;
      if (!pending || message.jobId !== pending.id) return {ok: false, cancelled: true};
      const connection = this.connection();
      if (message.type === 'CLICK') return this.trustedClick(connection, pending, message);
      if (message.type === 'FETCH_IMAGE') {
        const dataURL = await C.fetchImage(message.url, this.fetcher);
        if (!this.samePending(pending) || !this.current(connection)) return {ok: false, cancelled: true};
        return {ok: true, data_url: dataURL};
      }
      if (message.type === 'ARM_DOWNLOAD') {
        if (!C.ID.test(message.nonce)) throw new C.BridgeError('Mã nhận ảnh không hợp lệ.');
        pending.downloadNonce = message.nonce; await this.save();
        await this.chrome.scripting.executeScript({target: {tabId: connection.tabId}, world: 'MAIN', files: ['download-observer.js']});
        if (!this.current(connection) || !this.samePending(pending)) return {ok: false, cancelled: true};
        await this.chrome.scripting.executeScript({target: {tabId: connection.tabId}, world: 'MAIN',
          func: settings => window.SiteCraftFlowDownload.arm(settings),
          args: [{nonce: message.nonce, mediaId: String(message.mediaId || '').slice(0, 160), timeout: 180000}]});
        return {ok: true};
      }
      if (message.type === 'WAITING_USER') { await this.waiting(String(message.message || 'Kiểm tra Flow và nhập ảnh thủ công.').slice(0, 500)); return {ok: true}; }
      try {
        if (message.type === 'PROGRESS' || message.type === 'CHECK_LEASE') {
          pending.phase = String(message.phase || pending.phase).slice(0, 60);
          await this.save(); // Includes submission intent BEFORE the UI click.
          const data = await C.request(connection, '/jobs/' + pending.id + '/progress', {lease: pending.lease, state: 'running', message: String(message.message || 'Đang theo dõi Flow.').slice(0, 500)}, this.fetcher);
          return {ok: this.samePending(pending) && this.current(connection) && !['cancelled', 'error', 'waiting_user'].includes(data.job?.state)};
        }
        if (message.type === 'COMPLETE') {
          if (!Array.isArray(message.images) || message.images.length !== 1) throw new C.BridgeError('Chỉ nhận một ảnh kết quả xác định.');
          message.images.forEach(C.parseImage);
          pending.phase = 'completing'; await this.save();
          const data = await C.request(connection, '/jobs/' + pending.id + '/complete', {lease: pending.lease, images: message.images, flow: message.flow || null}, this.fetcher);
          if (this.samePending(pending) && this.current(connection)) {
            this.record.pending = null; this.record.message = 'Đã gửi ảnh kết quả về SiteCraft.'; await this.save();
          }
          return {ok: true, state: data.job?.state || 'complete'};
        }
        throw new C.BridgeError('Thông điệp bridge không được hỗ trợ.');
      } catch (error) {
        if ([401, 403, 404, 409].includes(error.status)) {
          if (!this.samePending(pending) || !this.current(connection)) return {ok: false, cancelled: true, error: error.message};
          this.record.pending = null;
          if ([401, 403].includes(error.status)) { this.record.enabled = false; this.record.token = ''; }
          this.record.message = error.message; await this.save();
          return {ok: false, cancelled: true, error: error.message};
        }
        return {ok: false, retryable: true, error: error.message};
      }
    }
    async popup(message) {
      await this.init();
      switch (message.type) {
        case 'POPUP_STATUS': return this.publicState();
        case 'PAIR': return this.pair(message.code, message.port);
        case 'CONNECT': return this.connect(message.tabId);
        case 'DISCONNECT': return this.disconnect();
        case 'MODES': {
          for (const key of ['trusted', 'auto_open']) if (key in message && typeof message[key] !== 'boolean') throw new C.BridgeError('Tùy chọn tiện ích không hợp lệ.');
          if (message.trusted === true && !await this.granted('debugger')) throw new C.BridgeError('Chrome chưa cấp quyền thao tác nền.');
          if (message.auto_open === true && !this.record.projectUrl) throw new C.BridgeError('Kết nối một tab dự án Flow trước khi bật tự mở lại.');
          if ('trusted' in message) this.record.trustedMode = message.trusted;
          if ('auto_open' in message) this.record.autoOpen = message.auto_open;
          await this.save(); return this.publicState();
        }
        case 'FIND': {
          const results = await Promise.all(Array.from({length: 8}, (_, index) => 17865 + index).map(async selectedPort => {
            try { const data = await C.request({port: selectedPort}, '/health', undefined, this.fetcher, 1500); return data.name === 'SiteCraft AI Bridge' && data.protocol === 1 ? selectedPort : null; }
            catch { return null; }
          }));
          return {ports: results.filter(Boolean)};
        }
        default: throw new C.BridgeError('Lệnh popup không hợp lệ.');
      }
    }
  }
  if (typeof module !== 'undefined') module.exports = {BridgeWorker, STORAGE};
  if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
    const worker = new BridgeWorker(chrome);
    chrome.runtime.onMessage.addListener((message, sender, respond) => {
      if (!message || message.sitecraft !== 1 || sender.id !== chrome.runtime.id) return false;
      // An extension popup opened in its own tab still has sender.tab. Only
      // this exact packaged page may issue pairing/connection commands.
      const popup = sender.url === 'chrome-extension://' + chrome.runtime.id + '/popup.html';
      if (!popup && !sender.tab) { respond({ok: false, error: 'Trang tiện ích không được hỗ trợ.'}); return false; }
      const action = popup ? worker.popup(message) : worker.content(message, sender);
      action.then(data => respond({ok: true, data}), error => respond({ok: false, error: error.message}));
      return true;
    });
    chrome.alarms.create('sitecraft-flow-heartbeat', {periodInMinutes: 1});
    chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'sitecraft-flow-heartbeat') worker.tick(); });
    chrome.tabs.onRemoved.addListener(tabId => { worker.tabClosed(tabId); });
  }
})(typeof self !== 'undefined' ? self : globalThis);
