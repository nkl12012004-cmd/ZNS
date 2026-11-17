/* SPDX-License-Identifier: MIT
 * Real Ruby VM checks with an explicit SketchUp host double. This does not
 * claim a live SketchUp capture or Google Flow render has been exercised.
 */
const fs = require('node:fs');
const path = require('node:path');
const { DefaultRubyVM } = require('@ruby/wasm-wasi/dist/node');

(async () => {
  const root = path.resolve(__dirname, '..');
  const wasm = require.resolve('@ruby/3.3-wasm-wasi/dist/ruby+stdlib.wasm');
  const module = await WebAssembly.compile(fs.readFileSync(wasm));
  const { vm } = await DefaultRubyVM(module);
  vm.eval(`
    require 'json'
    require 'base64'
    module Sketchup
      class ViewObserver; end
      class AppObserver; end
      class Color
        attr_reader :channels
        def initialize(*channels); @channels = channels; end
      end
      class Overlay
        attr_reader :overlay_id, :name
        attr_accessor :registered
        def initialize(id, name, description: '')
          @overlay_id, @name, @registered, @enabled = id, name, false, false
        end
        def enabled=(value)
          raise 'Unregistered overlay enabled' unless @registered
          @enabled = value
        end
        def enabled?; @enabled; end
        def valid?; @registered; end
      end
      @observers = []
      class << self
        attr_accessor :active_model
        attr_reader :observers
        def add_observer(observer); @observers << observer; end
        def remove_observer(observer); @observers.delete(observer); end
      end
    end
    module UI
      @sequence, @timers, @urls = 0, {}, []
      class << self
        attr_reader :timers, :urls
        attr_accessor :save_path
        def start_timer(interval, repeat, &block)
          raise 'Timer scheduled off main thread' unless Thread.current == Thread.main
          @sequence += 1
          @timers[@sequence] = [repeat, block]
          @sequence
        end
        def stop_timer(id); @timers.delete(id); end
        def pump
          @timers.dup.each do |id, value|
            next unless @timers[id]
            @timers.delete(id) unless value[0]
            value[1].call
          end
        end
        def openURL(url); @urls << url; true; end
        def messagebox(message); raise message; end
        def savepanel(*_args); @save_path; end
      end
      class HtmlDialog
        STYLE_DIALOG = 0
        attr_reader :scripts, :callbacks, :options, :file
        def initialize(options)
          @options, @scripts, @callbacks, @visible = options, [], {}, false
        end
        def set_file(path); @file = path; end
        def add_action_callback(name, &block); @callbacks[name] = block; end
        def set_on_closed(&block); @closed = block; end
        def show; @visible = true; end
        def visible?; @visible; end
        def bring_to_front; end
        def execute_script(script)
          raise 'HtmlDialog called off main thread' unless Thread.current == Thread.main
          @scripts << script
        end
        def close
          @visible = false
          @closed.call if @closed
        end
      end
    end
    GL_QUADS, GL_LINE_LOOP, GL_LINES = 7, 2, 1
    module OpenMapSketchUp
      VERSION = '0.5.0-beta1'
      module Runtime
        class << self
          attr_accessor :test_state
          def status; @test_state || {'state'=>'ready'}; end
          def state_root; '/sitecraft-private-state'; end
        end
      end
      module Core
        @managed, @calls, @pending = true, [], []
        Response = Struct.new(:status_code, :body)
        class << self
          attr_accessor :managed, :defer, :failure_status, :asset_reply, :job_reply
          attr_reader :calls, :pending
          def managed?; @managed; end
          def start_runtime; end
          def error_response(response, failure)
            return failure if failure
            response.status_code == 200 ? nil : JSON.parse(response.body)['error']
          end
          def http(method, path, body, &callback)
            raise 'HTTP invoked off main thread' unless Thread.current == Thread.main
            @calls << [method, path, body]
            result = path == '/api/ai/assets' ? {'id'=>'a'*32,'width'=>body['data_url'].split(',')[1].then{|e|Base64.strict_decode64(e).byteslice(16,4).unpack1('N')},'height'=>body['data_url'].split(',')[1].then{|e|Base64.strict_decode64(e).byteslice(20,4).unpack1('N')},'mime'=>'image/png'} : {'protocol'=>1}
            result = @asset_reply if method == 'GET' && path.start_with?('/api/ai/assets/') && @asset_reply
            result = @job_reply if method == 'GET' && path.start_with?('/api/ai/jobs/') && @job_reply
            result = {'error'=>'Bounded server error'} if @failure_status
            response = Response.new(@failure_status || 200, JSON.generate(result))
            @defer ? @pending << [callback, response] : callback.call(response, nil)
          end
          def finish
            callback, response = @pending.shift
            callback.call(response, nil)
          end
        end
      end
    end
  `);
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/importer.rb'), 'utf8'));
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/ai_render.rb'), 'utf8'));
  vm.eval(`
    $assertions = 0
    def check(condition, message)
      raise message unless condition
      $assertions += 1
    end
    def rejects(message)
      begin; yield; rescue StandardError; $assertions += 1; return; end
      raise message
    end
    def png(width, height)
      "\\x89PNG\\r\\n\\x1a\\n".b + [13].pack('N') + 'IHDR' + [width, height].pack('NN') + "\\x08\\x06\\x00\\x00\\x00".b + "\\x00".b * 4
    end
    def envelope(bytes, mime='image/png', width=1280, height=720)
      {'data_url'=>'data:' + mime + ';base64,' + Base64.strict_encode64(bytes), 'mime'=>mime, 'width'=>width, 'height'=>height}
    end
    class TestView
      attr_reader :observers, :image_options, :draw_calls, :overlay_visible_when_writing, :helpers_when_writing
      attr_accessor :fail_write, :raise_write, :drawing_color, :line_stipple, :line_width, :camera, :viewport_width, :viewport_height, :rendering_options
      def initialize
        @observers, @draw_calls = [], []
        @camera = Struct.new(:eye, :target, :up, :fov, :aspect_ratio, :projection) do
          def perspective?; projection; end
          def fov_is_height?; true; end
          def height; raise 'Height queried on perspective camera' if projection; 100.0; end
        end.new([1.0,2.0,3.0], [0.0,0.0,0.0], [0.0,0.0,1.0], 35.0, 0.0, true)
      end
      def vpwidth; @viewport_width || 1600; end
      def vpheight; @viewport_height || 900; end
      def add_observer(observer); @observers << observer; end
      def remove_observer(observer); @observers.delete(observer); end
      def invalidate; @invalidated = true; end
      def draw2d(kind, points); @draw_calls << [kind, points, @drawing_color, @line_width]; end
      def write_image(options)
        @image_options = options
        @helpers_when_writing = @rendering_options.dup if @rendering_options
        raise 'Native image write failed' if @raise_write
        return false if @fail_write
        overlay = OpenMapSketchUp::AIRender.instance_variable_get(:@frame_overlay)
        @overlay_visible_when_writing = OpenMapSketchUp::AIRender.overlay_drawable?(overlay,self)
        $capture_bytes = png(options[:width], options[:height])
        true
      end
    end
    class TestModel
      attr_reader :active_view, :overlays, :rendering_options
      def initialize
        @active_view, @overlays = TestView.new, TestOverlays.new
        @rendering_options={'HideConstructionGeometry'=>false,'DisplaySketchAxes'=>true,'DisplayInstanceAxes'=>true,'DisplaySectionPlanes'=>true,'DisplaySectionCuts'=>true,'Texture'=>true}
        @active_view.rendering_options = @rendering_options
      end
      def select_tool(*_args); raise 'Overlay stole active tool'; end
    end
    class TestOverlays
      attr_reader :items
      def initialize; @items = []; end
      def add(overlay)
        raise 'Overlays API called off main thread' unless Thread.current == Thread.main
        return false if @items.any?{|item|item.overlay_id == overlay.overlay_id}
        @items << overlay; overlay.registered = true; true
      end
      def remove(overlay)
        raise 'Overlays API called off main thread' unless Thread.current == Thread.main
        removed = @items.delete(overlay)
        overlay.registered = false if removed
        !!removed
      end
    end
    # The WASI host has no writable temp mount. This double replaces only
    # native capture file IO; Tempfile's production cleanup remains unchanged.
    class << File
      alias_method :ai_original_file?, :file?
      alias_method :ai_original_size, :size
      alias_method :ai_original_binread, :binread
      def file?(path); path == '/native-capture.png' || ai_original_file?(path); end
      def size(path); path == '/native-capture.png' ? $capture_bytes.bytesize : ai_original_size(path); end
      def binread(path); path == '/native-capture.png' ? $capture_bytes : ai_original_binread(path); end
    end
    class << Tempfile
      alias_method :ai_original_create, :create
      def create(*_args)
        temporary = Struct.new(:path) { def close; end }.new('/native-capture.png')
        yield temporary
      end
    end
    ai, core = OpenMapSketchUp::AIRender, OpenMapSketchUp::Core
    model = TestModel.new
    Sketchup.active_model = model
    ai.show
    dialog = ai.instance_variable_get(:@dialog)
    generation = ai.instance_variable_get(:@generation)
    check(dialog.file.end_with?('/ui/ai.html'), 'AI dialog loaded map HTML')
    check(dialog.callbacks.keys == ['sitecraft_ai'], 'Unexpected native callback exposed')
    ai.invoke('config', 'config', {})
    check(dialog.scripts.last.include?('"managed":true'), 'Config omitted local mode')
    check(dialog.scripts.last.include?('"supports_frame":true'), 'Overlay support not reported')
    check(dialog.scripts.last.include?('"capture_helpers":true') && dialog.scripts.last.include?('"capture_long_edge":true'), 'Clean/long-edge capture feature gates missing')
    camera_stamp = ai.camera_stamp
    check(camera_stamp.match?(/\\A[a-f0-9]{64}\\z/), 'Camera stamp missing or invalid')
    check(camera_stamp == ai.camera_stamp, 'Unchanged camera stamp was not stable')
    model.active_view.camera.eye[0] = 8.0
    check(camera_stamp != ai.camera_stamp, 'Camera eye change was not detected')
    model.active_view.camera.eye[0] = 1.0
    model.active_view.camera.projection = false
    check(ai.camera_stamp && ai.camera_stamp != camera_stamp, 'Orthographic camera stamp invalid')
    model.active_view.camera.projection = true
    check(!dialog.scripts.last.match?(/transport_token|X-OpenMap|Bearer/), 'Runtime secret exposed to HTML')
    check(ai.decode_image(envelope(png(1280,720)))[1] == '.png', 'Valid PNG rejected')
    rejects('SVG data accepted') { ai.decode_image({'data_url'=>'data:image/svg+xml;base64,PHN2Zy8+'}) }
    rejects('MIME/signature mismatch accepted') { ai.decode_image(envelope(png(1280,720), 'image/jpeg')) }
    rejects('Metadata dimension mismatch accepted') { ai.decode_image(envelope(png(1280,720), 'image/png', 1281, 720)) }
    rejects('Huge image dimensions accepted') { ai.decode_image(envelope(png(20000,20000), 'image/png', 20000, 20000)) }
    rejects('Broken base64 accepted') { ai.decode_image({'data_url'=>'data:image/png;base64,@@@@'}) }
    jpeg = ['ffd8ffc00011080020004003011100021100031100ffd9'].pack('H*')
    check(ai.decode_image(envelope(jpeg, 'image/jpeg', 64, 32))[1] == '.jpg', 'JPEG export validation failed')
    webp = 'RIFF' + [22].pack('V') + 'WEBPVP8X' + [10].pack('V') + [0,0,0,0,63,0,0,31,0,0].pack('C*')
    check(ai.decode_image(envelope(webp, 'image/webp', 64, 32))[1] == '.webp', 'WebP export validation failed')
    ['/api/jobs','/api/ai/assets/../../health','/api/ai/jobs?x=1','https://outside.invalid/','/api/ai/jobs/ZZZZ'].each do |invalid|
      rejects('API path escaped AI allowlist') { ai.request('GET', invalid, nil) {} }
    end
    rejects('HTTP method bypassed allowlist') { ai.request('PUT', '/api/ai/status', nil) {} }
    rejects('Array body accepted') { ai.request('POST', '/api/ai/jobs', []) {} }
    thumb = nil
    ai.request('GET','/api/ai/assets/'+'a'*32+'/thumbnail',nil){|data,error,_status|thumb=data unless error}
    check(thumb.is_a?(Hash), 'Thumbnail asset route rejected')
    core.managed = false
    rejects('Remote mode called AI backend') { ai.request('GET', '/api/ai/status', nil) {} }
    core.managed = true
    OpenMapSketchUp::Runtime.test_state = {'state'=>'starting'}
    rejects('Starting worker accepted request') { ai.request('GET', '/api/ai/status', nil) {} }
    OpenMapSketchUp::Runtime.test_state = nil
    core.failure_status = 413
    ai.invoke('oversize','api',{'method'=>'GET','path'=>'/api/ai/status'})
    check(dialog.scripts.last.include?('"status":413') && dialog.scripts.last.include?('Bounded server error'), 'HTTP status/message lost')
    core.failure_status = nil
    model.active_view.fail_write = true
    ai.invoke('capture-fail','capture',{'width'=>1280})
    check(dialog.scripts.last.include?('"ok":false') && !ai.instance_variable_get(:@capture_busy), 'Failed native capture left capture busy')
    model.active_view.fail_write = false
    original_options = model.rendering_options.dup
    ai.invoke('clean-capture','capture',{'width'=>1280,'hide_helpers'=>true})
    check(model.active_view.helpers_when_writing.values_at('HideConstructionGeometry','DisplaySketchAxes','DisplayInstanceAxes','DisplaySectionPlanes') == [true,false,false,false], 'Guide/axes/section-plane helpers not hidden during capture')
    check(model.active_view.helpers_when_writing['DisplaySectionCuts'] && model.active_view.helpers_when_writing['Texture'], 'Clean capture changed section-cut geometry or textures')
    check(model.rendering_options == original_options, 'Clean capture left changed rendering options')
    model.active_view.raise_write = true
    ai.invoke('clean-failed','capture',{'width'=>1280,'hide_helpers'=>true})
    check(dialog.scripts.last.include?('"ok":false') && model.rendering_options == original_options && !ai.instance_variable_get(:@capture_busy), 'Native write exception did not restore rendering options/busy state')
    model.active_view.raise_write = false
    model.active_view.viewport_width, model.active_view.viewport_height = 900, 1600
    ai.invoke('portrait-long','capture',{'width'=>1280,'size_mode'=>'long_edge'})
    check(model.active_view.image_options.values_at(:width,:height) == [720,1280], 'Long-edge portrait capture stretched/exceeded selected size')
    ai.invoke('portrait-width','capture',{'width'=>1280})
    check(model.active_view.image_options.values_at(:width,:height) == [1280,2276], 'Legacy portrait width mode changed')
    model.active_view.viewport_width, model.active_view.viewport_height = nil, nil
    ai.invoke('bad-size','capture',{'width'=>1280,'size_mode'=>'stretch'})
    check(dialog.scripts.last.include?('"ok":false'), 'Unknown capture sizing mode accepted')
    ai.invoke('bad-size-number','capture',{'width'=>1280.0})
    check(dialog.scripts.last.include?('"ok":false'), 'Non-integer capture pixel width accepted')
    ai.invoke('bad-helpers','capture',{'width'=>1280,'hide_helpers'=>'true'})
    check(dialog.scripts.last.include?('"ok":false'), 'Non-boolean helper toggle accepted')
    core.asset_reply = envelope(png(1280,720))
    UI.save_path = nil
    ai.invoke('save-cancel','save_image',{'asset_id'=>'a'*32})
    check(dialog.scripts.last.include?('"saved":false'), 'Cancelled save reported success')
    check(ai.frame_rectangle(1600.0,900.0,'1:1') == [350.0,0.0,900.0,900.0], 'Square frame does not match centered crop')
    check(ai.frame_rectangle(1600.0,900.0,'4000:3000') == [200.0,0.0,1200.0,900.0], 'Custom aspect frame incorrect')
    crop = {'x'=>0.1,'y'=>0.2,'width'=>0.5,'height'=>0.4}
    check(ai.frame_rectangle(1600.0,900.0,'16:9',crop) == [160.0,180.0,800.0,360.0], 'Normalized crop frame misaligned')
    rejects('Zero crop accepted') { ai.validate_frame('1:1',{'x'=>1,'y'=>0,'width'=>0.0000001,'height'=>0.5}) }
    rejects('NaN crop accepted') { ai.validate_frame('1:1',{'x'=>Float::NAN,'y'=>0,'width'=>0.5,'height'=>0.5}) }
    rejects('Outside crop accepted') { ai.validate_frame('1:1',{'x'=>0.9,'y'=>0,'width'=>0.5,'height'=>0.5}) }
    rejects('Malformed aspect accepted') { ai.validate_frame('16:9;exit',nil) }
    rejects('Extreme aspect accepted') { ai.validate_frame('9999:1',nil) }
    frame_state = ai.configure_frame({'enabled'=>true,'aspect'=>'1:1'})
    overlay = ai.instance_variable_get(:@frame_overlay)
    check(frame_state['enabled'] && model.overlays.items == [overlay] && overlay.enabled?, 'Native viewport frame not registered/enabled')
    check(Sketchup.observers.length == 1 && model.active_view.observers.empty?, 'Frame observer depends on camera-watch toggle')
    overlay.draw(model.active_view)
    check(model.active_view.draw_calls.map(&:first) == [GL_QUADS,GL_LINE_LOOP,GL_LINES], 'Viewport frame drawing/thirds missing')
    ai.invoke('capture-guide-test','capture',{'width'=>1280})
    check(!model.active_view.overlay_visible_when_writing, 'Viewport guide was included in source capture')
    check(ai.overlay_drawable?(overlay,model.active_view), 'Viewport guide did not resume after capture')
    new_frame_model = TestModel.new
    Sketchup.active_model = new_frame_model
    ai.model_changed
    check(model.overlays.items.empty? && !overlay.valid? && new_frame_model.overlays.items.length == 1, 'Viewport frame was reused/leaked across models')
    ai.watch_camera(true)
    ai.watch_camera(false)
    check(Sketchup.observers.length == 1 && new_frame_model.active_view.observers.empty?, 'Disabling camera-watch removed frame model observer')
    ai.configure_frame({'enabled'=>false,'aspect'=>'original'})
    check(new_frame_model.overlays.items.empty? && Sketchup.observers.empty?, 'Disabling frame leaked overlay/application observer')
    Sketchup.active_model = Struct.new(:active_view).new(TestView.new)
    unsupported = ai.configure_frame({'enabled'=>true,'aspect'=>'16:9'})
    check(!unsupported['supported'] && !unsupported['enabled'] && Sketchup.observers.empty?, 'Older SketchUp frame fallback did not degrade safely')
    Sketchup.active_model = model
    core.defer = true
    ai.invoke('capture', 'capture', {'width'=>1280})
    options = model.active_view.image_options
    check(options[:width] == 1280 && options[:height] == 720 && options[:antialias], 'Viewport aspect/capture options changed')
    check(Sketchup.active_model.equal?(model), 'Capture changed active model')
    check(core.calls.last[0..1] == ['POST','/api/ai/assets'], 'Capture bypassed private asset upload')
    ai.invoke('capture-duplicate', 'capture', {'width'=>1280})
    check(dialog.scripts.last.include?('"ok":false'), 'Overlapping capture was not bounded')
    core.finish
    check(dialog.scripts.last.include?('"id":"'+'a'*32+'"') && dialog.scripts.last.include?('data:image/png;base64,'), 'Capture did not return asset + actual image')
    check(dialog.scripts.last.include?(ai.camera_stamp), 'Capture omitted camera stamp')
    ai.invoke('capture-model', 'capture', {'width'=>1280})
    Sketchup.active_model = TestModel.new
    core.finish
    check(dialog.scripts.last.include?('"ok":false') && !dialog.scripts.last.include?('data:image/png;base64,'), 'Old model capture attached to new model')
    Sketchup.active_model = model
    ai.watch_camera(true)
    check(model.active_view.observers.length == 1 && Sketchup.observers.length == 1, 'Camera observers not attached exactly once')
    3.times { model.active_view.camera.eye[0] += 1.0; ai.camera_changed(model.active_view) }
    check(UI.timers.length == 1, 'Camera debounce scheduled duplicate timers')
    UI.pump
    check(dialog.scripts.last.include?('cameraChanged()'), 'Debounced camera event missing')
    check(UI.timers.empty?, 'One-shot camera timer leaked')
    ai.camera_changed(model.active_view)
    check(UI.timers.empty?, 'Unchanged deferred ViewChanged caused capture feedback')
    ai.invoke('camera-busy-capture','capture',{'width'=>1280})
    3.times { model.active_view.camera.eye[0] += 1.0; ai.camera_changed(model.active_view) }
    check(UI.timers.empty? && ai.instance_variable_get(:@camera_dirty), 'Camera motion during upload scheduled overlapping capture')
    core.finish
    check(UI.timers.length == 1 && !ai.instance_variable_get(:@camera_dirty), 'Latest camera motion was lost after upload')
    UI.pump
    check(dialog.scripts.last.include?('cameraChanged()'), 'Latest camera motion did not emit after upload')
    next_model = TestModel.new
    Sketchup.active_model = next_model
    ai.model_changed
    check(model.active_view.observers.empty? && next_model.active_view.observers.length == 1, 'Model switch left old view observer attached')
    calls = 0
    ai.request('GET','/api/ai/status',nil) { calls += 1 }
    ai.camera_changed(next_model.active_view)
    ai.configure_frame({'enabled'=>true,'aspect'=>'16:9'})
    old_script_count = dialog.scripts.length
    dialog.close
    check(next_model.active_view.observers.empty? && Sketchup.observers.empty? && UI.timers.empty?, 'Dialog close leaked observers/timers')
    check(next_model.overlays.items.empty?, 'Dialog close leaked viewport frame')
    ai.show
    replacement = ai.instance_variable_get(:@dialog)
    core.finish
    check(calls == 0 && replacement.scripts.empty? && dialog.scripts.length == old_script_count, 'Stale callback crossed dialog generations')
    ai.invoke('old-capture','capture',{'width'=>1280})
    replacement.close
    ai.show
    replacement = ai.instance_variable_get(:@dialog)
    ai.invoke('new-capture','capture',{'width'=>1280})
    core.finish
    check(replacement.scripts.empty? && ai.instance_variable_get(:@capture_busy), 'Old capture replied to/reset new capture')
    core.finish
    check(replacement.scripts.last.include?('new-capture') && !ai.instance_variable_get(:@capture_busy), 'New dialog capture did not finish independently')
    core.defer = false
    # Only fixed managed cache paths are written when opening an image in the
    # OS viewer. A host double records IO; the WASI VM has no writable mount.
    $preview_writes = []
    class << FileUtils
      alias_method :ai_original_mkdir_p, :mkdir_p
      def mkdir_p(path)
        return [path] if path == '/sitecraft-private-state/ai/exports'
        ai_original_mkdir_p(path)
      end
    end
    class << Dir
      alias_method :ai_original_children, :children
      def children(path)
        path == '/sitecraft-private-state/ai/exports' ? [] : ai_original_children(path)
      end
    end
    class << File
      alias_method :ai_original_open, :open
      def open(path,*args,&block)
        if path.start_with?('/sitecraft-private-state/ai/exports/sitecraft_preview_')
          sink=Struct.new(:bytes) { def binmode; self; end; def write(bytes); self.bytes=bytes; bytes.bytesize; end }.new
          $preview_writes << [path,args,sink]
          return yield sink
        end
        ai_original_open(path,*args,&block)
      end
    end
    ai.invoke('open-image','open_image',{'asset_id'=>'a'*32,'path'=>'/untrusted/location.jpg'})
    check($preview_writes.length == 1 && $preview_writes[0][0].match?(/\\A\\/sitecraft-private-state\\/ai\\/exports\\/sitecraft_preview_aaaaaaaa_[a-f0-9]{16}\\.png\\z/), 'Native viewer escaped fixed cache path')
    check(($preview_writes[0][1][0] & File::EXCL) != 0 && $preview_writes[0][2].bytes == png(1280,720), 'Native viewer overwrote/reencoded output')
    check(UI.urls.last.start_with?('file:///sitecraft-private-state/ai/exports/sitecraft_preview_'), 'Native viewer did not open managed image copy')
    ai.invoke('bad-open','open_image',{'asset_id'=>'../outside'})
    check($preview_writes.length == 1 && replacement.scripts.last.include?('"ok":false'), 'Invalid image ID reached file IO')
    module OpenMapSketchUp::AIImageTools
      def self.show(asset_id=nil); @shown = true; @asset_id=asset_id; end
      def self.shown?; @shown; end
      def self.asset_id; @asset_id; end
    end
    ai.invoke('cleanup','open_cleanup',{})
    check(OpenMapSketchUp::AIImageTools.shown? && replacement.scripts.last.include?('"opened":true'), 'Cleanup native delegation failed')
    ai.invoke('cleanup-asset','open_cleanup',{'asset_id'=>'a'*32})
    check(OpenMapSketchUp::AIImageTools.asset_id == 'a'*32, 'Cleanup selected asset was not passed safely')
    module OpenMapSketchUp::AIDownloads
      class << self
        attr_reader :callback, :starts, :stops
        def start(job_id,generation,&block)
          @starts=(@starts||0)+1; @job_id=job_id; @callback=block; @watching=true
          status
        end
        def stop
          @stops=(@stops||0)+1; @watching=false
          status
        end
        def status
          {'watching'=>@watching==true,'job_id'=>@job_id,'state'=>@watching ? 'watching' : 'idle'}
        end
      end
    end
    downloads = OpenMapSketchUp::AIDownloads
    core.job_reply = {'id'=>'b'*32,'state'=>'running'}
    ai.invoke('watch-running','watch_downloads',{'job_id'=>'b'*32})
    check(downloads.starts.nil? && replacement.scripts.last.include?('"ok":false'), 'Watcher attached to an active AI generation')
    core.job_reply['state'] = 'waiting_user'
    ai.invoke('watch-manual','watch_downloads',{'job_id'=>'b'*32})
    callback = downloads.callback
    check(downloads.status['watching'] && replacement.scripts.last.include?('"watching":true'), 'Manual fallback watcher did not start')
    callback.call({'id'=>'c'*32,'candidate_name'=>'download.png','job_id'=>'b'*32})
    check(replacement.scripts.last.include?('downloadCandidate') && replacement.scripts.last.include?('download.png'), 'Watcher candidate did not reach explicit UI confirmation event')
    ai.invoke('watch-stop','stop_downloads',{})
    script_count = replacement.scripts.length
    callback.call({'id'=>'c'*32,'candidate_name'=>'stale.png','job_id'=>'b'*32})
    check(replacement.scripts.length == script_count && !downloads.status['watching'], 'Stopped watcher sent a stale candidate')
    core.defer = true
    ai.invoke('watch-pending','watch_downloads',{'job_id'=>'b'*32})
    ai.invoke('stop-pending','stop_downloads',{})
    core.finish
    check(!downloads.status['watching'] && replacement.scripts.last.include?('superseded'), 'Late job validation restarted a stopped watcher')
    core.defer = false
    ai.invoke('watch-unpair','watch_downloads',{'job_id'=>'b'*32})
    ai.invoke('unpair','api',{'method'=>'POST','path'=>'/api/ai/unpair','body'=>{}})
    check(!downloads.status['watching'], 'Unpair did not stop download watcher')
    ai.invoke('watch-close','watch_downloads',{'job_id'=>'b'*32})
    check(downloads.status['watching'], 'Close watcher fixture did not start')
    ai.invoke('flow','open_flow',{'url'=>'https://untrusted.invalid'})
    check(UI.urls.last == 'https://flow.google.com/', 'Untrusted Flow URL opened')
    check(ai.instance_variable_get(:@generation) != generation, 'Dialog generation did not advance')
    replacement.close
    check(!downloads.status['watching'], 'Dialog close left file watcher active')
    puts "SiteCraft AI Ruby smoke PASS: #{$assertions} checks (host double; no real Flow/SketchUp generation)."
    STDOUT.flush
  `);
  console.log('SiteCraft AI native adapter: Ruby VM checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
