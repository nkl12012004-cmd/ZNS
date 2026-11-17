/* Offline tests for original SiteCraft bridge code. Never contacts Google. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const directory = path.resolve(__dirname, '../browser_extension/sitecraft_flow_bridge');
const C = require(path.join(directory, 'core.js'));
const {BridgeWorker, STORAGE} = require(path.join(directory, 'worker.js'));
const D = require(path.join(directory, 'flow-dom.js'));
const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6vL8AAAAASUVORK5CYII=';
const A = 'a'.repeat(32), B = 'b'.repeat(32), SESSION = 'c'.repeat(32), LEASE = 'test-lease-'.repeat(4);
const tests = [];
function test(name, body) { tests.push([name, body]); }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function response(data, status = 200) { return {ok: status < 400, status, headers: {get: () => null}, text: async () => JSON.stringify(data)}; }
function chromeMock(saved = {}) {
  const stored = {[STORAGE]: {...saved}}, sent = [], scripts = [], updates = [], creates = [], removed = [];
  const tabs = new Map([[1, {id: 1, url: 'https://flow.google.com/project/one', title: 'Flow one'}], [2, {id: 2, url: 'https://flow.google.com/project/two', title: 'Flow two'}]]);
  let activeId = null;
  const chrome = {runtime: {id: 'a'.repeat(32)},
    storage: {local: {get: async () => structuredClone(stored), set: async data => Object.assign(stored, structuredClone(data))}},
    tabs: {get: async id => { if (!tabs.has(id)) throw Error('gone'); return tabs.get(id); },
      sendMessage: async (id, input) => {
        sent.push({id, ...input});
        if (input.type === 'STATUS') return {ok: true, visible: true, ready: true, page_url: tabs.get(id)?.url, generating: false, running: Boolean(activeId), jobId: activeId};
        if (input.type === 'START') activeId = input.job.id;
        if (input.type === 'CANCEL') activeId = null;
        return {ok: true};
      }, update: async (id, values) => { updates.push({id, values}); const tab = tabs.get(id); if (!tab) throw Error('gone'); Object.assign(tab, values); return tab; },
      create: async values => { const tab = {id: 3, title: 'Flow restored', ...values}; creates.push(values); tabs.set(3, tab); return tab; },
      remove: async id => { removed.push(id); tabs.delete(id); }},
    scripting: {executeScript: async input => { scripts.push(input); return []; }}};
  return {chrome, stored, sent, scripts, tabs, updates, creates, removed, setActive: value => { activeId = value; }};
}
function saved(extra = {}) { return {port: 17865, clientId: A, token: 'offline-test-token-'.repeat(3), enabled: true, tabId: 1, session: SESSION, pending: null, ...extra}; }
function job(extra = {}) { return {id: A, lease: LEASE, operation: 'render', prompt: 'Render this building', options: {}, source: {id: B, data_url: PNG, width: 512, height: 512}, references: [], ...extra}; }
function sender(tabId = 1, url = 'https://flow.google.com/project/one') { return {id: 'a'.repeat(32), tab: {id: tabId, url}}; }
function message(type, extra = {}) { return {type, sitecraft: 1, session: SESSION, jobId: A, ...extra}; }
function fakeNetwork(jobs = []) {
  const requests = [];
  const fetcher = async (url, options = {}) => {
    requests.push({url, options, body: options.body ? JSON.parse(options.body) : null});
    if (url.endsWith('/jobs/claim')) return response({job: jobs.shift() || null});
    if (url.endsWith('/pair')) return response({token: 'offline-test-token-'.repeat(3), port: 17865, protocol: 1});
    if (url.endsWith('/health')) return response({name: 'SiteCraft AI Bridge', protocol: 1});
    return response({ok: true, job: {id: A, state: url.endsWith('/complete') ? 'complete' : 'running'}});
  };
  return {fetcher, requests};
}
const pending = () => ({id: A, lease: LEASE, tabId: 1, phase: 'submitted', started: Date.now()});

test('URL/port boundaries reject outside services and credentials', () => {
  for (const value of [17865, 17872, '17870']) assert.ok(C.port(value));
  for (const value of [0, 8877, 17873, '17865/path', 17865.5]) assert.throws(() => C.port(value));
  assert.ok(C.flowURL('https://flow.google.com/project/a/edit/b'));
  assert.ok(C.flowURL('https://labs.google/fx/vi/tools/flow/project/a'));
  for (const value of ['http://flow.google.com/', 'https://flow.google.com.evil.test/', 'https://evil@flow.google.com/', 'https://labs.google/not-flow']) assert.equal(C.flowURL(value), false);
  assert.ok(C.imageURL('https://lh3.googleusercontent.com/result.png'));
  for (const value of ['https://evil.test/image.png', 'file:///etc/passwd', 'http://storage.googleapis.com/image']) assert.equal(C.imageURL(value), false);
  assert.ok(C.imageURL('blob:https://flow.google.com/test', 'https://flow.google.com'));
  assert.equal(C.imageURL('blob:https://other.test/test', 'https://flow.google.com'), false);
});
test('image signatures and annotation prompt are validated without hidden vendor text', () => {
  assert.equal(C.parseImage(PNG).mime, 'image/png');
  assert.throws(() => C.parseImage('data:text/html;base64,PGh0bWw+'));
  assert.throws(() => C.parseImage(PNG.replace('image/png', 'image/jpeg')));
  const prompt = C.composePrompt(job({annotation_notes: 'Vùng đỏ: cây', options: {keep_design: true, keep_camera: true}}));
  assert.equal(prompt.split('Vùng đỏ: cây').length, 2);
  assert.match(prompt, /hình khối kiến trúc/); assert.match(prompt, /vị trí máy ảnh/);
  assert.equal(C.composePrompt(job({operation: 'upscale'})), '');
  assert.equal(C.composePrompt(job({prompt: 'Vùng đỏ: cây', annotation_notes: 'Vùng đỏ: cây'})).split('Vùng đỏ: cây').length, 2);
});
test('a complete prompt is sent verbatim with no second annotations/preset/instruction block', () => {
  const prompt = '  Exact preview\nVùng đỏ: cây\nKeep this wording.\n';
  assert.equal(C.composePrompt(job({prompt, annotation_notes: 'Vùng đỏ: cây', options: {prompt_is_complete: true, keep_design: true, keep_camera: true, aspect: '16:9', preset: 'architecture'}})), prompt);
});
test('stored Flow navigation targets and click coordinates are restricted', () => {
  assert.equal(C.flowPage('https://flow.google.com/project/p/edit/m?tracking=x#part'), 'https://flow.google.com/project/p/edit/m');
  assert.equal(C.flowPage('https://labs.google/fx/vi/tools/flow/project/p'), 'https://labs.google/fx/vi/tools/flow/project/p');
  for (const url of ['https://flow.google.com/redirect?url=https://evil.test', 'https://evil.test/project/p', 'http://flow.google.com/project/p', 'https://user@flow.google.com/project/p']) assert.throws(() => C.flowPage(url));
  assert.deepEqual(C.clickPoint({x: 100, y: 100, width: 100, height: 40, viewportWidth: 1000, viewportHeight: 800}), {x: 150, y: 120});
  for (const rect of [{x: -200, y: 1}, {x: Infinity, y: 1}, {x: 1200, y: 0}]) assert.throws(() => C.clickPoint({...rect, width: 100, height: 40, viewportWidth: 1000, viewportHeight: 800}));
});
test('private HTTP paths and bearer cannot escape the fixed loopback service', async () => {
  const network = fakeNetwork();
  await C.request(saved(), '/heartbeat', {client_id: A}, network.fetcher);
  const request = network.requests[0];
  assert.equal(request.url, 'http://127.0.0.1:17865/heartbeat');
  assert.equal(request.options.credentials, 'omit'); assert.equal(request.options.redirect, 'error');
  assert.match(request.options.headers.Authorization, /^Bearer offline-test/);
  await assert.rejects(C.request(saved(), '/api/ai/assets', {}, network.fetcher));
  await assert.rejects(C.request(saved(), '/health', undefined, async () => ({ok: true, status: 200, headers: {get: () => null}, text: async () => '<html>'})));
});
test('pairing code and public popup status never disclose the bearer', async () => {
  const mock = chromeMock(saved({enabled: false, token: ''})), network = fakeNetwork();
  const worker = new BridgeWorker(mock.chrome, network.fetcher);
  await assert.rejects(worker.pair('abc123', 17865)); assert.equal(network.requests.length, 0);
  const state = await worker.pair('123456', 17865);
  assert.equal(state.paired, true); assert.equal(state.enabled, false);
  assert.equal(JSON.stringify(state).includes('offline-test-token'), false);
  assert.equal(JSON.stringify(state).includes('lease'), false);
});
test('parallel ticks claim once and persist dispatch before a START message', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork([job()]);
  const original = mock.chrome.tabs.sendMessage;
  mock.chrome.tabs.sendMessage = async (id, input) => {
    if (input.type === 'START') assert.equal(mock.stored[STORAGE].pending.id, A);
    return original(id, input);
  };
  const worker = new BridgeWorker(mock.chrome, network.fetcher);
  await Promise.all([worker.tick(), worker.tick(), worker.tick()]); await worker.tick();
  assert.equal(network.requests.filter(item => item.url.endsWith('/jobs/claim')).length, 1);
  assert.equal(mock.sent.filter(item => item.type === 'START').length, 1);
});
test('a healthy background Flow tab claims and dispatches without requiring visibility', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork([job()]), original = mock.chrome.tabs.sendMessage;
  mock.chrome.tabs.sendMessage = async (id, input) => input.type === 'STATUS' ? {ok: true, visible: false, ready: true, running: false, generating: false} : original(id, input);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(mock.sent.filter(input => input.type === 'START').length, 1);
});
test('stored upscale media reopens only the paired tab after persisting navigation intent', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork([job({operation: 'upscale', flow: {page_url: 'https://flow.google.com/project/previous/edit/media', media_id: 'media'}})]);
  const original = mock.chrome.tabs.update;
  mock.chrome.tabs.update = async (id, values) => {
    assert.equal(mock.stored[STORAGE].pending.phase, 'navigation_intent');
    assert.equal(mock.sent.some(input => input.type === 'START'), false);
    return original(id, values);
  };
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.deepEqual(mock.updates, [{id: 1, values: {url: 'https://flow.google.com/project/previous/edit/media'}}]);
  assert.equal(mock.sent.filter(input => input.type === 'START').length, 1);
  assert.equal(mock.sent.find(input => input.type === 'START').id, 1);
  assert.ok(network.requests.some(item => item.url.endsWith('/progress')));
});
test('unsafe stored URL never navigates or dispatches', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork([job({operation: 'edit', flow: {page_url: 'https://evil.test/project/p', media_id: 'media'}})]);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(mock.updates.length, 0); assert.equal(mock.sent.some(input => input.type === 'START'), false);
  assert.equal(network.requests.find(item => item.url.endsWith('/progress')).body.state, 'waiting_user');
});
test('restart during navigation becomes manual rather than resuming START', async () => {
  const mock = chromeMock(saved({pending: {...pending(), phase: 'navigation_intent', navigationUrl: 'https://flow.google.com/project/old/edit/media'}})), network = fakeNetwork([job()]);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(mock.updates.length, 0); assert.equal(mock.sent.some(input => input.type === 'START'), false);
  assert.equal(network.requests.some(item => item.url.endsWith('/jobs/claim')), false);
  assert.equal(worker.record.pending, null);
});
test('automatic background tab reopening requires an explicit saved opt-in and never resumes an old job', async () => {
  const projectUrl = 'https://flow.google.com/project/one';
  for (const autoOpen of [false, true]) {
    const mock = chromeMock(saved({tabId: 99, autoOpen, projectUrl})), network = fakeNetwork();
    const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
    assert.equal(mock.creates.length, autoOpen ? 1 : 0);
    if (autoOpen) assert.deepEqual(mock.creates[0], {url: projectUrl, active: false});
  }
});
test('a late auto-created tab cannot replace a newly selected Flow connection', async () => {
  const mock = chromeMock(saved({tabId: 99, autoOpen: true, projectUrl: 'https://flow.google.com/project/one'}));
  const network = fakeNetwork(), creating = deferred(), release = deferred(), original = mock.chrome.tabs.create;
  mock.chrome.tabs.create = async args => { creating.resolve(); await release.promise; return original(args); };
  const worker = new BridgeWorker(mock.chrome, network.fetcher), tick = worker.tick();
  await creating.promise; const connecting = worker.connect(2); await new Promise(resolve => setImmediate(resolve));
  release.resolve(); await Promise.all([tick, connecting]);
  assert.equal(worker.record.tabId, 2); assert.deepEqual(mock.removed, [3]);
  assert.equal(mock.sent.some(item => item.id === 3 && item.type === 'START'), false);
});
test('a delayed old-tab close handler cannot erase a newer tab/session', async () => {
  const mock = chromeMock(saved({pending: pending()})), gate = deferred();
  const worker = new BridgeWorker(mock.chrome, async () => gate.promise); await worker.init();
  const closed = worker.tabClosed(1); await new Promise(resolve => setImmediate(resolve));
  worker.record.pending = null; worker.record.tabId = 2; worker.record.session = B;
  gate.resolve(response({ok: true, job: {state: 'waiting_user'}})); await closed;
  assert.equal(worker.record.tabId, 2); assert.equal(worker.record.session, B); assert.equal(worker.record.enabled, true);
});
test('trusted mode is off by default and cannot be enabled without the optional permission', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork();
  const worker = new BridgeWorker(mock.chrome, network.fetcher);
  await assert.rejects(worker.popup({type: 'MODES', trusted: true}), /chưa cấp quyền/);
  assert.equal(worker.record.trustedMode, false);
  mock.chrome.permissions = {contains: async value => value.permissions[0] === 'debugger'};
  const state = await worker.popup({type: 'MODES', trusted: true}); assert.equal(state.trusted_mode, true);
  await worker.popup({type: 'MODES', trusted: false}); assert.equal(worker.record.trustedMode, false);
});
function trustedMock() {
  const mock = chromeMock(saved({trustedMode: true, pending: {...pending(), phase: 'submission_intent'}}));
  mock.chrome.permissions = {contains: async () => true};
  const commands = []; const rect = {x: 100, y: 100, width: 100, height: 40, viewportWidth: 1000, viewportHeight: 800};
  mock.chrome.debugger = {
    attach: async target => { assert.equal(mock.stored[STORAGE].pending.clicks[B].phase, 'intent'); commands.push({method: 'attach', target}); },
    sendCommand: async (target, method, args) => { commands.push({target, method, args}); return method === 'Page.getLayoutMetrics' ? {cssVisualViewport: {clientWidth: 1000, clientHeight: 800}} : {}; },
    detach: async target => { commands.push({method: 'detach', target}); }};
  const original = mock.chrome.tabs.sendMessage;
  mock.chrome.tabs.sendMessage = async (id, input) => input.type === 'VERIFY_CLICK' ? {ok: true, rect} : original(id, input);
  return {...mock, commands, rect};
}
test('trusted clicks validate the paired tab, semantic, lease and viewport, with one Generate intent', async () => {
  const mock = trustedMock(), network = fakeNetwork(), worker = new BridgeWorker(mock.chrome, network.fetcher);
  const input = message('CLICK', {nonce: B, semantic: 'generate', rect: mock.rect});
  await assert.rejects(worker.content(input, sender(2)), /Tab/); assert.equal(mock.commands.length, 0);
  const result = await worker.content(input, sender()); assert.equal(result.mode, 'trusted');
  assert.deepEqual(mock.commands.map(item => item.method), ['attach', 'Page.getLayoutMetrics', 'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent', 'detach']);
  assert.ok(mock.commands.every(item => item.target.tabId === 1));
  assert.equal((await worker.content(input, sender())).manual, true);
  assert.equal((await worker.content({...input, nonce: 'd'.repeat(32)}, sender())).manual, true);
  assert.equal(mock.commands.filter(item => item.method === 'attach').length, 1);
});
test('cancelled lease and an invalid target cannot dispatch any trusted mouse event', async () => {
  const mock = trustedMock(), worker = new BridgeWorker(mock.chrome, async () => response({error: 'cancelled'}, 409));
  const input = message('CLICK', {nonce: B, semantic: 'generate', rect: mock.rect});
  await assert.rejects(worker.content({...input, rect: {...mock.rect, x: 2000}}, sender()));
  await assert.rejects(worker.content({...input, semantic: 'arbitrary_command'}, sender()));
  const result = await worker.content(input, sender()); assert.equal(result.manual, true);
  assert.equal(mock.commands.length, 0);
});
test('a connection changed during target lookup is never attached to debugger', async () => {
  const mock = trustedMock(), gate = deferred(), network = fakeNetwork();
  mock.chrome.tabs.get = async () => gate.promise;
  const worker = new BridgeWorker(mock.chrome, network.fetcher), clicking = worker.content(message('CLICK', {nonce: B, semantic: 'generate', rect: mock.rect}), sender());
  await new Promise(resolve => setImmediate(resolve));
  worker.record.tabId = 2; worker.record.session = B;
  gate.resolve({id: 1, url: 'https://flow.google.com/project/one'}); const result = await clicking;
  assert.equal(result.cancelled, true); assert.equal(mock.commands.length, 0);
});
test('a stale lease cancels content and cannot complete a cancelled job', async () => {
  const mock = chromeMock(saved({pending: pending()}));
  const worker = new BridgeWorker(mock.chrome, async () => response({error: 'cancelled'}, 409));
  const result = await worker.content(message('CHECK_LEASE'), sender());
  assert.equal(result.cancelled, true); assert.equal(worker.record.pending, null);
  const late = await worker.content(message('COMPLETE', {images: [PNG]}), sender());
  assert.equal(late.cancelled, true);
});
test('content messages from another tab/session cannot access image fetch or jobs', async () => {
  const mock = chromeMock(saved({pending: pending()})), network = fakeNetwork();
  const worker = new BridgeWorker(mock.chrome, network.fetcher);
  await assert.rejects(worker.content(message('FETCH_IMAGE', {url: 'https://lh3.googleusercontent.com/p.png'}), sender(2)), /Tab/);
  await assert.rejects(worker.content(message('PROGRESS', {session: B}), sender()), /Tab/);
  assert.equal(network.requests.length, 0);
});
test('restart with an ambiguous submitted job reports manual action, never START/claim', async () => {
  const mock = chromeMock(saved({pending: pending()})), network = fakeNetwork([job()]);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(mock.sent.filter(item => item.type === 'START').length, 0);
  assert.equal(network.requests.some(item => item.url.endsWith('/jobs/claim')), false);
  assert.equal(network.requests.find(item => item.url.endsWith('/progress')).body.state, 'waiting_user');
  assert.equal(worker.record.pending, null);
});
test('restart with the same live content operation monitors without resubmitting', async () => {
  const mock = chromeMock(saved({pending: pending()})), network = fakeNetwork(); mock.setActive(A);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(worker.record.pending.id, A);
  assert.equal(mock.sent.some(item => item.type === 'START'), false);
  assert.equal(network.requests.some(item => item.url.endsWith('/jobs/claim')), false);
});
test('an operation still finalizing in content prevents a premature second claim', async () => {
  const mock = chromeMock(saved()), network = fakeNetwork([job()]); mock.setActive(B);
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.tick();
  assert.equal(network.requests.some(item => item.url.endsWith('/jobs/claim')), false);
});
test('changing tabs while claim awaits never dispatches the old job to the new tab', async () => {
  const mock = chromeMock(saved()), gate = deferred(), network = fakeNetwork();
  const worker = new BridgeWorker(mock.chrome, async (url, options) => url.endsWith('/jobs/claim') ? gate.promise : network.fetcher(url, options));
  const running = worker.tick();
  while (!network.requests.some(item => item.url.endsWith('/heartbeat'))) await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  const connect = worker.connect(2);
  await new Promise(resolve => setImmediate(resolve)); gate.resolve(response({job: job()}));
  await Promise.all([running, connect]);
  assert.equal(mock.sent.some(item => item.type === 'START'), false);
  assert.equal(network.requests.find(item => item.url.endsWith('/progress')).body.state, 'waiting_user');
  assert.equal(worker.record.tabId, 2);
});
test('late completion cannot clear a newer job or fresh connection token', async () => {
  const mock = chromeMock(saved({pending: pending()})), gate = deferred();
  const worker = new BridgeWorker(mock.chrome, async () => gate.promise); await worker.init();
  const completion = worker.content(message('COMPLETE', {images: [PNG]}), sender());
  await new Promise(resolve => setImmediate(resolve));
  worker.record.pending = {id: B, lease: 'new-lease'.repeat(4), tabId: 2, phase: 'submitted', started: Date.now()};
  worker.record.session = B; worker.record.tabId = 2; worker.record.token = 'new-paired-token'.repeat(3);
  gate.resolve(response({ok: true, job: {state: 'complete'}})); await completion;
  assert.equal(worker.record.pending.id, B); assert.match(worker.record.token, /^new-paired/);
});
test('late stale-lease rejection cannot clear a newer job or new bearer', async () => {
  const mock = chromeMock(saved({pending: pending()})), gate = deferred();
  const worker = new BridgeWorker(mock.chrome, async () => gate.promise); await worker.init();
  const check = worker.content(message('CHECK_LEASE'), sender()); await new Promise(resolve => setImmediate(resolve));
  worker.record.pending = {id: B, lease: 'new-lease'.repeat(4)}; worker.record.session = B;
  worker.record.token = 'new-paired-token'.repeat(3); gate.resolve(response({error: 'old bearer'}, 401)); await check;
  assert.equal(worker.record.pending.id, B); assert.match(worker.record.token, /^new-paired/);
});
test('download observer injection stays bound to the original tab across a connection change', async () => {
  const mock = chromeMock(saved({pending: pending()})), gate = deferred(), network = fakeNetwork();
  mock.chrome.scripting.executeScript = async input => { mock.scripts.push(input); return gate.promise; };
  const worker = new BridgeWorker(mock.chrome, network.fetcher); await worker.init();
  const arm = worker.content(message('ARM_DOWNLOAD', {nonce: B, mediaId: 'original'}), sender());
  await new Promise(resolve => setImmediate(resolve)); worker.record.tabId = 2; worker.record.session = B;
  gate.resolve([]); const result = await arm;
  assert.equal(result.cancelled, true); assert.equal(mock.scripts.length, 1); assert.equal(mock.scripts[0].target.tabId, 1);
});
function image(id, source = 'https://lh3.googleusercontent.com/' + id + '.png') {
  return {src: source, currentSrc: source, complete: true, naturalWidth: 1024, naturalHeight: 1024,
    getAttribute: key => key === 'data-media-id' ? id : null, closest: () => null, getBoundingClientRect: () => ({width: 100, height: 100})};
}
function row(images, prompt = 'Render this building', source = 'source') {
  return {innerText: prompt, getAttribute: key => key === 'data-source-media-id' ? source : null, querySelectorAll: selector => selector === 'img' ? images : []};
}
function domFixture() {
  const state = {steps: [row([image('old')])], images: [image('old')], selectors: {}};
  const document = {visibilityState: 'visible', querySelectorAll: selector => selector === D.SELECTORS.history ? state.steps : selector === 'img' ? state.images : state.selectors[selector] || [], querySelector: () => null};
  const location = new URL('https://flow.google.com/project/p/edit/source');
  const dom = new D.FlowDOM({document, location, window: {getComputedStyle: () => ({display: 'block', visibility: 'visible', opacity: '1'})}});
  return {dom, state, location};
}
test('result association rejects old gallery images, changed pages, other prompts and ambiguous rows', () => {
  const {dom, state, location} = domFixture(), baseline = dom.snapshot();
  baseline.promptText = 'Render this building'; baseline.sourceMediaId = 'source';
  state.images.push(image('unrelated-gallery')); assert.equal(dom.resultCandidate(baseline), null);
  state.steps.push(row([image('new')])); assert.equal(D.mediaId(dom.resultCandidate(baseline)), 'new');
  state.steps[1] = row([image('other')], 'A different user prompt'); assert.throws(() => dom.resultCandidate(baseline), D.WaitingUser);
  state.steps[1] = row([image('new')], 'Render this building', 'wrong-source'); assert.throws(() => dom.resultCandidate(baseline), D.WaitingUser);
  state.steps[1] = row([image('new'), image('second')]); assert.throws(() => dom.resultCandidate(baseline), D.WaitingUser);
  location.pathname = '/project/other/edit/source'; assert.throws(() => dom.resultCandidate(baseline), /dự án khác/);
});
test('bounded waits stop on timeout and cancellation', async () => {
  const {dom} = domFixture(); let now = 0, checks = 0;
  dom.now = () => now; dom.sleep = async value => { now += value; };
  await assert.rejects(dom.waitFor(() => null, 1000, {check: async () => { checks++; }}), D.WaitingUser);
  assert.ok(checks <= 4);
  await assert.rejects(dom.waitFor(() => null, 1000, {check: async () => { throw new D.Cancelled(); }}), D.Cancelled);
});
test('a matching prompt without positive source binding requires manual import', () => {
  const {dom, state, location} = domFixture(); location.pathname = '/project/p/edit/editor-context';
  const baseline = dom.snapshot(); baseline.sourceMediaId = 'uploaded-source'; baseline.promptText = 'Render this building';
  const result = row([image('new')]); result.getAttribute = () => null; state.steps.push(result);
  assert.throws(() => dom.resultCandidate(baseline), /mã nguồn đủ rõ/);
});
test('file uploads use the prompt component and reject ambiguous input controls', () => {
  const {dom, state} = domFixture(), events = [];
  const globalInput = {set files(_) { throw Error('must not use unrelated global input'); }};
  state.selectors['input[type="file"]'] = [globalInput];
  const input = {accept: 'image/*', dispatchEvent: event => events.push(event.type)};
  const component = {querySelectorAll: () => [input]};
  const target = {closest: () => component};
  dom.DataTransfer = class { constructor() { this.files = []; this.items = {add: file => this.files.push(file)}; } };
  dom.window.Event = class { constructor(type) { this.type = type; } };
  dom.dispatchFiles([{name: 'source.png'}], target);
  assert.equal(input.files.length, 1); assert.deepEqual(events, ['input', 'change']);
  component.querySelectorAll = () => [input, input]; assert.throws(() => dom.dispatchFiles([], target), D.WaitingUser);
});
test('render persists submission intent and clicks Generate once before accepting the matched output', async () => {
  const {dom} = domFixture(), order = [], source = image('source');
  dom.uploadSource = async () => source; dom.openMedia = async () => 'source'; dom.references = async () => {};
  dom.fillPrompt = () => ({}); dom.generateButton = () => ({click: () => order.push('click')});
  dom.waitFor = async callback => { order.push('wait'); return image('result'); };
  dom.readImage = async () => ({dataURL: PNG, hash: 'new-hash'});
  const output = await dom.render(job(), {check: async () => {}, report: async phase => order.push(phase), intent: async baseline => { assert.equal(baseline.sourceMediaId, 'source'); order.push('persist'); }});
  assert.equal(order.filter(value => value === 'click').length, 1);
  assert.ok(order.indexOf('persist') < order.indexOf('click')); assert.ok(order.indexOf('submission_intent') < order.indexOf('click'));
  assert.deepEqual(output.images, [PNG]); assert.equal(output.flow.media_id, 'result');
});
test('upscale never calls Generate and refuses a 2K downgrade of a 4K source', async () => {
  const {dom, state} = domFixture(), source = image('source'), clicks = [];
  state.images = [source]; source.click = () => clicks.push('media');
  const download = {getAttribute: key => key === 'aria-label' ? 'Download media' : null, click: () => clicks.push('download')};
  const choice = {innerText: '2K', getAttribute: () => null, click: () => clicks.push('2K')};
  state.selectors.button = [download]; state.selectors[D.SELECTORS.menu] = [choice];
  dom.uploadSource = async () => source; dom.openMedia = async () => 'source'; dom.generateButton = () => { throw Error('upscale must not generate'); };
  dom.waitFor = async callback => { const result = await callback(); assert.ok(result); return result; };
  dom.readImage = async () => ({dataURL: PNG, width: 2048, height: 2048});
  const context = {check: async () => {}, report: async () => {}, armDownload: async id => assert.equal(id, 'source'), takeDownload: () => ({data_url: PNG, name: 'upscaled.png'})};
  const output = await dom.upscale(job({operation: 'upscale'}), context); assert.equal(output.images[0], PNG);
  await assert.rejects(dom.upscale(job({operation: 'upscale', source: {width: 4096, height: 4096}}), context), /không tăng kích thước/);
  assert.equal(clicks.filter(value => value === '2K').length, 2);
});
test('an existing Flow generation blocks submission before persisting or clicking', async () => {
  const {dom, state} = domFixture(); let clicks = 0, intents = 0;
  dom.uploadSource = async () => image('source'); dom.openMedia = async () => 'source'; dom.references = async () => {};
  dom.fillPrompt = () => ({}); dom.generateButton = () => ({click: () => { clicks++; }});
  state.selectors['[role="progressbar"], mat-progress-spinner, [aria-busy="true"], [data-state="generating"]'] = [{getBoundingClientRect: () => ({width: 12, height: 12})}];
  await assert.rejects(dom.render(job(), {check: async () => {}, report: async () => {}, intent: async () => { intents++; }}), /lượt khác/);
  assert.equal(clicks, 0); assert.equal(intents, 0);
});
test('Google image fetch validates source, signature and MIME without exposing browser credentials to Python', async () => {
  const bytes = C.parseImage(PNG).bytes;
  let called = false;
  const result = await C.fetchImage('https://lh3.googleusercontent.com/result.png', async (_url, options) => {
    called = true; assert.equal(options.credentials, 'include'); assert.equal(options.redirect, 'error');
    return {ok: true, headers: {get: key => key === 'Content-Type' ? 'image/png' : null}, arrayBuffer: async () => bytes.buffer};
  });
  assert.ok(called); assert.equal(result, PNG);
  await assert.rejects(C.fetchImage('https://evil.test/result.png', async () => { throw Error('must not fetch'); }));
});
function contentContext(storage, run, options = {}) {
  let listener; const events = {}, sent = [];
  const context = {console, URL, Blob, Uint8Array, crypto: webcrypto, atob, btoa,
    location: new URL('https://flow.google.com/project/p'), sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    setTimeout: () => 1, clearTimeout: () => {}, innerWidth: 1000, innerHeight: 800,
    document: {visibilityState: 'visible', createElement: () => ({style: {}, remove() {}}), documentElement: {appendChild() {}}, addEventListener: (type, callback) => { events[type] = callback; }},
    addEventListener: () => {},
    SiteCraftBridgeCore: C, SiteCraftFlowDOM: {...D, FlowDOM: class {run(job, ctx) { return run(job, ctx); } async sleep() {} blockers() {} ready() { return true; } prompt() { return options.prompt || null; } generating() { return false; } visible() { return true; }}},
    chrome: {runtime: {id: 'a'.repeat(32), onMessage: {addListener: callback => { listener = callback; }},
      sendMessage: async input => { sent.push(input); if (options.message) return options.message(input); return {ok: true, data: {ok: true, data_url: PNG}}; }}}
  };
  context.document.elementFromPoint = options.elementFromPoint || (() => null);
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'content.js'), 'utf8'), context);
  const send = input => new Promise(resolve => listener({sitecraft: 1, session: SESSION, ...input}, {id: 'a'.repeat(32)}, resolve));
  return {send, events, sent};
}
test('content remembers a dispatched job across reload and never submits the same job twice', async () => {
  const storage = new Map(), gate = deferred(); let runs = 0;
  const page = contentContext(storage, async () => { runs++; return gate.promise; });
  await page.send({type: 'CONFIGURE'}); assert.equal((await page.send({type: 'START', job: job()})).ok, true);
  assert.equal((await page.send({type: 'START', job: job()})).ok, true); assert.equal(runs, 1);
  const reloaded = contentContext(storage, async () => { throw Error('must not resubmit'); });
  await reloaded.send({type: 'CONFIGURE'}); assert.equal((await reloaded.send({type: 'START', job: job()})).ok, false);
  gate.resolve({images: [PNG]}); await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.sent.filter(input => input.type === 'COMPLETE').length, 1);
});
test('trusted user interaction after submission stops automatic result association', async () => {
  const gate = deferred(), storage = new Map();
  const page = contentContext(storage, async (_job, ctx) => { await ctx.report('submitted', 'Waiting for Flow'); await gate.promise; await ctx.check(true); return {images: [PNG]}; });
  await page.send({type: 'CONFIGURE'}); await page.send({type: 'START', job: job()}); await new Promise(resolve => setImmediate(resolve));
  page.events.pointerdown({isTrusted: true, type: 'pointerdown'}); gate.resolve(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.sent.some(input => input.type === 'COMPLETE'), false);
  assert.equal(page.sent.filter(input => input.type === 'WAITING_USER').length, 1);
});
test('the expected CDP click is exempt narrowly while another trusted target still cancels association', async () => {
  for (const interfere of [false, true]) {
    const gate = deferred(), storage = new Map(); let page;
    const button = {getBoundingClientRect: () => ({left: 100, top: 100, width: 100, height: 40}), contains: target => target === button, click() {}};
    page = contentContext(storage, async (_job, ctx) => {
      await ctx.report('submission_intent', 'Sending'); await ctx.click(button, 'generate');
      await ctx.report('submitted', 'Waiting'); await gate.promise; await ctx.check(true); return {images: [PNG]};
    }, {elementFromPoint: () => button, message: async input => {
      if (input.type === 'CLICK') {
        const check = await page.send({type: 'VERIFY_CLICK', jobId: A, nonce: input.nonce, semantic: input.semantic}); assert.equal(check.ok, true);
        page.events.pointerdown({type: 'pointerdown', isTrusted: true, target: button, clientX: 150, clientY: 120});
        return {ok: true, data: {ok: true, mode: 'trusted'}};
      }
      return {ok: true, data: {ok: true}};
    }});
    await page.send({type: 'CONFIGURE'}); await page.send({type: 'START', job: job()}); await new Promise(resolve => setImmediate(resolve));
    if (interfere) page.events.pointerdown({type: 'pointerdown', isTrusted: true, target: {}, clientX: 500, clientY: 500});
    gate.resolve(); await new Promise(resolve => setImmediate(resolve));
    assert.equal(page.sent.some(input => input.type === 'COMPLETE'), !interfere);
    assert.equal(page.sent.some(input => input.type === 'WAITING_USER'), interfere);
  }
});
test('manifest has optional-only debugger and no cookies/downloads permission, remote code or vendor identity key', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json')));
  assert.equal(manifest.manifest_version, 3);
  for (const permission of ['cookies', 'debugger', 'webRequest', 'downloads', '<all_urls>']) assert.equal(manifest.permissions.includes(permission), false);
  assert.equal(manifest.key, undefined); assert.deepEqual(manifest.optional_permissions, ['debugger']);
  assert.equal(manifest.version_name, '0.5.0-beta.1');
  assert.deepEqual(fs.readFileSync(path.join(directory, 'icon.png')), fs.readFileSync(path.resolve(__dirname, '../extension/openmap_sketchup/ui/icon.png')));
  for (const font of ['SVN-Avo-Regular.ttf', 'SVN-Avo-Bold.ttf', 'SVN-Avo-Italic.ttf', 'SVN-Avo-BoldItalic.ttf', 'fonts.css', 'NOTICE.md', 'font-manifest.json']) assert.deepEqual(fs.readFileSync(path.join(directory, 'fonts', font)), fs.readFileSync(path.resolve(__dirname, '../extension/openmap_sketchup/ui/fonts', font)));
  assert.match(fs.readFileSync(path.join(directory, 'popup.css'), 'utf8'), /font-family:'SVN-Avo'/);
  for (const file of fs.readdirSync(directory).filter(name => name.endsWith('.js'))) {
    const source = fs.readFileSync(path.join(directory, file), 'utf8');
    assert.doesNotMatch(source, /\beval\s*\(|new\s+Function\s*\(|importScripts\s*\(\s*['"]https?:/);
  }
});
test('trusted storage restriction and popup opened as a tab use the safe popup route', async () => {
  const mock = chromeMock(saved({enabled: false})); let accessLevel = null, listener;
  mock.chrome.storage.local.setAccessLevel = async value => { accessLevel = value.accessLevel; };
  mock.chrome.runtime.onMessage = {addListener: callback => { listener = callback; }};
  mock.chrome.tabs.onRemoved = {addListener() {}};
  mock.chrome.alarms = {create() {}, onAlarm: {addListener() {}}};
  const context = {SiteCraftBridgeCore: C, chrome: mock.chrome, fetch: async () => { throw Error('No API expected'); }, console};
  context.self = context;
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'worker.js'), 'utf8'), context);
  const call = (input, sender) => new Promise(resolve => listener({sitecraft: 1, ...input}, sender, resolve));
  const ownPopup = {id: mock.chrome.runtime.id, url: 'chrome-extension://' + mock.chrome.runtime.id + '/popup.html', tab: {id: 99}};
  const state = await call({type: 'POPUP_STATUS'}, ownPopup);
  assert.equal(state.ok, true); assert.equal(state.data.paired, true); assert.equal(accessLevel, 'TRUSTED_CONTEXTS');
  const rejected = await call({type: 'POPUP_STATUS'}, {id: mock.chrome.runtime.id, tab: {id: 99, url: 'https://flow.google.com/'}, url: 'https://flow.google.com/'});
  assert.equal(rejected.ok, false);
});
test('2K observer accepts positively associated image bytes and refuses generic unrelated downloads', async () => {
  const posts = [], handlers = new Map(); let originalClicks = 0;
  class Anchor {
    constructor(href, download) { this.href = href; this.download = download; }
    click() { originalClicks++; }
  }
  const original = Anchor.prototype.click;
  const context = {URL, Set, HTMLAnchorElement: Anchor, location: new URL('https://flow.google.com/project/p/edit/source'),
    document: {addEventListener: (type, handler) => handlers.set(type, handler), removeEventListener: type => handlers.delete(type)},
    setTimeout: () => 1, clearTimeout() {}, fetch: async () => ({blob: async () => new Blob([C.parseImage(PNG).bytes], {type: 'image/png'})}),
    FileReader: class {readAsDataURL() { this.result = PNG; this.onload(); }},
    postMessage: data => posts.push(data)};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'download-observer.js'), 'utf8'), context);
  context.SiteCraftFlowDownload.arm({nonce: B, mediaId: '12345678-source', timeout: 5000});
  new Anchor('blob:https://flow.google.com/own-result', '12345678_2K.png').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts[0].data_url, PNG); assert.equal(posts[0].nonce, B);
  new Anchor('blob:https://flow.google.com/unrelated', 'image.png').click();
  assert.match(posts[1].error, /không gắn mã ảnh/); assert.equal(posts[1].data_url, undefined);
  new Anchor('https://evil.test/image.png', '12345678_2K.png').click(); assert.equal(posts.length, 2);
  context.SiteCraftFlowDownload.disarm(); assert.equal(Anchor.prototype.click, original); assert.equal(handlers.size, 0);
  assert.equal(originalClicks, 3);
});

(async () => {
  let failed = 0;
  for (const [name, body] of tests) {
    try { await body(); process.stdout.write('PASS ' + name + '\n'); }
    catch (error) { failed++; process.stderr.write('FAIL ' + name + '\n' + error.stack + '\n'); }
  }
  process.stdout.write(`${tests.length - failed}/${tests.length} SiteCraft Flow offline checks passed.\n`);
  if (failed) process.exitCode = 1;
})();
