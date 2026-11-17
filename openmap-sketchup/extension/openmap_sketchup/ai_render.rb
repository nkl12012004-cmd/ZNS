# encoding: UTF-8
# SPDX-License-Identifier: MIT
# Independent SiteCraft UI/viewport adapter. The Flow session stays in Chrome.
require 'json'
require 'base64'
require 'tempfile'
require 'fileutils'
require 'uri'
require 'securerandom'
require 'digest'

module OpenMapSketchUp
  module AIRender
    MAX_MESSAGE = 64 * 1024 * 1024
    MAX_IMAGE = 32 * 1024 * 1024
    MAX_PIXELS = 64 * 1024 * 1024
    CAPTURE_WIDTHS = [1280, 1600, 2048, 2560, 3200].freeze
    FLOW_URL = 'https://flow.google.com/'.freeze
    IMAGE_ID = /\A[a-f0-9]{32}\z/.freeze
    API_PATH = %r{\A/api/ai/(?:status|pair|unpair|assets(?:/[a-f0-9]{32}(?:/thumbnail)?)?|jobs(?:/[a-f0-9]{32}(?:/import)?)?|history/[a-f0-9]{32})\z}.freeze
    PREVIEW_NAME = /\Asitecraft_preview_[a-f0-9]{8}_[a-f0-9]{16}\.(?:png|jpg|webp)\z/.freeze
    CAPTURE_HELPERS = { 'HideConstructionGeometry' => true, 'DisplaySketchAxes' => false,
                        'DisplayInstanceAxes' => false, 'DisplaySectionPlanes' => false }.freeze
    @generation = 0
    @watch_enabled = false
    @capture_busy = false
    @camera_dirty = false
    @frame_enabled = false
    @frame_aspect = 'original'
    @download_watch_serial = 0

    # Available in SketchUp 2023+. This class never selects a Tool or changes
    # camera/model data. Coordinates use the same screen units as vpwidth /
    # vpheight, including SketchUp 2025+'s logical-pixel API.
    class FrameOverlay < (defined?(Sketchup::Overlay) ? Sketchup::Overlay : Object)
      def initialize(aspect, crop)
        super('sitecraft.render_ai.frame', 'SiteCraft — Khung Render AI', description: 'Khung cắt và đường một phần ba để căn góc Render AI.')
        configure(aspect, crop)
      end

      def configure(aspect, crop)
        @aspect, @crop = aspect, crop
      end

      def draw(view)
        return unless AIRender.overlay_drawable?(self, view)
        width, height = view.vpwidth.to_f, view.vpheight.to_f
        return if width <= 0 || height <= 0
        x, y, frame_width, frame_height = AIRender.frame_rectangle(width, height, @aspect, @crop)
        right, bottom = x + frame_width, y + frame_height
        # Only outside the crop is darkened. Keep native camera navigation and
        # selection active underneath the non-interactive overlay.
        outside = []
        outside.concat([[0, 0, 0], [width, 0, 0], [width, y, 0], [0, y, 0]]) if y > 0
        outside.concat([[0, bottom, 0], [width, bottom, 0], [width, height, 0], [0, height, 0]]) if bottom < height
        outside.concat([[0, y, 0], [x, y, 0], [x, bottom, 0], [0, bottom, 0]]) if x > 0
        outside.concat([[right, y, 0], [width, y, 0], [width, bottom, 0], [right, bottom, 0]]) if right < width
        unless outside.empty?
          view.drawing_color = Sketchup::Color.new(12, 31, 25, 135)
          view.draw2d(GL_QUADS, outside)
        end
        view.line_stipple = ''
        view.line_width = 2
        view.drawing_color = Sketchup::Color.new(245, 255, 248, 240)
        view.draw2d(GL_LINE_LOOP, [[x, y, 0], [right, y, 0], [right, bottom, 0], [x, bottom, 0]])
        thirds = [1, 2].flat_map do |fraction|
          sx = x + frame_width * fraction / 3.0
          sy = y + frame_height * fraction / 3.0
          [[sx, y, 0], [sx, bottom, 0], [x, sy, 0], [right, sy, 0]]
        end
        view.line_width = 1
        view.drawing_color = Sketchup::Color.new(245, 255, 248, 110)
        view.draw2d(GL_LINES, thirds)
      end
    end

    class CameraObserver < (defined?(Sketchup::ViewObserver) ? Sketchup::ViewObserver : Object)
      def onViewChanged(view)
        AIRender.camera_changed(view)
      end
    end

    class ModelObserver < (defined?(Sketchup::AppObserver) ? Sketchup::AppObserver : Object)
      def onActivateModel(_model)
        AIRender.model_changed
      end

      def onNewModel(_model)
        AIRender.model_changed
      end

      def onOpenModel(_model)
        AIRender.model_changed
      end
    end

    def self.visible?
      @dialog && @dialog.visible?
    end

    def self.current?(generation)
      generation == @generation && visible?
    end

    def self.reply(id, result, generation = @generation)
      return unless current?(generation)
      @dialog.execute_script('window.SiteCraftAI && window.SiteCraftAI.receive(%s,%s)' % [JSON.generate(id), JSON.generate(result)])
    end

    def self.ensure_local!
      raise 'Render AI cần bộ xử lý cục bộ. Chọn “Trên máy này” trong cấu hình SiteCraft.' unless Core.managed?
      state = Runtime.status
      unless state['state'] == 'ready'
        Core.start_runtime if state['state'] == 'idle'
        raise(state['state'] == 'error' ? state['message'].to_s : 'Bộ xử lý SiteCraft đang khởi động. Đợi vài giây rồi thử lại.')
      end
    end

    def self.camera_stamp(model = Sketchup.active_model)
      view = model.active_view
      state = [model.object_id.to_s, view.vpwidth, view.vpheight]
      if view.respond_to?(:camera)
        camera = view.camera
        perspective = camera.perspective?
        state.concat([camera.eye.to_a, camera.target.to_a, camera.up.to_a, perspective])
        properties = perspective ? %i[fov aspect_ratio fov_is_height?] : %i[height aspect_ratio]
        properties.each do |property|
          state << camera.public_send(property) if camera.respond_to?(property)
        end
      end
      Digest::SHA256.hexdigest(JSON.generate(state))
    rescue StandardError
      # Some older host versions cannot query all camera properties. The
      # capture still carries its model identity and its actual pixel size.
      nil
    end

    def self.supports_frame?(model = Sketchup.active_model)
      !!(defined?(Sketchup::Overlay) && FrameOverlay < Sketchup::Overlay && model.respond_to?(:overlays))
    end

    def self.capture_helpers_supported?(model = Sketchup.active_model)
      return false unless model.respond_to?(:rendering_options)
      options = model.rendering_options
      options.respond_to?(:keys) && !(options.keys & CAPTURE_HELPERS.keys).empty?
    rescue StandardError
      false
    end

    def self.with_capture_helpers(model, enabled)
      return yield unless enabled
      raise 'Mô hình này không hỗ trợ ẩn đường phụ khi chụp. Bỏ chọn Ẩn đường phụ rồi thử lại.' unless capture_helpers_supported?(model)
      options = model.rendering_options
      available = options.keys
      saved = {}
      begin
        CAPTURE_HELPERS.each do |key, hidden|
          next unless available.include?(key) && options[key] != hidden
          saved[key] = options[key]
          options[key] = hidden
        end
        yield
      ensure
        failed = []
        saved.each do |key, original|
          begin
            options[key] = original if options[key] != original
          rescue StandardError
            failed << key
          end
        end
        model.active_view.invalidate if model.active_view.respond_to?(:invalidate)
        unless failed.empty?
          raise 'Không khôi phục được tùy chọn hiển thị sau khi chụp: ' + failed.join(', ') + '. Kiểm tra lại Styles của mô hình.'
        end
      end
    end

    def self.validate_frame(aspect, crop)
      aspect = 'original' if aspect.nil?
      unless aspect == 'original'
        match = aspect.is_a?(String) && /\A([1-9][0-9]{0,3}):([1-9][0-9]{0,3})\z/.match(aspect)
        raise 'Tỷ lệ khung phải có dạng Rộng:Cao, ví dụ 16:9.' unless match
        ratio = match[1].to_f / match[2].to_f
        raise 'Tỷ lệ khung phải nằm trong 1:20 đến 20:1.' unless ratio.between?(0.05, 20)
      end
      if crop
        unless crop.is_a?(Hash) && %w[x y width height].all? { |key| crop[key].is_a?(Numeric) && crop[key].finite? }
          raise 'Vùng khung cắt không hợp lệ.'
        end
        x, y, width, height = crop.values_at('x', 'y', 'width', 'height')
        unless x >= 0 && x < 1 && y >= 0 && y < 1 && width > 0 && height > 0 && x + width <= 1.000001 && y + height <= 1.000001
          raise 'Khung cắt phải nằm trong ảnh nguồn.'
        end
        crop = { 'x' => x.to_f, 'y' => y.to_f, 'width' => [width.to_f, 1 - x].min, 'height' => [height.to_f, 1 - y].min }
      end
      [aspect, crop]
    end

    def self.frame_rectangle(width, height, aspect, crop = nil)
      return [crop['x'] * width, crop['y'] * height, crop['width'] * width, crop['height'] * height] if crop
      return [0.0, 0.0, width, height] if aspect == 'original'
      wide, tall = aspect.split(':').map(&:to_f)
      ratio = wide / tall
      if width / height > ratio
        frame_width = height * ratio
        [(width - frame_width) / 2, 0.0, frame_width, height]
      else
        frame_height = width / ratio
        [0.0, (height - frame_height) / 2, width, frame_height]
      end
    end

    def self.overlay_drawable?(overlay, view)
      @frame_enabled && !@writing_image && overlay.equal?(@frame_overlay) &&
        Sketchup.active_model.equal?(@frame_model) && view.equal?(@frame_model.active_view)
    rescue StandardError
      false
    end

    def self.detach_frame
      overlay, model = @frame_overlay, @frame_model
      @frame_overlay = @frame_model = nil
      return unless overlay && model
      begin
        model.overlays.remove(overlay)
        model.active_view.invalidate
      rescue StandardError
        # Closing a document invalidates its manager/overlay automatically.
        # Always release Ruby references even if the model has already closed.
        nil
      end
    end

    def self.bind_frame
      model = Sketchup.active_model
      if @frame_model.equal?(model) && @frame_overlay
        @frame_overlay.configure(@frame_aspect, @frame_crop)
        model.active_view.invalidate
        return
      end
      detach_frame
      return unless @frame_enabled && supports_frame?(model)
      overlay = FrameOverlay.new(@frame_aspect, @frame_crop)
      raise 'Không thêm được khung Render AI vào mô hình này.' unless model.overlays.add(overlay)
      @frame_model, @frame_overlay = model, overlay
      overlay.enabled = true
      model.active_view.invalidate
    end

    def self.configure_frame(args)
      enabled = args['enabled'] == true
      aspect, crop = validate_frame(args['aspect'], args['crop'])
      supported = supports_frame?
      unless supported
        @frame_enabled = false
        detach_frame
        update_app_observer
        return { 'enabled' => false, 'supported' => false, 'aspect' => aspect, 'message' => 'Khung trên viewport cần SketchUp 2023 trở lên. Vẫn có thể cắt ảnh trong SiteCraft.' }
      end
      @frame_enabled, @frame_aspect, @frame_crop = enabled, aspect, crop
      enabled ? bind_frame : detach_frame
      update_app_observer
      { 'enabled' => @frame_enabled, 'supported' => true, 'aspect' => @frame_aspect }
    rescue StandardError
      @frame_enabled = false
      detach_frame
      update_app_observer
      raise
    end

    def self.request(method, path, body, generation = @generation, &callback)
      ensure_local!
      unless %w[GET POST DELETE].include?(method) && path.is_a?(String) && path.match?(API_PATH)
        raise 'Đường dẫn Render AI không hợp lệ.'
      end
      raise 'Tham số Render AI không hợp lệ.' unless body.nil? || body.is_a?(Hash)
      Core.http(method, path, body) do |response, failure|
        next unless current?(generation)
        begin
          error = Core.error_response(response, failure)
          raise error if error
          raise 'Phản hồi Render AI quá lớn.' unless response.body.is_a?(String) && response.body.bytesize <= MAX_MESSAGE
          value = JSON.parse(response.body, max_nesting: 24)
          raise 'Phản hồi Render AI không hợp lệ.' unless value.is_a?(Hash)
          callback.call(value, nil, response.status_code)
        rescue StandardError => error
          callback.call(nil, error.message, response ? response.status_code : 0)
        end
      end
    end

    # Validate the bounded image envelope returned by the authenticated worker.
    # Full image decoding/verification is performed by Pillow before storage.
    def self.decode_image(asset)
      raise 'Ảnh Render AI không hợp lệ.' unless asset.is_a?(Hash)
      data = asset['data_url']
      unless data.is_a?(String) && data.bytesize <= (MAX_IMAGE * 4 / 3 + 128)
        raise 'Ảnh Render AI vượt giới hạn 32 MB.'
      end
      match = /\Adata:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+\/=]+)\z/m.match(data)
      raise 'Ảnh phải là PNG, JPEG hoặc WebP.' unless match
      bytes = Base64.strict_decode64(match[2])
      raise 'Ảnh Render AI vượt giới hạn 32 MB.' unless bytes.bytesize.between?(16, MAX_IMAGE)
      mime = match[1]
      dimensions = if mime == 'image/png'
                     raise 'Ảnh PNG không hợp lệ.' unless bytes.start_with?("\x89PNG\r\n\x1a\n".b) && bytes.bytesize >= 33 && bytes.byteslice(12, 4) == 'IHDR'
                     bytes.byteslice(16, 8).unpack('NN')
                   elsif mime == 'image/jpeg'
                     Importer.jpeg_size(bytes)
                   else
                     webp_size(bytes)
                   end
      width, height = dimensions
      unless dimensions.all? { |number| number.is_a?(Integer) && number.between?(1, 16_384) } && width * height <= MAX_PIXELS
        raise 'Kích thước ảnh Render AI không hợp lệ.'
      end
      if asset['width'] && asset['width'] != width || asset['height'] && asset['height'] != height
        raise 'Kích thước ảnh không khớp dữ liệu đã lưu.'
      end
      raise 'Loại ảnh không khớp dữ liệu đã lưu.' if asset['mime'] && asset['mime'] != mime
      [bytes, { 'image/png' => '.png', 'image/jpeg' => '.jpg', 'image/webp' => '.webp' }.fetch(mime)]
    rescue ArgumentError
      raise 'Dữ liệu ảnh Render AI bị hỏng.'
    end

    def self.webp_size(bytes)
      unless bytes.byteslice(0, 4) == 'RIFF' && bytes.byteslice(8, 4) == 'WEBP' && bytes.byteslice(4, 4).unpack('V')[0] + 8 == bytes.bytesize
        raise 'Ảnh WebP không hợp lệ.'
      end
      kind = bytes.byteslice(12, 4)
      if kind == 'VP8X' && bytes.bytesize >= 30
        width = bytes.byteslice(24, 3).unpack('C*').each_with_index.sum { |v, i| v << (i * 8) } + 1
        height = bytes.byteslice(27, 3).unpack('C*').each_with_index.sum { |v, i| v << (i * 8) } + 1
        [width, height]
      elsif kind == 'VP8L' && bytes.bytesize >= 25 && bytes.getbyte(20) == 47
        packed = bytes.byteslice(21, 4).unpack('V')[0]
        [(packed & 0x3fff) + 1, ((packed >> 14) & 0x3fff) + 1]
      elsif kind == 'VP8 ' && bytes.bytesize >= 30 && bytes.byteslice(23, 3) == "\x9d\x01\x2a".b
        bytes.byteslice(26, 4).unpack('vv').map { |number| number & 0x3fff }
      else
        raise 'Không đọc được kích thước WebP.'
      end
    end

    def self.capture(id, args, generation)
      ensure_local!
      selected_size = args.fetch('width', 2048)
      raise 'Chọn kích thước chụp 1280–3200 px.' unless selected_size.is_a?(Integer) && CAPTURE_WIDTHS.include?(selected_size)
      size_mode = args.fetch('size_mode', 'width')
      raise 'Chế độ kích thước chụp không hợp lệ.' unless %w[width long_edge].include?(size_mode)
      hide_helpers = args.fetch('hide_helpers', false)
      raise 'Tùy chọn ẩn đường phụ không hợp lệ.' unless hide_helpers == true || hide_helpers == false
      raise 'Đang lưu khung nhìn trước. Đợi ảnh xuất hiện rồi chụp lại.' if @capture_busy
      model = Sketchup.active_model
      view = model.active_view
      stamp = camera_stamp(model)
      viewport_width, viewport_height = view.vpwidth, view.vpheight
      unless viewport_width.to_i > 0 && viewport_height.to_i > 0
        raise 'Khung nhìn SketchUp chưa sẵn sàng.'
      end
      if size_mode == 'long_edge' && viewport_height > viewport_width
        height = selected_size
        width = (height.to_f * viewport_width / viewport_height).round
      else
        width = selected_size
        height = (width.to_f * viewport_height / viewport_width).round
      end
      unless width.between?(1, 8192) && height.between?(1, 8192) && width * height <= MAX_PIXELS
        raise 'Tỷ lệ khung nhìn quá cao. Mở rộng cửa sổ SketchUp rồi chụp lại.'
      end
      stop_camera_timer
      @camera_dirty = false
      @observed_camera_stamp = stamp if view.equal?(@watched_view)
      @capture_busy = true
      begin
        data_url = nil
        Tempfile.create(['sitecraft_ai_view_', '.png']) do |temporary|
          path = temporary.path
          temporary.close
          begin
            @writing_image = true
            result = with_capture_helpers(model, hide_helpers) do
              view.write_image(filename: path, width: width, height: height, antialias: true, transparent: false)
            end
          ensure
            @writing_image = false
          end
          raise 'Không chụp được khung nhìn SketchUp.' unless result && File.file?(path)
          raise 'Ảnh khung nhìn quá lớn.' unless File.size(path).between?(1, MAX_IMAGE)
          data_url = 'data:image/png;base64,' + Base64.strict_encode64(File.binread(path))
          decode_image({ 'data_url' => data_url, 'width' => width, 'height' => height, 'mime' => 'image/png' })
        end
        raise 'Bạn đã chuyển mô hình trong lúc chụp. Hãy chụp lại khung hiện tại.' unless Sketchup.active_model.equal?(model)
        request('POST', '/api/ai/assets', { 'data_url' => data_url, 'name' => 'Khung nhìn SketchUp', 'role' => 'source' }, generation) do |asset, failure, status|
          finish_capture
          if failure
            reply(id, { 'ok' => false, 'error' => failure, 'status' => status }, generation)
          elsif !Sketchup.active_model.equal?(model)
            reply(id, { 'ok' => false, 'error' => 'Bạn đã chuyển mô hình trong lúc tải ảnh. Hãy chụp lại.' }, generation)
          else
            reply(id, { 'ok' => true, 'data' => asset.merge('data_url' => data_url, 'model_context' => model.object_id.to_s, 'camera_stamp' => stamp,
              'capture' => { 'size_mode' => size_mode, 'hide_helpers' => hide_helpers, 'width' => width, 'height' => height }) }, generation)
          end
        end
      rescue StandardError
        finish_capture
        raise
      end
    end

    def self.finish_capture
      @capture_busy = false
      dirty = @camera_dirty
      @camera_dirty = false
      camera_changed(@watched_view, true) if dirty && @watch_enabled && @watched_view
    end

    def self.save_image(id, args, generation)
      asset_id = args['asset_id']
      raise 'Mã ảnh không hợp lệ.' unless asset_id.is_a?(String) && asset_id.match?(IMAGE_ID)
      request('GET', '/api/ai/assets/' + asset_id, nil, generation) do |asset, failure, status|
        begin
          raise failure if failure
          bytes, extension = decode_image(asset)
          path = UI.savepanel('Lưu ảnh SiteCraft Render AI', @last_export_dir, 'SiteCraft_Render_' + asset_id[0, 8] + extension)
          if path
            raise 'Cửa sổ Render AI đã đóng. Mở lại để lưu ảnh.' unless current?(generation)
            path += extension unless File.extname(path).downcase == extension
            Tempfile.create(['.sitecraft_ai_', '.tmp'], File.dirname(path)) do |temporary|
              temporary.binmode
              temporary.write(bytes)
              temporary.flush
              temporary.close
              File.rename(temporary.path, path)
            end
            @last_export_dir = File.dirname(path)
          end
          reply(id, { 'ok' => true, 'data' => { 'saved' => !path.nil? } }, generation)
        rescue StandardError => error
          reply(id, { 'ok' => false, 'error' => error.message, 'status' => status }, generation)
        end
      end
    end

    def self.prune_previews(directory, keep)
      entries = Dir.children(directory).select { |name| name.match?(PREVIEW_NAME) }.map { |name| File.join(directory, name) }
      entries.select! { |path| File.file?(path) && !File.symlink?(path) }
      entries.sort_by! { |path| File.mtime(path) }.reverse!
      bytes = 0
      entries.each_with_index do |path, index|
        bytes += File.size(path)
        next if path == keep || (index < 12 && bytes <= 128 * 1024 * 1024)
        File.delete(path) rescue nil # An external viewer may still hold it.
      end
    end

    def self.open_image(id, args, generation)
      asset_id = args['asset_id']
      raise 'Mã ảnh không hợp lệ.' unless asset_id.is_a?(String) && asset_id.match?(IMAGE_ID)
      request('GET', '/api/ai/assets/' + asset_id, nil, generation) do |asset, failure, status|
        begin
          raise failure if failure
          bytes, extension = decode_image(asset)
          directory = File.join(Runtime.state_root, 'ai', 'exports')
          FileUtils.mkdir_p(directory)
          raise 'Thư mục xem ảnh không hợp lệ.' if File.symlink?(directory)
          path = File.join(directory, 'sitecraft_preview_' + asset_id[0, 8] + '_' + SecureRandom.hex(8) + extension)
          File.open(path, File::WRONLY | File::CREAT | File::EXCL, 0o600) do |stream|
            stream.binmode
            stream.write(bytes)
          end
          prune_previews(directory, path)
          open_local_file(path)
          reply(id, { 'ok' => true, 'data' => { 'opened' => true } }, generation)
        rescue StandardError => error
          reply(id, { 'ok' => false, 'error' => error.message, 'status' => status }, generation)
        end
      end
    end

    def self.downloads_module
      require_relative 'ai_downloads' if !defined?(OpenMapSketchUp::AIDownloads) && File.file?(File.join(__dir__, 'ai_downloads.rb'))
      raise 'Theo dõi ảnh tải về chưa có trong bộ cài này.' unless defined?(OpenMapSketchUp::AIDownloads)
      OpenMapSketchUp::AIDownloads
    end

    def self.stop_downloads
      @download_watch_serial += 1
      return OpenMapSketchUp::AIDownloads.stop if defined?(OpenMapSketchUp::AIDownloads)
      { 'watching' => false, 'state' => 'idle' }
    end

    def self.downloads_status
      return OpenMapSketchUp::AIDownloads.status if defined?(OpenMapSketchUp::AIDownloads)
      { 'watching' => false, 'state' => 'idle' }
    end

    def self.watch_downloads(id, args, generation)
      job_id = args['job_id']
      raise 'Mã lượt Render AI không hợp lệ.' unless job_id.is_a?(String) && job_id.match?(IMAGE_ID)
      stop_downloads
      serial = @download_watch_serial
      request('GET', '/api/ai/jobs/' + job_id, nil, generation) do |job, failure, status|
        begin
          raise failure if failure
          if serial != @download_watch_serial
            reply(id, { 'ok' => true, 'data' => { 'watching' => false, 'state' => 'superseded' } }, generation)
            next
          end
          unless %w[waiting_user error].include?(job['state'])
            raise 'Chỉ theo dõi ảnh cho lượt đang chờ thao tác hoặc bị lỗi. Không tự gán ảnh cho lượt đang render.'
          end
          result = downloads_module.start(job_id, generation) do |metadata|
            next unless current?(generation) && serial == @download_watch_serial && metadata.is_a?(Hash) && metadata['id'].is_a?(String) && metadata['id'].match?(IMAGE_ID)
            @dialog.execute_script('window.SiteCraftAI && window.SiteCraftAI.downloadCandidate && window.SiteCraftAI.downloadCandidate(%s,%s)' % [JSON.generate(metadata), JSON.generate(job_id)])
          end
          reply(id, { 'ok' => true, 'data' => result }, generation)
        rescue StandardError => error
          reply(id, { 'ok' => false, 'error' => error.message, 'status' => status }, generation)
        end
      end
    end

    def self.stop_camera_timer
      UI.stop_timer(@camera_timer) if @camera_timer
      @camera_timer = nil
    end

    def self.detach_camera
      stop_camera_timer
      view = @watched_view
      @watched_view = nil
      @observed_camera_stamp = nil
      view.remove_observer(@camera_observer) if view && @camera_observer && view.respond_to?(:remove_observer)
    rescue StandardError
      # A closed SketchUp document invalidates its View and its observers.
      nil
    end

    def self.bind_camera
      detach_camera
      return unless @watch_enabled
      view = Sketchup.active_model.active_view
      raise 'Phiên bản SketchUp này không hỗ trợ theo dõi camera.' unless view.respond_to?(:add_observer)
      @camera_observer ||= CameraObserver.new
      view.add_observer(@camera_observer)
      @watched_view = view
      @observed_camera_stamp = camera_stamp
    end

    def self.watch_camera(enabled)
      @watch_enabled = enabled == true
      if @watch_enabled
        update_app_observer
        bind_camera
      else
        @camera_dirty = false
        detach_camera
        update_app_observer
      end
      { 'enabled' => @watch_enabled }
    rescue StandardError
      @watch_enabled = false
      detach_camera
      update_app_observer
      raise
    end

    def self.update_app_observer
      needed = @watch_enabled || @frame_enabled
      if needed && !@app_observer_attached
        @model_observer ||= ModelObserver.new
        Sketchup.add_observer(@model_observer)
        @app_observer_attached = true
      elsif !needed && @app_observer_attached
        Sketchup.remove_observer(@model_observer)
        @app_observer_attached = false
      end
    end

    def self.model_changed
      return unless (@watch_enabled || @frame_enabled) && visible?
      if @watch_enabled
        bind_camera
        camera_changed(@watched_view, true)
      end
      bind_frame if @frame_enabled
    rescue StandardError
      @frame_enabled = false
      detach_frame
      watch_camera(false)
    end

    def self.camera_changed(view, force = false)
      return unless @watch_enabled && visible? && view.equal?(@watched_view) && !@writing_image
      stamp = camera_stamp
      return if !force && stamp && stamp == @observed_camera_stamp
      @observed_camera_stamp = stamp
      if @capture_busy
        @camera_dirty = true
        return
      end
      stop_camera_timer
      generation = @generation
      @camera_timer = UI.start_timer(0.7, false) do
        @camera_timer = nil
        if current?(generation) && @watch_enabled && Sketchup.active_model.active_view.equal?(@watched_view)
          if @capture_busy
            @camera_dirty = true
          else
            @dialog.execute_script('window.SiteCraftAI && window.SiteCraftAI.cameraChanged && window.SiteCraftAI.cameraChanged()')
          end
        end
      end
    end

    def self.open_local_file(path)
      encoded = path.tr('\\', '/').split('/').map { |part| URI::DEFAULT_PARSER.escape(part, /[^A-Za-z0-9\-._~:]/) }.join('/')
      UI.openURL('file:///' + encoded.sub(%r{\A/+}, ''))
      { 'opened' => true }
    end

    def self.open_local_folder(path)
      open_local_file(path)
    end

    def self.open_folder
      path = @last_export_dir || File.join(Runtime.state_root, 'ai')
      FileUtils.mkdir_p(path)
      open_local_folder(path)
    end

    def self.open_bridge_folder
      path = File.join(__dir__, 'browser_extension', 'sitecraft_flow_bridge')
      raise 'Chưa có thư mục extension Chrome trong bộ cài này. Dùng bản Full mới hoặc giải nén SiteCraft Flow Bridge ZIP.' unless File.directory?(path)
      open_local_folder(path)
    end

    def self.invoke(id, action, args, generation = @generation)
      raise 'Mã yêu cầu không hợp lệ.' unless id.is_a?(String) && id.bytesize.between?(1, 128)
      raise 'Tham số Render AI không hợp lệ.' unless args.is_a?(Hash)
      case action
      when 'config'
        reply(id, { 'ok' => true, 'data' => { 'version' => OpenMapSketchUp::VERSION, 'managed' => Core.managed?, 'model_context' => Sketchup.active_model.object_id.to_s, 'camera_stamp' => camera_stamp, 'runtime' => Runtime.status, 'capture_widths' => CAPTURE_WIDTHS, 'supports_frame' => supports_frame?, 'capture_helpers' => capture_helpers_supported?, 'capture_long_edge' => true } }, generation)
      when 'api'
        request(args['method'], args['path'], args['body'], generation) do |data, error, status|
          if !error && args['method'] == 'POST' && args['path'] == '/api/ai/unpair'
            stop_downloads
          elsif !error && args['method'] == 'DELETE' && args['path'] == '/api/ai/jobs/' + downloads_status['job_id'].to_s
            stop_downloads
          end
          reply(id, error ? { 'ok' => false, 'error' => error, 'status' => status } : { 'ok' => true, 'data' => data }, generation)
        end
      when 'capture'
        capture(id, args, generation)
      when 'save_image'
        save_image(id, args, generation)
      when 'open_image'
        open_image(id, args, generation)
      when 'watch_downloads'
        watch_downloads(id, args, generation)
      when 'stop_downloads'
        reply(id, { 'ok' => true, 'data' => stop_downloads }, generation)
      when 'downloads_status'
        reply(id, { 'ok' => true, 'data' => downloads_status }, generation)
      when 'camera_watch'
        reply(id, { 'ok' => true, 'data' => watch_camera(args['enabled']) }, generation)
      when 'frame_overlay'
        reply(id, { 'ok' => true, 'data' => configure_frame(args) }, generation)
      when 'open_cleanup'
        require_relative 'ai_image_tools' if !defined?(OpenMapSketchUp::AIImageTools) && File.file?(File.join(__dir__, 'ai_image_tools.rb'))
        raise 'Công cụ xử lý ảnh chưa có trong bộ cài này.' unless defined?(OpenMapSketchUp::AIImageTools) && OpenMapSketchUp::AIImageTools.respond_to?(:show)
        asset_id = args['asset_id']
        raise 'Mã ảnh không hợp lệ.' unless asset_id.nil? || (asset_id.is_a?(String) && asset_id.match?(IMAGE_ID))
        asset_id ? OpenMapSketchUp::AIImageTools.show(asset_id) : OpenMapSketchUp::AIImageTools.show
        reply(id, { 'ok' => true, 'data' => { 'opened' => true } }, generation)
      when 'open_flow'
        UI.openURL(FLOW_URL)
        reply(id, { 'ok' => true, 'data' => { 'opened' => true } }, generation)
      when 'open_folder'
        reply(id, { 'ok' => true, 'data' => open_folder }, generation)
      when 'open_bridge_folder'
        reply(id, { 'ok' => true, 'data' => open_bridge_folder }, generation)
      when 'close'
        reply(id, { 'ok' => true, 'data' => {} }, generation)
        @dialog.close if current?(generation)
      else
        raise 'Lệnh Render AI không được hỗ trợ.'
      end
    rescue StandardError => error
      reply(id, { 'ok' => false, 'error' => error.message }, generation)
    end

    def self.closed(generation)
      return unless generation == @generation
      stop_downloads
      watch_camera(false)
      @frame_enabled = false
      detach_frame
      update_app_observer
      @capture_busy = false
      @dialog = nil
      @generation += 1
    end

    def self.show
      Core.start_runtime
      if visible?
        @dialog.bring_to_front
        return
      end
      @generation += 1
      generation = @generation
      @dialog = UI::HtmlDialog.new(dialog_title: 'SiteCraft Render AI', preferences_key: 'SiteCraftRenderAI', scrollable: true, resizable: true, width: 1280, height: 860, min_width: 860, min_height: 640, style: UI::HtmlDialog::STYLE_DIALOG)
      @dialog.set_file(File.join(__dir__, 'ui', 'ai.html'))
      @dialog.add_action_callback('sitecraft_ai') do |_context, raw|
        begin
          next unless current?(generation)
          raise 'Yêu cầu Render AI quá lớn.' unless raw.is_a?(String) && raw.bytesize <= MAX_MESSAGE
          message = JSON.parse(raw, max_nesting: 24)
          raise 'Lệnh Render AI không hợp lệ.' unless message.is_a?(Hash)
          invoke(message['id'], message['action'], message['args'] || {}, generation)
        rescue StandardError => error
          # Oversized/malformed envelopes may not contain a trusted request ID.
          # Do not log the raw message (it can contain image data or prompts).
          warn('SiteCraft Render AI: ' + error.message)
        end
      end
      @dialog.set_on_closed { closed(generation) }
      @dialog.show
    rescue StandardError => error
      UI.messagebox(error.message)
    end
  end
end
