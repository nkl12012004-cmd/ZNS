/* Google Flow DOM adapter. Selectors are isolated and checked before use. */
(function (scope) {
  'use strict';
  const C = scope.SiteCraftBridgeCore || require('./core.js');
  const SELECTORS = Object.freeze({
    prompt: 'flow-edit-image-prompt-box .ProseMirror[role="textbox"], flow-base-prompt-box .ProseMirror[role="textbox"], .ProseMirror[role="textbox"]',
    grid: 'flow-grid-tile-container img[data-media-id], [data-media-id] img, img[data-media-id]',
    history: 'div.history-step',
    ingredients: 'flow-edit-image-prompt-box flow-ingredient-chip, flow-edit-image-prompt-box img.chip-image',
    alert: 'mat-snack-bar-container, .mat-mdc-snack-bar-container, [role="alert"], [aria-live="assertive"]',
    dialog: 'mat-dialog-container, [role="dialog"]',
    menu: '.cdk-overlay-container [role="menuitem"]'
  });
  class WaitingUser extends Error { constructor(message, code = 'FLOW_NEEDS_USER') { super(message); this.code = code; } }
  class Cancelled extends Error {}
  function mediaId(image) { return image?.getAttribute?.('data-media-id') || image?.closest?.('[data-media-id]')?.getAttribute('data-media-id') || ''; }
  function mediaKey(image) { return mediaId(image) || image?.currentSrc || image?.src || ''; }
  function canonicalPage(value) { const url = new URL(value); url.search = ''; url.hash = ''; return url.href; }
  class FlowDOM {
    constructor(environment = {}) {
      this.document = environment.document || scope.document;
      this.window = environment.window || scope;
      this.location = environment.location || scope.location;
      this.sleep = environment.sleep || (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)));
      this.now = environment.now || (() => Date.now());
      this.fetcher = environment.fetch || scope.fetch?.bind(scope);
      this.bitmap = environment.createImageBitmap || scope.createImageBitmap?.bind(scope);
      this.File = environment.File || scope.File;
      this.DataTransfer = environment.DataTransfer || scope.DataTransfer;
    }
    all(selector, root = this.document) { return Array.from(root.querySelectorAll(selector)); }
    visible(element) {
      if (!element || element.hidden || element.getAttribute?.('aria-hidden') === 'true') return false;
      const rectangle = element.getBoundingClientRect?.();
      if (rectangle && (!rectangle.width || !rectangle.height)) return false;
      const style = this.window.getComputedStyle?.(element);
      return !style || style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
    }
    prompt() { return this.all(SELECTORS.prompt).find(element => this.visible(element)); }
    ready() { return C.flowURL(this.location.href); }
    requireVisible() {
      // A paired background tab is supported. Individual controls must still
      // be rendered and checked; document.visibilityState is not a UI lock.
      if (!this.ready()) throw new WaitingUser('Tab đã rời Google Flow.');
    }
    generating() { return this.all('[role="progressbar"], mat-progress-spinner, [aria-busy="true"], [data-state="generating"]').some(element => this.visible(element)); }
    async click(element, semantic, context) {
      if (!this.visible(element) || element.disabled || element.getAttribute?.('aria-disabled') === 'true') throw new WaitingUser('Nút Flow chưa sẵn sàng.');
      element.scrollIntoView?.({block: 'center', inline: 'center'});
      await context.check(true);
      if (context.click) await context.click(element, semantic); else element.click();
    }
    blockers() {
      const captcha = this.all('iframe').some(element => /recaptcha|captcha/i.test(element.src || '') && this.visible(element));
      if (captcha) throw new WaitingUser('Google yêu cầu xác minh CAPTCHA. Tự hoàn tất trên Flow; SiteCraft không tự gửi lại lượt này.', 'CAPTCHA');
      const alert = this.all(SELECTORS.alert).find(element => this.visible(element) && /quota|limit|try again|error|giới hạn|hết lượt|quá nhiều|không thể|lỗi/i.test(element.innerText || element.textContent || ''));
      if (alert) throw new WaitingUser('Flow báo lỗi hoặc giới hạn tài khoản. Xem thông báo trên Flow, rồi nhập ảnh thủ công hoặc tạo lượt mới.', 'FLOW_QUOTA_OR_ERROR');
      const dialog = this.all(SELECTORS.dialog).find(element => this.visible(element) && /agree|accept|đồng ý|điều khoản|sign in|đăng nhập/i.test(element.innerText || element.textContent || ''));
      if (dialog) throw new WaitingUser('Flow cần đăng nhập hoặc xác nhận điều khoản. Tự xử lý hộp thoại trên Flow rồi tạo lượt mới.', 'FLOW_AUTH_OR_CONSENT');
    }
    async waitFor(predicate, timeout, context, interval = 400) {
      const deadline = this.now() + timeout;
      while (this.now() < deadline) {
        await context.check(); this.blockers();
        const value = await predicate(); if (value) return value;
        await this.sleep(Math.min(interval, Math.max(1, deadline - this.now())));
      }
      throw new WaitingUser('Không xác nhận được bước hiện tại trên Flow. Kiểm tra trang và dùng Nhập ảnh trong SiteCraft; lượt này không tự gửi lại.', 'FLOW_UI_CHANGED');
    }
    snapshot() {
      const steps = this.all(SELECTORS.history);
      return {historyCount: steps.length, keys: new Set(this.all('img').map(mediaKey).filter(Boolean)), page: canonicalPage(this.location.href)};
    }
    resultCandidate(baseline) {
      if (canonicalPage(this.location.href) !== baseline.page) throw new WaitingUser('Trang Flow đã chuyển sang ảnh hoặc dự án khác. Chọn đúng kết quả rồi nhập ảnh thủ công.', 'FLOW_PAGE_CHANGED');
      const steps = this.all(SELECTORS.history).slice(baseline.historyCount);
      const candidates = [];
      for (const step of steps) {
        const images = this.all('img', step).filter(image => image.complete && Math.min(image.naturalWidth || 0, image.naturalHeight || 0) >= 128 &&
          !image.closest?.('flow-ingredient-chip, .ingredients-list') && mediaKey(image) && !baseline.keys.has(mediaKey(image)));
        if (!images.length) continue;
        const text = String(step.getAttribute?.('data-prompt') || step.innerText || step.textContent || '').replace(/\s+/g, ' ').trim();
        const source = step.getAttribute?.('data-source-media-id') || step.getAttribute?.('data-input-media-id');
        if (source && source !== baseline.sourceMediaId) throw new WaitingUser('Flow hiển thị kết quả của ảnh nguồn khác. Nhập đúng ảnh kết quả thủ công.', 'FLOW_AMBIGUOUS_RESULT');
        const routeId = new URL(baseline.page).pathname.match(/\/edit\/([^/]+)\/?$/)?.[1];
        const inputMatches = this.all('img', step).some(image => mediaId(image) === baseline.sourceMediaId);
        if (!(source === baseline.sourceMediaId || inputMatches || routeId === baseline.sourceMediaId)) throw new WaitingUser('Flow không hiển thị mã nguồn đủ rõ để xác nhận ảnh thuộc lượt này. Chọn đúng kết quả và nhập thủ công.', 'FLOW_AMBIGUOUS_RESULT');
        if (!baseline.promptText || !text.includes(baseline.promptText)) throw new WaitingUser('Flow có ảnh mới nhưng không hiển thị thông tin đủ để gắn với lệnh này. Tải đúng kết quả rồi chọn Nhập ảnh trong SiteCraft.', 'FLOW_AMBIGUOUS_RESULT');
        candidates.push(...images);
      }
      const unique = [...new Map(candidates.map(image => [mediaKey(image), image])).values()];
      if (unique.length > 1) throw new WaitingUser('Có nhiều ảnh mới trên Flow. Chọn đúng ảnh rồi nhập thủ công để tránh lấy nhầm lượt.', 'FLOW_AMBIGUOUS_RESULT');
      return unique[0] || null;
    }
    makeFile(asset, name) {
      const parsed = C.parseImage(asset.data_url);
      const extension = parsed.mime === 'image/jpeg' ? 'jpg' : parsed.mime.split('/')[1];
      return new this.File([parsed.bytes], name + '.' + extension, {type: parsed.mime});
    }
    fileTransfer(files) {
      if (!this.DataTransfer) throw new WaitingUser('Trình duyệt không hỗ trợ chuyển ảnh. Tải ảnh nguồn từ SiteCraft rồi tải lên Flow thủ công.');
      const transfer = new this.DataTransfer(); files.forEach(file => transfer.items.add(file)); return transfer;
    }
    dispatchFiles(files, target) {
      const transfer = this.fileTransfer(files);
      const component = target.closest?.('flow-edit-image-prompt-box, flow-base-prompt-box') || target;
      const inputs = this.all('input[type="file"]', component).filter(element => !element.disabled && (!element.accept || /image|\*/.test(element.accept)));
      if (inputs.length > 1) throw new WaitingUser('Có nhiều ô tải tệp trong Flow. Chọn đúng ô bằng tay; SiteCraft không tự chọn ô không rõ mục đích.');
      const input = inputs[0];
      if (input) {
        input.files = transfer.files;
        input.dispatchEvent(new this.window.Event('input', {bubbles: true}));
        input.dispatchEvent(new this.window.Event('change', {bubbles: true}));
        return;
      }
      target.focus?.();
      try { target.dispatchEvent(new this.window.ClipboardEvent('paste', {clipboardData: transfer, bubbles: true, cancelable: true})); }
      catch {
        const dropTarget = this.document.querySelector('cdk-virtual-scroll-viewport, .tiles-container, main') || target;
        for (const type of ['dragenter', 'dragover', 'drop']) dropTarget.dispatchEvent(new this.window.DragEvent(type, {dataTransfer: transfer, bubbles: true, cancelable: true}));
      }
    }
    async uploadSource(job, context) {
      this.requireVisible(); await context.report('uploading', 'Đang tải ảnh nguồn lên dự án Flow đã chọn.');
      if (/\/edit\//.test(this.location.pathname || '')) {
        const project = this.location.pathname.split('/edit/')[0];
        const link = this.all('a[href]').find(element => {
          try { return new URL(element.href, this.location.href).pathname === project && this.visible(element); } catch { return false; }
        });
        const back = link || this.all('button').find(element => this.visible(element) && /^(back to project|quay lại dự án|arrow_back)$/i.test(((element.getAttribute('aria-label') || '') + ' ' + (element.innerText || '')).trim()));
        if (!back) throw new WaitingUser('Quay về trang dự án Flow trước khi tải nguồn mới, rồi tạo lượt mới trong SiteCraft. Không dùng ảnh đang chỉnh làm nguồn nhầm.');
        await this.click(back, 'back_project', context);
        await this.waitFor(() => !/\/edit\//.test(this.location.pathname || ''), 8000, context);
      }
      const input = await this.waitFor(() => this.prompt(), 12000, context);
      const baseline = this.snapshot();
      const file = this.makeFile(job.source, 'sitecraft_' + job.id + '_source');
      await context.check(true); this.dispatchFiles([file], input);
      const image = await this.waitFor(() => this.all(SELECTORS.grid).find(image => {
        const tile = image.closest?.('flow-grid-tile-container');
        const name = tile?.getAttribute('aria-label') || image.alt || image.title || '';
        return image.complete && mediaId(image) && !baseline.keys.has(mediaKey(image)) && name.includes(file.name);
      }), 45000, context);
      return image;
    }
    async openMedia(image, context) {
      this.requireVisible(); await context.check(true);
      const id = mediaId(image);
      if (!id) throw new WaitingUser('Flow không cung cấp mã ảnh rõ ràng. Mở đúng ảnh bằng tay rồi nhập kết quả trong SiteCraft.');
      if (/\/edit\//.test(this.location.pathname || '') && image.closest?.('div.history-step')) return id;
      await this.click(image.closest?.('flow-grid-tile-container') || image, 'open_source', context);
      await this.waitFor(() => this.document.querySelector('flow-edit-image-prompt-box .ProseMirror[role="textbox"]'), 15000, context);
      return id;
    }
    async references(job, context) {
      if (!job.references?.length) return;
      if (job.references.length > 4) throw new WaitingUser('Chỉ hỗ trợ tối đa 4 ảnh tham chiếu.');
      await context.report('references', 'Đang thêm ảnh tham chiếu vào Flow.');
      this.requireVisible(); await context.check(true);
      const countIngredients = () => new Set(this.all(SELECTORS.ingredients).map(element => element.closest?.('flow-ingredient-chip') || element)).size;
      const prompt = this.prompt(), count = countIngredients();
      if (!prompt) throw new WaitingUser('Không thấy ô nhập ảnh tham chiếu trong Flow.');
      this.dispatchFiles(job.references.map((asset, index) => this.makeFile(asset, 'sitecraft_' + job.id + '_ref_' + index)), prompt);
      await this.waitFor(() => countIngredients() >= count + job.references.length, 45000, context);
    }
    fillPrompt(value) {
      const target = this.prompt();
      if (!target) throw new WaitingUser('Không thấy ô lệnh Flow. Mở dự án và ảnh nguồn trước.');
      target.focus();
      const selection = this.window.getSelection?.();
      if (selection && this.document.createRange) {
        const range = this.document.createRange(); range.selectNodeContents(target);
        selection.removeAllRanges(); selection.addRange(range);
      }
      const inserted = this.document.execCommand?.('insertText', false, value);
      if (!inserted) {
        target.textContent = value;
        target.dispatchEvent(new this.window.InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
      }
      if (String(target.textContent || '').replace(/\s+/g, ' ').trim() !== value.replace(/\s+/g, ' ').trim()) throw new WaitingUser('Flow chưa nhận câu lệnh. Kiểm tra ô nhập trên Flow.');
      return target;
    }
    generateButton(prompt) {
      const root = prompt.closest?.('flow-edit-image-prompt-box') || prompt.parentElement;
      if (!root) return null;
      const buttons = this.all('button', root).filter(button => this.visible(button) && !button.disabled && button.getAttribute('aria-disabled') !== 'true' &&
        /generate|create|send|bắt đầu tạo|tạo ảnh|tạo|arrow_forward/i.test((button.getAttribute('aria-label') || '') + ' ' + (button.innerText || button.textContent || '')));
      return buttons.length === 1 ? buttons[0] : null;
    }
    async readImage(value, context) {
      let dataURL = value;
      if (!String(value).startsWith('data:')) {
        if (!C.imageURL(value, this.location.origin)) throw new WaitingUser('Nguồn ảnh trả về không được phép. Tải ảnh trên Flow rồi nhập thủ công.');
        if (String(value).startsWith('blob:')) {
          const response = await this.fetcher(value);
          const blob = await response.blob();
          if (blob.size > C.MAX_IMAGE_BYTES) throw new WaitingUser('Ảnh kết quả vượt 32 MiB.');
          dataURL = C.bytesURL(new Uint8Array(await blob.arrayBuffer()), blob.type);
        } else dataURL = await context.fetchImage(value);
      }
      const parsed = C.parseImage(dataURL);
      let bitmap;
      try { bitmap = await this.bitmap(new Blob([parsed.bytes], {type: parsed.mime})); }
      catch { throw new WaitingUser('Flow chưa trả một ảnh hợp lệ. Tải kết quả và nhập thủ công.'); }
      const dimensions = {width: bitmap.width, height: bitmap.height}; bitmap.close?.();
      if (Math.min(dimensions.width, dimensions.height) < 16 || Math.max(dimensions.width, dimensions.height) > 32768 || dimensions.width * dimensions.height > 100000000) throw new WaitingUser('Kích thước ảnh kết quả không được hỗ trợ.');
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', parsed.bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
      return {dataURL, hash, ...dimensions};
    }
    async render(job, context) {
      const uploaded = await this.uploadSource(job, context);
      await this.openMedia(uploaded, context); await this.references(job, context);
      await context.report('filling', 'Đang điền yêu cầu render vào Flow.');
      this.requireVisible(); await context.check(true);
      const prompt = this.fillPrompt(C.composePrompt(job));
      const button = this.generateButton(prompt);
      if (!button) throw new WaitingUser('Ảnh và lệnh đã sẵn sàng nhưng không xác định được duy nhất nút Tạo. Kiểm tra Flow, bấm Tạo một lần nếu cần rồi nhập kết quả trong SiteCraft.');
      if (this.generating()) throw new WaitingUser('Flow đang xử lý lượt khác. Chờ lượt đó xong rồi tạo một lượt SiteCraft mới.');
      const baseline = this.snapshot();
      baseline.sourceMediaId = mediaId(uploaded);
      baseline.promptText = String(job.prompt || '').replace(/\s+/g, ' ').trim().slice(0, 100);
      await context.intent(baseline);
      await context.report('submission_intent', 'Đang gửi một yêu cầu tạo ảnh trên Flow.');
      this.requireVisible(); await this.click(button, 'generate', context);
      await context.report('submitted', 'Đã bấm Tạo trên Flow. Đang chờ đúng ảnh mới; không tự bấm lại.');
      const candidate = await this.waitFor(() => this.resultCandidate(baseline), 240000, context, 1000);
      await context.report('receiving', 'Đang nhận ảnh mới của lượt Flow này.');
      const output = await this.readImage(candidate.currentSrc || candidate.src, context);
      if ([job.source, ...(job.references || [])].some(asset => asset.sha256 && asset.sha256 === output.hash)) throw new WaitingUser('Ảnh nhận được trùng ảnh đầu vào. SiteCraft chưa xác nhận được kết quả mới; hãy nhập đúng ảnh từ Flow.');
      return {images: [output.dataURL], flow: {page_url: canonicalPage(this.location.href), media_id: mediaId(candidate)}};
    }
    async upscale(job, context) {
      this.requireVisible();
      let image = job.flow?.media_id ? this.all(SELECTORS.grid + ', div.history-step img').find(image => mediaId(image) === job.flow.media_id) : null;
      if (job.flow?.media_id && !image) {
        image = await this.waitFor(() => this.all(SELECTORS.grid + ', div.history-step img').find(image => mediaId(image) === job.flow.media_id), 15000, context);
      }
      if (!image) image = await this.uploadSource(job, context);
      const id = await this.openMedia(image, context);
      await context.report('download_menu', 'Đang mở menu tải 2K của đúng ảnh nguồn. Không tạo ảnh mới.');
      this.requireVisible(); await context.check(true);
      const exact = this.all('img').find(image => mediaId(image) === id && this.visible(image));
      if (!exact) throw new WaitingUser('Không xác nhận được đúng ảnh nguồn đang mở. Chọn ảnh trên Flow rồi tải 2K và nhập thủ công.');
      await this.click(exact, 'open_source', context);
      const download = await this.waitFor(() => this.all('button').find(button => this.visible(button) && /download media|tải nội dung nghe nhìn xuống/i.test(button.getAttribute('aria-label') || '')), 8000, context);
      await this.click(download, 'download', context);
      const choice = await this.waitFor(() => this.all(SELECTORS.menu).find(element => this.visible(element) && /(^|\s)2K(\s|$)/i.test((element.innerText || element.textContent || '').trim())), 5000, context);
      if (choice.disabled || choice.getAttribute('aria-disabled') === 'true') throw new WaitingUser('Flow không cho tải 2K với ảnh/tài khoản này. Không có lượt tạo ảnh thay thế.');
      await context.armDownload(id); await context.check(true);
      await this.click(choice, 'download_2k', context);
      await context.report('upscale_download', 'Đã chọn tải 2K trên Flow. Đang chờ tệp ảnh; đây không phải tiến độ phần trăm.');
      const captured = await this.waitFor(() => context.takeDownload(), 180000, context, 750);
      if (captured.error) throw new WaitingUser(captured.error, 'FLOW_AMBIGUOUS_DOWNLOAD');
      if (captured.name && !/\.(png|jpe?g|webp)$/i.test(captured.name)) throw new WaitingUser('Tệp tải về không có định dạng ảnh được hỗ trợ.');
      const output = await this.readImage(captured.data_url || captured.url, context);
      const source = job.source;
      if (source.width && source.height && (Math.max(output.width, output.height) <= Math.max(source.width, source.height) || Math.abs(output.width / output.height / (source.width / source.height) - 1) > .02)) throw new WaitingUser('Ảnh 2K không tăng kích thước hoặc đã đổi tỷ lệ so với nguồn. Giữ ảnh gốc; không báo upscale thành công.');
      return {images: [output.dataURL], flow: {page_url: canonicalPage(this.location.href), media_id: id}};
    }
    async run(job, context) {
      if (!this.ready()) throw new WaitingUser('Tab này không phải Google Flow.');
      this.blockers();
      return job.operation === 'upscale' ? this.upscale(job, context) : this.render(job, context);
    }
  }
  const api = {FlowDOM, WaitingUser, Cancelled, SELECTORS, mediaId, mediaKey, canonicalPage};
  scope.SiteCraftFlowDOM = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof self !== 'undefined' ? self : globalThis);
