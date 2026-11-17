# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'json'
require 'digest'
require 'fileutils'
require 'tmpdir'
require 'zlib'
require 'securerandom'
require 'socket'
require 'timeout'
require 'uri'

module OpenMapSketchUp
  module Runtime
    MAGIC = 'OPENMAPR1'.freeze
    MAX_FILE = 80 * 1024 * 1024
    MAX_TOTAL = 512 * 1024 * 1024
    @mutex = Mutex.new
    @epoch = 0
    @state = { 'state' => 'idle', 'progress' => 0, 'message' => 'Chuẩn bị bộ xử lý cục bộ' }

    def self.supported?
      !!(RUBY_PLATFORM =~ /mingw|mswin/i) && [0].pack('J').bytesize == 8
    end

    def self.state_root
      explicit = ENV['OPENMAP_STATE_DIR'].to_s
      return File.expand_path(explicit) unless explicit.empty?
      base = ENV['LOCALAPPDATA'].to_s
      base = Dir.tmpdir if base.empty?
      File.join(base, 'OpenMapSketchUp')
    end

    def self.status
      @mutex.synchronize { @state.dup }
    end

    def self.base_url
      @mutex.synchronize { @url }
    end

    def self.transport_token
      @mutex.synchronize { @token }
    end

    def self.publish(epoch, state, percent, message)
      @mutex.synchronize do
        @state = { 'state' => state, 'progress' => percent, 'message' => message } if epoch == @epoch
      end
    end

    def self.read_exact(io, length)
      value = io.read(length)
      raise 'Gói bộ xử lý bị cắt ngắn. Hãy cài lại RBZ.' unless value && value.bytesize == length
      value
    end

    def self.safe_relative?(path)
      return false unless path.is_a?(String) && path.valid_encoding? && path.bytesize.between?(1, 240)
      return false if path.start_with?('/', '\\') || path.include?('\\') || path =~ /[\x00-\x1f:]/
      path.split('/').all? { |part| !['', '.', '..'].include?(part) && part !~ /[. ]\z/ && part !~ /\A(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|\z)/i }
    end

    def self.extract_package(package, destination)
      seen, total = {}, 0
      File.open(package, 'rb') do |io|
        raise 'Định dạng gói bộ xử lý không hợp lệ.' unless read_exact(io, 9) == MAGIC
        count = read_exact(io, 4).unpack('V')[0]
        raise 'Số tệp runtime không hợp lệ.' unless count.between?(1, 5000)
        count.times do |index|
          length = read_exact(io, 2).unpack('v')[0]
          raise 'Tên tệp runtime quá dài.' unless length.between?(1, 240)
          path = read_exact(io, length).force_encoding('UTF-8')
          raise 'Đường dẫn runtime không hợp lệ.' unless safe_relative?(path) && !seen[path.downcase]
          seen[path.downcase] = true
          raw_size, compressed_size = read_exact(io, 8).unpack('VV')
          raise 'Tệp runtime vượt kích thước hợp lệ.' if raw_size > MAX_FILE || compressed_size > MAX_FILE || compressed_size == 0
          total += raw_size
          raise 'Runtime vượt kích thước hợp lệ.' if total > MAX_TOTAL
          expected = read_exact(io, 32)
          target = File.join(destination, path)
          FileUtils.mkdir_p(File.dirname(target))
          digest, produced = Digest::SHA256.new, 0
          inflater = Zlib::Inflate.new
          begin
            File.open(target, 'wb') do |output|
              remaining = compressed_size
              while remaining > 0
                chunk = read_exact(io, [remaining, 65_536].min)
                remaining -= chunk.bytesize
                decoded = inflater.inflate(chunk)
                produced += decoded.bytesize
                raise 'Runtime giải nén vượt kích thước khai báo.' if produced > raw_size
                digest.update(decoded)
                output.write(decoded)
              end
              tail = inflater.finish
              produced += tail.bytesize
              digest.update(tail)
              output.write(tail)
            end
          ensure
            inflater.close
          end
          raise 'Kiểm tra tệp runtime thất bại.' unless produced == raw_size && digest.digest == expected
          yield(index + 1, count) if block_given?
        end
        raise 'Runtime có dữ liệu dư không hợp lệ.' unless io.read(1).nil?
      end
      total
    end

    def self.install(epoch)
      package = File.join(__dir__, 'runtime', 'windows-x64.pak')
      manifest_path = File.join(__dir__, 'runtime', 'manifest.json')
      raise 'Thiếu bộ xử lý Windows. Hãy cài gói Windows Full RBZ.' unless File.file?(package) && File.file?(manifest_path)
      manifest = JSON.parse(File.read(manifest_path, encoding: 'UTF-8'))
      expected = manifest.fetch('package_sha256')
      raise 'Hash runtime không hợp lệ.' unless expected =~ /\A[0-9a-f]{64}\z/
      raise 'Gói runtime bị lỗi khi tải/cài. Hãy tải lại RBZ.' unless Digest::SHA256.file(package).hexdigest == expected
      root = File.join(state_root, 'runtime')
      FileUtils.mkdir_p(root)
      target = File.join(root, expected[0, 32])
      File.open(File.join(root, 'install.lock'), File::RDWR | File::CREAT, 0600) do |lock|
        lock.flock(File::LOCK_EX)
        marker = File.join(target, '.ready')
        if File.file?(marker) && File.read(marker) == expected && File.file?(File.join(target, 'pythonw.exe'))
          return target
        end
        raise 'Cache runtime chưa hoàn tất. Đóng các phiên SketchUp rồi xóa thư mục cache OpenMap để thử lại.' if File.exist?(target)
        stage = Dir.mktmpdir('unpack_', root)
        begin
          extract_package(package, stage) do |done, count|
            publish(epoch, 'preparing', 5 + (done * 75 / count), 'Đang cài bộ xử lý lần đầu (%d/%d tệp)' % [done, count])
          end
          File.write(File.join(stage, '.ready'), expected)
          File.rename(stage, target)
        ensure
          FileUtils.rm_rf(stage) if File.directory?(stage)
        end
      end
      target
    end

    def self.exchange(url_port, token, method = 'GET', path = '/health')
      socket = nil
      Timeout.timeout(2) do
        socket = TCPSocket.new('127.0.0.1', url_port)
        socket.write("#{method} #{path} HTTP/1.0\r\nHost: 127.0.0.1\r\nX-OpenMap-Local: #{token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        raw = socket.read(65_536)
        headers, body = raw.split("\r\n\r\n", 2)
        raise 'Bộ xử lý chưa sẵn sàng.' unless headers.to_s.start_with?('HTTP/1.0 200', 'HTTP/1.1 200')
        JSON.parse(body.to_s)
      end
    ensure
      socket.close if socket && !socket.closed?
    end

    def self.start(server_dir, executable_dir = nil)
      epoch = @mutex.synchronize do
        return if ['preparing', 'starting', 'ready'].include?(@state['state'])
        @epoch += 1
        @state = { 'state' => 'preparing', 'progress' => 1, 'message' => 'Kiểm tra bộ xử lý Windows' }
        @epoch
      end
      unless supported?
        publish(epoch, 'error', 0, 'Bộ cài tự chứa này hỗ trợ Windows x64. macOS/Linux có thể dùng máy chủ riêng trong Cấu hình.')
        return
      end
      @worker = Thread.new do
        pid = nil
        begin
          root = install(epoch)
          next unless @mutex.synchronize { epoch == @epoch }
          raise 'Thiếu mã bộ xử lý đi kèm.' unless File.file?(File.join(server_dir, 'run.py'))
          instances = File.join(state_root, 'instances')
          FileUtils.mkdir_p(instances)
          instance, token = SecureRandom.hex(16), SecureRandom.hex(32)
          ready = File.join(instances, instance + '.json')
          config = File.join(state_root, 'config.env')
          log = File.join(state_root, 'worker-%d.log' % Process.pid)
          shim = 'import runpy,sys;p=sys.argv.pop(1);sys.path.insert(0,p);runpy.run_path(p+"/run.py",run_name="__main__")'
          paths = [root, executable_dir, ENV['PATH']].compact.reject(&:empty?).join(File::PATH_SEPARATOR)
          env = { 'OPENMAP_LOCAL_TOKEN' => token, 'OPENMAP_OCR_DIR' => File.join(root, 'ocr'), 'OPENMAP_LOG_PATH' => log, 'OMP_THREAD_LIMIT' => '2', 'PATH' => paths, 'PYTHONIOENCODING' => 'utf-8' }
          publish(epoch, 'starting', 85, 'Đang khởi động bộ xử lý bản đồ và OCR')
          pid = Process.spawn(env, File.join(root, 'pythonw.exe'), '-c', shim, server_dir, '--port', '0', '--env', config, '--ready-file', ready, '--parent-pid', Process.pid.to_s, '--instance', instance, out: log, err: log, new_pgroup: true)
          waiter = Process.detach(pid)
          accepted = @mutex.synchronize do
            if epoch == @epoch
              @pid, @token, @url, @waiter, @ready_file = pid, token, nil, waiter, ready
              true
            else
              false
            end
          end
          unless accepted
            Process.kill('KILL', pid) rescue nil if waiter.alive?
            next
          end
          deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 90
          connected = false
          while Process.clock_gettime(Process::CLOCK_MONOTONIC) < deadline
            raise 'Bộ xử lý dừng khi khởi động. Mở thư mục OpenMap để xem nhật ký worker.' unless waiter.alive?
            break unless @mutex.synchronize { epoch == @epoch }
            if File.file?(ready)
              doc = JSON.parse(File.read(ready)) rescue nil
              if doc.is_a?(Hash) && doc['pid'] == pid && doc['instance'] == instance && doc['port'].is_a?(Integer) && doc['port'].between?(1, 65_535)
                begin
                  health = exchange(doc['port'], token)
                  if health['instance'] == instance && health['name'] == 'OpenMap SketchUp'
                    @mutex.synchronize { @url = 'http://127.0.0.1:%d' % doc['port'] if epoch == @epoch }
                    publish(epoch, 'ready', 100, 'Bộ xử lý cục bộ đã sẵn sàng')
                    connected = true
                    break
                  end
                rescue StandardError
                  nil
                end
              end
            end
            sleep(0.15)
          end
          raise 'Bộ xử lý khởi động quá thời gian. Hãy thử lại hoặc xem nhật ký worker.' unless connected
          waiter.join
          publish(epoch, 'error', 0, 'Bộ xử lý đã dừng. Mở Cấu hình để khởi động lại.')
        rescue StandardError => error
          Process.kill('KILL', pid) rescue nil if pid && (!waiter || waiter.alive?)
          publish(epoch, 'error', 0, error.message)
        end
      end
    end

    def self.stop
      pid, url, token, waiter, ready = @mutex.synchronize do
        @epoch += 1
        values = [@pid, @url, @token, @waiter, @ready_file]
        @pid, @url, @token, @waiter, @ready_file = nil, nil, nil, nil, nil
        @state = { 'state' => 'idle', 'progress' => 0, 'message' => 'Bộ xử lý đã dừng' }
        values
      end
      return unless pid
      Thread.new do
        begin
          exchange(URI.parse(url).port, token, 'POST', '/api/runtime/shutdown') if url
        rescue StandardError
          nil
        ensure
          sleep(0.5)
          Process.kill('KILL', pid) rescue nil if !waiter || waiter.alive?
          File.delete(ready) rescue nil if ready && File.file?(ready)
        end
      end
    end

    class ApplicationObserver < Sketchup::AppObserver
      def onQuit
        Runtime.stop
      end
    end

    def self.observe
      return if @observer
      @observer = ApplicationObserver.new
      Sketchup.add_observer(@observer)
    end
  end
end
