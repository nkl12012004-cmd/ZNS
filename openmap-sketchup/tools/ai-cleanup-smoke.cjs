/* Independent local cleanup fixtures. No user image or cloud requests. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const PNG='iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPUCKhgYGBgYmBgYGBgAAALGgD0KRPd0QAAAABJRU5ErkJggg==';
async function nativeTests(){
 const {RubyVM}=require('@ruby/wasm-wasi'),{WASI}=require('node:wasi'),os=require('node:os');const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'sitecraft-cleanup-fixture-'));const module=await WebAssembly.compile(fs.readFileSync(require.resolve('@ruby/3.3-wasm-wasi/dist/ruby+stdlib.wasm')));const wasi=new WASI({version:'preview1',returnOnExit:true,env:{TMPDIR:'/tmp'},preopens:{'/tmp':temporary}});const{vm}=await RubyVM.instantiateModule({module,wasip1:wasi});
 vm.eval(`require 'json';require 'base64';require 'tmpdir';module Sketchup;class ViewObserver;end;class AppObserver;end;end
 module UI
  class << self;attr_accessor :directory,:save_path;end
  def self.select_directory(**);@directory;end
  def self.savepanel(*);@save_path;end
 end
 module OpenMapSketchUp
  VERSION='test'
  module Runtime;def self.status;{'state'=>'ready'};end;end
  module Core
   class << self;attr_accessor :asset,:calls;end;self.calls=[]
   def self.managed?;true;end
   def self.error_response(*);nil;end
   def self.http(method,path,body);self.calls << [method,path];yield Struct.new(:body,:status_code).new(JSON.generate(asset),200),nil;end
  end
 end`);
 vm.eval(fs.readFileSync(path.join(root,'extension/openmap_sketchup/ai_render.rb'),'utf8'));
 vm.eval(fs.readFileSync(path.join(root,'extension/openmap_sketchup/ai_image_tools.rb'),'utf8'));
 vm.eval(`
 module OpenMapSketchUp::AIImageTools
  @test_replies={}
  def self.reply(id,value,generation);@test_replies[id]=value;end
  def self.current?(_);true;end
  def self.answers;@test_replies;end
 end
 $cleanup_checks=0
 def check(value,message);raise message unless value;$cleanup_checks+=1;end
 tools=OpenMapSketchUp::AIImageTools
 core=OpenMapSketchUp::Core
 core.asset={'id'=>'a'*32,'name'=>'source.png','width'=>2,'height'=>2,'mime'=>'image/png','data_url'=>'data:image/png;base64,${PNG}'}
 folder=Dir.mktmpdir('cleanup-test-')
 begin
  original=File.join(folder,'source_cleaned.png');File.binwrite(original,'ORIGINAL')
  UI.directory=folder
  tools.invoke('batch','save_batch',{'items'=>[{'asset_id'=>'a'*32,'name'=>'../../source.png'},{'asset_id'=>'a'*32,'name'=>'CON.jpg'}]},1)
  answer=tools.answers['batch'];check(answer['ok'] && answer['data']['saved']==2,'Batch failed')
  check(File.binread(original)=='ORIGINAL','Existing original overwritten')
  check(File.file?(File.join(folder,'source_cleaned_2.png')),'Unique name was not allocated')
  check(File.file?(File.join(folder,'SiteCraft_Image_cleaned.png')),'Reserved filename was not sanitized')
  check(!File.exist?(File.join(File.dirname(folder),'source_cleaned.png')),'Path escaped selected directory')
  check(File.binread(File.join(folder,'source_cleaned_2.png'))==Base64.strict_decode64('${PNG}'),'Saved bytes changed')
  UI.save_path=original
  tools.invoke('existing','save_image',{'asset_id'=>'a'*32,'name'=>'source'},1)
  check(!tools.answers['existing']['ok'],'Save allowed overwriting existing original')
  check(File.binread(original)=='ORIGINAL','Rejected save changed original')
  before=Dir.children(folder).sort;UI.directory=nil
  tools.invoke('cancel','save_batch',{'items'=>[{'asset_id'=>'a'*32}]},1)
  check(tools.answers['cancel']['data']['cancelled'],'Cancel was reported as success')
  check(Dir.children(folder).sort==before,'Cancelled save wrote files')
  calls=core.calls.length
  tools.invoke('path','api',{'method'=>'GET','path'=>'https://evil.invalid/file'},1)
  check(!tools.answers['path']['ok'] && core.calls.length==calls,'Arbitrary URL was accepted')
  tools.invoke('too-many','save_batch',{'items'=>Array.new(13){{'asset_id'=>'a'*32}}},1)
  check(!tools.answers['too-many']['ok'],'Batch size bound ignored')
  begin;tools.write_new(original,'BAD');rescue Errno::EEXIST;end
  check(File.binread(original)=='ORIGINAL','Exclusive writer clobbered existing bytes')
 ensure
  FileUtils.remove_entry(folder)
 end
 `);
 console.log('PASS cleanup native batch: '+vm.eval('$cleanup_checks').toString()+' Ruby VM checks; existing originals retained.');fs.rmSync(temporary,{recursive:true,force:true});
}
async function uiTests(){
 const{chromium}=require('playwright');const{pathToFileURL}=require('node:url');const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{const page=await browser.newPage({viewport:{width:1120,height:800}});await page.route(/^https?:\/\//,route=>route.abort());
 await page.addInitScript(()=>{let count=0;const data={assets:{},cleanups:[],saves:[]};window.cleanupFixture=data;
  const id=()=> (++count).toString(16).padStart(32,'0');
  window.sketchup={sitecraft_cleanup(raw){const m=JSON.parse(raw),a=m.args;let result;
   try{if(m.action==='config')result={managed:true,version:'fixture'};
    else if(m.action==='api'){const p=a.path.slice('/api/ai/'.length);
     if(a.method==='POST'&&p==='assets'){const identifier=id();data.assets[identifier]={id:identifier,data_url:a.body.data_url,name:a.body.name,width:160,height:120,mime:'image/png'};result=data.assets[identifier];}
     else if(a.method==='GET'&&p.startsWith('assets/'))result=data.assets[p.slice(7)];
     else if(a.method==='POST'&&p==='cleanup'){const source=data.assets[a.body.asset_id];if(!source)throw Error('Missing source');data.cleanups.push(structuredClone(a.body));if(a.body.mode==='gemini'&&source.name!=='second.png')result={...source,source_id:source.id,cleanup:{applied:false,original_preserved:true,confidence_kind:'heuristic_not_probability'}};else{const identifier=id();result={...source,id:identifier,source_id:source.id,cleanup:{applied:true,original_preserved:true,confidence_kind:'heuristic_not_probability'}};data.assets[identifier]=result;}}
     else throw Error('Unexpected API');
    }else if(m.action==='save_image'){data.saves.push(a);result={saved:true};}
    else if(m.action==='save_batch'){data.saves.push(a);result={saved:a.items.length,total:a.items.length,errors:[]};}
    else result={assets:[]};setTimeout(()=>window.SiteCraftCleanup.receive(m.id,{ok:true,data:result}),1);
   }catch(e){setTimeout(()=>window.SiteCraftCleanup.receive(m.id,{ok:false,error:e.message}),1);}
  }};});
 await page.goto(pathToFileURL(path.join(root,'extension/openmap_sketchup/ui/ai-cleanup.html')).href);
 const source=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=120;const c=canvas.getContext('2d');c.fillStyle='#648fac';c.fillRect(0,0,160,120);c.fillStyle='white';c.fillText('LOGO',138,112);return canvas.toDataURL().split(',')[1];});
 const fixture={name:'fixture.png',mimeType:'image/png',buffer:Buffer.from(source,'base64')};
 await page.locator('#files').setInputFiles([fixture,{...fixture,name:'second.png'}]);
 await page.waitForFunction(()=>document.querySelectorAll('.image-item').length===2&&!document.getElementById('apply').disabled);
 assert.match(await page.locator('body').innerText(),/không khôi phục chi tiết gốc/);
 await page.locator('.image-item').nth(1).click();await page.waitForFunction(()=>document.getElementById('image-title').textContent==='second.png'&&!document.getElementById('apply').disabled);
 await page.locator('.image-item').first().click();await page.waitForFunction(()=>document.getElementById('image-title').textContent==='fixture.png'&&!document.getElementById('apply').disabled);
 await page.locator('#apply').click();await page.waitForFunction(()=>cleanupFixture.cleanups.length===1&&!document.getElementById('save').disabled);
 const first=await page.evaluate(()=>cleanupFixture.cleanups[0]);assert(first.regions[0].width*first.regions[0].height<=.1);
 await page.locator('#same-regions').check();await page.locator('#apply-all').click();await page.waitForFunction(()=>cleanupFixture.cleanups.length===3&&!document.getElementById('save-all').disabled);
 const calls=await page.evaluate(()=>cleanupFixture.cleanups);assert.deepEqual(calls[1].regions,calls[2].regions);
 await page.locator('#save-all').click();await page.waitForFunction(()=>cleanupFixture.saves.length===1);
 assert.equal((await page.evaluate(()=>cleanupFixture.saves[0].items)).length,2);
 assert.equal(await page.evaluate(()=>document.querySelector('#canvas').width<=document.querySelector('#stage').clientWidth),true);
 await page.locator('#gemini').click();await page.waitForFunction(()=>cleanupFixture.cleanups.length===4&&!document.getElementById('gemini').disabled);
 assert.equal(await page.locator('#save').isDisabled(),true);assert.equal(await page.locator('#compare-label').isHidden(),true);
 assert.match(await page.locator('#notice').innerText(),/Không tìm thấy.*chưa tạo bản kết quả/);
 const attempt=await page.evaluate(()=>cleanupFixture.cleanups[3]);assert.equal(attempt.mode,'gemini');assert.equal('regions' in attempt,false);
 await page.locator('#gemini-all').click();await page.waitForFunction(()=>cleanupFixture.cleanups.length===6&&!document.getElementById('gemini-all').disabled);
 assert.match(await page.locator('#notice').innerText(),/2 ảnh: 1 bản xử lý Gemini, 1 ảnh không khớp giữ nguyên/);
 assert.equal(await page.locator('.image-item.done').count(),1);assert.equal(await page.locator('#save').isDisabled(),true);
 await page.locator('#save-all').click();await page.waitForFunction(()=>cleanupFixture.saves.length===2);
 assert.equal((await page.evaluate(()=>cleanupFixture.saves[1].items)).length,1);
 await page.locator('.image-item').nth(1).click();await page.waitForFunction(()=>document.getElementById('image-title').textContent==='second.png'&&!document.getElementById('save').disabled);
 assert.equal(await page.locator('#compare-label').isVisible(),true);
 assert.match(await page.locator('body').innerText(),/ước lượng, có thể nhầm hoặc bỏ sót/);
 const region=await page.locator('#canvas').boundingBox();await page.mouse.move(region.x+5,region.y+5);await page.mouse.down();await page.mouse.move(region.x+region.width-5,region.y+region.height-5);await page.mouse.up();assert.match(await page.locator('#notice').innerText(),/Vùng quá lớn/);
 console.log('PASS cleanup UI: manual masks/batch/save; explicit Gemini single/batch, no-match retains original, only detected outputs saved; comparison and heuristic warning. No cloud.');
 }finally{await browser.close();}
}
(async()=>{await nativeTests();await uiTests();})().catch(error=>{console.error(error);process.exitCode=1;});
