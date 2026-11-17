/* Run after npm install in tools/ and npx playwright install chromium. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1040, height: 860 } });
  let modePreference = null;
  await page.exposeFunction('__testModePreference', value => {
    if (typeof value === 'string') modePreference = value;
    return modePreference;
  });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const root = path.resolve(__dirname, '..');
  const png = fs.readFileSync(path.join(root, 'extension/openmap_sketchup/ui/icon.png'));
  const tileRequests = new Set();
  await page.route(/^https?:\/\//, route => {
    const url = route.request().url();
    if (/^https:\/\/(?:server\.arcgisonline\.com|mt[0-3]\.google\.com|tile\.openstreetmap\.org)\//.test(url)) {
      tileRequests.add(url); return route.fulfill({ contentType: 'image/png', body: png });
    }
    return route.abort();
  });
  await page.addInitScript(() => {
    const remote = window.location.search.includes('remote');
    // SketchUp preferences live in the host, not file:// browser storage.
    const override = null;
    window.testState = { token: null, apiCalls: [], imported: 0, mode: override || (remote ? 'remote' : 'bundled'), configured: remote, failHealth: window.location.search.includes('failed') && !override, runtimePolls: 0, restarts: 0, previousDocument: window.name, nativeCalls: [], anchor: null, nextJobPartial: false, currentJobPartial: false };
    window.addEventListener('beforeunload', () => { window.name = JSON.stringify({stored:sessionStorage.getItem('test-runtime-mode'),url:location.href,calls:window.testState.nativeCalls}); });
    window.sketchup = { async openmap(raw) {
      const message = JSON.parse(raw), a = message.args, s = window.testState;
      s.nativeCalls.push({action:message.action,args:a,id:message.id,time:Date.now()});
      let result = { ok: true, data: {} }, delay = 1;
      const session = { access_token: 'ui-valid-token', refresh_token: 'ui-refresh', user: { email: 'test@example.org' } };
      if (message.action === 'config') {
        const preferred = await window.__testModePreference(null);
        if (preferred) { s.mode = preferred; s.failHealth = false; }
        result.data = { server: 'http://127.0.0.1:50001', mode: s.mode, version: 'test', anchor: s.anchor };
      }
      if (message.action === 'runtime_status') { s.runtimePolls++; result.data = s.runtimePolls < 2 ? { state: 'preparing', progress: 40, mode: s.mode, message: 'Đang cài bộ xử lý' } : { state: 'ready', progress: 100, mode: s.mode, message: 'Bộ xử lý sẵn sàng' }; }
      if (message.action === 'runtime_restart') { s.restarts++; s.runtimePolls = 0; s.token = null; s.failHealth = false; }
      if (message.action === 'session') s.token = a.access_token;
      if (message.action === 'set_mode') await window.__testModePreference(a.mode);
      if (message.action === 'api') {
        s.apiCalls.push({ method: a.method, path: a.path, body: a.body });
        if (a.path === '/health') result = s.failHealth ? { ok: false, status: 0, error: 'Không nhận được phản hồi hợp lệ từ bộ xử lý cục bộ.' } : { ok: true, data: { auth_mode: s.mode === 'bundled' ? 'local' : 'supabase', auth_configured: s.configured, ocr_available: true, version: 'test' } };
        else if (a.path === '/api/runtime/config') { if (a.method === 'POST') s.configured = true; result.data = { supabase_url: '', public_key: '', auth_configured: s.configured, redirect_url: 'http://127.0.0.1:*/auth/callback**' }; }
        else if (a.path === '/api/auth/login') result = a.body.password === 'correct-test-password' ? { ok: true, data: session } : { ok: false, status: 401, error: 'Email hoặc mật khẩu không đúng.' };
        else if (a.path === '/api/auth/google/start') result.data = { flow_id: 'test-flow', poll_secret: 'test-secret', authorize_url: 'https://test.supabase.co/auth/v1/authorize?provider=google' };
        else if (a.path.indexOf('/api/auth/google/status?') === 0) result.data = { state: 'ready', session };
        else if (a.path === '/api/auth/logout') result.data = { ok: true };
        else if (s.mode !== 'bundled' && s.token !== 'ui-valid-token') result = { ok: false, status: 401, error: 'Chưa đăng nhập.' };
        else if (a.path === '/api/me') result.data = s.mode === 'bundled' ? { id: 'local-device', email: 'Trên máy này' } : { id: 'ui-user', email: 'test@example.org' };
        else if (a.path === '/api/geocode' || a.path === '/api/search_suggest' || a.path.startsWith('/api/search?')) {
          const query = a.body?.query || new URLSearchParams(a.path.split('?')[1]).get('q') || '';
          const place = (label, lat, lon) => ({ label, title: label, display_name: label, lat, lon });
          let results = [];
          if (query.includes('Hà Nội')) results = [place('Hà Nội, Việt Nam',21.028511,105.854444),place('Hoàn Kiếm, Hà Nội',21.028,105.852)];
          else if (query.includes('Đà Nẵng')) results = [place('Đà Nẵng, Việt Nam',16.0544,108.2022),place('Hải Châu, Đà Nẵng',16.047,108.206)];
          else if (query.includes('Đà Lạt')) results = [place('Đà Lạt, Lâm Đồng',11.9404,108.4583),place('Hồ Xuân Hương, Đà Lạt',11.9418,108.4458)];
          else if (query.includes('Huế')) results = [place('Huế, Việt Nam',16.4637,107.5909)];
          result.data = { results, attribution: 'Fixture geocoder' };
          if (a.path === '/api/search_suggest') delay = query.includes('Huế') ? 900 : 15;
        }
        else if (a.path === '/api/jobs') { s.currentJobPartial = s.nextJobPartial; s.nextJobPartial = false; result.data = { id: 'a'.repeat(32), state: 'queued' }; }
        else if (a.path === '/api/jobs/' + 'a'.repeat(32)) result.data = {
          state: 'complete', progress: 100,
          message: s.currentJobPartial ? 'Đã dựng nền/địa hình; thiếu lớp OSM đường, nhà.' : 'Sẵn sàng nạp vào SketchUp',
          partial: s.currentJobPartial, missing_layers: s.currentJobPartial ? ['roads','buildings'] : [],
          warnings: s.currentJobPartial ? ['Chưa tải được đường/nhà OSM; chỉ có nền ảnh và địa hình.'] : []
        };
        else throw new Error('Unexpected test API: ' + a.path);
      }
      if (message.action === 'import') {
        s.imported++; s.anchor = { lat: Number(document.getElementById('lat').value), lon: Number(document.getElementById('lon').value), elevation: 0, terrain_mode: 'flat' };
        result.data = { name: 'OpenMap_test', triangles: 32, warnings: s.currentJobPartial ? ['Thiếu đường và nhà OSM.'] : [] };
      }
      if (message.action === 'reset_anchor') s.anchor = null;
      if (message.action === 'export' || message.action === 'export_glb' || message.action === 'save_skp') result.data = { saved: true };
      if (message.action === 'preview') result.data = { materials: [{ name: 'Ground', color: [140,180,140] }], meshes: [{ vertices: [[0,0,0],[100,0,0],[0,100,20]], triangles: [[0,1,2]], uv: [[0,0],[1,0],[0,1]], material: 0, smooth: true }] };
      setTimeout(() => window.OpenMap.receive(message.id, result), delay);
    } };
  });
  async function centerIs(lat, lon) {
    await page.waitForFunction(({lat,lon}) => document.getElementById('lat').value === lat && document.getElementById('lon').value === lon, {lat,lon});
  }
  async function assertOnePanel() {
    const layout = await page.evaluate(() => {
      const panel = document.getElementById('control-panel'), job = document.querySelector('.job-card'), anchor = document.getElementById('anchor-panel');
      const box = panel.getBoundingClientRect(), j = job.getBoundingClientRect(), select = document.getElementById('selection-box').getBoundingClientRect();
      return {
        contained: [job,anchor,document.getElementById('app-header')].every(el => panel.contains(el)),
        jobPosition: getComputedStyle(job).position, anchorPosition: getComputedStyle(anchor).position,
        center: select.left + select.width/2, right: box.right,
        within: j.left >= box.left-1 && j.right <= box.right+1, overflow: document.documentElement.scrollWidth > innerWidth
      };
    });
    assert(layout.contained, 'Header, progress, exports and anchor must share one sidebar');
    assert.notEqual(layout.jobPosition, 'fixed'); assert.notEqual(layout.anchorPosition, 'fixed');
    assert(layout.within, 'Progress should stay inside the sidebar');
    assert(layout.center > layout.right+2, 'Selection center should remain visible beside the sidebar');
    assert(!layout.overflow, 'No horizontal page overflow');
  }
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href);
  await page.waitForFunction(() => !document.getElementById('workspace').hidden);
  assert(await page.locator('#login').isHidden());
  assert(await page.locator('#logout').isHidden());
  assert(await page.locator('#setup-overlay').isHidden());
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/') || c.path === '/api/runtime/config'));
  assert(await page.locator('#anchor-panel').isHidden());
  await assertOnePanel();
  assert.equal(await page.locator('#map-style').inputValue(), 'esri_sat');
  assert.match(await page.locator('#map-style option:checked').textContent(), /Vệ tinh sạch/);
  await page.waitForFunction(() => Array.from(document.querySelectorAll('#tiles img')).some(i => i.src.includes('World_Imagery/MapServer/tile/')));
  await page.locator('#address').fill('10.770000, 106.700000');
  await page.locator('#address').press('Enter'); await centerIs('10.770000','106.700000');
  await page.locator('#address').fill('Hà Nội');
  await page.locator('#address').press('Enter');
  await centerIs('21.028511','105.854444');
  await page.waitForFunction(() => document.getElementById('address').value === 'Hà Nội, Việt Nam');
  assert((await page.evaluate(() => window.testState.apiCalls)).some(c => c.path === '/api/geocode' && c.body.query === 'Hà Nội'));
  await page.locator('#address').fill('Đà Nẵng');
  await page.locator('#search-results button').filter({hasText:'Đà Nẵng, Việt Nam'}).waitFor();
  await page.locator('#address').press('ArrowDown'); await page.locator('#address').press('Enter');
  await centerIs('16.054400','108.202200');
  await page.locator('#address').fill('Đà Lạt');
  await page.locator('#search-results button').filter({hasText:'Hồ Xuân Hương'}).click();
  await centerIs('11.941800','108.445800');
  await page.locator('#address').fill('Huế');
  await page.waitForFunction(() => window.testState.apiCalls.some(c => c.path === '/api/search_suggest' && c.body.query === 'Huế'));
  await page.locator('#address').fill('Hà Nội');
  await page.locator('#search-results button').filter({hasText:'Hà Nội, Việt Nam'}).waitFor();
  await page.waitForTimeout(1000); // Fixture intentionally delivers stale Huế after Hà Nội.
  assert.equal(await page.locator('#search-results button').filter({hasText:'Huế'}).count(),0);
  await page.locator('#address').press('Escape');
  assert.equal(await page.locator('#search-results button:visible').count(),0);
  await page.locator('#address').fill('10.770000, 106.700000');
  await page.locator('#address').press('Enter');
  assert.equal(await page.locator('#lat').inputValue(), '10.770000');
  await page.locator('#address').fill('10°46′12″N 106°42′0″E');
  await page.locator('#address').press('Enter');
  assert.equal(await page.locator('#lat').inputValue(), '10.770000');
  await page.locator('#address').fill('https://www.google.com/maps/@16.0544,108.2022,18z');
  await page.locator('#address').press('Enter'); await centerIs('16.054400','108.202200');
  await page.locator('#map-style').selectOption('google_sat');
  assert.equal(await page.locator('#imagery').inputValue(),'google_sat');
  await page.locator('#auto-import').uncheck();
  await page.locator('#build').click();
  await page.waitForFunction(() => !document.getElementById('import').disabled);
  const builds = (await page.evaluate(() => window.testState.apiCalls)).filter(c => c.path === '/api/jobs' && c.method === 'POST');
  assert.equal(builds.at(-1).body.imagery,'google_sat');
  await page.locator('#import').click();
  await page.locator('#job-detail').filter({ hasText: '32 tam giác' }).waitFor();
  assert.equal(await page.evaluate(() => window.testState.imported), 1);
  await page.locator('#anchor-panel').waitFor(); await assertOnePanel();
  await page.locator('#export').click();
  await page.locator('#notice').filter({ hasText: 'Đã lưu gói OBJ' }).waitFor();
  await page.locator('#export-glb').click();
  await page.locator('#notice').filter({ hasText: 'Đã lưu mô hình GLB' }).waitFor();
  await page.locator('#theme').click();
  assert(await page.locator('body').evaluate(e => e.classList.contains('dark')));
  await page.locator('#theme').click();
  await page.locator('#view3d').click();
  await page.locator('#preview3d').waitFor();
  await page.waitForFunction(() => document.getElementById('preview3d').width > 200);
  assert.equal(await page.locator('#preview3d').evaluate(e => e.getContext('webgl').getError()), 0);
  await page.locator('#wireframe').click();
  await page.locator('#reset-camera').click();
  await page.locator('#view2d').click();
  await page.locator('#auto-import').check();
  await page.locator('#build').click();
  await page.waitForFunction(() => window.testState.imported === 2);
  const artifacts = process.env.OPENMAP_TEST_ARTIFACTS || path.join(root, 'test-artifacts');
  fs.mkdirSync(artifacts, { recursive: true });
  await page.screenshot({ path: path.join(artifacts, 'interface-fixture.png'), fullPage: true });
  assert(Array.from(tileRequests).some(url => url.includes('server.arcgisonline.com')));
  assert(Array.from(tileRequests).some(url => url.includes('google.com/vt/')));
  await page.evaluate(() => { window.testState.nextJobPartial = true; });
  await page.locator('#build').click(); await page.locator('#job-warning').waitFor();
  assert.match(await page.locator('#job-warning').textContent(),/OSM|đường|nhà/);
  await page.waitForTimeout(150); // Native fixture replies all complete within 1 ms.
  assert.equal(await page.evaluate(() => window.testState.imported),2);
  assert.match(await page.locator('#import').textContent(),/Nạp.*nền|Nạp.*địa hình/i);
  await page.locator('#import').click(); await page.waitForFunction(() => window.testState.imported === 3);
  await page.screenshot({path:path.join(artifacts,'partial-osm-fixture.png'),fullPage:true});
  await page.setViewportSize({ width: 650, height: 860 });
  await assertOnePanel();
  await page.screenshot({path:path.join(artifacts,'interface-650-fixture.png'),fullPage:true});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.locator('#settings').click();
  await page.locator('#setup-overlay').waitFor();
  await page.locator('#setup-local-info').filter({ hasText: 'không cần đăng nhập' }).waitFor();
  await page.locator('#setup-restart').click();
  await page.waitForFunction(() => !document.getElementById('workspace').hidden);
  assert.equal(await page.evaluate(() => window.testState.restarts), 1);
  assert.equal(await page.evaluate(() => window.testState.token), null);
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/') || c.path === '/api/runtime/config'));

  // Optional remote server mode retains genuine authentication.
  await page.setViewportSize({width:1040,height:860});
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?remote=1');
  await page.locator('#login-options').waitFor();
  await page.locator('#email').fill('test@example.org');
  await page.locator('#password').fill('wrong-password');
  await page.locator('#login-button').click();
  await page.locator('#notice').filter({ hasText: 'không đúng' }).waitFor();
  assert(await page.locator('#workspace').isHidden());
  await page.locator('#password').fill('correct-test-password');
  await page.locator('#login-button').click();
  await page.waitForFunction(() => !document.getElementById('workspace').hidden);
  await page.setViewportSize({width:650,height:860});
  assert(await page.locator('#logout').isVisible());
  await page.locator('#logout').click();
  await page.locator('#login').waitFor();
  await page.locator('#google').click();
  await page.waitForFunction(() => !document.getElementById('workspace').hidden);
  assert.equal(await page.locator('#account-email').textContent(), 'test@example.org');

  // Failed local health opens recovery settings; retry returns to the map.
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?failed=1');
  await page.locator('#setup-overlay').waitFor();
  assert(await page.locator('#login-options').isHidden());
  await page.locator('#setup-restart').click();
  await page.waitForFunction(() => !document.getElementById('workspace').hidden);
  assert.equal(await page.evaluate(() => window.testState.restarts), 1);
  // Remote failure from a retained setting exposes one-click local recovery.
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?remote=1&failed=1');
  await page.locator('#setup-overlay').waitFor();
  assert.equal(await page.locator('#setup-mode').inputValue(), 'remote');
  await page.locator('#setup-runtime').filter({hasText:'Bộ xử lý sẵn sàng'}).waitFor();
  await Promise.all([page.waitForEvent('load'), page.locator('#setup-use-local').click()]);
  await page.waitForFunction(() => !document.getElementById('workspace').hidden, null, {timeout:5000}).catch(async e => {
    const snapshot = await page.evaluate(() => ({state:window.testState,storage:sessionStorage.getItem('test-runtime-mode'),url:location.href,notice:document.getElementById('notice').textContent,connection:document.getElementById('connection').textContent,setup:document.getElementById('setup-message').textContent,overlayHidden:document.getElementById('setup-overlay').hidden}));
    console.error('RECOVERY STATE',JSON.stringify(snapshot,null,2),errors); throw e;
  });
  assert.equal(await page.evaluate(() => window.testState.mode), 'bundled');
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/')));
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('UI PASS: single sidebar, clean Esri satellite, instant geocoding, keyboard/click suggestions, stale search rejection, linked output imagery, partial OSM manual import, direct local workspace without Supabase/login, worker failure/retry, remote failure to local recovery, optional remote login/Google, decimal/DMS coordinates, manual/automatic import, OBJ/GLB, theme, WebGL 3D/wireframe, responsive layout, logout and worker restart. Native bridge/auth responses are fixtures.');
})().catch(error => { console.error(error); process.exit(1); });
