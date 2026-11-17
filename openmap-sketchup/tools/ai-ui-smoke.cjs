/* New SiteCraft UI, exercised with the documented native/worker protocol only.
 * This test does not open Google Flow or submit a cloud generation.
 * Run: PLAYWRIGHT_BROWSERS_PATH=/workspace/work/browsers node tools/ai-ui-smoke.cjs
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const file = pathToFileURL(path.join(root, 'extension/openmap_sketchup/ui/ai.html')).href;
const artifacts = path.join(root, 'test-artifacts');
fs.mkdirSync(artifacts, { recursive: true });

async function fixture(page) {
  await page.route(/^https?:\/\//, route => route.abort());
  await page.addInitScript(() => {
    let count = 1;
    const id = () => (count++).toString(16).padStart(32, '0');
    const clone = value => JSON.parse(JSON.stringify(value));
    const s = window.fixture = { native: [], calls: [], assets: {}, jobs: {}, requests: {}, saves: [], bridge: {port:17865,paired:false,connected:false}, failAck:false, failCapture:false, failCancel:false, cancelComplete:false, delayAsset:null, uploads:[], cameraStamp:'camera-a' };
    function image(color, width = 800, height = 600) {
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      const c = canvas.getContext('2d'); c.fillStyle = color; c.fillRect(0, 0, width, height);
      c.fillStyle = '#efe8ca'; c.fillRect(width*.12,height*.2,width*.56,height*.62); c.fillStyle = '#416652'; c.fillRect(width*.2,height*.35,width*.36,height*.3);
      return canvas.toDataURL('image/png');
    }
    async function put(dataURL, name, role) {
      const img = new Image(); img.src = dataURL; await img.decode();
      const asset = { id:id(), name, role, mime:dataURL.match(/^data:([^;]+)/)[1], width:img.naturalWidth, height:img.naturalHeight, data_url:dataURL };
      s.assets[asset.id] = asset; return asset;
    }
    s.makeAsset = async (color,width,height) => clone(await put(image(color,width,height), 'Flow_fixture.png', 'result'));
    s.complete = async jobId => {
      const result = await s.makeAsset('#779d80'); Object.assign(s.jobs[jobId], {state:'complete',result_ids:[result.id],message:'Ảnh thực nhận từ fixture',progress:100}); return result.id;
    };
    s.summary = job => { const copy = clone(job); delete copy.prompt; delete copy.options; delete copy.reference_ids; delete copy.annotation_notes; return copy; };
    window.sketchup = { async sitecraft_ai(raw) {
      const message = JSON.parse(raw), a = message.args || {};
      s.native.push(clone(message)); let response = {ok:true,data:{}}, delay = 1;
      try {
        if (message.action === 'config') response.data = {managed:true,model_context:'model-a',version:'fixture',runtime:{state:'ready'},supports_frame:true,capture_helpers:true,capture_long_edge:true,camera_stamp:s.cameraStamp};
        else if (message.action === 'capture') {
          if (s.failCapture) { s.failCapture=false; response={ok:false,status:500,error:'Fixture capture failed'}; }
          else { response.data = clone(await put(image('#9faeb8'), 'SketchUp_capture.png', 'source')); response.data.camera_stamp=s.cameraStamp; response.data.model_context='model-a'; }
        }
        else if (message.action === 'save_image') { assertAsset(a.asset_id); s.saves.push(a.asset_id); response.data = {saved:true}; }
        else if (message.action === 'watch_downloads') { s.watching=a.job_id; response.data={watching:true,job_id:a.job_id,state:'watching',message:'Đang theo dõi thư mục đã chọn'}; }
        else if (message.action === 'downloads_status') response.data={watching:!!s.watching,job_id:s.watching,state:s.watching?'watching':'idle'};
        else if (message.action === 'stop_downloads') { s.watching=null; response.data={watching:false}; }
        else if (message.action === 'api') {
          s.calls.push(clone(a)); const p = a.path.replace('/api/ai/',''), body = a.body;
          if (p === 'status') response.data = {protocol:1,bridge:clone(s.bridge),jobs:Object.values(s.jobs).map(s.summary)};
          else if (p === 'pair') response.data = {code:'C7K9Q2',port:17865,expires_in:120};
          else if (p === 'unpair') s.bridge = {port:17865,paired:false,connected:false};
          else if (p === 'assets' && a.method === 'POST') { const v = await put(body.data_url, body.name, body.role); s.uploads.push(clone(v)); response.data = clone(v); delete response.data.data_url; }
          else if (p.startsWith('assets/')) {
            const assetId = p.split('/')[1]; assertAsset(assetId); response.data = clone(s.assets[assetId]);
            if (p.endsWith('/thumbnail')) {
              const source=new Image(); source.src=response.data.data_url; await source.decode(); const canvas=document.createElement('canvas');
              const scale=Math.min(1,192/Math.max(source.width,source.height)); canvas.width=Math.round(source.width*scale);canvas.height=Math.round(source.height*scale);canvas.getContext('2d').drawImage(source,0,0,canvas.width,canvas.height);
              Object.assign(response.data,{width:canvas.width,height:canvas.height,data_url:canvas.toDataURL('image/png'),mime:'image/png'});
            } else if (s.delayAsset === assetId) delay=1000;
          }
          else if (p === 'jobs' && a.method === 'POST') {
            if (!/^[a-f0-9]{32}$/.test(body.client_request_id)) throw new Error('Missing idempotency key');
            const previous = s.requests[body.client_request_id];
            if (previous && JSON.stringify(previous.body) !== JSON.stringify(body)) throw new Error('Idempotency body changed');
            let job;
            if (previous) job = s.jobs[previous.id];
            else { job = Object.assign(clone(body), {id:id(),state:body.options.manual_handoff?'waiting_user':'queued',created:Date.now()/1000,updated:Date.now()/1000,result_ids:[],message:body.options.manual_handoff?'Thao tác thủ công trong Flow':'Đã xếp hàng, chưa có tiến độ xác nhận',progress:null}); s.jobs[job.id]=job; s.requests[body.client_request_id]={id:job.id,body:clone(body)}; }
            response.data = s.summary(job);
            if (s.failAck) { s.failAck=false; response = {ok:false,status:0,error:'Fixture lost acknowledgement'}; }
          }
          else if (p === 'jobs' && a.method === 'GET') response.data = {jobs:Object.values(s.jobs).map(s.summary)};
          else if (/^jobs\/[a-f0-9]{32}\/import$/.test(p)) {
            const job = s.jobs[p.split('/')[1]]; if (!['waiting_user','error'].includes(job.state)) throw new Error('Not waiting'); assertAsset(body.asset_id);
            Object.assign(job,{state:'complete',result_ids:[body.asset_id],manual_import:true,message:'Đã nhập ảnh thủ công',progress:100}); response.data=s.summary(job);
          }
          else if (p.startsWith('jobs/')) {
            const job = s.jobs[p.split('/')[1]]; if (!job) throw new Error('Missing job');
            if (a.method === 'DELETE') {
              if (s.failCancel) { s.failCancel=false; response={ok:false,status:503,error:'Fixture cancel unavailable'}; setTimeout(()=>window.SiteCraftAI.receive(message.id,response),1); return; }
              if (s.cancelComplete) { s.cancelComplete=false; await s.complete(job.id); }
              else if (job.state !== 'complete') Object.assign(job,{state:'cancelled',result_ids:[],message:'Đã hủy'});
              response.data = {ok:true,job:s.summary(job)};
            } else response.data=clone(job);
          }
          else if (p.startsWith('history/') && a.method === 'DELETE') { delete s.jobs[p.split('/')[1]]; response.data = {ok:true}; }
          else throw new Error('Unexpected API '+a.method+' '+p);
        }
        else if (!['open_flow','open_folder','open_bridge_folder','camera_watch','close','frame_overlay','open_image','open_cleanup','watch_downloads','stop_downloads'].includes(message.action)) throw new Error('Unexpected native action '+message.action);
      } catch (error) { response = {ok:false,status:400,error:error.message}; }
      setTimeout(() => window.SiteCraftAI.receive(message.id, response),delay);
    } };
    function assertAsset(assetId) { if (!s.assets[assetId]) throw new Error('Missing asset '+assetId); }
  });
}

(async () => {
  const browser = await chromium.launch({ headless:true, args:['--no-sandbox'] });
  const page = await browser.newPage({viewport:{width:1440,height:950}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  try {
    await fixture(page); await page.goto(file);
    await page.waitForFunction(() => document.getElementById('connection-label').textContent === 'Chưa ghép Chrome');
    assert.equal(await page.locator('#prompt').inputValue(),await page.evaluate(()=>SiteCraftAIReferencePrompts.basePreviewFixture.render),'Fresh editable prompt uses only the verified visible preview fixture');
    assert.equal(await page.evaluate(()=>SiteCraftAIReferencePrompts.productionBaseUnavailable),true);
    assert(await page.locator('#render').isDisabled());
    assert.match(await page.locator('.flow-note').innerText(),/Google Flow.*đăng nhập Google/s);
    await page.locator('#settings-open').click();
    await page.locator('#open-bridge-folder').click();
    await page.locator('#pair').click();
    await page.waitForFunction(() => document.getElementById('pair-code').textContent === 'C7K9Q2');
    assert.match(await page.locator('#pair-info').innerText(),/17865/);
    assert((await page.evaluate(() => fixture.native)).some(v=>v.action==='open_bridge_folder'));
    await page.screenshot({path:path.join(artifacts,'ai-settings-fixture.png')});
    await page.keyboard.press('Escape');
    await page.locator('#capture').click();
    await page.waitForFunction(() => document.getElementById('source-info').textContent.includes('800 × 600'));
    assert(await page.locator('#render').isDisabled(), 'Capture does not fake a connected Flow');
    await page.evaluate(() => fixture.bridge={port:17865,paired:true,connected:true});
    await page.waitForFunction(() => !document.getElementById('render').disabled);

    // File/drop/paste upload real media into the asset protocol, references capped at four.
    const png = Buffer.from((await page.evaluate(() => Object.values(fixture.assets)[0].data_url)).split(',')[1],'base64');
    const refs = Array.from({length:5},(_,i)=>({name:`ref${i}.png`,mimeType:'image/png',buffer:png}));
    await page.locator('#reference-file').setInputFiles(refs);
    await page.waitForFunction(() => document.querySelectorAll('.reference-thumb').length === 4);
    assert(await page.locator('#add-reference').isDisabled());
    assert.equal((await page.evaluate(()=>fixture.uploads.filter(v=>v.role==='reference'))).length,4);
    await page.locator('#aspect').selectOption('1:1');
    assert.match(await page.locator('#source-info').innerText(),/600 × 600/);
    await page.locator('[data-tool="rectangle"]').click();
    const canvas = await page.locator('#annotation-canvas').boundingBox();
    await page.mouse.move(canvas.x+canvas.width*.2,canvas.y+canvas.height*.2); await page.mouse.down();
    await page.mouse.move(canvas.x+canvas.width*.65,canvas.y+canvas.height*.7); await page.mouse.up();
    await page.locator('#region-list textarea').fill('Đổi phần tường trong vùng sang gạch đỏ.');
    assert.equal(await page.locator('#region-list textarea').count(),1);
    await page.locator('#annotation-undo').click(); assert.equal(await page.locator('#region-list textarea').count(),0);
    await page.locator('#annotation-redo').click(); assert.equal(await page.locator('#region-list textarea').count(),1);
    await page.screenshot({path:path.join(artifacts,'ai-annotations-fixture.png')});
    await page.locator('#render').click();
    await page.waitForFunction(() => Object.keys(fixture.jobs).length===1 && !document.getElementById('render').disabled);
    const job1 = await page.evaluate(() => Object.values(fixture.jobs)[0]);
    assert.equal(job1.reference_ids.length,4); assert.equal(job1.options.aspect,'1:1');
    assert.equal(job1.options.keep_design,true); assert.equal(job1.options.keep_camera,true);
    assert.match(job1.annotation_notes,/gạch đỏ/); assert.equal(job1.prompt.match(/gạch đỏ/g).length,1,'Notes occur once in the complete prompt');
    assert.equal(job1.options.prompt_is_complete,true); assert.equal(job1.prompt,await page.locator('#prompt-preview').inputValue());
    const sent = await page.evaluate(id=>fixture.assets[id],job1.source_id);
    assert.equal(sent.role,'annotation'); assert.equal(sent.width,600); assert.equal(sent.height,600);
    const markedPixel=await page.evaluate(async id=>{
      const image=new Image(); image.src=fixture.assets[id].data_url; await image.decode();
      const canvas=document.createElement('canvas'); canvas.width=image.width; canvas.height=image.height;
      const context=canvas.getContext('2d'); context.drawImage(image,0,0); return Array.from(context.getImageData(120,200,1,1).data);
    },sent.id);
    assert(markedPixel[0]>200&&markedPixel[1]<150,'The transmitted source contains the annotation ink');
    assert.equal(await page.locator('#job-progress').getAttribute('value'),null,'No invented progress for unknown state');
    await page.evaluate(id=>Object.assign(fixture.jobs[id],{state:'running',progress:37,message:'Flow reported 37%'}),job1.id);
    await page.waitForFunction(() => document.getElementById('job-progress').value===37);
    assert.equal(await page.locator('#job-progress').evaluate(el=>el.max),100);
    const result1 = await page.evaluate(id=>fixture.complete(id),job1.id);
    await page.waitForFunction(() => !document.getElementById('save-result').disabled);
    assert.equal(await page.locator('#result-image').getAttribute('src'),await page.evaluate(id=>fixture.assets[id].data_url,result1));
    await page.locator('#compare-toggle').click();
    await page.locator('#compare-range').fill('31'); await page.locator('#compare-range').dispatchEvent('input');
    assert.match(await page.locator('#compare-before-clip').getAttribute('style'),/69%/);
    await page.locator('#save-result').click();
    await page.waitForFunction(id=>fixture.saves.includes(id),result1);
    await page.waitForFunction(()=>!document.getElementById('save-result').disabled);
    await page.evaluate(()=>document.getElementById('notice').hidden=true);
    await page.screenshot({path:path.join(artifacts,'ai-render-fixture.png')});

    // A slow alternate image cannot overwrite a later user choice or trigger repeated full downloads.
    const alternate=await page.evaluate(async id=>{
      const value=await fixture.makeAsset('#b9a26f'); fixture.jobs[id].result_ids.push(value.id); fixture.delayAsset=value.id; return value.id;
    },job1.id);
    await page.waitForFunction(()=>!document.getElementById('next-result').disabled);
    await page.locator('#next-result').click();
    await page.waitForFunction(id=>fixture.calls.some(v=>v.path==='/api/ai/assets/'+id),alternate);
    await page.locator('#previous-result').click();
    await page.waitForTimeout(1200);
    assert.equal(await page.locator('#result-image').getAttribute('src'),await page.evaluate(id=>fixture.assets[id].data_url,result1),'Late alternate result cannot replace the selected image');

    // Flow 2K uses the selected real result; completion wins a concurrent cancellation.
    await page.locator('#upscale').click();
    await page.waitForFunction(() => Object.keys(fixture.jobs).length===2 && !document.getElementById('cancel-job').disabled);
    const job2 = await page.evaluate(()=>Object.values(fixture.jobs)[1]);
    assert.equal(job2.operation,'upscale'); assert.equal(job2.source_id,result1); assert.equal(job2.prompt,''); assert.deepEqual(job2.reference_ids,[]);
    await page.evaluate(()=>fixture.cancelComplete=true); await page.locator('#cancel-job').click();
    await page.waitForFunction(()=>document.getElementById('job-state').textContent==='Hoàn thành');
    assert(!(await page.locator('#save-result').isDisabled()), 'Completion cannot be hidden as a cancelled result');
    assert.match(await page.locator('#notice').innerText(),/đã hoàn thành trước/);

    // Lost acknowledgement: accepted job cannot cause a fresh paid duplicate. Retry is identical.
    await page.evaluate(()=>fixture.failAck=true); await page.locator('#edit').click();
    await page.waitForFunction(()=>!document.getElementById('retry-submit').hidden && document.getElementById('busy-message').textContent==='Nguồn và kết quả trong cùng cửa sổ');
    assert(await page.locator('#render').isDisabled()); assert(await page.locator('#edit').isDisabled()); assert(await page.locator('#upscale').isDisabled());
    const beforeRetry = await page.evaluate(()=>fixture.calls.filter(v=>v.path==='/api/ai/jobs'&&v.method==='POST').at(-1).body);
    await page.locator('#retry-submit').click();
    await page.waitForFunction(()=>document.getElementById('retry-submit').hidden && !document.getElementById('cancel-job').disabled);
    const afterRetry = await page.evaluate(()=>fixture.calls.filter(v=>v.path==='/api/ai/jobs'&&v.method==='POST').at(-1).body);
    assert.deepEqual(afterRetry,beforeRetry); assert.equal(await page.evaluate(()=>Object.keys(fixture.jobs).length),3);
    const job3 = await page.evaluate(()=>Object.values(fixture.jobs)[2]);
    await page.evaluate(id=>Object.assign(fixture.jobs[id],{state:'waiting_user',progress:null,message:'Cần đăng nhập Google / hoàn tất trong Flow'}),job3.id);
    await page.waitForFunction(()=>!document.getElementById('manual-fallback').hidden);
    await page.locator('#manual-result-file').setInputFiles({name:'manual-flow.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>document.getElementById('job-state').textContent==='Hoàn thành' && document.getElementById('result-info').textContent.includes('thủ công'));
    assert.equal(await page.evaluate(()=>fixture.uploads.at(-1).role),'manual_result');

    // History loads metadata, not all image bytes, and explicit selection survives polling.
    const getsBefore = await page.evaluate(()=>fixture.calls.filter(v=>v.path.startsWith('/api/ai/assets/')&&!v.path.endsWith('/thumbnail')&&v.method==='GET').length);
    await page.locator('#history-open').click();
    await page.waitForFunction(()=>document.querySelectorAll('.history-card').length===3);
    assert.equal(await page.locator('.history-card').count(),3);
    const getsAfter = await page.evaluate(()=>fixture.calls.filter(v=>v.path.startsWith('/api/ai/assets/')&&!v.path.endsWith('/thumbnail')&&v.method==='GET').length);
    assert.equal(getsAfter,getsBefore,'Opening history does not fetch every full image');
    await page.locator(`.history-card[data-job-id="${job1.id}"]`).getByRole('button',{name:'Xem',exact:true}).click();
    await page.waitForFunction(id=>document.getElementById('result-image').src===fixture.assets[id].data_url,result1);
    await page.waitForTimeout(2800);
    assert.equal(await page.locator('#result-image').getAttribute('src'),await page.evaluate(id=>fixture.assets[id].data_url,result1));
    await page.locator('#restore-job').click();
    await page.waitForFunction(preset=>document.getElementById('preset').value===preset&&!document.getElementById('restore-job').disabled,job1.options.preset);
    assert.equal(await page.locator('#prompt-preview').inputValue(),job1.prompt, 'Reused prompt cannot duplicate the preset');
    await page.locator('#reuse-result').click();
    await page.waitForFunction(()=>document.getElementById('source-info').textContent.includes('Nguồn từ kết quả'));
    // Free one reference, then reuse a result as a reference without uploading or duplicating bytes.
    await page.locator('.reference-thumb button').first().click(); await page.locator('#reference-result').click();
    await page.waitForFunction(()=>document.getElementById('reference-count').textContent==='4 / 4');
    await page.locator('#edit').click();
    await page.waitForFunction(()=>Object.keys(fixture.jobs).length===4 && !document.getElementById('cancel-job').disabled);
    await page.evaluate(()=>fixture.failCancel=true); await page.locator('#cancel-job').click();
    await page.waitForFunction(()=>document.getElementById('notice').textContent==='Fixture cancel unavailable' && !document.getElementById('cancel-job').disabled);
    assert.notEqual(await page.locator('#job-state').innerText(),'Đã hủy','A failed cancel remains retryable');
    await page.locator('#cancel-job').click();
    await page.waitForFunction(()=>document.getElementById('job-state').textContent==='Đã hủy');
    assert(await page.locator('#save-result').isDisabled());
    assert(await page.locator('#manual-fallback').isHidden());

    // Source file, paste and drop all go through validated worker assets.
    await page.locator('#source-file').setInputFiles({name:'source-upload.png',mimeType:'image/png',buffer:png});
    await page.waitForFunction(()=>document.getElementById('source-info').textContent.includes('source-upload.png'));
    await page.evaluate(async () => {
      const data=Object.values(fixture.assets)[0].data_url;
      const file=new File([await (await fetch(data)).blob()],'pasted.png',{type:'image/png'}), transfer=new DataTransfer(); transfer.items.add(file);
      document.getElementById('source-stage').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
      document.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true}));
    });
    await page.waitForFunction(()=>document.getElementById('source-info').textContent.includes('pasted.png'));
    await page.evaluate(async () => {
      const data=Object.values(fixture.assets)[0].data_url, transfer=new DataTransfer();
      transfer.items.add(new File([await (await fetch(data)).blob()],'dropped.png',{type:'image/png'}));
      document.getElementById('source-stage').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));
    });
    await page.waitForFunction(()=>document.getElementById('source-info').textContent.includes('dropped.png'));
    assert.equal(await page.evaluate(()=>fixture.uploads.at(-1).role),'source');
    await page.locator('#settings-open').click(); await page.locator('#camera-watch').check(); await page.keyboard.press('Escape');
    const captureCount=await page.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length);
    await page.evaluate(()=>{SiteCraftAI.cameraChanged();SiteCraftAI.cameraChanged();SiteCraftAI.cameraChanged();});
    await page.waitForFunction(n=>fixture.native.filter(v=>v.action==='capture').length===n+1,captureCount);
    await page.waitForFunction(()=>document.getElementById('source-info').textContent.includes('Góc nhìn SketchUp')&&!document.getElementById('capture').disabled);
    const updatedCanvas=await page.locator('#annotation-canvas').boundingBox();
    for (const tool of ['ellipse','pen']) {
      await page.locator(`[data-tool="${tool}"]`).click();
      await page.mouse.move(updatedCanvas.x+updatedCanvas.width*.25,updatedCanvas.y+updatedCanvas.height*.3); await page.mouse.down();
      await page.mouse.move(updatedCanvas.x+updatedCanvas.width*.7,updatedCanvas.y+updatedCanvas.height*.65,{steps:5}); await page.mouse.up();
    }
    assert.equal(await page.locator('#region-list textarea').count(),2);
    await page.evaluate(()=>SiteCraftAI.cameraChanged()); await page.waitForTimeout(800);
    assert.equal(await page.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length),captureCount+1,'Camera watch preserves marked source');
    await page.evaluate(()=>fixture.failCapture=true); await page.locator('#capture').click();
    await page.waitForFunction(()=>document.getElementById('notice').textContent==='Fixture capture failed'&&!document.getElementById('capture').disabled);
    assert.equal(await page.locator('#region-list textarea').count(),2,'Capture failure preserves source and notes');

    await page.setViewportSize({width:1040,height:860});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.evaluate(()=>document.getElementById('notice').hidden=true);
    await page.screenshot({path:path.join(artifacts,'ai-render-1040-fixture.png')});
    await page.setViewportSize({width:650,height:850});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Narrow panel does not overflow horizontally');
    await page.screenshot({path:path.join(artifacts,'ai-render-650-fixture.png')});
    assert.deepEqual(errors,[]);
    const standalone = await browser.newPage({viewport:{width:1040,height:860}});
    await standalone.goto(file); assert(await standalone.locator('#render').isDisabled());
    assert(await standalone.locator('#capture').isDisabled());
    assert.match(await standalone.locator('#bridge-help-text').innerText(),/Mở Render AI.*SketchUp/);
    await standalone.close();
    const parity=await browser.newPage({viewport:{width:1440,height:1000}});
    parity.on('pageerror',error=>errors.push(error.message)); parity.on('dialog',dialog=>dialog.accept());
    await fixture(parity); await parity.goto(file);
    await parity.waitForFunction(()=>document.getElementById('source-info').textContent.includes('800 × 600')&&!document.getElementById('capture').disabled);
    assert.equal(await parity.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length),1,'Initial SU capture occurs once when ready');
    const firstCapture=await parity.evaluate(()=>fixture.native.find(v=>v.action==='capture').args);
    assert.equal(firstCapture.size_mode,'long_edge'); assert.equal(firstCapture.hide_helpers,true);
    await parity.locator('#aspect').selectOption('custom');
    await parity.locator('#aspect-width').fill('1920'); await parity.locator('#aspect-height').fill('1080');
    assert.match(await parity.locator('#source-info').innerText(),/800 × 450/);
    await parity.locator('#crop-zoom').fill('2'); await parity.locator('#crop-zoom').dispatchEvent('input');
    assert.match(await parity.locator('#source-info').innerText(),/400 × 225/);
    const panBox=await parity.locator('#annotation-canvas').boundingBox(), xBefore=await parity.locator('#crop-x').inputValue();
    await parity.mouse.move(panBox.x+panBox.width*.5,panBox.y+panBox.height*.5); await parity.mouse.down();
    await parity.mouse.move(panBox.x+panBox.width*.7,panBox.y+panBox.height*.5); await parity.mouse.up();
    assert.notEqual(await parity.locator('#crop-x').inputValue(),xBefore,'Dragging changes the crop position');
    await parity.locator('#viewport-frame').check();
    await parity.waitForFunction(()=>fixture.native.some(v=>v.action==='frame_overlay'&&v.args.enabled));
    const frame=await parity.evaluate(()=>fixture.native.filter(v=>v.action==='frame_overlay'&&v.args.enabled).at(-1).args);
    assert.equal(frame.aspect,'1920:1080'); assert(frame.crop.width>0&&frame.crop.width<1);
    await parity.locator('#viewport-frame').uncheck();
    await parity.locator('#crop-reset').click();
    await parity.locator('#aspect').selectOption('2:3'); assert.match(await parity.locator('#source-info').innerText(),/400 × 600/);
    await parity.locator('#aspect').selectOption('5:4'); assert.match(await parity.locator('#source-info').innerText(),/750 × 600/);
    await parity.locator('#aspect').selectOption('8:1'); assert.match(await parity.locator('#source-info').innerText(),/800 × 100/);
    await parity.locator('#crop-reset').click();
    async function draw(tool,from,to) {
      await parity.locator(`[data-tool="${tool}"]`).click(); const box=await parity.locator('#annotation-canvas').boundingBox();
      await parity.mouse.move(box.x+box.width*from[0],box.y+box.height*from[1]); await parity.mouse.down();
      await parity.mouse.move(box.x+box.width*to[0],box.y+box.height*to[1],{steps:8}); await parity.mouse.up();
    }
    await draw('rectangle',[.2,.2],[.8,.8]);
    await parity.locator('.region-quick').selectOption('3');
    assert.equal(await parity.locator('#region-list textarea').inputValue(),await parity.evaluate(()=>SiteCraftAIReferencePrompts.getOptions('regionQuickActions').find(value=>value.id==='3').prompt));
    await parity.locator('#region-list textarea').fill('Tường gạch theo ảnh kèm.');
    await parity.locator('#annotation-size').fill('60'); await draw('eraser',[.2,.4],[.2,.6]);
    assert.equal(await parity.locator('#region-list textarea').count(),1,'Eraser is an ink operation, not a new edit region');
    await parity.locator('.region-reference input[type=file]').setInputFiles({name:'region-material.png',mimeType:'image/png',buffer:png});
    await parity.waitForFunction(()=>document.getElementById('reference-count').textContent==='1 / 4'&&!document.getElementById('manual-handoff').disabled);
    assert.match(await parity.locator('#prompt-preview').inputValue(),/Ảnh tham chiếu 1.*áp dụng cho vùng này/);
    await parity.locator('.preset-details summary').click();
    await parity.locator('#photo-style').selectOption('film'); await parity.locator('#context').selectOption('garden');
    await parity.locator('#lighting').selectOption('golden'); await parity.locator('[data-extra="plants"]').check();
    await parity.evaluate(()=>fixture.failAck=true); await parity.locator('#manual-handoff').click();
    await parity.waitForFunction(()=>!document.getElementById('retry-submit').hidden&&!document.getElementById('retry-submit').disabled);
    assert.equal(await parity.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length),2,'Rendering a SU source recaptures the current camera');
    await parity.locator('#retry-submit').click();
    await parity.waitForFunction(()=>document.getElementById('job-state').textContent==='Cần bạn thao tác'&&document.getElementById('retry-submit').hidden);
    const manual=await parity.evaluate(()=>Object.values(fixture.jobs)[0]);
    assert.equal(manual.options.manual_handoff,true); assert.equal(manual.options.prompt_is_complete,true);
    assert.equal(manual.prompt,await parity.locator('#prompt-preview').inputValue());
    for (const [group,id] of [['style','film'],['context','garden'],['extras','plants']]) {
      const literal=await parity.evaluate(({group,id})=>SiteCraftAIReferencePrompts.getOptions(group).find(value=>value.id===id).prompt,{group,id});
      assert(manual.prompt.includes(literal),'Selected recovered preset text stays exact');
    }
    assert.match(manual.annotation_notes,/Tường gạch/); assert.notEqual(manual.comparison_source_id,manual.source_id);
    const pixels=await parity.evaluate(async job=>{
      async function points(id) { const image=new Image(); image.src=fixture.assets[id].data_url;await image.decode();const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const c=canvas.getContext('2d');c.drawImage(image,0,0);return [Array.from(c.getImageData(160,300,1,1).data),Array.from(c.getImageData(640,300,1,1).data)]; }
      return {marked:await points(job.source_id),clean:await points(job.comparison_source_id)};
    },manual);
    assert(pixels.marked[0][0]<200,'Partial eraser reveals original source pixels');
    assert(pixels.marked[1][0]>200&&pixels.marked[1][1]<150,'Other parts of the ink remain');
    assert(pixels.clean[1][0]<200,'Clean comparison does not contain the colored rectangle');
    await parity.locator('#manual-save-source').click(); await parity.waitForFunction(id=>fixture.saves.includes(id),manual.source_id);
    await parity.locator('#manual-watch').click();
    await parity.waitForFunction(()=>fixture.native.some(v=>v.action==='watch_downloads'));
    const candidate=await parity.evaluate(()=>fixture.makeAsset('#b2a285'));
    await parity.evaluate(({candidate,id})=>SiteCraftAI.downloadCandidate(candidate,id),{candidate,id:'f'.repeat(32)});
    assert(await parity.locator('#download-candidate').isHidden(),'A stale job download is ignored');
    await parity.evaluate(({candidate,id})=>SiteCraftAI.downloadCandidate(candidate,id),{candidate,id:manual.id});
    await parity.waitForFunction(()=>!document.getElementById('download-candidate').hidden);
    assert.equal(await parity.evaluate(id=>fixture.jobs[id].state,manual.id),'waiting_user','Download is never attached without explicit acceptance');
    await parity.screenshot({path:path.join(artifacts,'ai-manual-parity-fixture.png')});
    await parity.locator('#download-accept').click(); await parity.waitForFunction(()=>document.getElementById('job-state').textContent==='Hoàn thành');
    await parity.locator('#compare-file').setInputFiles({name:'comparison.png',mimeType:'image/png',buffer:png});
    await parity.waitForFunction(()=>document.getElementById('compare-source-label').textContent==='comparison.png');
    assert.equal(await parity.locator('.reference-thumb').count(),1,'Comparison file is not silently a Flow reference');
    await parity.locator('#compare-reset').click(); assert.equal(await parity.locator('#compare-source-label').innerText(),'Nguồn sạch');
    await parity.locator('#open-result').click(); await parity.locator('#cleanup-open').click();
    assert((await parity.evaluate(()=>fixture.native)).some(v=>v.action==='open_image'&&v.args.asset_id===candidate.id));
    assert((await parity.evaluate(()=>fixture.native)).some(v=>v.action==='open_cleanup'));
    await parity.locator('#history-open').click();
    await parity.waitForFunction(()=>document.querySelector('.history-thumbnail')?.naturalWidth>0);
    assert(await parity.locator('.history-thumbnail').evaluate(image=>image.naturalWidth<=192));
    await parity.locator('#history-size').fill('320'); await parity.locator('#history-fit').selectOption('cover');
    await parity.waitForFunction(()=>document.querySelector('.history-thumbnail')?.naturalWidth>0);
    assert.equal(await parity.locator('#history-list').evaluate(el=>el.style.getPropertyValue('--thumb-size')),'320px');
    assert.equal(await parity.locator('.history-thumbnail').evaluate(el=>getComputedStyle(el).objectFit),'cover');
    await parity.evaluate(()=>document.getElementById('notice').hidden=true);
    await parity.screenshot({path:path.join(artifacts,'ai-history-parity-fixture.png')});
    await parity.keyboard.press('Escape');
    await parity.locator('#restore-job').click();
    await parity.waitForFunction(()=>!document.getElementById('restored-notes').hidden);
    assert.match(await parity.locator('#restored-notes-text').inputValue(),/Tường gạch/);
    assert.equal(await parity.locator('#prompt-preview').inputValue(),manual.prompt,'Restored complete prompt stays identical');

    const large=await parity.evaluate(()=>fixture.makeAsset('#a8bbb1',2400,1200));
    await parity.locator('#source-file').setInputFiles({name:'large-source.png',mimeType:'image/png',buffer:Buffer.from(large.data_url.split(',')[1],'base64')});
    await parity.waitForFunction(()=>document.getElementById('source-info').textContent.includes('large-source.png'));
    await parity.locator('#settings-open').click(); await parity.locator('#upload-max').selectOption('1024');
    await parity.locator('#upload-format').selectOption('jpeg'); await parity.locator('#jpeg-quality').fill('80'); await parity.keyboard.press('Escape');
    await parity.evaluate(()=>fixture.bridge={port:17865,paired:true,connected:true});
    await parity.waitForFunction(()=>!document.getElementById('render').disabled);
    const captureBeforeFileRender=await parity.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length);
    await parity.locator('#render').click(); await parity.waitForFunction(()=>Object.keys(fixture.jobs).length===2&&!document.getElementById('cancel-job').disabled);
    const resized=await parity.evaluate(()=>Object.values(fixture.jobs)[1]);
    assert(!resized.prompt.includes('Tường gạch theo ảnh kèm.'),'Changing the source cannot retain old region notes inside the editable prompt');
    const prepared=await parity.evaluate(job=>({source:fixture.assets[job.source_id],clean:fixture.assets[job.comparison_source_id],reference:fixture.assets[job.reference_ids[0]]}),resized);
    assert.equal(prepared.source.mime,'image/jpeg');assert.equal(prepared.source.width,1024);assert.equal(prepared.source.height,512);
    assert.equal(prepared.clean.mime,'image/png');assert.equal(prepared.clean.width,1024);assert.equal(prepared.reference.mime,'image/jpeg');
    assert.equal(await parity.evaluate(()=>fixture.native.filter(v=>v.action==='capture').length),captureBeforeFileRender,'Uploaded images are not silently replaced by a SU capture');
    await parity.locator('#render').click(); await parity.waitForFunction(()=>!document.getElementById('active-job-dialog').hidden); await parity.locator('#dismiss-job-choice').click();
    await parity.waitForFunction(()=>!document.getElementById('render').disabled); assert.equal(await parity.evaluate(()=>Object.keys(fixture.jobs).length),2);
    await parity.locator('#render').click(); await parity.locator('#queue-new').click();
    await parity.waitForFunction(()=>Object.keys(fixture.jobs).length===3&&!document.getElementById('render').disabled);
    assert.equal(await parity.evaluate(id=>fixture.jobs[id].state,resized.id),'queued','Explicit queue keeps the earlier job');
    await parity.locator('#render').click(); await parity.locator('#replace-active').click();
    await parity.waitForFunction(()=>Object.keys(fixture.jobs).length===4&&!document.getElementById('render').disabled);
    assert.equal(await parity.evaluate(()=>Object.values(fixture.jobs).filter(job=>job.state==='queued').length),1,'Replace cancels pending jobs before creating the next');
    await parity.locator('#cancel-job').click(); await parity.waitForFunction(()=>document.getElementById('job-state').textContent==='Đã hủy');
    await parity.locator('#return-capture').click(); await parity.waitForFunction(()=>document.getElementById('source-info').textContent.includes('Ảnh SketchUp đã chụp'));
    await draw('pen',[.3,.3],[.6,.6]); await parity.locator('#region-list textarea').fill('Không được đặt nét này vào camera khác.');
    await parity.evaluate(()=>fixture.cameraStamp='camera-b'); await parity.locator('#render').click();
    await parity.waitForFunction(()=>Object.keys(fixture.jobs).length===5&&!document.getElementById('render').disabled);
    assert.equal(await parity.locator('#region-list textarea').count(),0,'Changed camera clears old marks only after explicit confirmation');
    assert.equal(await parity.evaluate(()=>Object.values(fixture.jobs)[4].annotation_notes),'');
    await parity.screenshot({path:path.join(artifacts,'ai-parity-fixture.png')});
    await parity.locator('#prompt').fill('Mô tả riêng cần giữ sau khi mở lại.');
    await parity.reload(); await parity.waitForFunction(()=>!document.getElementById('capture').disabled);
    assert.equal(await parity.locator('#prompt').inputValue(),'Mô tả riêng cần giữ sau khi mở lại.','Recovered sample never overwrites a saved custom prompt');
    await parity.locator('#prompt-template').selectOption('edit');
    assert.equal(await parity.locator('#prompt').inputValue(),await parity.evaluate(()=>SiteCraftAIReferencePrompts.basePreviewFixture.edit));
    await parity.close();
    assert.deepEqual(errors,[]);
    console.log('PASS SiteCraft AI UI + reference workflow parity (custom/pan/zoom/frame, partial eraser/region refs, presets, clean comparison, unpaired manual/watch confirmation, lazy thumbnails, SU recapture/camera guard, real upload settings, active-job choice): pairing, real assets/crop/annotations, queue/progress, native save, Flow 2K, completion/cancel race, idempotent lost-ack retry, manual fallback, bounded metadata history, persistent selection, reuse, standalone state. Protocol mocks only; no cloud generation.');
  } catch (error) {
    await page.screenshot({path:path.join(artifacts,'ai-ui-failure.png'),fullPage:true});
    console.error('Fixture state:',await page.evaluate(()=>({job:document.getElementById('job-state').textContent,notice:document.getElementById('notice').textContent,calls:window.fixture?.calls.slice(-8),busy:document.getElementById('busy-message').textContent})));
    throw error;
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
