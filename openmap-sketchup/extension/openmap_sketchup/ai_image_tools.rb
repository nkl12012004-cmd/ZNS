# encoding: UTF-8
# SPDX-License-Identifier: MIT
# Local, user-masked cleanup. No model/camera changes or external AI requests.
require 'json'
require 'base64'
require 'uri'

module OpenMapSketchUp
  module AIImageTools
    API_PATH = %r{\A/api/ai/(?:assets(?:/[a-f0-9]{32})?|cleanup)\z}.freeze
    IMAGE_ID = /\A[a-f0-9]{32}\z/.freeze
    @generation = 0

    def self.visible?
      @dialog && @dialog.visible?
    end

    def self.current?(generation)
      generation == @generation && visible?
    end

    def self.reply(id, value, generation)
      return unless current?(generation)
      @dialog.execute_script('window.SiteCraftCleanup && window.SiteCraftCleanup.receive(%s,%s)' % [JSON.generate(id), JSON.generate(value)])
    end

    def self.request(method, path, body, generation, &callback)
      raise 'Công cụ ảnh cần bộ xử lý cục bộ của SiteCraft.' unless Core.managed?
      raise 'Bộ xử lý chưa sẵn sàng. Mở SiteCraft rồi thử lại.' unless Runtime.status['state'] == 'ready'
      raise 'Đường dẫn công cụ ảnh không hợp lệ.' unless %w[GET POST].include?(method) && path.is_a?(String) && path.match?(API_PATH)
      raise 'Tham số công cụ ảnh không hợp lệ.' unless body.nil? || body.is_a?(Hash)
      Core.http(method, path, body) do |response, failure|
        next unless current?(generation)
        begin
          error = Core.error_response(response, failure)
          raise error if error
          raise 'Phản hồi ảnh quá lớn.' unless response.body.is_a?(String) && response.body.bytesize <= AIRender::MAX_MESSAGE
          data = JSON.parse(response.body, max_nesting: 24)
          raise 'Phản hồi ảnh không hợp lệ.' unless data.is_a?(Hash)
        rescue StandardError => error
          data, failure = nil, error.message
        end
        callback.call(data, failure)
      end
    end

    def self.safe_base(name)
      value = name.to_s.tr('\\', '/').split('/').last.to_s.sub(/\.(png|jpe?g|webp)\z/i, '')
      value = value.gsub(/[^\p{L}\p{N}._ -]/, '_')[0, 80].to_s.sub(/[. ]+\z/, '').sub(/\A[. ]+/, '')
      value = 'SiteCraft_Image' if value.empty? || value.match?(/\A(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|\z)/i)
      value
    end

    def self.write_new(path, bytes)
      created = false
      begin
        File.open(path, File::WRONLY | File::CREAT | File::EXCL, 0o600) do |file|
          created = true
          file.binmode
          file.write(bytes)
          file.flush
          file.fsync
        end
      rescue StandardError
        File.delete(path) if created && File.file?(path)
        raise
      end
      path
    end

    def self.unique_path(directory, name, extension)
      base = safe_base(name) + '_cleaned'
      1000.times do |index|
        path = File.join(directory, base + (index.zero? ? '' : '_%d' % (index + 1)) + extension)
        return path unless File.exist?(path)
      end
      raise 'Thư mục có quá nhiều tệp trùng tên. Chọn thư mục khác.'
    end

    def self.save_image(id, args, generation)
      asset_id = args['asset_id']
      raise 'Mã ảnh không hợp lệ.' unless asset_id.is_a?(String) && asset_id.match?(IMAGE_ID)
      request('GET', '/api/ai/assets/' + asset_id, nil, generation) do |asset, failure|
        begin
          raise failure if failure
          bytes, extension = AIRender.decode_image(asset)
          suggestion = safe_base(args['name'] || asset['name']) + '_cleaned' + extension
          path = UI.savepanel('Lưu bản ảnh mới — không ghi đè', @last_directory, suggestion)
          if path
            path += extension unless File.extname(path).downcase == extension
            raise 'Tệp đã tồn tại. Chọn tên mới; công cụ không ghi đè ảnh gốc.' if File.exist?(path)
            write_new(path, bytes)
            @last_directory = File.dirname(path)
          end
          reply(id, { 'ok' => true, 'data' => { 'saved' => !path.nil? } }, generation)
        rescue StandardError => error
          reply(id, { 'ok' => false, 'error' => error.message }, generation)
        end
      end
    end

    def self.save_batch(id, args, generation)
      items = args['items']
      raise 'Chọn từ 1 đến 12 ảnh kết quả.' unless items.is_a?(Array) && items.length.between?(1, 12) && items.all? { |v| v.is_a?(Hash) && v['asset_id'].is_a?(String) && v['asset_id'].match?(IMAGE_ID) }
      directory = UI.select_directory(title: 'Chọn thư mục lưu các bản ảnh mới', directory: @last_directory)
      return reply(id, { 'ok' => true, 'data' => { 'saved' => 0, 'cancelled' => true, 'errors' => [] } }, generation) unless directory
      raise 'Thư mục đã chọn không tồn tại.' unless File.directory?(directory)
      @last_directory = directory
      saved, errors, index = 0, [], 0
      step = nil
      step = proc do
        next unless current?(generation)
        if index >= items.length
          reply(id, { 'ok' => true, 'data' => { 'saved' => saved, 'total' => items.length, 'errors' => errors } }, generation)
          next
        end
        item = items[index]
        index += 1
        request('GET', '/api/ai/assets/' + item['asset_id'], nil, generation) do |asset, failure|
          begin
            raise failure if failure
            bytes, extension = AIRender.decode_image(asset)
            path = unique_path(directory, item['name'] || asset['name'], extension)
            write_new(path, bytes)
            saved += 1
          rescue StandardError => error
            errors << { 'index' => index, 'error' => error.message }
          end
          begin
            step.call
          rescue StandardError => error
            reply(id, { 'ok' => false, 'error' => error.message }, generation)
          end
        end
      end
      step.call
    end

    def self.open_files(id, generation)
      filter = 'Image Files|*.png;*.jpg;*.jpeg;*.webp||'
      begin
        selected = UI.openpanel('Chọn ảnh để dọn vùng', @last_directory, filter, true)
      rescue ArgumentError
        selected = UI.openpanel('Chọn ảnh để dọn vùng', @last_directory, filter)
      end
      paths = Array(selected).compact
      raise 'Chọn tối đa 12 ảnh một lần.' if paths.length > 12
      return reply(id, { 'ok' => true, 'data' => { 'assets' => [] } }, generation) if paths.empty?
      @last_directory = File.dirname(paths.first)
      assets, index = [], 0
      step = nil
      step = proc do
        next unless current?(generation)
        if index >= paths.length
          reply(id, { 'ok' => true, 'data' => { 'assets' => assets } }, generation)
          next
        end
        path = paths[index]
        index += 1
        raise 'Ảnh quá lớn hoặc không đọc được.' unless File.file?(path) && File.size(path).between?(16, AIRender::MAX_IMAGE)
        bytes = File.binread(path)
        mime = bytes.start_with?("\x89PNG\r\n\x1a\n".b) ? 'image/png' : bytes.start_with?("\xff\xd8".b) ? 'image/jpeg' : 'image/webp'
        url = 'data:' + mime + ';base64,' + Base64.strict_encode64(bytes)
        AIRender.decode_image({ 'data_url' => url, 'mime' => mime })
        request('POST', '/api/ai/assets', { 'data_url' => url, 'name' => File.basename(path), 'role' => 'source' }, generation) do |asset, failure|
          if failure
            reply(id, { 'ok' => false, 'error' => failure }, generation)
          else
            assets << asset
            begin
              step.call
            rescue StandardError => error
              reply(id, { 'ok' => false, 'error' => error.message }, generation)
            end
          end
        end
      end
      step.call
    end

    def self.invoke(id, action, args, generation)
      raise 'Mã yêu cầu không hợp lệ.' unless id.is_a?(String) && id.bytesize.between?(1, 128)
      raise 'Tham số công cụ ảnh không hợp lệ.' unless args.is_a?(Hash)
      case action
      when 'config'
        reply(id, { 'ok' => true, 'data' => { 'managed' => Core.managed?, 'version' => OpenMapSketchUp::VERSION, 'initial_asset_id' => @initial_asset_id } }, generation)
      when 'api'
        request(args['method'], args['path'], args['body'], generation) do |data, error|
          reply(id, error ? { 'ok' => false, 'error' => error } : { 'ok' => true, 'data' => data }, generation)
        end
      when 'open_files' then open_files(id, generation)
      when 'save_image' then save_image(id, args, generation)
      when 'save_batch' then save_batch(id, args, generation)
      when 'close' then @dialog.close if current?(generation)
      else raise 'Lệnh công cụ ảnh không được hỗ trợ.'
      end
    rescue StandardError => error
      reply(id, { 'ok' => false, 'error' => error.message }, generation)
    end

    def self.show(asset_id = nil)
      asset_id = asset_id['asset_id'] if asset_id.is_a?(Hash)
      @initial_asset_id = asset_id.is_a?(String) && asset_id.match?(IMAGE_ID) ? asset_id : nil
      if visible?
        @dialog.bring_to_front
        @dialog.execute_script('window.SiteCraftCleanup && window.SiteCraftCleanup.openAsset(%s)' % JSON.generate(@initial_asset_id)) if @initial_asset_id
        return
      end
      Core.start_runtime
      @generation += 1
      generation = @generation
      @dialog = UI::HtmlDialog.new(dialog_title: 'SiteCraft — Dọn vùng ảnh cục bộ', preferences_key: 'SiteCraftImageCleanup', scrollable: true, resizable: true, width: 1120, height: 800, min_width: 800, min_height: 620, style: UI::HtmlDialog::STYLE_DIALOG)
      @dialog.set_file(File.join(__dir__, 'ui', 'ai-cleanup.html'))
      @dialog.add_action_callback('sitecraft_cleanup') do |_context, raw|
        begin
          next unless current?(generation)
          raise 'Yêu cầu quá lớn.' unless raw.is_a?(String) && raw.bytesize <= AIRender::MAX_MESSAGE
          message = JSON.parse(raw, max_nesting: 24)
          invoke(message['id'], message['action'], message['args'] || {}, generation)
        rescue StandardError => error
          warn('SiteCraft cleanup: ' + error.message)
        end
      end
      @dialog.set_on_closed do
        if generation == @generation
          @dialog = nil
          @generation += 1
        end
      end
      @dialog.show
    rescue StandardError => error
      UI.messagebox(error.message)
    end
  end
end
