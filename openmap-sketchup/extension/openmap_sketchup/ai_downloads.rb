# encoding: UTF-8
# SPDX-License-Identifier: MIT
# An explicit, local-only Downloads fallback. A discovered image is a candidate
# for the user to confirm; this module never attaches it to a job or calls Flow.
require 'json'
require 'base64'

module OpenMapSketchUp
  module AIDownloads
    MAX_IMAGE = 32 * 1024 * 1024
    MAX_ENTRIES = 1000
    MAX_READS_PER_POLL = 4
    WATCH_SECONDS = 600
    POLL_SECONDS = 2.0
    IMAGE_ID = /\A[a-f0-9]{32}\z/.freeze
    IMAGE_EXTENSIONS = %w[.png .jpg .jpeg .webp].freeze
    @epoch = 0
    @watching = false
    @busy = false
    @state = 'stopped'
    @message = 'Chưa theo dõi thư mục tải về.'

    def self.monotonic
      Process.clock_gettime(Process::CLOCK_MONOTONIC)
    end

    def self.host_current?(generation)
      defined?(AIRender) && AIRender.respond_to?(:current?) && AIRender.current?(generation)
    end

    def self.current?(epoch, generation)
      @watching && @epoch == epoch && @generation == generation && @deadline && monotonic < @deadline && host_current?(generation)
    end

    def self.alive?
      !!(@watching && @deadline && monotonic < @deadline && host_current?(@generation))
    end

    def self.status
      result = { 'watching' => alive?, 'job_id' => @job_id, 'state' => @state, 'message' => @message }
      result['candidate'] = @candidate.dup if @candidate
      result
    end

    def self.stop_timer
      UI.stop_timer(@timer) if @timer
      @timer = nil
    end

    def self.stop(state = 'stopped', message = 'Đã dừng theo dõi thư mục tải về.')
      @epoch += 1
      stop_timer
      @watching = @busy = false
      @folder = @on_candidate = @deadline = nil
      @seen = {}
      @baseline = {}
      @state, @message = state, message
      status
    end

    def self.safe_directory?(path)
      entry = File.lstat(path)
      entry.directory? && !entry.symlink?
    rescue SystemCallError, IOError
      false
    end

    def self.default_folder
      saved = Sketchup.read_default('SiteCraftRenderAI', 'downloads_watch_folder', '').to_s
      return saved if !saved.empty? && safe_directory?(saved)
      downloads = File.join(Dir.home, 'Downloads')
      safe_directory?(downloads) ? downloads : nil
    rescue StandardError
      nil
    end

    def self.fingerprint(stat)
      [stat.size, stat.mtime.to_i, stat.mtime.nsec, stat.dev, stat.ino]
    end

    def self.scan(folder)
      raise 'Thư mục theo dõi không còn khả dụng.' unless safe_directory?(folder)
      names = Dir.each_child(folder).lazy.take(MAX_ENTRIES + 1).to_a
      if names.length > MAX_ENTRIES
        raise 'Thư mục có hơn 1.000 mục. Chọn một thư mục tải ảnh riêng để theo dõi.'
      end
      names.filter_map do |name|
        next unless IMAGE_EXTENSIONS.include?(File.extname(name).downcase)
        path = File.join(folder, name)
        begin
          entry = File.lstat(path)
          next unless entry.file? && !entry.symlink? && entry.size.between?(16, MAX_IMAGE)
          { 'name' => name, 'path' => path, 'fingerprint' => fingerprint(entry), 'mtime' => entry.mtime }
        rescue SystemCallError, IOError
          # Downloads can be renamed between directory enumeration and stat.
          next
        end
      end
    end

    def self.start(job_id, generation, &on_candidate)
      raise 'Mã tác vụ AI không hợp lệ.' unless job_id.is_a?(String) && job_id.match?(IMAGE_ID)
      raise 'Phiên Render AI không hợp lệ.' unless generation.is_a?(Integer) && generation >= 0 && host_current?(generation)
      raise 'Thiếu bộ nhận ảnh tải về.' unless on_candidate
      AIRender.ensure_local! if AIRender.respond_to?(:ensure_local!)
      stop
      @candidate = nil
      @job_id, @generation = job_id, generation
      picker = { title: 'Theo dõi ảnh tải về' }
      initial = default_folder
      picker[:directory] = initial if initial
      selected = UI.select_directory(**picker)
      return stop('cancelled', 'Chưa chọn thư mục tải ảnh.') unless selected
      return stop('stopped', 'Cửa sổ Render AI đã thay đổi.') unless host_current?(generation)
      raise 'Thư mục theo dõi không hợp lệ.' unless selected.is_a?(String) && !selected.empty? && selected.bytesize <= 32_768 && !selected.include?("\x00")
      folder = File.expand_path(selected)
      entries = scan(folder)
      @folder = folder
      @baseline = entries.to_h { |entry| [entry['name'], entry['fingerprint']] }
      @seen = {}
      @on_candidate = on_candidate
      @deadline = monotonic + WATCH_SECONDS
      @watching, @busy = true, false
      @state, @message = 'watching', 'Đang chờ ảnh PNG/JPEG/WebP mới tải về. Ảnh sẽ cần bạn xác nhận trước khi gắn vào tác vụ.'
      begin
        Sketchup.write_default('SiteCraftRenderAI', 'downloads_watch_folder', folder)
      rescue StandardError
        # Failing to remember the picker does not prevent this explicit watch.
      end
      epoch = @epoch
      @timer = UI.start_timer(POLL_SECONDS, true) { poll(epoch, generation) }
      status
    rescue StandardError
      stop('error', 'Không mở được thư mục theo dõi. Chọn thư mục tải ảnh riêng có tối đa 1.000 mục.')
      raise
    end

    def self.read_stable(entry)
      before = File.lstat(entry['path'])
      return nil unless before.file? && !before.symlink? && fingerprint(before) == entry['fingerprint']
      flags = File::RDONLY
      flags |= File::NOFOLLOW if File.const_defined?(:NOFOLLOW) && RUBY_PLATFORM !~ /mingw|mswin/i
      raw = File.open(entry['path'], flags) do |stream|
        opened = stream.stat
        next nil unless opened.file? && fingerprint(opened) == entry['fingerprint']
        bytes = stream.read(MAX_IMAGE + 1)
        next nil unless bytes && bytes.bytesize.between?(16, MAX_IMAGE) && fingerprint(stream.stat) == entry['fingerprint']
        bytes
      end
      after = File.lstat(entry['path'])
      return nil unless raw && after.file? && !after.symlink? && fingerprint(after) == entry['fingerprint']
      raw
    rescue SystemCallError, IOError
      # A browser/antivirus may hold a download briefly. Wait for a later poll.
      nil
    end

    def self.image_url(raw)
      mime = if raw.start_with?("\x89PNG\r\n\x1a\n".b)
               'image/png'
             elsif raw.start_with?("\xff\xd8".b)
               'image/jpeg'
             elsif raw.byteslice(0, 4) == 'RIFF' && raw.byteslice(8, 4) == 'WEBP'
               'image/webp'
             else
               raise 'Tệp tải về không phải ảnh được hỗ trợ.'
             end
      value = 'data:' + mime + ';base64,' + Base64.strict_encode64(raw)
      AIRender.decode_image({ 'data_url' => value })
      value
    end

    def self.candidate_name(name)
      name.encode('UTF-8', invalid: :replace, undef: :replace, replace: '').gsub(/[\x00-\x1f\x7f]/, ' ').slice(0, 120)
    end

    def self.upload_candidate(entry, value, epoch, generation)
      # The map window can switch processing mode while this timer is active.
      # Never let an earlier local-folder choice send bytes to a remote server.
      AIRender.ensure_local! if AIRender.respond_to?(:ensure_local!)
      name = candidate_name(entry['name'])
      @busy, @state = true, 'uploading'
      @message = 'Đã tìm thấy một ảnh tải về; đang lưu bản tạm trên máy để bạn kiểm tra.'
      Core.http('POST', '/api/ai/assets', { 'data_url' => value, 'name' => name, 'role' => 'manual_result' }) do |response, failure|
        next unless current?(epoch, generation)
        begin
          AIRender.ensure_local! if AIRender.respond_to?(:ensure_local!)
          error = Core.error_response(response, failure)
          raise error if error
          raise 'Phản hồi ảnh tạm không hợp lệ.' unless response && response.body.is_a?(String) && response.body.bytesize <= 65_536
          asset = JSON.parse(response.body, max_nesting: 16)
          raise 'Mã ảnh tạm không hợp lệ.' unless asset.is_a?(Hash) && asset['id'].is_a?(String) && asset['id'].match?(IMAGE_ID)
          metadata = asset.select { |key, _| %w[id name mime width height sha256].include?(key) }
          metadata.merge!('job_id' => @job_id, 'candidate_name' => name)
          callback = @on_candidate
          @candidate = metadata
          @watching = @busy = false
          @state, @message = 'candidate', 'Đã tìm thấy ảnh. Kiểm tra ảnh và xác nhận đúng tác vụ trước khi nhập.'
          stop_timer
          @folder = @on_candidate = nil
          callback.call(metadata) if @epoch == epoch && host_current?(generation)
        rescue StandardError
          stop('error', 'Không lưu được ảnh tải về. Bạn có thể chọn Nhập ảnh thủ công hoặc bắt đầu theo dõi lại.')
        end
      end
    rescue StandardError
      stop('error', 'Không kết nối được bộ xử lý để lưu ảnh tải về. Bạn có thể chọn Nhập ảnh thủ công hoặc theo dõi lại.')
    end

    # Public for deterministic host-double tests; production calls come only
    # from the main-thread UI timer installed by start.
    def self.poll(epoch = @epoch, generation = @generation)
      return unless @watching && epoch == @epoch && generation == @generation
      return stop('stopped', 'Cửa sổ Render AI đã đóng hoặc thay đổi.') unless host_current?(generation)
      return stop('expired', 'Đã chờ ảnh trong 10 phút. Tải ảnh rồi bắt đầu theo dõi lại hoặc chọn Nhập ảnh thủ công.') if monotonic >= @deadline
      return if @busy
      entries = scan(@folder)
      present = entries.to_h { |entry| [entry['name'], true] }
      @seen.delete_if { |name, _| !present[name] }
      changed = entries.reject { |entry| @baseline[entry['name']] == entry['fingerprint'] }
      changed.each do |entry|
        previous = @seen[entry['name']]
        count = previous && previous['fingerprint'] == entry['fingerprint'] ? previous['count'] + 1 : 1
        @seen[entry['name']] = { 'fingerprint' => entry['fingerprint'], 'count' => count }
      end
      candidates = changed.select { |entry| @seen[entry['name']]['count'] >= 2 }.sort_by { |entry| entry['mtime'] }.reverse.take(MAX_READS_PER_POLL)
      candidates.each do |entry|
        raw = read_stable(entry)
        next unless raw
        begin
          value = image_url(raw)
        rescue StandardError
          # Ignore a stable non-image once. Other newly downloaded images can
          # still become a candidate without repeatedly opening the bad file.
          @baseline[entry['name']] = entry['fingerprint']
          @seen.delete(entry['name'])
          @message = 'Đã bỏ qua một tệp không đọc được như ảnh. Đang chờ ảnh tải về khác.'
          @busy, @state = false, 'watching'
          next
        end
        upload_candidate(entry, value, epoch, generation)
        break
      end
      status
    rescue StandardError
      stop('error', 'Không đọc được thư mục hoặc thư mục có hơn 1.000 mục. Chọn một thư mục tải ảnh riêng rồi thử lại.')
    end
  end
end
