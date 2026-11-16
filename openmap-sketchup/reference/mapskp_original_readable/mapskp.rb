# ==============================================================================
# File: mapskp.rb (Đặt tại thư mục gốc Plugins của SketchUp)
# Plugin: MapSKP 3D for SketchUp v2.8.1 — Map Phẳng Z=0, Trám Đồi 3D, Auto-Update GitHub & Mã Giới Thiệu
# Version: 2.8.1 | Tác giả: HiepAI | Bản quyền: 2026
# Chuẩn tương thích: Ruby 2.2 -> 3.2 (SketchUp 2017 - 2026) | Cổng động nội bộ: 8807..8815
# ==============================================================================

require 'sketchup.rb'
require 'extensions.rb'

module MapSKP
  def self.consume_bat_pending_enable!(plugins_dir)
    local_app = ENV['LOCALAPPDATA'].to_s.tr('\\', '/')
    return false if local_app.empty?
    pend_fp = File.join(local_app, 'HiepAI_Studio', 'MapSKP', 'bat_pending_enable_v281.json')
    return false unless File.file?(pend_fp) && !File.symlink?(pend_fp) && File.size(pend_fp) <= 65_536

    require 'json'
    doc = JSON.parse(File.read(pend_fp, encoding: 'UTF-8')) rescue nil
    return false unless doc.is_a?(Hash) && (doc['plugins_dirs'].is_a?(Array) || doc['plugins_dirs'].is_a?(String))

    norm_dir = File.expand_path(plugins_dir.to_s).tr('\\', '/').chomp('/').downcase
    dirs = Array(doc['plugins_dirs']).map { |d| d.to_s.tr('\\', '/').chomp('/').downcase }
    return false unless dirs.include?(norm_dir)

    remaining = dirs.reject { |d| d == norm_dir }
    if remaining.empty?
      File.delete(pend_fp) rescue nil
    else
      doc['plugins_dirs'] = remaining
      File.write(pend_fp, JSON.generate(doc), mode: 'w:UTF-8') rescue nil
    end
    true
  rescue StandardError
    false
  end

  unless file_loaded?(__FILE__)
    @extension = SketchupExtension.new(
      'MapSKP 3D for SketchUp - Map Phẳng Z=0, Trám Đồi 3D & Khối Kiến Trúc',
      'mapskp/main'
    )
    @extension.description = 'Lấy ảnh vệ tinh 4K/8K, 2 chế độ Map Phẳng Z=0 & Trám Đồi Địa Hình 3D 2 lớp, Đường 2 cấp Google Street Map nổi phẳng, khối nhà tách Tag & tự động ghép khít mảnh mở rộng 0.0mm.'
    @extension.version     = '2.8.1'
    @extension.creator     = 'HiepAI'
    @extension.copyright   = '2026'

    Sketchup.register_extension(@extension, true)
    if consume_bat_pending_enable!(__dir__)
      if @extension.respond_to?(:loaded?) && !@extension.loaded?
        @extension.check if @extension.respond_to?(:check)
        Sketchup.require('mapskp/main') unless @extension.loaded?
      end
    end
    file_loaded(__FILE__)
  else
    # Khi người dùng cài đè gói .RBZ qua Extension Manager -> Install Extension... ngay trong phiên SketchUp đang mở:
    begin
      @extension.check if defined?(@extension) && @extension && @extension.respond_to?(:loaded?) && !@extension.loaded? && @extension.respond_to?(:check)
      boot_rb = File.join(__dir__, 'mapskp', 'runtime_bootstrap.rb')
      imp_rb  = File.join(__dir__, 'mapskp', 'map_importer.rb')
      main_rb = File.join(__dir__, 'mapskp', 'main.rb')
      if File.file?(main_rb)
        load(boot_rb) if File.file?(boot_rb)
        load(imp_rb)  if File.file?(imp_rb)
        load(main_rb)
        MapSKP::Bootstrap.consume_first_install_auto_open!(__dir__) if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.respond_to?(:consume_first_install_auto_open!)
        if defined?(MapSKP::Core)
          MapSKP::Core.ensure_toolbar_visible!(force_show: true) if MapSKP::Core.respond_to?(:ensure_toolbar_visible!)
          UI.start_timer(0.35, false) do
            begin
              MapSKP::Core.show_ui
            rescue StandardError => e
              MapSKP::Core.log_ruby_error('ReinstallAutoOpen', e) if MapSKP::Core.respond_to?(:log_ruby_error)
            end
          end
        end
      end
    rescue StandardError
      nil
    end
  end
end
