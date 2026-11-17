# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'sketchup.rb'
require 'json'
require 'uri'
require_relative 'importer'
require_relative 'linking'
require_relative 'runtime'
require_relative 'local_http'

module OpenMapSketchUp
  module Core
    @requests = {}
    @contexts = {}
    @token = nil

    def self.mode
      # The old mode/server preferences could silently select an obsolete server
      # after installing Full. Only a choice made in the new UI enables remote.
      value = Sketchup.read_default('OpenMapSketchUp', 'runtime_mode', 'bundled').to_s
      %w[bundled remote].include?(value) ? value : 'bundled'
    end

    def self.managed?
      mode == 'bundled'
    end

    def self.base_url
      managed? ? Runtime.base_url : Sketchup.read_default('OpenMapSketchUp', 'server', 'http://127.0.0.1:8877')
    end

    def self.start_runtime
      return unless managed?
      executable = Sketchup.find_support_file('SketchUp.exe').to_s
      Runtime.start(File.join(__dir__, 'server'), executable.empty? ? nil : File.dirname(executable))
    end

    def self.valid_base!(raw)
      uri = URI.parse(raw)
      local = %w[127.0.0.1 localhost ::1 [::1]].include?(uri.host)
      unless uri.host && !uri.userinfo && !uri.query && !uri.fragment && ['', '/'].include?(uri.path) && (uri.scheme == 'https' || (uri.scheme == 'http' && local))
        raise 'Nhập URL HTTPS, hoặc http://127.0.0.1:8877 cho máy chủ cục bộ.'
      end
      raw.chomp('/')
    rescue URI::InvalidURIError
      raise 'URL máy chủ không hợp lệ.'
    end

    def self.settings
      @open_settings = true
      if @dialog && @dialog.visible?
        @dialog.execute_script('if(window.OpenMap && window.OpenMap.openSettings){window.OpenMap.openSettings();}')
      else
        show
      end
    rescue StandardError => error
      UI.messagebox(error.message)
    end

    def self.reply(id, result)
      if id == 'menu' && !result['ok']
        UI.messagebox(result['error'])
        return
      end
      return unless @dialog && @dialog.visible?
      @dialog.execute_script('window.OpenMap.receive(%s,%s)' % [JSON.generate(id), JSON.generate(result)])
    end

    def self.refresh_anchor
      @dialog.execute_script('if(window.OpenMap && window.OpenMap.refreshAnchor){window.OpenMap.refreshAnchor();}') if @dialog && @dialog.visible?
    end

    def self.http(method, path, body, extra_headers = {}, &callback)
      raise 'Bộ xử lý đang khởi động. Đợi thông báo sẵn sàng hoặc mở Cấu hình để thử lại.' if managed? && Runtime.status['state'] != 'ready'
      raise 'Đường dẫn API không hợp lệ.' unless path.is_a?(String) && path.bytesize <= 2048 && path =~ %r{\A/(?:api/[A-Za-z0-9_/?=&%.+\-]+|health)\z}
      raise 'Phương thức HTTP không hợp lệ.' unless %w[GET POST DELETE].include?(method)
      url = valid_base!(base_url) + path
      headers = { 'Content-Type' => 'application/json' }
      headers['X-OpenMap-Local'] = Runtime.transport_token if managed?
      headers['Authorization'] = 'Bearer ' + @token if @token
      if extra_headers['X-Flow-Secret'].is_a?(String) && extra_headers['X-Flow-Secret'].length <= 256
        headers['X-Flow-Secret'] = extra_headers['X-Flow-Secret']
      end
      encoded = body ? JSON.generate(body) : nil
      if managed?
        return LocalHTTP.start(url, method, headers, encoded, &callback)
      end
      methods = { 'GET' => Sketchup::Http::GET, 'POST' => Sketchup::Http::POST, 'DELETE' => Sketchup::Http::DELETE }
      request = Sketchup::Http::Request.new(url, methods[method])
      request.headers = headers
      request.body = encoded if encoded
      key = request.object_id
      @requests[key] = request
      request.start do |_req, response|
        @requests.delete(key)
        if response.nil? || response.status_code.to_i <= 0
          callback.call(nil, managed? ? 'Bộ xử lý cục bộ chưa phản hồi. Mở Cấu hình và bấm Khởi động lại.' : 'Không kết nối được máy chủ riêng. Kiểm tra URL trong Cấu hình.')
        elsif response.body && response.body.bytesize > 140_000_000
          callback.call(nil, 'Phản hồi quá lớn. Chia vùng thành mảnh nhỏ hơn.')
        else
          callback.call(response, nil)
        end
      end
    end

    def self.error_response(response, failure)
      return failure if failure
      return 'Không nhận được phản hồi HTTP hợp lệ. Mở Cấu hình để kiểm tra kết nối.' unless response && response.status_code.to_i > 0
      return nil if response.status_code.between?(200, 299)
      parsed = JSON.parse(response.body) rescue {}
      parsed['error'] || 'Máy chủ trả lỗi HTTP %d.' % response.status_code
    end

    def self.invoke(id, action, args)
      case action
      when 'config'
        reply(id, { 'ok' => true, 'data' => { 'server' => base_url, 'mode' => mode, 'version' => OpenMapSketchUp::VERSION, 'anchor' => Importer.anchor(Sketchup.active_model), 'session' => @auth_session, 'open_settings' => @open_settings } })
      when 'runtime_status'
        start_runtime if managed? && Runtime.status['state'] == 'idle'
        state = managed? ? Runtime.status : { 'state' => 'ready', 'progress' => 100, 'message' => 'Đang dùng máy chủ riêng' }
        reply(id, { 'ok' => true, 'data' => state.merge('mode' => mode) })
      when 'runtime_restart'
        raise 'Chỉ dùng khởi động lại cho bộ xử lý cục bộ.' unless managed?
        Runtime.stop
        @token = @auth_session = nil
        start_runtime
        reply(id, { 'ok' => true, 'data' => {} })
      when 'ack_settings'
        @open_settings = false
        reply(id, { 'ok' => true, 'data' => {} })
      when 'set_mode'
        target = args['mode']
        raise 'Chế độ bộ xử lý không hợp lệ.' unless %w[bundled remote].include?(target)
        if target == 'remote'
          url = valid_base!(args['server'].to_s.strip)
          Sketchup.write_default('OpenMapSketchUp', 'server', url)
        end
        Runtime.stop
        Sketchup.write_default('OpenMapSketchUp', 'runtime_mode', target)
        @token = @auth_session = nil
        reply(id, { 'ok' => true, 'data' => {} })
      when 'open_runtime_folder'
        path = Runtime.state_root.tr('\\', '/')
        FileUtils.mkdir_p(path)
        encoded = path.split('/').map { |part| URI::DEFAULT_PARSER.escape(part, /[^A-Za-z0-9\-._~:]/) }.join('/')
        UI.openURL('file:///' + encoded.sub(%r{\A/+}, ''))
        reply(id, { 'ok' => true, 'data' => {} })
      when 'settings'
        settings
        reply(id, { 'ok' => true, 'data' => {} })
      when 'session'
        token = args['access_token']
        raise 'Phiên đăng nhập không hợp lệ.' unless token.nil? || (token.is_a?(String) && token.bytesize.between?(1, 16_384) && token !~ /[\r\n]/)
        @token = token
        @auth_session = token ? args.select { |key, _value| %w[access_token refresh_token expires_at expires_in user].include?(key) } : nil
        reply(id, { 'ok' => true, 'data' => {} })
      when 'open_url'
        value = URI.parse(args['url'].to_s)
        raise 'Đường dẫn đăng nhập không hợp lệ.' unless value.scheme == 'https' && value.host && !value.userinfo && value.path == '/auth/v1/authorize'
        UI.openURL(value.to_s)
        reply(id, { 'ok' => true, 'data' => {} })
      when 'api'
        method, path, body = args['method'], args['path'], args['body']
        context = nil
        if method == 'POST' && path == '/api/jobs'
          raise 'Tham số bản đồ không hợp lệ.' unless body.is_a?(Hash)
          model = Sketchup.active_model
          body = body.merge('anchor' => Importer.anchor(model))
          context = { 'model' => model, 'anchor' => body['anchor'] }
        end
        http(method, path, body, args['headers'].is_a?(Hash) ? args['headers'] : {}) do |response, failure|
          begin
            error = error_response(response, failure)
            if error
              reply(id, { 'ok' => false, 'status' => response ? response.status_code : 0, 'error' => error })
            else
              data = JSON.parse(response.body)
              @contexts[data['id']] = context if context && data['id']
              reply(id, { 'ok' => true, 'data' => data })
            end
          rescue StandardError => error
            reply(id, { 'ok' => false, 'error' => error.message })
          end
        end
      when 'import', 'export', 'export_glb', 'preview'
        job_id = args['job_id'].to_s
        raise 'Mã tác vụ không hợp lệ.' unless job_id =~ /\A[a-f0-9]{32}\z/
        model = Sketchup.active_model
        context = @contexts[job_id]
        if action == 'import'
          raise 'Tác vụ không thuộc mô hình đang mở. Dựng lại mảnh trong mô hình này.' unless context && context['model'].equal?(model)
        end
        suffix = { 'import' => 'mesh', 'export' => 'export', 'export_glb' => 'glb', 'preview' => 'preview' }[action]
        http('GET', '/api/jobs/%s/%s' % [job_id, suffix], nil) do |response, failure|
          begin
            error = error_response(response, failure)
            raise error if error
            if action == 'import'
              raise 'Phiên đăng nhập đã kết thúc.' unless managed? || @token
              raise 'Bạn đã chuyển mô hình trong lúc tải. Quay lại mô hình ban đầu.' unless Sketchup.active_model.equal?(model)
              result = Importer.import!(model, JSON.parse(response.body, max_nesting: 32), job_id)
              reply(id, { 'ok' => true, 'data' => result })
            elsif action == 'preview'
              reply(id, { 'ok' => true, 'data' => JSON.parse(response.body, max_nesting: 32) })
            else
              extension = action == 'export_glb' ? '.glb' : '.zip'
              path = UI.savepanel(action == 'export_glb' ? 'Lưu GLB' : 'Lưu OBJ + ảnh + metadata', nil, 'OpenMap_%s%s' % [job_id[0, 8], extension])
              if path
                path += extension unless File.extname(path).downcase == extension
                File.binwrite(path, response.body)
                @last_export_dir = File.dirname(path)
              end
              reply(id, { 'ok' => true, 'data' => { 'saved' => !path.nil? } })
            end
          rescue StandardError => error
            reply(id, { 'ok' => false, 'error' => error.message })
          end
        end
      when 'save_skp'
        group = Sketchup.active_model.selection.find { |entity| (entity.is_a?(Sketchup::Group) || entity.is_a?(Sketchup::ComponentInstance)) && entity.get_attribute(Importer::DICTIONARY, 'job_id') }
        raise 'Chọn một nhóm OpenMap trước khi lưu SKP.' unless group
        path = UI.savepanel('Lưu mảnh OpenMap dạng SKP', nil, group.name + '.skp')
        if path
          path += '.skp' unless File.extname(path).downcase == '.skp'
          model = Sketchup.active_model
          model.start_operation('OpenMap — Metadata mảnh SKP', true)
          group.definition.set_attribute(Importer::DICTIONARY, 'anchor', group.get_attribute(Importer::DICTIONARY, 'anchor'))
          attribution = group.get_attribute(Importer::DICTIONARY, 'attribution') || group.definition.get_attribute(Importer::DICTIONARY, 'attribution')
          group.definition.set_attribute(Importer::DICTIONARY, 'attribution', attribution) if attribution
          model.commit_operation
          raise 'Không lưu được SKP.' unless group.definition.save_as(path)
          @last_export_dir = File.dirname(path)
        end
        reply(id, { 'ok' => true, 'data' => { 'saved' => !path.nil? } })
      when 'reset_anchor'
        model = Sketchup.active_model
        occupied = model.entities.any? { |entity| entity.respond_to?(:get_attribute) && entity.get_attribute(Importer::DICTIONARY, 'job_id') }
        raise 'Xóa các mảnh OpenMap đang có trước khi đặt lại mốc.' if occupied
        model.start_operation('OpenMap — Đặt lại mốc', true)
        model.delete_attribute(Importer::DICTIONARY, 'anchor')
        model.delete_attribute(Importer::DICTIONARY, 'frame')
        model.commit_operation
        reply(id, { 'ok' => true, 'data' => {} })
      when 'undo'
        Sketchup.undo
        reply(id, { 'ok' => true, 'data' => {} })
      when 'sync_shadow'
        lat, lon = args['lat'], args['lon']
        raise 'Tọa độ bóng nắng không hợp lệ.' unless Importer.finite_number?(lat, 80) && Importer.finite_number?(lon, 180)
        model = Sketchup.active_model
        model.start_operation('OpenMap — Đồng bộ bóng nắng', true)
        model.shadow_info['Latitude'] = lat
        model.shadow_info['Longitude'] = lon
        model.shadow_info['NorthAngle'] = 0
        model.commit_operation
        reply(id, { 'ok' => true, 'data' => {} })
      when 'open_folder'
        raise 'Lưu tệp xuất trước để mở thư mục.' unless @last_export_dir && File.directory?(@last_export_dir)
        encoded = @last_export_dir.tr('\\', '/').split('/').map { |part| URI::DEFAULT_PARSER.escape(part, /[^A-Za-z0-9\-._~:]/) }.join('/')
        UI.openURL('file:///' + encoded.sub(%r{\A/+}, ''))
        reply(id, { 'ok' => true, 'data' => {} })
      else
        raise 'Lệnh không được hỗ trợ.'
      end
    rescue StandardError => error
      reply(id, { 'ok' => false, 'error' => error.message })
    end

    def self.show
      start_runtime
      if @dialog && @dialog.visible?
        @dialog.bring_to_front
        return
      end
      @dialog = UI::HtmlDialog.new(dialog_title: 'OpenMap SketchUp', preferences_key: 'OpenMapSketchUp', scrollable: true, resizable: true, width: 1040, height: 860, min_width: 720, min_height: 600, style: UI::HtmlDialog::STYLE_DIALOG)
      @dialog.set_file(File.join(__dir__, 'ui', 'index.html'))
      @dialog.add_action_callback('openmap') do |_context, raw|
        begin
          raise 'Lệnh quá lớn.' unless raw.is_a?(String) && raw.bytesize <= 12_000_000
          message = JSON.parse(raw, max_nesting: 16)
          invoke(message['id'], message['action'], message['args'].is_a?(Hash) ? message['args'] : {})
        rescue StandardError => error
          warn('OpenMap: ' + error.message)
        end
      end
      @dialog.set_on_closed { @dialog = nil }
      @dialog.show
    end

    unless file_loaded?(__FILE__)
      menu = UI.menu('Extensions').add_submenu('OpenMap SketchUp')
      menu.add_item('Mở OpenMap') { show }
      menu.add_item('Cấu hình máy chủ') { settings }
      menu.add_item('Lưu mảnh đã chọn thành SKP') { invoke('menu', 'save_skp', {}) }
      command = UI::Command.new('OpenMap') { show }
      command.tooltip = 'OpenMap SketchUp'
      command.small_icon = command.large_icon = File.join(__dir__, 'ui', 'icon.png')
      toolbar = UI::Toolbar.new('OpenMap SketchUp')
      toolbar.add_item(command)
      toolbar.restore
      @toolbar = toolbar
      Linking.install
      Runtime.observe
      file_loaded(__FILE__)
    end
  end
end
