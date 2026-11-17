/* SPDX-License-Identifier: MIT
 * Deterministic Ruby VM / SketchUp timer + filesystem doubles. No real user
 * Downloads are opened, no external program is run, no Google call is made.
 * Full image decoding remains the separately tested AIRender/Pillow contract.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { DefaultRubyVM } = require('@ruby/wasm-wasi/dist/node');

(async () => {
  const root = path.resolve(__dirname, '..');
  const wasm = require.resolve('@ruby/3.3-wasm-wasi/dist/ruby+stdlib.wasm');
  const { vm } = await DefaultRubyVM(await WebAssembly.compile(fs.readFileSync(wasm)));
  vm.eval(`
    require 'json'
    require 'base64'
    $entries, $file_reads, $enumerated, $clock = {}, Hash.new(0), 0, 100.0
    $assertions = 0
    def check(condition, message)
      raise message unless condition
      $assertions += 1
    end
    def rejects(message)
      begin; yield; rescue StandardError; $assertions += 1; return; end
      raise message
    end
    TestStat = Struct.new(:size, :mtime, :dev, :ino, :kind) do
      def file?; kind == :file; end
      def directory?; kind == :directory; end
      def symlink?; kind == :symlink; end
    end
    def stat_for(entry)
      TestStat.new(entry.fetch(:reported_size, entry[:bytes].bytesize), Time.at(entry[:mtime]), 1, entry[:ino], entry[:kind])
    end
    def add_image(name, bytes = nil, kind = :file)
      bytes ||= "\\x89PNG\\r\\n\\x1a\\n".b + [13].pack('N') + 'IHDR' + [16, 16].pack('NN') + "\\x08\\x06\\x00\\x00\\x00".b + "\\x00".b * 8
      $entries[name] = {bytes: bytes, kind: kind, mtime: $clock, ino: $entries.length + 100}
      bytes
    end
    class TestStream
      def initialize(entry); @entry = entry; end
      def stat; stat_for(@entry); end
      def read(length)
        bytes = @entry[:bytes].byteslice(0, length)
        if @entry.delete(:mutate_on_read)
          @entry[:mtime] += 1
        end
        bytes
      end
    end
    class << File
      alias_method :downloads_original_lstat, :lstat
      alias_method :downloads_original_open, :open
      def lstat(path)
        return TestStat.new(0, Time.at(0), 1, 1, :directory) if ['/downloads', '/testhome/Downloads'].include?(path)
        if path.start_with?('/downloads/')
          entry = $entries[path.delete_prefix('/downloads/')]
          raise Errno::ENOENT unless entry
          return stat_for(entry)
        end
        downloads_original_lstat(path)
      end
      def open(path, flags, &block)
        if path.start_with?('/downloads/')
          name = path.delete_prefix('/downloads/')
          entry = $entries[name]
          raise Errno::ENOENT unless entry
          $file_reads[name] += 1
          raise Errno::EACCES if entry[:locked]
          stream = TestStream.new(entry)
          return block ? block.call(stream) : stream
        end
        downloads_original_open(path, flags, &block)
      end
    end
    class << Dir
      alias_method :downloads_original_each_child, :each_child
      def home; '/testhome'; end
      def each_child(path)
        return downloads_original_each_child(path) { |name| yield name } if path != '/downloads' && block_given?
        return downloads_original_each_child(path) if path != '/downloads'
        return enum_for(:each_child, path) unless block_given?
        $entries.each_key { |name| $enumerated += 1; yield name }
      end
    end
    module Sketchup
      @defaults = {}
      class << self
        def read_default(section, name, fallback); @defaults.fetch([section, name], fallback); end
        def write_default(section, name, value); @defaults[[section, name]] = value; end
      end
    end
    module UI
      @timers, @sequence = {}, 0
      class << self
        attr_reader :timers, :picker_options
        attr_accessor :selected_folder
        def select_directory(**options)
          raise 'Picker off main thread' unless Thread.current == Thread.main
          @picker_options = options
          @selected_folder
        end
        def start_timer(interval, repeat, &block)
          raise 'Timer off main thread' unless Thread.current == Thread.main
          raise 'Bad watch polling period' unless interval == 2.0 && repeat
          @sequence += 1; @timers[@sequence] = block; @sequence
        end
        def stop_timer(id); @timers.delete(id); end
      end
    end
    module OpenMapSketchUp
      module AIRender
        @generation, @visible, @local = 10, true, true
        class << self
          attr_accessor :generation, :visible, :local
          def current?(generation); @visible && @generation == generation; end
          def ensure_local!; raise 'Managed worker required' unless @local; end
          def decode_image(asset)
            data = asset.fetch('data_url')
            bytes = Base64.strict_decode64(data.split(',')[1])
            raise 'Bad image envelope' unless data.start_with?('data:image/png;base64,') && bytes.start_with?("\\x89PNG\\r\\n\\x1a\\n".b) && bytes.bytesize >= 33
            [bytes, '.png']
          end
        end
      end
      module Core
        Response = Struct.new(:status_code, :body)
        @calls, @pending = [], []
        class << self
          attr_reader :calls, :pending
          attr_accessor :defer, :fail
          def error_response(response, failure)
            return failure if failure
            response.status_code == 200 ? nil : 'Local fixture upload failed'
          end
          def http(method, path, body, &callback)
            raise 'HTTP off main thread' unless Thread.current == Thread.main
            @calls << [method, path, body]
            asset = {'id'=>'a'*32, 'name'=>body['name'], 'width'=>16, 'height'=>16, 'mime'=>'image/png', 'sha256'=>'b'*64}
            response = Response.new(@fail ? 503 : 200, JSON.generate(asset))
            @defer ? @pending << [callback, response] : callback.call(response, nil)
          end
          def finish
            callback, response = @pending.shift
            callback.call(response, nil)
          end
          def reset
            @calls.clear; @pending.clear; @defer = @fail = false
          end
        end
      end
    end
  `);
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/ai_downloads.rb'), 'utf8'));
  vm.eval(`
    module OpenMapSketchUp::AIDownloads
      def self.monotonic; $clock; end
    end
    watcher = OpenMapSketchUp::AIDownloads
    ai, core = OpenMapSketchUp::AIRender, OpenMapSketchUp::Core
    $events = []
    def start_watch(id = 'c'*32)
      OpenMapSketchUp::AIDownloads.start(id, OpenMapSketchUp::AIRender.generation) { |candidate| $events << candidate }
    end
    def reset_watch
      OpenMapSketchUp::AIDownloads.stop
      $entries.clear; $file_reads.clear; $events.clear; $enumerated = 0
      OpenMapSketchUp::Core.reset
      OpenMapSketchUp::AIRender.generation = 10
      OpenMapSketchUp::AIRender.visible = OpenMapSketchUp::AIRender.local = true
      UI.selected_folder = '/downloads'
    end

    reset_watch
    rejects('Traversal job accepted') { watcher.start('../escape', 10) {} }
    rejects('Wrong generation accepted') { watcher.start('c'*32, 9) {} }
    rejects('Missing callback accepted') { watcher.start('c'*32, 10) }
    ai.local = false
    rejects('Remote worker accepted') { start_watch }
    ai.local = true
    UI.selected_folder = nil
    check(start_watch['state'] == 'cancelled' && !watcher.alive?, 'Picker cancel created a watch')
    check(core.calls.empty? && UI.timers.empty?, 'Picker cancel started IO')

    reset_watch
    add_image('existing.png')
    add_image('incomplete.png.crdownload')
    check(start_watch['watching'], 'Explicit folder watch did not start')
    check(UI.picker_options[:title] == 'Theo dõi ảnh tải về', 'Wrong explicit picker')
    check(UI.picker_options[:directory] == '/testhome/Downloads', 'Default Downloads folder was not used')
    watcher.poll; watcher.poll
    check(core.calls.empty? && $file_reads.empty?, 'Existing files were treated as newly downloaded')
    add_image('new.png')
    watcher.poll
    check(core.calls.empty?, 'New file uploaded before two stable polls')
    $entries['new.png'][:mtime] += 1
    watcher.poll
    check(core.calls.empty?, 'Changing download treated as stable')
    watcher.poll
    check(core.calls.length == 1 && $events.length == 1, 'Stable image was not uploaded exactly once')
    check(core.calls[0][0..1] == ['POST', '/api/ai/assets'], 'Watcher attached an image or used a wrong endpoint')
    check(core.calls[0][2]['role'] == 'manual_result', 'Candidate was not tagged as manual result')
    check($events[0]['job_id'] == 'c'*32 && $events[0]['candidate_name'] == 'new.png' && $events[0]['id'] == 'a'*32, 'Candidate did not retain explicit target job/asset identity')
    check(!$events[0].to_json.include?('/downloads') && !$events[0].key?('data_url'), 'Candidate exposed a local path or duplicate image payload')
    check(!watcher.alive? && UI.timers.empty? && watcher.status['state'] == 'candidate', 'Candidate did not pause the watch')
    add_image('later.png'); watcher.poll
    check(core.calls.length == 1, 'Paused watcher processed another image')

    reset_watch
    add_image('old.png'); start_watch
    $entries['old.png'][:mtime] += 1
    watcher.poll; watcher.poll
    check($events.length == 1 && $events[0]['candidate_name'] == 'old.png', 'Explicit overwrite of an existing filename was missed')

    reset_watch
    start_watch
    add_image('half.png.crdownload')
    add_image('linked.png', nil, :symlink)
    add_image('nested.png', nil, :directory)
    add_image('huge.png'); $entries['huge.png'][:reported_size] = watcher::MAX_IMAGE + 1
    add_image('empty.png', ''.b)
    watcher.poll; watcher.poll
    check(core.calls.empty? && $file_reads.empty?, 'Partial/symlink/directory/oversized/empty file was read')
    add_image('finished.PNG')
    watcher.poll; watcher.poll
    check($events[0]['candidate_name'] == 'finished.PNG', 'Case-insensitive final image extension was missed')

    reset_watch
    start_watch
    add_image('locked.png'); $entries['locked.png'][:locked] = true
    watcher.poll; watcher.poll
    check(core.calls.empty? && watcher.alive?, 'Transient locked download aborted or uploaded')
    $entries['locked.png'].delete(:locked); watcher.poll
    check(core.calls.length == 1, 'Unlocked stable image was not retried')

    reset_watch
    start_watch
    add_image('moving.png'); $entries['moving.png'][:mutate_on_read] = true
    watcher.poll; watcher.poll
    check(core.calls.empty?, 'File changed during read was uploaded')
    watcher.poll; watcher.poll
    check(core.calls.length == 1, 'Stable later version did not become a candidate')

    reset_watch
    core.defer = true
    start_watch('c'*32); add_image('first.png'); watcher.poll; watcher.poll
    check(core.pending.length == 1 && watcher.status['state'] == 'uploading', 'Deferred candidate upload did not remain in progress')
    watcher.stop
    start_watch('d'*32); add_image('second.png'); watcher.poll; watcher.poll
    check(core.pending.length == 2, 'New explicit watch did not start after stop')
    core.finish
    check($events.empty? && watcher.status['state'] == 'uploading', 'Old upload callback altered a newer watch')
    core.finish
    check($events.length == 1 && $events[0]['job_id'] == 'd'*32, 'Newest candidate callback was lost or mixed with the old job')

    reset_watch
    core.defer = true
    start_watch; add_image('closed.png'); watcher.poll; watcher.poll
    ai.visible = false; core.finish; watcher.poll
    check($events.empty? && UI.timers.empty? && !watcher.alive?, 'Closed dialog accepted a late candidate')

    reset_watch
    start_watch; add_image('mode_changed.png'); watcher.poll
    ai.local = false; watcher.poll
    check(core.calls.empty? && watcher.status['state'] == 'error', 'Processing-mode change sent Downloads bytes to a remote server')

    reset_watch
    core.defer = true
    start_watch; add_image('expired_upload.png'); watcher.poll; watcher.poll
    $clock += watcher::WATCH_SECONDS + 1
    core.finish; watcher.poll
    check($events.empty? && watcher.status['state'] == 'expired', 'Upload callback revived an expired watch')

    reset_watch
    start_watch
    $clock += watcher::WATCH_SECONDS + 1
    watcher.poll
    check(watcher.status['state'] == 'expired' && UI.timers.empty? && core.calls.empty?, 'Ten-minute watch deadline was not enforced')

    reset_watch
    1200.times { |index| add_image("entry_#{index}.tmp") }
    rejects('Oversized directory accepted at start') { start_watch }
    check($enumerated == 1001 && UI.timers.empty? && $file_reads.empty?, 'Directory scan was not bounded before file IO')

    reset_watch
    start_watch
    1200.times { |index| add_image("entry_#{index}.tmp") }
    watcher.poll
    check(watcher.status['state'] == 'error' && $enumerated == 1001 && UI.timers.empty?, 'Growing directory did not stop at the scan bound')

    reset_watch
    start_watch
    10.times { |index| add_image("invalid_#{index}.png", 'not an image'.b * 4) }
    watcher.poll; watcher.poll
    check($file_reads.values.sum == watcher::MAX_READS_PER_POLL, 'Invalid candidate file reads exceeded the per-poll budget')
    check(core.calls.empty? && watcher.alive?, 'Invalid image bytes were uploaded or stopped further candidates')
    add_image('valid.png'); $entries['valid.png'][:mtime] += 10
    watcher.poll; watcher.poll
    check($events.length == 1 && $events[0]['candidate_name'] == 'valid.png', 'Invalid image prevented a later valid candidate')

    reset_watch
    core.fail = true
    start_watch; add_image('failure.png'); watcher.poll; watcher.poll
    check(watcher.status['state'] == 'error' && $events.empty? && UI.timers.empty?, 'Failed local upload produced a fake candidate or a silent retry')
    check(core.calls.all? { |call| call[1] == '/api/ai/assets' }, 'Watcher invoked a job import or cloud endpoint')
    watcher.stop
    check(!watcher.alive? && UI.timers.empty?, 'Stop leaked a timer')
    puts "SiteCraft AI Downloads fallback PASS: #{$assertions} Ruby host-double checks; no automatic job import, cloud calls, shell or external file deletion."
    STDOUT.flush
  `);
  console.log('SiteCraft AI Downloads: Ruby VM checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
