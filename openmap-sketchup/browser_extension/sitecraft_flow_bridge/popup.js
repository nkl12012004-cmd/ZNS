'use strict';
const element = id => document.getElementById(id);
for (let port = 17865; port <= 17872; port++) element('port').add(new Option(String(port), String(port)));
async function command(type, args = {}) {
  const response = await chrome.runtime.sendMessage({sitecraft: 1, type, ...args});
  if (!response?.ok) throw new Error(response?.error || 'Không kết nối được tiện ích.');
  return response.data;
}
function display(state) {
  element('port').value = state.port;
  element('status').className = '';
  element('status').textContent = (state.paired ? 'Đã ghép nối' : 'Chưa ghép nối') +
    (state.enabled && state.tab ? '\nTab: ' + state.tab.title : '\nChưa chọn tab Flow') +
    (state.active ? '\nĐang xử lý: ' + state.active.phase : '') + (state.message ? '\n' + state.message : '');
  element('auto-open').checked = Boolean(state.auto_open);
  element('trusted').textContent = state.trusted_mode ? 'Tắt cú bấm nền' : 'Cho phép thao tác nền';
  element('mode-status').textContent = state.trusted_mode ? 'Cú bấm nền: bật cho đúng tab Flow đã ghép.' : 'Cú bấm nền: chưa bật. Tệp không xác nhận được vẫn có thể nhập trong SiteCraft.';
}
async function action(callback) {
  for (const button of document.querySelectorAll('button')) button.disabled = true;
  try { const result = await callback(); if (result) display(result); }
  catch (error) { element('status').className = 'error'; element('status').textContent = error.message; }
  finally { for (const button of document.querySelectorAll('button')) button.disabled = false; }
}
element('pair-form').addEventListener('submit', event => {
  event.preventDefault(); action(async () => { const state = await command('PAIR', {code: element('code').value.trim(), port: Number(element('port').value)}); element('code').value = ''; return state; });
});
element('connect').addEventListener('click', () => action(async () => {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tabs[0]) throw new Error('Mở tab Flow rồi thử lại.');
  return command('CONNECT', {tabId: tabs[0].id});
}));
element('disconnect').addEventListener('click', () => action(() => command('DISCONNECT')));
for (const [id, permission] of [['trusted', 'debugger']]) {
  element(id).addEventListener('click', () => {
    // request() must be called directly in this explicit user gesture.
    const disabling = element(id).textContent.startsWith('Tắt');
    const grant = disabling ? Promise.resolve(false) : chrome.permissions.request({permissions: [permission]});
    action(async () => command('MODES', {trusted: Boolean(await grant)}));
  });
}
element('auto-open').addEventListener('change', () => action(() => command('MODES', {auto_open: element('auto-open').checked})));
element('find').addEventListener('click', () => action(async () => {
  const result = await command('FIND');
  if (!result.ports.length) throw new Error('Chưa tìm thấy SiteCraft. Mở Render AI trong SketchUp.');
  element('port').value = result.ports[0]; element('status').textContent = 'Đã tìm thấy cổng ' + result.ports.join(', ') + '. Nhập mã tương ứng từ SketchUp.';
}));
action(() => command('POPUP_STATUS'));
