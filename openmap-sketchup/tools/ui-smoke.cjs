/* Run after npm install in tools/ and npx playwright install chromium. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1040, height: 860 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const root = path.resolve(__dirname, '..');
  const png = fs.readFileSync(path.join(root, 'extension/openmap_sketchup/ui/icon.png'));
  await page.route('https://tile.openstreetmap.org/**', route => route.fulfill({ contentType: 'image/png', body: png }));
  await page.addInitScript(() => {
    const remote = window.location.search.includes('remote');
    const override = sessionStorage.getItem('test-runtime-mode');
    window.testState = { token: null, apiCalls: [], imported: 0, mode: override || (remote ? 'remote' : 'bundled'), configured: remote, failHealth: window.location.search.includes('failed') && !override, runtimePolls: 0, restarts: 0 };
    window.sketchup = { openmap(raw) {
      const message = JSON.parse(raw), a = message.args, s = window.testState;
      let result = { ok: true, data: {} };
      const session = { access_token: 'ui-valid-token', refresh_token: 'ui-refresh', user: { email: 'test@example.org' } };
      if (message.action === 'config') result.data = { server: 'http://127.0.0.1:50001', mode: s.mode, version: '0.2.3', anchor: null };
      if (message.action === 'runtime_status') { s.runtimePolls++; result.data = s.runtimePolls < 2 ? { state: 'preparing', progress: 40, mode: s.mode, message: 'Đang cài bộ xử lý' } : { state: 'ready', progress: 100, mode: s.mode, message: 'Bộ xử lý sẵn sàng' }; }
      if (message.action === 'runtime_restart') { s.restarts++; s.runtimePolls = 0; s.token = null; s.failHealth = false; }
      if (message.action === 'session') s.token = a.access_token;
      if (message.action === 'set_mode') sessionStorage.setItem('test-runtime-mode', a.mode);
      if (message.action === 'api') {
        s.apiCalls.push({ method: a.method, path: a.path, body: a.body });
        if (a.path === '/health') result = s.failHealth ? { ok: false, status: 0, error: 'Không nhận được phản hồi hợp lệ từ bộ xử lý cục bộ.' } : { ok: true, data: { auth_mode: s.mode === 'bundled' ? 'local' : 'supabase', auth_configured: s.configured, ocr_available: true, version: 'test' } };
        else if (a.path === '/api/runtime/config') { if (a.method === 'POST') s.configured = true; result.data = { supabase_url: '', public_key: '', auth_configured: s.configured, redirect_url: 'http://127.0.0.1:*/auth/callback**' }; }
        else if (a.path === '/api/auth/login') result = a.body.password === 'correct-test-password' ? { ok: true, data: session } : { ok: false, status: 401, error: 'Email hoặc mật khẩu không đúng.' };
        else if (a.path === '/api/auth/google/start') result.data = { flow_id: 'test-flow', poll_secret: 'test-secret', authorize_url: 'https://test.supabase.co/auth/v1/authorize?provider=google' };
        else if (a.path.indexOf('/api/auth/google/status?') === 0) result.data = { state: 'ready', session };
        else if (a.path === '/api/auth/logout') result.data = { ok: true };
        else if (s.mode !== 'bundled' && s.token !== 'ui-valid-token') result = { ok: false, status: 401, error: 'Chưa đăng nhập.' };
        else if (a.path === '/api/me') result.data = { id: 'ui-user', email: 'test@example.org' };
        else if (a.path === '/api/jobs') result.data = { id: 'a'.repeat(32), state: 'queued' };
        else if (a.path === '/api/jobs/' + 'a'.repeat(32)) result.data = { state: 'complete', progress: 100, message: 'Sẵn sàng nạp vào SketchUp' };
        else throw new Error('Unexpected test API: ' + a.path);
      }
      if (message.action === 'import') { s.imported++; result.data = { name: 'OpenMap_test', triangles: 32, warnings: [] }; }
      if (message.action === 'export' || message.action === 'export_glb' || message.action === 'save_skp') result.data = { saved: true };
      if (message.action === 'preview') result.data = { materials: [{ name: 'Ground', color: [140,180,140] }], meshes: [{ vertices: [[0,0,0],[100,0,0],[0,100,20]], triangles: [[0,1,2]], uv: [[0,0],[1,0],[0,1]], material: 0, smooth: true }] };
      setTimeout(() => window.OpenMap.receive(message.id, result), 1);
    } };
  });
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href);
  await page.locator('#workspace').waitFor();
  assert(await page.locator('#login').isHidden());
  assert(await page.locator('#logout').isHidden());
  assert(await page.locator('#setup-overlay').isHidden());
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/') || c.path === '/api/runtime/config'));
  await page.locator('#address').fill('10.770000, 106.700000');
  await page.locator('#search-form button').click();
  assert.equal(await page.locator('#lat').inputValue(), '10.770000');
  await page.locator('#address').fill('10°46′12″N 106°42′0″E');
  await page.locator('#search-form button').click();
  assert.equal(await page.locator('#lat').inputValue(), '10.770000');
  await page.locator('#auto-import').uncheck();
  await page.locator('#build').click();
  await page.waitForFunction(() => !document.getElementById('import').disabled);
  await page.locator('#import').click();
  await page.locator('#job-detail').filter({ hasText: '32 tam giác' }).waitFor();
  assert.equal(await page.evaluate(() => window.testState.imported), 1);
  await page.locator('#export').click();
  await page.locator('#notice').filter({ hasText: 'Đã lưu gói OBJ' }).waitFor();
  await page.locator('#export-glb').click();
  await page.locator('#notice').filter({ hasText: 'Đã lưu mô hình GLB' }).waitFor();
  await page.locator('#theme').click();
  assert(await page.locator('body').evaluate(e => e.classList.contains('dark')));
  await page.locator('#theme').click();
  await page.locator('#view3d').click();
  await page.locator('#preview3d').waitFor();
  await page.waitForFunction(() => document.getElementById('preview3d').width > 1000);
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
  await page.setViewportSize({ width: 650, height: 860 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.locator('#settings').click();
  await page.locator('#setup-overlay').waitFor();
  await page.locator('#setup-local-info').filter({ hasText: 'không cần đăng nhập' }).waitFor();
  await page.locator('#setup-restart').click();
  await page.locator('#workspace').waitFor();
  assert.equal(await page.evaluate(() => window.testState.restarts), 1);
  assert.equal(await page.evaluate(() => window.testState.token), null);
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/') || c.path === '/api/runtime/config'));

  // Optional remote server mode retains genuine authentication.
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?remote=1');
  await page.locator('#login-options').waitFor();
  await page.locator('#email').fill('test@example.org');
  await page.locator('#password').fill('wrong-password');
  await page.locator('#login-button').click();
  await page.locator('#notice').filter({ hasText: 'không đúng' }).waitFor();
  assert(await page.locator('#workspace').isHidden());
  await page.locator('#password').fill('correct-test-password');
  await page.locator('#login-button').click();
  await page.locator('#workspace').waitFor();
  await page.locator('#logout').click();
  await page.locator('#login').waitFor();
  await page.locator('#google').click();
  await page.locator('#workspace').waitFor();
  assert.equal(await page.locator('#account-email').textContent(), 'test@example.org');

  // Failed local health opens recovery settings; retry returns to the map.
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?failed=1');
  await page.locator('#setup-overlay').waitFor();
  assert(await page.locator('#login-options').isHidden());
  await page.locator('#setup-restart').click();
  await page.locator('#workspace').waitFor();
  assert.equal(await page.evaluate(() => window.testState.restarts), 1);
  // Remote failure from a retained setting exposes one-click local recovery.
  await page.goto(pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href + '?remote=1&failed=1');
  await page.locator('#setup-overlay').waitFor();
  assert.equal(await page.locator('#setup-mode').inputValue(), 'remote');
  await page.locator('#setup-use-local').click();
  await page.locator('#workspace').waitFor();
  assert.equal(await page.evaluate(() => window.testState.mode), 'bundled');
  assert(!(await page.evaluate(() => window.testState.apiCalls)).some(c => c.path.startsWith('/api/auth/')));
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('UI PASS: direct local workspace without Supabase/login, worker failure/retry, remote failure to local recovery, optional remote login/Google, decimal/DMS coordinates, manual/automatic import, OBJ/GLB, theme, WebGL 3D/wireframe, responsive layout, logout and worker restart. Native bridge/auth responses are fixtures.');
})().catch(error => { console.error(error); process.exit(1); });
