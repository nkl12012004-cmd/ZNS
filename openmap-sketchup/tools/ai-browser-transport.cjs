/* SPDX-License-Identifier: MIT
 * Real Chrome MV3 -> actual Python loopback bridge test. No Google request,
 * login, generation or paid service is involved. The output image is a fixture.
 * Run with full Chromium, not chromium-headless-shell:
 *   npx playwright install chromium
 *   SITECRAFT_AI_PYTHON=python3 node tools/ai-browser-transport.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const extensionDir = path.join(root, 'browser_extension', 'sitecraft_flow_bridge');
const driver = String.raw`
import base64, json, secrets, sys, threading
from io import BytesIO
from PIL import Image
sys.path.insert(0, sys.argv[2])  # Embedded Windows Python ignores PYTHONPATH.
from openmap_server.ai_render import AIRenderService

class ObservedService(AIRenderService):
    def __init__(self, config):
        super().__init__(config)
        self.events = []
    def _origin_allowed(self, origin, path):
        allowed = super()._origin_allowed(origin, path)
        self.events.append({'path':path, 'origin':origin, 'allowed':allowed})
        return allowed

service = ObservedService({'OPENMAP_LOCAL_TOKEN':secrets.token_urlsafe(32), 'OPENMAP_AI_DIR':sys.argv[1]})
def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)
try:
    pair = service.route('POST','/api/ai/pair',{})
    stream = BytesIO(); Image.new('RGB',(16,16),(45,98,61)).save(stream,'PNG')
    asset = service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(), 'name':'Transport fixture', 'role':'source'})
    job = service.create_job({'client_request_id':secrets.token_hex(16), 'operation':'render', 'source_id':asset['id'], 'reference_ids':[], 'prompt':'Transport fixture only; never sent to Google.', 'options':{'keep_camera':True,'keep_design':True}})
    emit({'ready':True, 'pair':pair, 'job_id':job['id']})
    for line in sys.stdin:
        try:
            command=json.loads(line); op=command['op']
            if op=='events': result=service.events[:]
            elif op=='status': result=service.status()
            elif op=='job': result=service.route('GET','/api/ai/jobs/'+job['id'],{})
            elif op=='close':
                service.close(); emit({'reply':command['id'],'result':{'closed':True}}); break
            else: raise ValueError('Unknown test command')
            emit({'reply':command['id'],'result':result})
        except Exception as error:
            emit({'reply':command.get('id'), 'error':type(error).__name__+': '+str(error)})
finally:
    service.close()
`;

function startPython(folder) {
  const python = process.env.SITECRAFT_AI_PYTHON || 'python3';
  const child = spawn(python, ['-u', '-c', driver, folder, path.join(root, 'server')], {
    cwd: root, env: {...process.env, PYTHONPATH: path.join(root, 'server')}, stdio: ['pipe', 'pipe', 'pipe']
  });
  const pending = new Map(); let sequence = 0, stderr = '', done = false;
  let resolveReady, rejectReady;
  const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  const bootTimer = setTimeout(() => rejectReady(new Error('Python bridge fixture did not start. ' + stderr.slice(-2000))), 15000);
  child.stderr.on('data', chunk => { stderr += chunk; });
  child.on('error', rejectReady);
  child.on('exit', code => {
    done = true;
    if (code) rejectReady(new Error('Python fixture exited ' + code + ': ' + stderr.slice(-2000)));
    for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error('Python bridge fixture stopped.')); }
  });
  readline.createInterface({input: child.stdout}).on('line', line => {
    let message; try { message = JSON.parse(line); } catch { return; }
    if (message.ready) { clearTimeout(bootTimer); resolveReady(message); return; }
    const item = pending.get(message.reply); if (!item) return;
    pending.delete(message.reply); clearTimeout(item.timer);
    message.error ? item.reject(new Error(message.error)) : item.resolve(message.result);
  });
  function request(op) {
    return new Promise((resolve, reject) => {
      const id = ++sequence, timer = setTimeout(() => {pending.delete(id); reject(new Error('Python fixture command timed out: ' + op));}, 15000);
      pending.set(id, {resolve, reject, timer}); child.stdin.write(JSON.stringify({id, op}) + '\n');
    });
  }
  return {child, ready, request, async close() {
    clearTimeout(bootTimer);
    if (!done) { try { await request('close'); } finally { child.stdin.end(); } }
  }};
}

(async () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionDir, 'manifest.json'), 'utf8'));
  assert.equal(manifest.manifest_version, 3);
  for (const file of [manifest.background.service_worker, manifest.action.default_popup, ...manifest.content_scripts.flatMap(script => script.js)]) {
    assert(fs.existsSync(path.join(extensionDir, file)), 'Extension file missing: ' + file);
  }
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'sitecraft-chrome-transport-'));
  const python = startPython(path.join(temporary, 'ai'));
  let context, pageServer;
  try {
    const ready = await python.ready;
    context = await chromium.launchPersistentContext(path.join(temporary, 'chrome-profile'), {
      channel: 'chromium', headless: true,
      args: ['--no-sandbox', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run',
        '--disable-extensions-except=' + extensionDir, '--load-extension=' + extensionDir]
    });
    const blockedGoogleRequests = [];
    await context.route(/^https?:\/\//, route => {
      const url = new URL(route.request().url());
      if (url.hostname === '127.0.0.1') return route.continue();
      blockedGoogleRequests.push(url.hostname); return route.abort();
    });
    const workers = context.serviceWorkers();
    const worker = workers[0] || await context.waitForEvent('serviceworker', {timeout: 15000});
    const extensionId = new URL(worker.url()).host;
    assert.match(extensionId, /^[a-p]{32}$/);
    const extensionOrigin = 'chrome-extension://' + extensionId;
    // Exercise the actual worker's browser-generated Origin before involving
    // popup routing. The deliberately wrong code must fail, without injecting
    // an Origin header or ever exposing the map transport token.
    await worker.evaluate(async selectedPort => {
      try { await self.SiteCraftBridgeCore.request({port:selectedPort}, '/pair', {code:'invalid-fixture-code',client_id:'a'.repeat(32)}); }
      catch (error) { if (error.status !== 403) throw error; }
    }, ready.pair.port);
    const initialEvents = await python.request('events');
    assert(initialEvents.some(event => event.path === '/pair' && event.origin === extensionOrigin && event.allowed),
      'Actual Chrome worker POST did not send paired extension Origin: ' + JSON.stringify(initialEvents));
    const popup = await context.newPage();
    await popup.goto(extensionOrigin + '/' + manifest.action.default_popup);
    await popup.waitForFunction(() => typeof chrome?.runtime?.sendMessage === 'function');
    const statusBefore = await popup.evaluate(() => chrome.runtime.sendMessage({sitecraft:1,type:'POPUP_STATUS'}));
    assert(statusBefore.ok && !statusBefore.data.paired, 'Fresh popup state must be unpaired: ' + JSON.stringify(statusBefore));
    const found = await popup.evaluate(() => chrome.runtime.sendMessage({sitecraft:1,type:'FIND'}));
    assert(found.ok && found.data.ports.includes(ready.pair.port), 'Real extension could not discover Python loopback health.');

    const paired = await popup.evaluate(({code,port}) => chrome.runtime.sendMessage({sitecraft:1,type:'PAIR',code,port}), ready.pair);
    assert(paired.ok && paired.data.paired, 'Real Chrome pairing failed: ' + String(paired.error || JSON.stringify(paired.data)));
    assert(!Object.hasOwn(paired.data, 'token') && !JSON.stringify(paired).includes('Bearer '), 'Popup publicState exposed bridge bearer.');
    const heartbeat = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      return self.SiteCraftBridgeCore.request(record, '/heartbeat', {client_id:record.clientId});
    });
    assert.equal(heartbeat.connected, true);
    const bearerFailures = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      const statuses = [];
      for (const config of [{port:record.port},{port:record.port,token:'invalid-fixture-bearer'}]) {
        try { await self.SiteCraftBridgeCore.request(config,'/heartbeat',{client_id:record.clientId}); statuses.push(200); }
        catch (error) { statuses.push(error.status); }
      }
      return statuses;
    });
    assert.deepEqual(bearerFailures,[401,401], 'Actual Chrome Origin bypassed missing/invalid bearer checks.');
    const claim = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      const result = await self.SiteCraftBridgeCore.request(record, '/jobs/claim', {client_id:record.clientId});
      self.__sitecraftTransportProbe = result.job;
      return {id:result.job?.id, operation:result.job?.operation, source:result.job?.source?.id, image:result.job?.source?.data_url?.startsWith('data:image/png;base64,')};
    });
    assert.equal(claim.id, ready.job_id); assert.equal(claim.operation, 'render'); assert.equal(claim.image, true);
    const duplicateClaim = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      return self.SiteCraftBridgeCore.request(record, '/jobs/claim', {client_id:record.clientId});
    });
    assert.equal(duplicateClaim.job, null, 'A second claim duplicated the active generation.');
    const progress = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      const job = self.__sitecraftTransportProbe;
      return self.SiteCraftBridgeCore.request(record, '/jobs/' + job.id + '/progress', {lease:job.lease,state:'running',message:'Browser transport fixture only.'});
    });
    assert.equal(progress.job.state, 'running');
    const complete = await worker.evaluate(async () => {
      const record = (await chrome.storage.local.get('sitecraftFlowBridgeV1')).sitecraftFlowBridgeV1;
      const job = self.__sitecraftTransportProbe;
      const body = {lease:job.lease,images:[job.source.data_url]};
      const first = await self.SiteCraftBridgeCore.request(record, '/jobs/' + job.id + '/complete', body);
      const retry = await self.SiteCraftBridgeCore.request(record, '/jobs/' + job.id + '/complete', body);
      return {first:first.job,retry:retry.job};
    });
    assert.equal(complete.first.state, 'complete');
    assert.deepEqual(complete.first.result_ids, complete.retry.result_ids, 'Completion retry created duplicate output.');
    const localJob = await python.request('job');
    assert.equal(localJob.state, 'complete'); assert.equal(localJob.result_ids.length, 1);

    pageServer = http.createServer((_request, response) => {
      response.writeHead(200, {'Content-Type':'text/html'}); response.end('<!doctype html><title>Unauthorized web origin fixture</title>');
    });
    await new Promise(resolve => pageServer.listen(0, '127.0.0.1', resolve));
    const hostileOrigin = 'http://127.0.0.1:' + pageServer.address().port;
    const hostilePage = await context.newPage(); await hostilePage.goto(hostileOrigin);
    const unauthorizedWeb = await hostilePage.evaluate(async port => {
      try {
        const response = await fetch('http://127.0.0.1:' + port + '/heartbeat', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        return {allowed:true,status:response.status};
      } catch { return {allowed:false}; }
    }, ready.pair.port);
    assert.equal(unauthorizedWeb.allowed, false, 'Unpaired web page read the extension-only bridge.');
    const unauthorizedNoOrigin = await fetch('http://127.0.0.1:' + ready.pair.port + '/heartbeat', {
      method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
    });
    assert.equal(unauthorizedNoOrigin.status, 403, 'No-Origin request bypassed extension pairing.');
    const publicState = await popup.evaluate(() => chrome.runtime.sendMessage({sitecraft:1,type:'POPUP_STATUS'}));
    assert(publicState.ok && !Object.hasOwn(publicState.data,'token'));
    const events = await python.request('events');
    for (const target of ['/pair','/heartbeat','/jobs/claim','/jobs/' + ready.job_id + '/complete']) {
      assert(events.some(event => event.path === target && event.origin === extensionOrigin && event.allowed), 'Chrome did not send the expected actual extension Origin to ' + target);
    }
    assert(events.some(event => event.origin === hostileOrigin && !event.allowed), 'Wrong web Origin was not observed/rejected by actual backend.');
    assert(events.some(event => event.origin === null && event.path === '/heartbeat' && !event.allowed));
    assert.equal(blockedGoogleRequests.length, 0, 'Transport test attempted an external page request.');
    const summary = {
      browser:'full Chromium MV3', service:'actual AIRenderService', fixture_only:true,
      extension_origin:extensionOrigin, pair:true, heartbeat:true, claim:true,
      duplicate_claim_rejected:true, progress:true, complete:true, idempotent_complete:true,
      wrong_web_origin_rejected:true, missing_origin_rejected:true, public_state_hides_bearer:true,
      missing_bearer_rejected:true, invalid_bearer_rejected:true,
      actual_observed_origins:events.map(event => ({path:event.path,origin:event.origin,allowed:event.allowed})),
      google_requests:0, ai_generation_tested:false
    };
    const artifact = path.join(root,'test-artifacts','ai-browser-transport.json');
    fs.mkdirSync(path.dirname(artifact),{recursive:true}); fs.writeFileSync(artifact,JSON.stringify(summary,null,2)+'\n');
    console.log('SiteCraft real Chrome MV3 transport PASS: pairing, Origin/auth, queue, fixture-image completion, no Google calls.');
    console.log('Evidence: ' + artifact);
  } finally {
    if (context) await context.close();
    if (pageServer) await new Promise(resolve => pageServer.close(resolve));
    await python.close().catch(() => python.child.kill());
    fs.rmSync(temporary,{recursive:true,force:true});
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
