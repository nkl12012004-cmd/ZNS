/* Focused lifecycle regressions. Native SketchUp responses are controlled fixtures. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');

(async () => {
  const diagnose = process.argv.includes('--diagnose');
  const failures = [], observations = [];
  function check(value, message) { if (!value) failures.push(message); }
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const root = path.resolve(__dirname, '..');
  const fileURL = pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/index.html')).href;
  async function fixturePage() {
    const page = await browser.newPage({ viewport: { width: 1040, height: 860 } });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.route(/^https?:\/\//, route => route.abort());
    await page.addInitScript(() => {
      const s = window.jobTest = {
        calls: [], jobs: [], imported: 0, importRequests: 0, exports: 0,
        nextPartial: false, holdImport: false, holdPoll: false, holdCancel: false,
        importFailures: 0, exportFailures: 0, meFailures: 0, cancelFailures: 0,
        heldImports: [], heldPolls: [], heldCancels: [], lastSkp: null,
      };
      function receive(message, result) { setTimeout(() => window.OpenMap.receive(message.id, result), 1); }
      function success(data) { return {ok:true,data}; }
      s.releaseImport = ok => {
        const item = s.heldImports.shift();
        if (!item) throw new Error('No import is pending');
        if (ok) { s.imported++; receive(item.message, success({name:'Job_' + item.job.id.slice(-2),triangles:32,warnings:[]})); }
        else receive(item.message, {ok:false,error:'SketchUp không nạp được mô hình thử nghiệm.'});
      };
      s.releasePoll = complete => {
        const item = s.heldPolls.shift();
        if (!item) throw new Error('No job poll is pending');
        receive(item.message, success({state:complete?'complete':'running',progress:complete?100:40,message:complete?'Sẵn sàng nạp vào SketchUp':'Đang dựng mô hình',partial:item.job.partial,warnings:[],missing_layers:[]}));
      };
      s.releaseCancel = () => {
        const message = s.heldCancels.shift();
        if (!message) throw new Error('No cancellation is pending');
        receive(message, success({ok:true}));
      };
      window.sketchup = {openmap(raw) {
        const message = JSON.parse(raw), a = message.args;
        s.calls.push({action:message.action,args:a});
        let result = success({});
        if (message.action === 'config') result = success({mode:'bundled',server:'http://127.0.0.1:50001',version:'fixture',anchor:null,last_tile:null});
        else if (message.action === 'runtime_status') result = success({mode:'bundled',state:'ready',progress:100,message:'Bộ xử lý sẵn sàng'});
        else if (message.action === 'api') {
          if (a.path === '/health') result = success({auth_mode:'local',auth_configured:false,ocr_available:true,version:'fixture'});
          else if (a.path === '/api/me') {
            if (s.meFailures-- > 0) result = {ok:false,status:502,error:'Không kết nối được bộ xử lý thử nghiệm.'};
            else result = success({id:'local-device',email:'Trên máy này'});
          }
          else if (a.path === '/api/jobs' && a.method === 'POST') {
            const job = {id:(s.jobs.length+1).toString(16).padStart(32,'0'),partial:s.nextPartial};
            s.jobs.push(job); s.nextPartial = false; result = success({id:job.id,state:'queued'});
          }
          else if (a.path.startsWith('/api/jobs/')) {
            const job = s.jobs.find(j => j.id === a.path.split('/')[3]);
            if (!job) throw new Error('Unknown job');
            if (a.method === 'DELETE') {
              if (s.holdCancel) { s.heldCancels.push(message); return; }
              result = s.cancelFailures-- > 0 ? {ok:false,error:'Hủy thử nghiệm thất bại.'} : success({ok:true});
            } else {
              if (s.holdPoll) { s.heldPolls.push({message,job}); return; }
              result = success({state:'complete',progress:100,message:job.partial?'Đã dựng nền/địa hình; thiếu lớp OSM.':'Sẵn sàng nạp vào SketchUp',partial:job.partial,missing_layers:job.partial?['buildings']:[],warnings:job.partial?['Thiếu lớp nhà OSM.']:[]});
            }
          } else throw new Error('Unexpected API '+a.path);
        }
        else if (message.action === 'import') {
          const job = s.jobs.find(j => j.id === a.job_id);
          if (!job) throw new Error('Import lacks a current job');
          s.importRequests++;
          if (s.holdImport) { s.heldImports.push({message,job}); return; }
          if (s.importFailures-- > 0) result = {ok:false,error:'SketchUp không nạp được mô hình thử nghiệm.'};
          else { s.imported++; result = success({name:'Job_'+job.id.slice(-2),triangles:32,warnings:[]}); }
        }
        else if (message.action === 'export' || message.action === 'export_glb') {
          s.exports++;
          result = s.exportFailures-- > 0 ? {ok:false,error:'Không ghi được tệp xuất thử nghiệm.'} : success({saved:true});
        }
        else if (message.action === 'save_skp') { s.lastSkp = a; result = success({saved:true}); }
        receive(message, result);
      }};
    });
    await page.goto(fileURL);
    await page.waitForFunction(() => !document.getElementById('workspace').hidden);
    await page.locator('#auto-import').uncheck();
    return {page,pageErrors};
  }
  async function build(page, partial=false) {
    await page.evaluate(partial => { window.jobTest.nextPartial = partial; }, partial);
    await page.locator('#build').click();
    await page.waitForFunction(() => !document.getElementById('import').disabled);
  }
  async function buttons(page) {
    return page.evaluate(() => Object.fromEntries(['build','import','export','export-glb','cancel'].map(id=>[id,document.getElementById(id).disabled])));
  }

  // A second operation must not unlock Build while a held import still runs.
  {
    const {page,pageErrors} = await fixturePage();
    await build(page,true);
    await page.evaluate(() => { window.jobTest.holdImport = true; });
    await page.locator('#import').click();
    await page.waitForFunction(() => window.jobTest.heldImports.length === 1);
    const during = await buttons(page);
    const phase = await page.locator('#job-message').textContent();
    if (!during.export) {
      await page.locator('#export').click();
      await page.waitForFunction(() => window.jobTest.exports === 1 && !document.getElementById('export').disabled);
    }
    const afterExport = await buttons(page);
    observations.push({case:'held-import',during,phase,afterExport});
    check(afterExport.build, 'Completing another operation must not unlock Build during an import');
    check(/nạp|tải.*mô hình|import/i.test(phase) && !/sẵn sàng/i.test(phase), 'Pending import must show its own phase instead of the old ready message');
    const jobCount = await page.evaluate(() => window.jobTest.jobs.length);
    await page.locator('#build').evaluate(button => {
      button.click();
      button.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    });
    check(await page.evaluate(() => window.jobTest.jobs.length) === jobCount, 'A pending import must prevent a second job from being submitted');
    const previousActions = await page.evaluate(() => window.jobTest.calls.filter(c => ['export','export_glb','save_skp','preview'].includes(c.action)).length);
    await page.evaluate(() => ['export','export-glb','save-skp','view3d'].forEach(id => document.getElementById(id).dispatchEvent(new MouseEvent('click',{bubbles:true}))));
    check(await page.evaluate(() => window.jobTest.calls.filter(c => ['export','export_glb','save_skp','preview'].includes(c.action)).length) === previousActions, 'Queued action events must not bypass the busy operation guard');
    await page.evaluate(() => window.jobTest.releaseImport(false));
    await page.locator('#notice').filter({hasText:'không nạp được'}).waitFor();
    await page.waitForFunction(() => !document.getElementById('import').disabled && !document.getElementById('build').disabled);
    check((await pageErrors).length===0,'Held import recovery must not throw page errors');
    await page.close();
  }

  // Errors retain the completed job and offer a retry without creating it again.
  {
    const {page,pageErrors} = await fixturePage();
    await build(page,true);
    await page.evaluate(() => { window.jobTest.importFailures = 1; });
    await page.locator('#import').click();
    await page.locator('#notice').filter({hasText:'không nạp được'}).waitFor();
    await page.waitForFunction(() => !document.getElementById('import').disabled && !document.getElementById('build').disabled);
    check(await page.locator('#job-warning').isVisible(),'Partial OSM warning must survive an import failure');
    const failedPhase = (await page.locator('#job-message').textContent()) + ' ' + (await page.locator('#job-detail').textContent());
    check(/không|lỗi/i.test(failedPhase),'Native import failure must stay visible in job progress, not only a transient toast');
    await page.locator('#import').click();
    await page.waitForFunction(() => window.jobTest.imported===1 && !document.getElementById('import').disabled && !document.getElementById('build').disabled);
    check(await page.evaluate(() => window.jobTest.jobs.length)===1,'Import retry must not create a duplicate job');
    check(await page.locator('#job-warning').isVisible(),'Partial OSM warning must remain visible after manual import');

    await page.evaluate(() => { window.jobTest.meFailures = 1; });
    const before = await page.evaluate(() => window.jobTest.importRequests);
    await page.locator('#import').click();
    await page.locator('#notice').filter({hasText:'Không kết nối được'}).waitFor();
    check(await page.evaluate(() => window.jobTest.importRequests)===before,'Failed preflight must not invoke native import');
    check(!(await buttons(page)).import && !(await buttons(page)).build,'Preflight error must restore retry controls');

    await page.evaluate(() => { window.jobTest.exportFailures = 1; });
    await page.locator('#export').click();
    await page.locator('#notice').filter({hasText:'Không ghi được'}).waitFor();
    check(!(await buttons(page)).export && !(await buttons(page)).build,'Failed export must restore retry controls');
    await page.locator('#export').click();
    await page.locator('#notice').filter({hasText:'Đã lưu gói OBJ'}).waitFor();
    check(await page.evaluate(() => window.jobTest.jobs.length)===1,'Export retry must reuse the same job');
    observations.push({case:'error-retries',buttons:await buttons(page),jobs:await page.evaluate(()=>window.jobTest.jobs.length),pageErrors});
    if (process.env.OPENMAP_TEST_JOB_SKP === '1') {
      await page.locator('#save-skp').click();
      await page.waitForFunction(() => !!window.jobTest.lastSkp);
      check(await page.evaluate(() => window.jobTest.lastSkp.job_id === window.jobTest.jobs[0].id),'SKP action must identify the current completed job');
    }
    await page.close();
  }

  // A late completed poll must not auto-import after the user requests Cancel.
  {
    const {page,pageErrors} = await fixturePage();
    await page.locator('#auto-import').check();
    await page.evaluate(() => { window.jobTest.holdPoll=true; window.jobTest.holdCancel=true; });
    await page.locator('#build').click();
    await page.waitForFunction(() => window.jobTest.heldPolls.length===1);
    await page.locator('#cancel').click();
    await page.waitForFunction(() => window.jobTest.heldCancels.length===1);
    await page.evaluate(() => window.jobTest.releasePoll(true));
    await page.waitForTimeout(80); // Controlled callbacks resolve within 1 ms.
    const requestedImports = await page.evaluate(() => window.jobTest.importRequests);
    observations.push({case:'cancel-late-complete',requestedImports,buttons:await buttons(page)});
    check(requestedImports===0,'A completed poll received after Cancel must not auto-import');
    await page.evaluate(() => window.jobTest.releaseCancel());
    await page.waitForFunction(() => !document.getElementById('build').disabled);
    check((await pageErrors).length===0,'Cancellation must not throw page errors');
    await page.close();
  }

  // Failed cancellation resumes observation without reviving automatic import.
  {
    const {page,pageErrors} = await fixturePage();
    await page.locator('#auto-import').check();
    await page.evaluate(() => { window.jobTest.holdPoll=true; window.jobTest.cancelFailures=1; });
    await page.locator('#build').click();
    await page.waitForFunction(() => window.jobTest.heldPolls.length===1);
    await page.locator('#cancel').click();
    await page.locator('#notice').filter({hasText:'Hủy thử nghiệm thất bại'}).waitFor();
    await page.waitForFunction(() => window.jobTest.heldPolls.length===2);
    check(!(await buttons(page)).cancel,'Failed cancellation must offer a retry while the job is running');
    await page.evaluate(() => { window.jobTest.releasePoll(true); window.jobTest.releasePoll(true); });
    await page.waitForFunction(() => !document.getElementById('import').disabled);
    check(await page.evaluate(() => window.jobTest.importRequests)===0,'Failed cancellation must not revive auto-import');
    await page.locator('#import').click();
    await page.waitForFunction(() => window.jobTest.imported===1 && !document.getElementById('build').disabled);
    check((await pageErrors).length===0,'Failed cancellation recovery must not throw page errors');
    observations.push({case:'failed-cancel',buttons:await buttons(page),imported:await page.evaluate(()=>window.jobTest.imported)});
    await page.close();
  }

  // A reply from a pre-restart native action must not overwrite or unlock a new job.
  {
    const {page,pageErrors} = await fixturePage();
    await build(page);
    await page.evaluate(() => { window.jobTest.holdImport=true; });
    await page.locator('#import').click();
    await page.waitForFunction(() => window.jobTest.heldImports.length===1);
    await page.locator('#settings').click();
    await page.locator('#setup-overlay').waitFor();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#setup-restart').click();
    await page.waitForFunction(() => !document.getElementById('workspace').hidden && !document.getElementById('build').disabled);
    await page.evaluate(() => { window.jobTest.holdPoll=true; });
    await page.locator('#build').click();
    await page.waitForFunction(() => window.jobTest.heldPolls.length===1);
    await page.evaluate(() => window.jobTest.releaseImport(true));
    await page.waitForTimeout(60);
    check((await buttons(page)).build,'An obsolete import finally must not unlock a newly running job');
    check(!(await page.locator('#job-detail').textContent()).includes('Job_01'),'An obsolete import must not replace the new job status');
    await page.locator('#cancel').click();
    await page.waitForFunction(() => !document.getElementById('build').disabled);
    check((await pageErrors).length===0,'Restart invalidation must not throw page errors');
    observations.push({case:'restart-stale-import',jobs:await page.evaluate(()=>window.jobTest.jobs.length),buttons:await buttons(page)});
    await page.close();
  }

  await browser.close();
  console.log(JSON.stringify({observations,failures},null,2));
  if (!diagnose) assert.deepEqual(failures,[]);
  console.log(diagnose?'Job lifecycle diagnosis complete.':'UI job lifecycle PASS: held operations, partial/manual retries, API/native errors, cancellation intent/retry and stale post-restart replies.');
})().catch(error => { console.error(error); process.exit(1); });

