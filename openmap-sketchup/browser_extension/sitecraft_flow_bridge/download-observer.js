/* Temporary observer for a user-requested Flow 2K download. Runs in MAIN world.
 * It observes image bytes only; no extension credentials are passed here. */
(function () {
  'use strict';
  if (window.SiteCraftFlowDownload?.version === 1) return;
  let active = null, restore = null;
  function allowed(value) {
    try {
      const url = new URL(value, location.href);
      return url.protocol === 'blob:' && url.origin === location.origin || url.protocol === 'data:' && /^data:image\/(png|jpeg|webp);base64,/.test(value) ||
        url.protocol === 'https:' && !url.username && !url.password && (/(^|\.)googleusercontent\.com$/.test(url.hostname) || /(^|\.)flow-content\.google$/.test(url.hostname) || url.hostname === 'storage.googleapis.com');
    } catch { return false; }
  }
  function disarm() { if (restore) restore(); restore = null; active = null; }
  function arm(settings) {
    disarm();
    if (!/^[a-f0-9]{32}$/.test(settings?.nonce || '')) return;
    const state = {nonce: settings.nonce, mediaId: String(settings.mediaId || ''), seen: new Set()}; active = state;
    const original = HTMLAnchorElement.prototype.click;
    async function observe(anchor) {
      if (active !== state || !(anchor instanceof HTMLAnchorElement)) return;
      const url = anchor.href, name = String(anchor.download || '').slice(0, 250);
      if (!allowed(url) || !/\.(png|jpe?g|webp)$/i.test(name) || state.seen.has(url)) return;
      // Accept only a positive media association. A generic image.png from a
      // different background download is never guessed to be this result.
      const identifier = state.mediaId.toLowerCase(), filename = name.toLowerCase();
      if (identifier.length < 8 || !(filename.includes(identifier.slice(0, 8)) || url.toLowerCase().includes(identifier))) {
        window.postMessage({source: 'sitecraft-flow-download', nonce: state.nonce,
          error: 'Flow tải tệp nhưng không gắn mã ảnh đủ rõ. Chọn đúng tệp vừa tải và nhập ảnh thủ công trong SiteCraft.', name}, location.origin);
        return;
      }
      state.seen.add(url);
      try {
        if (/^data:image\//.test(url)) { window.postMessage({source: 'sitecraft-flow-download', nonce: state.nonce, data_url: url, name}, location.origin); return; }
        if (!url.startsWith('blob:')) { window.postMessage({source: 'sitecraft-flow-download', nonce: state.nonce, url, name}, location.origin); return; }
        const response = await fetch(url), blob = await response.blob();
        if (blob.size > 32 * 1024 * 1024 || !/^image\/(png|jpeg|webp)$/.test(blob.type)) return;
        const reader = new FileReader();
        reader.onload = () => { if (active === state) window.postMessage({source: 'sitecraft-flow-download', nonce: state.nonce, data_url: reader.result, name}, location.origin); };
        reader.readAsDataURL(blob);
      } catch { /* Downloads-folder/manual import remains available. */ }
    }
    const handler = event => { const anchor = event.target?.closest?.('a[download]'); if (anchor) observe(anchor); };
    const wrapped = function () { observe(this); return original.apply(this, arguments); };
    HTMLAnchorElement.prototype.click = wrapped;
    document.addEventListener('click', handler, true);
    const timer = setTimeout(disarm, Math.min(180000, Math.max(1000, Number(settings.timeout) || 180000)));
    restore = () => { clearTimeout(timer); document.removeEventListener('click', handler, true); if (HTMLAnchorElement.prototype.click === wrapped) HTMLAnchorElement.prototype.click = original; };
  }
  window.SiteCraftFlowDownload = Object.freeze({version: 1, arm, disarm});
})();
