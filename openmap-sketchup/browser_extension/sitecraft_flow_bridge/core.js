/* SiteCraft Flow Bridge. New MIT code; no vendor implementation or credentials. */
(function (scope) {
  'use strict';
  const MAX_IMAGE_BYTES = 32 * 1024 * 1024;
  const ID = /^[a-f0-9]{32}$/;
  class BridgeError extends Error {
    constructor(message, status = 0) { super(message); this.status = status; }
  }
  function port(value) {
    const number = Number(value);
    if (!Number.isInteger(number) || number < 17865 || number > 17872) throw new BridgeError('Cổng phải từ 17865 đến 17872.');
    return number;
  }
  function flowURL(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password || url.port) return false;
      return url.hostname === 'flow.google.com' || (url.hostname === 'labs.google' && /^\/fx\/(?:[a-z-]+\/)?tools\/flow(?:\/|$)/i.test(url.pathname));
    } catch { return false; }
  }
  function imageURL(value, origin) {
    try {
      const url = new URL(value);
      if (url.protocol === 'blob:') return Boolean(origin && url.origin === origin);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port &&
        (/(^|\.)googleusercontent\.com$/.test(url.hostname) || /(^|\.)flow-content\.google$/.test(url.hostname) || url.hostname === 'storage.googleapis.com');
    } catch { return false; }
  }
  function flowPage(value) {
    if (!flowURL(value)) throw new BridgeError('Chỉ được mở lại trang ảnh/dự án Google Flow.');
    const url = new URL(value);
    if (url.hostname === 'flow.google.com' && !/^\/project\/[A-Za-z0-9_-]+(?:\/edit\/[A-Za-z0-9_-]+)?\/?$/.test(url.pathname)) throw new BridgeError('Đường dẫn dự án Flow không hợp lệ.');
    if (url.hostname === 'labs.google' && !/^\/fx\/(?:[a-z-]+\/)?tools\/flow(?:\/[A-Za-z0-9_-]+)*\/?$/i.test(url.pathname)) throw new BridgeError('Đường dẫn dự án Flow không hợp lệ.');
    url.search = ''; url.hash = ''; return url.href;
  }
  function clickPoint(rect) {
    if (!rect || !['x', 'y', 'width', 'height', 'viewportWidth', 'viewportHeight'].every(key => typeof rect[key] === 'number' && Number.isFinite(rect[key]))) throw new BridgeError('Tọa độ nút Flow không hợp lệ.');
    if (rect.width < 2 || rect.height < 2 || rect.width > rect.viewportWidth || rect.height > rect.viewportHeight || rect.viewportWidth < 16 || rect.viewportHeight < 16 || rect.viewportWidth > 32768 || rect.viewportHeight > 32768) throw new BridgeError('Nút Flow nằm ngoài khung trang.');
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    if (x < 0 || y < 0 || x >= rect.viewportWidth || y >= rect.viewportHeight) throw new BridgeError('Nút Flow nằm ngoài khung trang.');
    return {x, y};
  }
  function randomID() {
    return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  function parseImage(value) {
    if (typeof value !== 'string' || value.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4 + 100) throw new BridgeError('Ảnh quá lớn. Giới hạn 32 MiB mỗi ảnh.');
    const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$/.exec(value);
    if (!match || match[2].length % 4) throw new BridgeError('Ảnh phải là PNG, JPEG hoặc WebP dạng base64.');
    let binary;
    try { binary = atob(match[2]); } catch { throw new BridgeError('Dữ liệu ảnh base64 không hợp lệ.'); }
    if (binary.length < 12 || binary.length > MAX_IMAGE_BYTES) throw new BridgeError('Kích thước tệp ảnh không hợp lệ.');
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const png = [137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value);
    const jpeg = bytes[0] === 255 && bytes[1] === 216;
    const webp = binary.slice(0, 4) === 'RIFF' && binary.slice(8, 12) === 'WEBP';
    if (!(match[1] === 'image/png' && png || match[1] === 'image/jpeg' && jpeg || match[1] === 'image/webp' && webp)) throw new BridgeError('Định dạng ảnh không khớp nội dung tệp.');
    return {mime: match[1], bytes};
  }
  function composePrompt(job) {
    if (job.options?.prompt_is_complete === true) return String(job.prompt || '');
    if (job.operation === 'upscale') return '';
    const parts = [String(job.prompt || '').trim()];
    const options = job.options || {};
    if (options.keep_design) parts.push('Giữ nguyên hình khối kiến trúc và vị trí các bộ phận công trình trong ảnh nguồn.');
    if (options.keep_camera) parts.push('Giữ nguyên vị trí máy ảnh, hướng nhìn và phối cảnh của ảnh nguồn.');
    if (options.aspect) parts.push('Tỷ lệ ảnh kết quả: ' + String(options.aspect).slice(0, 32) + '.');
    if (typeof options.preset === 'string' && options.preset.trim()) parts.push('Phong cách mong muốn: ' + options.preset.slice(0, 300) + '.');
    const notes = String(job.annotation_notes || '').trim();
    if (notes && !parts[0].includes(notes)) parts.push('Hướng dẫn theo vùng đánh dấu:\n' + notes);
    return parts.filter(Boolean).join('\n\n');
  }
  function bytesURL(bytes, mime) {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 16384) binary += String.fromCharCode(...bytes.subarray(offset, offset + 16384));
    return 'data:' + mime + ';base64,' + btoa(binary);
  }
  async function fetchImage(url, fetcher = fetch) {
    if (!imageURL(url)) throw new BridgeError('Địa chỉ ảnh không thuộc nguồn ảnh Google được phép.');
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetcher(url, {credentials: 'include', redirect: 'error', cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new BridgeError('Không tải được ảnh kết quả từ Flow.');
      const mime = (response.headers.get('Content-Type') || '').split(';')[0].toLowerCase();
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(mime)) throw new BridgeError('Flow chưa trả tệp PNG/JPEG/WebP.');
      if (Number(response.headers.get('Content-Length') || 0) > MAX_IMAGE_BYTES) throw new BridgeError('Ảnh kết quả vượt 32 MiB.');
      const chunks = []; let length = 0;
      if (response.body?.getReader) {
        const reader = response.body.getReader();
        try {
          for (;;) {
            const next = await reader.read(); if (next.done) break;
            length += next.value.length;
            if (length > MAX_IMAGE_BYTES) throw new BridgeError('Ảnh kết quả vượt 32 MiB.');
            chunks.push(next.value);
          }
        } finally { await reader.cancel().catch(() => {}); }
      } else {
        const bytes = new Uint8Array(await response.arrayBuffer()); length = bytes.length; chunks.push(bytes);
        if (length > MAX_IMAGE_BYTES) throw new BridgeError('Ảnh kết quả vượt 32 MiB.');
      }
      const bytes = new Uint8Array(length); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      const result = bytesURL(bytes, mime); parseImage(result); return result;
    } finally { clearTimeout(timer); }
  }
  async function request(config, path, body, fetcher = fetch, timeout = 15000) {
    port(config.port);
    if (!/^\/(?:health|pair|heartbeat|jobs\/claim|jobs\/[a-f0-9]{32}\/(?:progress|complete|fail))$/.test(path)) throw new BridgeError('Đường dẫn bridge không hợp lệ.');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const headers = {'Content-Type': 'application/json'};
      if (config.token && path !== '/pair' && path !== '/health') headers.Authorization = 'Bearer ' + config.token;
      const response = await fetcher('http://127.0.0.1:' + config.port + path, {
        method: body === undefined ? 'GET' : 'POST', headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: 'omit', redirect: 'error', cache: 'no-store', signal: controller.signal
      });
      const declared = Number(response.headers?.get('Content-Length') || 0);
      if (declared > 72 * 1024 * 1024) throw new BridgeError('Phản hồi bridge quá lớn.');
      const text = await response.text();
      if (text.length > 72 * 1024 * 1024) throw new BridgeError('Phản hồi bridge quá lớn.');
      let data;
      try { data = JSON.parse(text); } catch { throw new BridgeError('Bridge trả JSON không hợp lệ.', response.status); }
      if (!response.ok) throw new BridgeError(String(data.error || 'Bridge không nhận yêu cầu.').slice(0, 400), response.status);
      return data;
    } catch (error) {
      if (error instanceof BridgeError) throw error;
      throw new BridgeError(error.name === 'AbortError' ? 'Hết thời gian kết nối SiteCraft.' : 'Không kết nối được SiteCraft. Mở Render AI trong SketchUp.');
    } finally { clearTimeout(timer); }
  }
  const api = {ID, MAX_IMAGE_BYTES, BridgeError, port, flowURL, flowPage, imageURL, clickPoint, randomID, parseImage, composePrompt, bytesURL, fetchImage, request};
  scope.SiteCraftBridgeCore = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof self !== 'undefined' ? self : globalThis);
