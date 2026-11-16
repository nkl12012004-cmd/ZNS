# ==============================================================================
# File: mapskp/main.rb
# Plugin: MapSKP Hybrid v2.0.0 SaaS — Bản Đồ Vệ Tinh, Địa Hình DEM, Google 3D & Ghép Mảnh 0.0mm
# Chuẩn tương thích: Ruby 2.2 -> 3.2 (SketchUp 2017 - 2026) | Cổng động: 8807..8815
# ==============================================================================

require 'sketchup.rb'
require 'json'
require 'base64'
require 'fileutils'
require 'securerandom'
require 'tmpdir'
require 'uri'
Sketchup.require 'mapskp/runtime_bootstrap'
Sketchup.require 'mapskp/map_importer'

module MapSKP
  class DropLinkObserver < Sketchup::EntitiesObserver
    PLACE_COMPONENT_TOOL_ID = 21013

    def initialize
      @pending = []
      @timer_id = nil
      @wait_ticks = 0
      @settled_once = false
      @processing = false
    end

    def onElementAdded(_entities, element)
      return if @processing
      return unless element && element.valid?
      return unless element.is_a?(Sketchup::ComponentInstance)
      return if element.get_attribute("MapSKP_Meta", "linked", false)

      @pending << element unless @pending.include?(element)
      @wait_ticks = 0
      @settled_once = false
      start_watch_timer!
    end

    def start_watch_timer!
      return if @timer_id
      @timer_id = UI.start_timer(0.12, true) do
        poll_drop_completion!
      end
    end

    def stop_watch_timer!
      if @timer_id
        UI.stop_timer(@timer_id)
        @timer_id = nil
      end
    end

    def poll_drop_completion!
      model = Sketchup.active_model
      unless model
        @pending.clear
        stop_watch_timer!
        return
      end

      # Chờ người dùng click đặt xong file .skp xuống mặt nền SketchUp (nếu đang giữ chuột kéo thả)
      active_tool = model.tools ? model.tools.active_tool_id.to_i : 0
      if active_tool == PLACE_COMPONENT_TOOL_ID && @wait_ticks < 300
        @wait_ticks += 1
        @settled_once = false
        return
      end

      unless @settled_once
        @settled_once = true
        return
      end

      stop_watch_timer!
      items = @pending.dup
      @pending.clear
      if (defined?(MapSKP::Bootstrap) && (MapSKP::Bootstrap.recovery_required_latched? || MapSKP::Bootstrap.pending_restart_info["pending_restart"])) ||
         (defined?(MapSKP::Core) && MapSKP::Core.mandatory_update_locked?)
        return
      end
      @processing = true
      begin
        items.each do |inst|
          next unless inst && inst.valid?
          res = MapSKP::Importer.link_dropped_instance!(model, inst)
          if res && res["ok"]
            MapSKP::Core.notify_drop_linked(res)
          end
        end
      rescue StandardError => e
        MapSKP::Core.log_ruby_error("DropLinkObserver", e)
      ensure
        @processing = false
      end
    end
  end

  class AppLinkObserver < Sketchup::AppObserver
    def onNewModel(model)
      MapSKP::Core.on_model_switched(model)
    end

    def onOpenModel(model)
      MapSKP::Core.on_model_switched(model)
    end

    def onActivateModel(model)
      MapSKP::Core.on_model_switched(model)
    end

    def onQuit
      MapSKP::Bootstrap.shutdown_bridge_on_quit!
    end
  end

  module Core
    remove_const(:CORE_VERSION) if const_defined?(:CORE_VERSION)
    CORE_VERSION = "2.8.1"
    CORE_BUILD_NUMBER = 20801 unless const_defined?(:CORE_BUILD_NUMBER)
    MAX_CALLBACK_JSON_BYTES = 262_144 unless const_defined?(:MAX_CALLBACK_JSON_BYTES)
    MAX_OCR_PICK_BYTES      = 15 * 1024 * 1024 unless const_defined?(:MAX_OCR_PICK_BYTES)

    @dialog ||= nil
    @toolbar ||= nil
    @dialog_centered_in_session ||= false
    @app_observer ||= nil
    @observed_models ||= {}
    @ui_session_gen ||= 0
    @init_poll_timer_id ||= nil
    @mandatory_update_locked ||= false
    @pending_restart_locked ||= false
    @recovery_required_locked ||= false

    def self.toolbar
      @toolbar
    end

    def self.register_toolbar(tb)
      @toolbar = tb
    end

    def self.ensure_toolbar_visible!(force_show: false)
      tb = @toolbar
      return false unless tb
      never_shown = defined?(::TB_NEVER_SHOWN) ? ::TB_NEVER_SHOWN : -1
      last_st = tb.respond_to?(:get_last_state) ? tb.get_last_state.to_i : never_shown
      if (force_show || last_st == never_shown) && tb.respond_to?(:show)
        tb.show
        true
      elsif tb.respond_to?(:restore)
        tb.restore
        true
      else
        false
      end
    rescue StandardError
      false
    end

    def self.ui_session_gen
      (@ui_session_gen || 0).to_i
    end

    def self.mandatory_update_locked?
      @mandatory_update_locked == true
    end

    def self.latch_mandatory_update_lock!(reason = "")
      @mandatory_update_locked = true
      @mandatory_update_reason = reason.to_s
    end

    def self.reset_locks_for_test!
      @mandatory_update_locked = false
      @pending_restart_locked = false
      @recovery_required_locked = false
    end

    def self.current_model_token(model = nil)
      mdl = model || (defined?(Sketchup) ? Sketchup.active_model : nil)
      return "" unless mdl && (!mdl.respond_to?(:valid?) || mdl.valid?)
      guid_str = mdl.respond_to?(:guid) ? mdl.guid.to_s.gsub(/[^A-Za-z0-9_\-]/, "") : ""
      "mdl_#{mdl.object_id}_#{guid_str}"
    rescue StandardError
      ""
    end

    def self.on_model_switched(model)
      attach_model_observer(model)
      return unless @dialog && @dialog.visible?
      send_js("window.onMapSKPModelChanged", {
        "model_token"  => current_model_token(model),
        "geo"          => current_model_geo_state,
        "anchor_state" => MapSKP::Importer.scan_anchor_state(model)
      })
    rescue StandardError
      nil
    end

    def self.parse_callback_json(raw_str, max_bytes = MAX_CALLBACK_JSON_BYTES)
      s = raw_str.to_s
      raise "CALLBACK_PAYLOAD_TOO_LARGE" if s.bytesize > max_bytes
      JSON.parse(s, max_nesting: 24)
    end

    def self.session_dirs
      dirs = []
      appdata = ENV["APPDATA"].to_s
      dirs << File.join(appdata, "HiepAI_MapSKP", "live_session") unless appdata.empty?
      dirs << File.join(Dir.tmpdir, "HiepAI_MapSKP", "live_session")
      dirs.uniq
    end

    def self.ensure_latest_modules
      @loaded_module_mtimes ||= {}
      ["runtime_bootstrap.rb", "map_importer.rb"].each do |fn|
        fpath = File.join(__dir__, fn)
        next unless File.exist?(fpath)
        cur_mt = (File.mtime(fpath).to_r rescue nil)
        if !@loaded_module_mtimes.key?(fpath)
          @loaded_module_mtimes[fpath] = cur_mt
        elsif @loaded_module_mtimes[fpath] != cur_mt
          load(fpath)
          @loaded_module_mtimes[fpath] = cur_mt
        end
      end
    end

    def self.attach_model_observer(model)
      return unless model && model.valid?
      mid = model.object_id
      return if @observed_models[mid]

      obs = MapSKP::DropLinkObserver.new
      model.entities.add_observer(obs)
      @observed_models[mid] = obs
    rescue StandardError
      nil
    end

    def self.ensure_global_observers!
      unless @app_observer
        @app_observer = MapSKP::AppLinkObserver.new
        Sketchup.add_observer(@app_observer)
      end
      attach_model_observer(Sketchup.active_model)
    rescue StandardError
      nil
    end

    def self.notify_drop_linked(res)
      if res["anchor_state"]
        send_js("window.onMapSKPAnchorUpdated", res["anchor_state"])
      end
      send_js("window.onMapSKPToast", {
        "kind"    => "success",
        "message" => res["message"].to_s
      })
    end

    def self.log_ruby_error(ctx_label, err)
      bt = (err.backtrace || []).first(6).join("\n")
      msg = "[#{Time.now.strftime('%H:%M:%S')}] #{ctx_label}: #{err.class} — #{err.message}\n#{bt}\n"
      session_dirs.first(2).each do |dir|
        begin
          FileUtils.mkdir_p(dir)
          File.open(File.join(dir, "ruby_error.log"), "a:UTF-8") { |f| f.puts(msg) }
        rescue StandardError
          nil
        end
      end
      send_js("window.onMapSKPToast", {
        "kind"    => "error",
        "message" => "Lỗi Ruby (#{ctx_label}): #{err.message}"
      })
    end

    def self.ensure_bridge_server
      bridge_dir = File.join(__dir__, "bridge")
      MapSKP::Bootstrap.ensure_bridge_running!(bridge_dir, Process.pid)
    end

    def self.send_js(fn_name, payload_obj)
      return unless @dialog && @dialog.visible?
      json_str = JSON.generate(payload_obj)
      @dialog.execute_script("#{fn_name}(#{json_str});")
    rescue StandardError
      nil
    end

    def self.current_model_geo_state
      su_dir = MapSKP::Bootstrap.sketchup_exe_dir rescue ""
      su_ver = Sketchup.version.to_s rescue ""
      model = Sketchup.active_model
      return { "has_model" => false, "su_version" => su_ver, "su_exe_dir" => su_dir } unless model

      si = model.respond_to?(:shadow_info) ? model.shadow_info : nil
      geo_ref = model.respond_to?(:get_attribute) ? model.get_attribute("GeoReference", "GeoReferenced", false) : false
      {
        "has_model"      => true,
        "su_version"     => su_ver,
        "su_exe_dir"     => su_dir,
        "geo_referenced" => (geo_ref ? true : false),
        "lat"            => si ? si["Latitude"].to_f : 21.028511,
        "lon"            => si ? si["Longitude"].to_f : 105.854444,
        "tz_offset"      => si ? si["TZOffset"].to_f : 7.0
      }
    rescue StandardError
      { "has_model" => false, "su_version" => (Sketchup.version.to_s rescue ""), "su_exe_dir" => "" }
    end

    def self.strict_allowed_external_url?(raw_url)
      clean = raw_url.to_s.strip
      return false if clean.empty? || clean.include?("\0") || clean =~ /[\r\n\t\s]/
      # Cấm tuyệt đối cú pháp userinfo chứa @ phía trước dấu / đầu tiên của path (ví dụ https://accounts.google.com@evil.com)
      authority_part = clean.sub(/\Ahttps?:\/\//i, "").split("/", 2).first.to_s
      return false if authority_part.include?("@")

      uri = URI.parse(clean)
      return false unless uri.is_a?(URI::HTTP) || uri.is_a?(URI::HTTPS)
      return false unless uri.userinfo.nil?
      host = uri.host.to_s.downcase
      return false if host.empty?
      raw_path_low = uri.path.to_s.downcase
      return false if raw_path_low.include?("..") || raw_path_low.include?("%2e") || raw_path_low.include?("%5c") || raw_path_low.include?("\\")

      if uri.scheme == "https"
        return false unless uri.port.nil? || uri.port == 443
        return true if ["accounts.google.com", "hiepd5.com", "www.hiepd5.com", "api.hiepd5.com"].include?(host)
        if host == "github.com"
          path_norm = uri.path.to_s.downcase
          return true if path_norm.start_with?("/hiepd5/") && !path_norm.include?("..") && !path_norm.include?("%2f")
        end
        return false
      elsif uri.scheme == "http"
        act_port = MapSKP::Bootstrap.active_port.to_i
        return false unless host == "127.0.0.1" && act_port > 0 && uri.port.to_i == act_port
        return raw_path_low.start_with?("/api/saas/google")
      end
      false
    rescue StandardError
      false
    end

    def self.mtl_references_safe?(mtl_txt, expected_maps_dir_name)
      prefix_low = "#{expected_maps_dir_name.to_s.downcase}/"
      mtl_txt.to_s.each_line do |line|
        s = line.strip
        next if s.empty? || s.start_with?("#")
        if s =~ /\A(?:map_[A-Za-z0-9_]+|bump|disp|decal|refl)\s+(.+)\z/i
          ref = Regexp.last_match(1).to_s.strip.tr("\\", "/")
          return false if ref.include?("\0") || ref.include?(":") || ref.start_with?("/") || ref.split("/").include?("..")
          return false unless ref.downcase.start_with?(prefix_low)
          leaf = ref[prefix_low.length..-1].to_s
          return false if leaf.empty? || leaf.include?("/") || leaf == "." || leaf == ".."
        end
      end
      true
    end

    def self.extract_mtl_map_leaves(mtl_txt, expected_maps_dir_name)
      prefix_low = "#{expected_maps_dir_name.to_s.downcase}/"
      leaves = []
      mtl_txt.to_s.each_line do |line|
        s = line.strip
        next if s.empty? || s.start_with?("#")
        if s =~ /\A(?:map_[A-Za-z0-9_]+|bump|disp|decal|refl)\s+(.+)\z/i
          ref = Regexp.last_match(1).to_s.strip.tr("\\", "/")
          if ref.downcase.start_with?(prefix_low)
            leaf = ref[prefix_low.length..-1].to_s
            leaves << leaf unless leaf.empty? || leaves.include?(leaf)
          end
        end
      end
      leaves
    end

    def self.rewrite_mtl_maps_prefix(mtl_txt, old_maps_dir_name, new_maps_dir_name)
      prefix_low = "#{old_maps_dir_name.to_s.downcase}/"
      out_lines = []
      mtl_txt.to_s.each_line do |raw_line|
        ending = raw_line.end_with?("\r\n") ? "\r\n" : (raw_line.end_with?("\n") ? "\n" : "")
        body = raw_line.chomp
        if body =~ /\A(\s*(?:map_[A-Za-z0-9_]+|bump|disp|decal|refl)\s+)(.+)\z/i
          head = Regexp.last_match(1)
          ref = Regexp.last_match(2).to_s.strip.tr("\\", "/")
          if ref.downcase.start_with?(prefix_low)
            leaf = ref[prefix_low.length..-1].to_s
            out_lines << "#{head}#{new_maps_dir_name}/#{leaf}#{ending}"
            next
          end
        end
        out_lines << raw_line
      end
      out_lines.join
    end

    def self.execute_atomic_export_copy!(src, ext, dest, conflict_policy: :prompt, &test_hook)
      ext_clean = ext.to_s.downcase
      unless %w[obj glb skp].include?(ext_clean)
        return { "ok" => false, "error_code" => "INVALID_FORMAT", "error" => "Định dạng lưu không hợp lệ." }
      end
      if src.to_s.strip.empty? || !MapSKP::Importer.safe_export_path?(src, [".#{ext_clean}"]) || File.symlink?(src) || !File.file?(src)
        return { "ok" => false, "error_code" => "INVALID_SOURCE_PATH", "error" => "Không tìm thấy tệp nguồn hợp lệ trong thư mục xuất để lưu bản sao." }
      end

      dest_str = dest.to_s.strip
      return { "ok" => false, "error_code" => "EMPTY_DEST", "error" => "Chưa chọn đường dẫn đích." } if dest_str.empty?
      dest_str = "#{dest_str}.#{ext_clean}" unless dest_str.downcase.end_with?(".#{ext_clean}")
      if dest_str.include?("\0") || File.symlink?(dest_str) || (File.exist?(dest_str) && File.directory?(dest_str))
        return { "ok" => false, "error_code" => "UNSAFE_DEST_PATH", "error" => "Đường dẫn đích không hợp lệ hoặc là liên kết mềm (symlink)." }
      end
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.respond_to?(:path_has_reparse_ancestor?) &&
         MapSKP::Bootstrap.path_has_reparse_ancestor?(dest_str)
        return { "ok" => false, "error_code" => "DEST_REPARSE_ANCESTOR", "error" => "Thư mục đích nằm dưới liên kết mềm (junction/reparse point) không an toàn." }
      end
      if File.expand_path(src).casecmp(File.expand_path(dest_str)).zero?
        return { "ok" => false, "error_code" => "SAME_SRC_AND_DEST", "error" => "Đường dẫn đích không được trùng với tệp nguồn nội bộ." }
      end

      dst_dir  = File.dirname(dest_str)
      dst_stem = File.basename(dest_str, File.extname(dest_str))
      dst_mtl  = File.join(dst_dir, "#{dst_stem}.mtl")
      dst_maps = File.join(dst_dir, "#{dst_stem}_maps")

      src_mtl       = nil
      src_maps      = nil
      rewritten_obj = nil
      rewritten_mtl = nil
      map_src_files = []

      if ext_clean == "obj"
        cand_mtl  = src.sub(/\.obj\z/i, ".mtl")
        cand_maps = src.sub(/\.obj\z/i, "_maps")
        expected_old_maps = File.basename(cand_maps)

        obj_bytes = File.binread(src)
        obj_txt = obj_bytes.dup.force_encoding("UTF-8")
        unless obj_txt.valid_encoding?
          return { "ok" => false, "error_code" => "INVALID_OBJ_ENCODING", "error" => "Tệp .OBJ nguồn không đúng bảng mã UTF-8." }
        end
        obj_mentions_mtl = !(obj_txt =~ /^\s*mtllib\s+.+$/i).nil?

        if obj_mentions_mtl || File.exist?(cand_mtl) || File.symlink?(cand_mtl)
          if !MapSKP::Importer.safe_export_path?(cand_mtl, [".mtl"]) || File.symlink?(cand_mtl) || !File.file?(cand_mtl)
            return { "ok" => false, "error_code" => "MISSING_OR_UNSAFE_MTL", "error" => "Thiếu tệp vật liệu .MTL đi kèm hoặc .MTL nằm ngoài vùng xuất an toàn." }
          end
          src_mtl = cand_mtl
          mtl_bytes = File.binread(src_mtl)
          mtl_txt = mtl_bytes.dup.force_encoding("UTF-8")
          unless mtl_txt.valid_encoding?
            return { "ok" => false, "error_code" => "INVALID_MTL_ENCODING", "error" => "Tệp .MTL nguồn không đúng bảng mã UTF-8." }
          end
          unless mtl_references_safe?(mtl_txt, expected_old_maps)
            return { "ok" => false, "error_code" => "UNSAFE_MTL_REFERENCE", "error" => "Đã hủy lưu: Tệp .MTL chứa đường dẫn tham chiếu ngoài thư mục ảnh _maps an toàn." }
          end

          ref_leaves = extract_mtl_map_leaves(mtl_txt, expected_old_maps)
          if !ref_leaves.empty? || File.exist?(cand_maps) || File.symlink?(cand_maps)
            if !MapSKP::Importer.safe_export_path?(cand_maps) || File.symlink?(cand_maps) || !File.directory?(cand_maps)
              return { "ok" => false, "error_code" => "MISSING_OR_UNSAFE_MAPS_DIR", "error" => "Đã hủy lưu: Thiếu hoặc không hợp lệ thư mục ảnh vật liệu _maps đi kèm." }
            end
            src_maps = cand_maps
            ref_leaves.each do |leaf|
              tf = File.join(src_maps, leaf)
              if File.symlink?(tf) || !File.file?(tf) || !MapSKP::Importer.safe_export_path?(tf, [".png", ".jpg", ".jpeg", ".webp", ".bmp"])
                return { "ok" => false, "error_code" => "MISSING_REFERENCED_MAP_ASSET", "error" => "Đã hủy lưu: Thiếu tệp ảnh vật liệu được tham chiếu trong .MTL (#{leaf})." }
              end
              map_src_files << tf unless map_src_files.include?(tf)
            end
            Dir.entries(src_maps).each do |entry|
              next if entry == "." || entry == ".."
              tf = File.join(src_maps, entry)
              if File.symlink?(tf) || !File.file?(tf) || !MapSKP::Importer.safe_export_path?(tf, [".png", ".jpg", ".jpeg", ".webp", ".bmp"])
                return { "ok" => false, "error_code" => "UNSAFE_EXTRA_MAP_ASSET", "error" => "Đã hủy lưu: Thư mục _maps chứa tệp không an toàn (#{entry})." }
              end
              map_src_files << tf unless map_src_files.include?(tf)
            end
          end

          new_maps_name = "#{dst_stem}_maps"
          rewritten_mtl = rewrite_mtl_maps_prefix(mtl_txt, expected_old_maps, new_maps_name)
          rewritten_obj = obj_txt.gsub(/^(\s*mtllib\s+).+$/i) { "#{Regexp.last_match(1)}#{dst_stem}.mtl" }
        else
          rewritten_obj = obj_txt
        end

        if src_mtl && (File.symlink?(dst_mtl) || (File.exist?(dst_mtl) && File.directory?(dst_mtl)))
          return { "ok" => false, "error_code" => "DEST_MTL_CONFLICT", "error" => "Đã hủy lưu: Tệp đích #{File.basename(dst_mtl)} là symlink hoặc thư mục." }
        end
        if !map_src_files.empty? && (File.symlink?(dst_maps) || (File.exist?(dst_maps) && !File.directory?(dst_maps)))
          return { "ok" => false, "error_code" => "DEST_MAPS_CONFLICT", "error" => "Đã hủy lưu: Đường dẫn #{File.basename(dst_maps)} bị chiếm bởi symlink hoặc tệp đơn." }
        end

        sidecar_exists = (src_mtl && File.exist?(dst_mtl)) || (!map_src_files.empty? && File.exist?(dst_maps))
        if sidecar_exists
          case conflict_policy
          when :abort
            return { "ok" => false, "error_code" => "SIDECAR_CONFLICT_ABORTED", "error" => "Đã hủy lưu để bảo vệ tệp .MTL / _maps sẵn có tại thư mục đích." }
          when :prompt
            ans = UI.messagebox(
              "Thư mục đích đã có sẵn tệp vật liệu đi kèm (#{File.basename(dst_mtl)} hoặc #{File.basename(dst_maps)}).\nBạn có muốn ghi đè đồng bộ trọn bộ .OBJ + .MTL + _maps không?",
              MB_YESNO
            )
            if ans != IDYES
              return { "ok" => false, "error_code" => "USER_CANCELLED_SIDECAR_OVERWRITE", "cancelled" => true, "error" => "Đã hủy lưu theo lựa chọn của người dùng." }
            end
          when :overwrite
            nil
          else
            return { "ok" => false, "error_code" => "INVALID_CONFLICT_POLICY", "error" => "Chính sách xử lý trùng tệp không hợp lệ." }
          end
        end
      end

      FileUtils.mkdir_p(dst_dir)
      if File.symlink?(dst_dir)
        return { "ok" => false, "error_code" => "UNSAFE_DEST_DIR", "error" => "Thư mục đích không được là symlink." }
      end

      tx_dir = File.join(dst_dir, ".mapskp_save_tx_#{Process.pid}_#{SecureRandom.hex(6)}")
      tx_stage_dir  = File.join(tx_dir, "stage")
      tx_backup_dir = File.join(tx_dir, "backup")
      moved_backups = []
      placed_targets = []

      begin
        Dir.mkdir(tx_dir, 0o700)
        Dir.mkdir(tx_stage_dir, 0o700)
        Dir.mkdir(tx_backup_dir, 0o700)

        staged_main = File.join(tx_stage_dir, File.basename(dest_str))
        if ext_clean == "obj"
          File.binwrite(staged_main, rewritten_obj.b)
          if src_mtl && rewritten_mtl
            File.binwrite(File.join(tx_stage_dir, File.basename(dst_mtl)), rewritten_mtl.b)
          end
          unless map_src_files.empty?
            staged_maps_dir = File.join(tx_stage_dir, File.basename(dst_maps))
            Dir.mkdir(staged_maps_dir, 0o700)
            map_src_files.each do |tf|
              raise "SOURCE_MAP_TAMPERED" if File.symlink?(tf) || !File.file?(tf) || !MapSKP::Importer.safe_export_path?(tf, [".png", ".jpg", ".jpeg", ".webp", ".bmp"])
              FileUtils.cp(tf, File.join(staged_maps_dir, File.basename(tf)))
            end
          end
        else
          FileUtils.cp(src, staged_main)
        end

        unless MapSKP::Importer.safe_export_path?(src, [".#{ext_clean}"]) && !File.symlink?(src) && File.file?(src)
          raise "SOURCE_TAMPERED_DURING_STAGE: Tệp nguồn đã thay đổi trạng thái trong lúc chuẩn bị lưu."
        end

        test_hook.call(:after_stage, tx_stage_dir) if test_hook

        targets_plan = [[staged_main, dest_str, "main"]]
        if ext_clean == "obj"
          targets_plan << [File.join(tx_stage_dir, File.basename(dst_mtl)), dst_mtl, "mtl"] if src_mtl && rewritten_mtl
          targets_plan << [File.join(tx_stage_dir, File.basename(dst_maps)), dst_maps, "maps"] unless map_src_files.empty?
        end

        targets_plan.each do |_st_src, final_dst, slot_key|
          raise "DEST_SYMLINK_DETECTED" if File.symlink?(final_dst)
          if File.exist?(final_dst)
            bak_slot = File.join(tx_backup_dir, slot_key)
            File.rename(final_dst, bak_slot)
            moved_backups << [bak_slot, final_dst]
          end
        end

        targets_plan.each_with_index do |(st_src, final_dst, slot_key), idx|
          test_hook.call(:before_swap_item, slot_key, idx) if test_hook
          File.rename(st_src, final_dst)
          placed_targets << final_dst
        end

        FileUtils.rm_rf(tx_dir) if Dir.exist?(tx_dir) && !File.symlink?(tx_dir)
        {
          "ok"   => true,
          "dest" => dest_str.tr("\\", "/")
        }
      rescue StandardError => e
        placed_targets.reverse_each do |p_dst|
          begin
            if File.symlink?(p_dst)
              File.unlink(p_dst)
            elsif File.directory?(p_dst)
              FileUtils.rm_rf(p_dst)
            elsif File.exist?(p_dst)
              File.delete(p_dst)
            end
          rescue StandardError
            nil
          end
        end
        moved_backups.reverse_each do |(bak_slot, orig_dst)|
          begin
            File.rename(bak_slot, orig_dst) if File.exist?(bak_slot) && !File.exist?(orig_dst)
          rescue StandardError
            nil
          end
        end
        begin
          FileUtils.rm_rf(tx_dir) if Dir.exist?(tx_dir) && !File.symlink?(tx_dir)
        rescue StandardError
          nil
        end
        {
          "ok"          => false,
          "rolled_back" => true,
          "error_code"  => "SAVE_TRANSACTION_ROLLED_BACK",
          "error"       => e.message.to_s
        }
      end
    end

    def self.save_export_copy_dialog(payload)
      raise "INVALID_SAVE_PAYLOAD" unless payload.is_a?(Hash)
      src = payload["source_path"].to_s.strip
      fmt = payload["format"].to_s.downcase
      slug = payload["slug"].to_s.strip.gsub(/[^\p{L}\p{N}_\- ]/u, "")[0, 120]
      slug = "MapSKP_Context" if slug.empty?

      ext = fmt == "obj" ? "obj" : (fmt == "glb" ? "glb" : "skp")
      if src.empty? || !MapSKP::Importer.safe_export_path?(src, [".#{ext}"]) || File.symlink?(src) || !File.file?(src)
        send_js("window.onMapSKPToast", { "kind" => "error", "message" => "Không tìm thấy tệp nguồn hợp lệ trong thư mục xuất để lưu bản sao." })
        return
      end

      filter = ext == "obj" ? "Wavefront OBJ (*.obj)|*.obj||" : (ext == "glb" ? "glTF Binary (*.glb)|*.glb||" : "SketchUp Model (*.skp)|*.skp||")
      dest = UI.savepanel("Lưu mô hình MapSKP (.#{ext.upcase})", "", "#{slug}.#{ext}", filter)
      return unless dest && !dest.empty?

      res = execute_atomic_export_copy!(src, ext, dest, conflict_policy: :prompt)
      if res["cancelled"]
        send_js("window.onMapSKPToast", { "kind" => "info", "message" => res["error"].to_s })
      elsif res["ok"]
        extra_note = ext == "skp" ? " (Đã nhúng khóa tọa độ: kéo thả xuống nền SketchUp sẽ tự khớp với Mảnh #1)" : ""
        send_js("window.onMapSKPToast", {
          "kind"    => "success",
          "message" => "Đã lưu: #{res['dest']}#{extra_note}"
        })
      else
        send_js("window.onMapSKPToast", {
          "kind"    => "error",
          "message" => res["error"].to_s
        })
      end
      res
    end

    def self.stop_init_poll_timer!
      if @init_poll_timer_id
        begin
          UI.stop_timer(@init_poll_timer_id)
        rescue StandardError
          nil
        end
        @init_poll_timer_id = nil
      end
    end

    def self.emit_init_ready_payload!(cur_gen, st)
      bridge_ok = st.is_a?(Hash) && st["alive"] == true && st["ipc_token"].to_s.bytesize >= 32 && st["pid"].to_i > 0
      @pending_restart_locked   = (st.is_a?(Hash) && st["pending_restart"] == true)
      @recovery_required_locked = (st.is_a?(Hash) && st["recovery_required"] == true)
      pend_info_doc = nil
      if st.is_a?(Hash)
        pend_info_doc = st["pending_info"] || (@pending_restart_locked ? { "target_version" => st["pending_target_version"].to_s } : nil)
      end
      active_mdl = Sketchup.active_model
      send_js("window.onMapSKPReady", {
        "ok"                => bridge_ok,
        "session_gen"       => cur_gen,
        "bridge_alive"      => bridge_ok,
        "port"              => (bridge_ok ? st["port"] : nil),
        "pid"               => (bridge_ok ? st["pid"].to_i : 0),
        "ipc_token"         => (bridge_ok ? st["ipc_token"].to_s : ""),
        "model_token"       => current_model_token(active_mdl),
        "pending_restart"   => @pending_restart_locked,
        "pending_info"      => pend_info_doc,
        "recovery_required" => @recovery_required_locked,
        "error_code"        => (bridge_ok ? "" : (st.is_a?(Hash) && st["error_code"] ? st["error_code"].to_s : "BRIDGE_START_FAILED")),
        "error"             => (bridge_ok ? "" : (st.is_a?(Hash) && st["error"] ? st["error"].to_s : "Không thể khởi động cầu nối MapSKP an toàn.")),
        "runtime_source"    => (st.is_a?(Hash) ? st["runtime_source"] : "none"),
        "geo"               => current_model_geo_state,
        "anchor_state"      => MapSKP::Importer.scan_anchor_state(active_mdl)
      })
    end

    def self.emit_init_exception_payload!(cur_gen, err_obj)
      send_js("window.onMapSKPReady", {
        "ok"           => false,
        "session_gen"  => cur_gen,
        "bridge_alive" => false,
        "pid"          => 0,
        "ipc_token"    => "",
        "model_token"  => current_model_token(Sketchup.active_model),
        "error_code"   => "INIT_EXCEPTION",
        "error"        => err_obj.message.to_s
      })
      log_ruby_error("mapskp_init", err_obj)
    end

    def self.validate_import_gate!(manifest, active_model)
      raise "INVALID_MANIFEST" unless manifest.is_a?(Hash)
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.recovery_required_latched?
        return {
          "ok"         => false,
          "error_code" => "RECOVERY_REQUIRED",
          "error"      => "Plugin đang ở trạng thái chờ cài lại gói .RBZ sạch. Đã chặn tự động nạp để bảo vệ bản vẽ."
        }
      end
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.pending_restart_info["pending_restart"]
        return {
          "ok"         => false,
          "error_code" => "PENDING_RESTART_LOCKED",
          "error"      => "Bản cập nhật mới đang chờ khởi động lại SketchUp để kích hoạt. Vui lòng khởi động lại SketchUp trước khi nạp mô hình."
        }
      end
      if mandatory_update_locked?
        return {
          "ok"         => false,
          "error_code" => "MANDATORY_UPDATE_REQUIRED",
          "error"      => "Phiên bản hiện tại bắt buộc cập nhật lên bản mới nhất trước khi sử dụng hoặc nạp mô hình."
        }
      end

      exp_gen = manifest["expected_session_gen"]
      if !exp_gen.is_a?(Integer) || exp_gen != (@ui_session_gen || 0).to_i
        return {
          "ok"         => false,
          "error_code" => "STALE_UI_SESSION",
          "error"      => "Phiên giao diện đã thay đổi trong lúc xử lý. Đã hủy tự động nạp mô hình cũ để tránh nhầm phiên."
        }
      end

      cur_mdl_tok = current_model_token(active_model)
      exp_mdl_tok = manifest["expected_model_token"].to_s
      if cur_mdl_tok.empty? || exp_mdl_tok.empty? || exp_mdl_tok != cur_mdl_tok
        return {
          "ok"         => false,
          "error_code" => "MODEL_CHANGED_DURING_JOB",
          "error"      => "Bản vẽ SketchUp đang mở đã thay đổi trong lúc tải bản đồ. Đã chặn tự động chèn để bảo vệ file của bạn."
        }
      end

      { "ok" => true }
    end

    def self.show_ui
      ensure_latest_modules
      ensure_global_observers!

      if @dialog && @dialog.visible?
        @dialog.bring_to_front
        send_js("window.onMapSKPModelChanged", {
          "model_token"  => current_model_token(Sketchup.active_model),
          "geo"          => current_model_geo_state,
          "anchor_state" => MapSKP::Importer.scan_anchor_state(Sketchup.active_model)
        })
        return
      end

      html_path = File.join(__dir__, "ui", "index.html")
      @dialog = UI::HtmlDialog.new({
        dialog_title:    "MapSKP — Bản Đồ & Địa Hình 3D",
        preferences_key: "com.hiepai.mapskp.saas.v281",
        scrollable:      false,
        resizable:       true,
        width:           1120,
        height:          740,
        min_width:       780,
        min_height:      540,
        style:           UI::HtmlDialog::STYLE_DIALOG
      })
      @dialog.set_file(html_path)
      if @dialog.respond_to?(:set_on_closed)
        @dialog.set_on_closed do
          stop_init_poll_timer!
        end
      elsif @dialog.respond_to?(:set_on_close)
        @dialog.set_on_close do
          stop_init_poll_timer!
        end
      end

      @dialog.add_action_callback("mapskp_init") do |_ctx|
        stop_init_poll_timer!
        @ui_session_gen = (@ui_session_gen || 0) + 1
        cur_gen = @ui_session_gen
        ensure_global_observers!

        # Khởi tạo cầu nối theo máy trạng thái UI.start_timer trên luồng chính của SketchUp:
        # - Tuyệt đối KHÔNG dùng Thread.new (vì vòng lặp C++ Win32 GetMessage của SketchUp bỏ đói luồng phụ Ruby GVL)
        # - Tuyệt đối KHÔNG gọi sleep() trong lúc thăm dò HTTP (thăm dò từng nhịp 0.10s qua UI.start_timer)
        su_dir_snapshot = (MapSKP::Bootstrap.sketchup_exe_dir rescue "")
        su_pid_snapshot = Process.pid
        bridge_dir_path = File.join(__dir__, "bridge")

        UI.start_timer(0.03, false) do
          next if (@ui_session_gen || 0) != cur_gen || !@dialog || !@dialog.visible?
          begin
            boot_ctx = MapSKP::Bootstrap.begin_bridge_boot_session!(
              bridge_dir_path,
              su_pid_snapshot,
              su_exe_dir_override: su_dir_snapshot
            )
            if boot_ctx.is_a?(Hash) && boot_ctx["state"] == "done"
              emit_init_ready_payload!(cur_gen, boot_ctx["result"])
              next
            end

            started_mono = (Process.clock_gettime(Process::CLOCK_MONOTONIC) rescue Time.now.to_f)
            @init_poll_timer_id = UI.start_timer(0.10, true) do
              if (@ui_session_gen || 0) != cur_gen || !@dialog || !@dialog.visible?
                stop_init_poll_timer!
                next
              end

              begin
                boot_ctx = MapSKP::Bootstrap.poll_bridge_boot_session!(boot_ctx)
                elapsed = (Process.clock_gettime(Process::CLOCK_MONOTONIC) rescue Time.now.to_f) - started_mono
                if boot_ctx.is_a?(Hash) && boot_ctx["state"] == "done"
                  stop_init_poll_timer!
                  emit_init_ready_payload!(cur_gen, boot_ctx["result"])
                elsif elapsed >= 28.0
                  stop_init_poll_timer!
                  send_js("window.onMapSKPReady", {
                    "ok"           => false,
                    "session_gen"  => cur_gen,
                    "bridge_alive" => false,
                    "pid"          => 0,
                    "ipc_token"    => "",
                    "model_token"  => current_model_token(Sketchup.active_model),
                    "error_code"   => "BRIDGE_INIT_TIMEOUT",
                    "error"        => "Quá thời gian khởi động cầu nối MapSKP an toàn (28s). Vui lòng thử lại."
                  })
                end
              rescue StandardError => poll_err
                stop_init_poll_timer!
                emit_init_exception_payload!(cur_gen, poll_err)
              end
            end
          rescue StandardError => init_err
            stop_init_poll_timer!
            emit_init_exception_payload!(cur_gen, init_err)
          end
        end
      end

      @dialog.add_action_callback("mapskp_latch_mandatory_update") do |_ctx, json_str|
        begin
          payload = parse_callback_json(json_str)
          if payload.is_a?(Hash) && payload["locked"] == true
            latch_mandatory_update_lock!(payload["reason"].to_s)
          end
        rescue StandardError => e
          log_ruby_error("mapskp_latch_mandatory_update", e)
        end
      end

      @dialog.add_action_callback("mapskp_get_anchor") do |_ctx|
        begin
          ensure_latest_modules
          active_mdl = Sketchup.active_model
          st = MapSKP::Importer.scan_anchor_state(active_mdl)
          st["model_token"] = current_model_token(active_mdl) if st.is_a?(Hash)
          send_js("window.onMapSKPAnchorUpdated", st)
        rescue StandardError => e
          log_ruby_error("mapskp_get_anchor", e)
        end
      end

      @dialog.add_action_callback("mapskp_reset_anchor") do |_ctx|
        begin
          ensure_latest_modules
          st = MapSKP::Importer.reset_anchor!(Sketchup.active_model)
          send_js("window.onMapSKPAnchorUpdated", st)
          send_js("window.onMapSKPToast", {
            "kind"    => "info",
            "message" => "Đã mở khóa Gốc Tọa Độ mới — lần xuất tiếp theo sẽ trở thành Mảnh Gốc #1 mới."
          })
        rescue StandardError => e
          log_ruby_error("mapskp_reset_anchor", e)
        end
      end

      @dialog.add_action_callback("mapskp_import") do |_ctx, json_str|
        begin
          ensure_latest_modules
          ensure_global_observers!
          manifest = parse_callback_json(json_str)
          active_mdl = Sketchup.active_model
          gate = validate_import_gate!(manifest, active_mdl)
          unless gate["ok"]
            send_js("window.onMapSKPImported", gate)
            next
          end
          res = MapSKP::Importer.import_manifest!(active_mdl, manifest)
          send_js("window.onMapSKPImported", res)
          if res["anchor_state"]
            send_js("window.onMapSKPAnchorUpdated", res["anchor_state"])
          end
        rescue StandardError => e
          log_ruby_error("mapskp_import", e)
        end
      end

      @dialog.add_action_callback("mapskp_sync_shadow") do |_ctx, json_str|
        op_started = false
        model = nil
        begin
          ensure_latest_modules
          origin = parse_callback_json(json_str)
          unless MapSKP::Importer.valid_geo_meta_hash?(origin)
            raise "INVALID_ORIGIN_METADATA: Tọa độ đồng bộ bóng nắng không hợp lệ"
          end
          model = Sketchup.active_model
          if model
            model.start_operation("MapSKP — Đồng bộ Tọa độ & Bóng nắng", true)
            op_started = true
            MapSKP::Importer.apply_geo_shadow!(model, origin)
            model.commit_operation
            op_started = false
            send_js("window.onMapSKPToast", {
              "kind"    => "success",
              "message" => "Đã đồng bộ Vĩ độ #{origin['lat']}, Kinh độ #{origin['lon']} & Múi giờ vào SketchUp ShadowInfo!"
            })
          end
        rescue StandardError => e
          model.abort_operation if model && op_started
          log_ruby_error("mapskp_sync_shadow", e)
        end
      end

      @dialog.add_action_callback("mapskp_save_copy") do |_ctx, json_str|
        begin
          payload = parse_callback_json(json_str)
          save_export_copy_dialog(payload)
        rescue StandardError => e
          log_ruby_error("mapskp_save_copy", e)
        end
      end

      @dialog.add_action_callback("mapskp_pick_ocr_image") do |_ctx|
        begin
          chosen = UI.openpanel("Chọn Ảnh Chụp Màn Hình Google Earth / Maps", "", "Image Files|*.png;*.jpg;*.jpeg;*.webp;*.bmp||")
          if chosen && !chosen.to_s.empty?
            if File.symlink?(chosen) || (defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.windows_reparse_point?(chosen)) || !File.file?(chosen)
              send_js("window.onMapSKPToast", { "kind" => "error", "message" => "Tệp ảnh chọn không hợp lệ." })
              next
            end
            f_sz = File.size(chosen)
            if f_sz <= 0 || f_sz > MAX_OCR_PICK_BYTES
              send_js("window.onMapSKPToast", { "kind" => "error", "message" => "Ảnh chụp vượt giới hạn an toàn (15 MB). Vui lòng cắt vùng tọa độ nhỏ hơn." })
              next
            end
            dim = MapSKP::Importer.inspect_image_dimensions(chosen, 8192)
            unless dim["ok"]
              send_js("window.onMapSKPToast", { "kind" => "error", "message" => "Định dạng hoặc kích thước điểm ảnh vượt ngưỡng cho phép (8192px)." })
              next
            end
            ext = File.extname(chosen).downcase
            mime = case ext
                   when ".png" then "image/png"
                   when ".webp" then "image/webp"
                   when ".bmp" then "image/bmp"
                   else "image/jpeg"
                   end
            b64 = Base64.strict_encode64(File.binread(chosen))
            send_js("window.onMapSKPOcrImage", {
              "ok"       => true,
              "filename" => File.basename(chosen),
              "data_url" => "data:#{mime};base64,#{b64}"
            })
          end
        rescue StandardError => e
          log_ruby_error("mapskp_pick_ocr_image", e)
        end
      end

      @dialog.add_action_callback("mapskp_open_folder") do |_ctx, folder_str|
        begin
          target = folder_str.to_s.strip
          if !target.empty? && MapSKP::Importer.safe_export_path?(target) && !File.symlink?(target) && File.exist?(target)
            dir_path = File.directory?(target) ? target : File.dirname(target)
            real_dir = File.realpath(dir_path).tr("\\", "/")
            if MapSKP::Importer.safe_export_path?(real_dir)
              UI.openURL("file:///#{real_dir}")
            end
          end
        rescue StandardError => e
          log_ruby_error("mapskp_open_folder", e)
        end
      end

      @dialog.add_action_callback("mapskp_open_external_url") do |_ctx, raw_url|
        begin
          clean_url = raw_url.to_s.strip
          if strict_allowed_external_url?(clean_url)
            UI.openURL(clean_url)
          end
        rescue StandardError => e
          log_ruby_error("mapskp_open_external_url", e)
        end
      end

      @dialog.add_action_callback("mapskp_apply_staged_update") do |_ctx, json_str|
        begin
          ensure_latest_modules
          payload = parse_callback_json(json_str)
          raise "INVALID_UPDATE_PAYLOAD" unless payload.is_a?(Hash)
          upd_job_id = payload["update_job_id"].to_s.strip
          bridge_dir = File.join(__dir__, "bridge")
          res = MapSKP::Bootstrap.apply_staged_hotpatch!(bridge_dir, nil, Process.pid, update_job_id: upd_job_id)
          if res.is_a?(Hash) && res["pending_restart"] == true
            @pending_restart_locked = true
          end
          if res["dev_protected_dry_run"] || !res["ok"] || res["pending_restart"]
            send_js("window.onMapSKPUpdateApplied", res)
          else
            ensure_latest_modules
            main_rb_file = File.join(__dir__, "main.rb")
            load(main_rb_file) if File.exist?(main_rb_file)
            new_html = File.join(__dir__, "ui", "index.html")
            @dialog.set_file(new_html) if @dialog && File.exist?(new_html)
            ver_txt = res["latest_version"].to_s
            UI.start_timer(0.45, false) do
              send_js("window.onMapSKPToast", {
                "kind"    => "success",
                "message" => "🎉 Đã cập nhật thành công lên MapSKP v#{ver_txt} ngay trong SketchUp!"
              })
            end
          end
        rescue StandardError => e
          log_ruby_error("mapskp_apply_staged_update", e)
        end
      end

      @dialog.add_action_callback("mapskp_undo") do |_ctx|
        Sketchup.undo
        send_js("window.onMapSKPAnchorUpdated", MapSKP::Importer.scan_anchor_state(Sketchup.active_model))
        send_js("window.onMapSKPToast", { "kind" => "info", "message" => "Đã hoàn tác (Undo) thao tác vừa rồi trong SketchUp." })
      end

      @dialog.show
      if !@dialog_centered_in_session && @dialog.respond_to?(:center)
        @dialog.center
        @dialog_centered_in_session = true
      end
      true
    end
  end

  # Kích hoạt ngay bộ lắng nghe kéo-thả file .skp xuống mặt nền SketchUp từ lúc mở phần mềm!
  MapSKP::Core.ensure_global_observers!

  unless file_loaded?(__FILE__)
    menu = UI.menu("Plugins")
    menu.add_item("MapSKP 3D — Bản Đồ Vệ Tinh, Địa Hình & Google 3D") do
      main_rb = File.join(__dir__, "main.rb")
      load(main_rb) if File.exist?(main_rb)
      MapSKP::Core.show_ui
    end

    tb = UI::Toolbar.new("MapSKP Hybrid 3D")
    cmd = UI::Command.new("MapSKP 3D") do
      main_rb = File.join(__dir__, "main.rb")
      load(main_rb) if File.exist?(main_rb)
      MapSKP::Core.show_ui
    end
    icon_16 = File.join(__dir__, "ui", "icons", "mapskp_avatar_16.png")
    icon_24 = File.join(__dir__, "ui", "icons", "mapskp_avatar_24.png")
    cmd.small_icon      = icon_16 if File.exist?(icon_16)
    cmd.large_icon      = icon_24 if File.exist?(icon_24)
    cmd.tooltip         = "Mở MapSKP 3D — Lấy ảnh vệ tinh 4K/8K, địa hình DEM, Map công trình cao tầng, Google 3D Tiles & Ghép mảnh 0.0mm"
    cmd.status_bar_text = "Mở cửa sổ MapSKP 3D — Cắm là chạy, khớp tọa độ 1:1"
    tb.add_item(cmd)
    MapSKP::Core.register_toolbar(tb)

    # Tự hiện Thanh công cụ & bật giao diện chào mừng ngay lần đầu tiên sau mỗi lần cài .RBZ / .BAT trên bản SketchUp này
    fresh_install_open = MapSKP::Bootstrap.consume_first_install_auto_open!(File.expand_path("..", __dir__))
    MapSKP::Core.ensure_toolbar_visible!(force_show: fresh_install_open)
    if fresh_install_open
      UI.start_timer(0.55, false) do
        begin
          MapSKP::Core.show_ui
        rescue StandardError => e
          MapSKP::Core.log_ruby_error("AutoOpenFirstInstall", e)
        end
      end
    end

    file_loaded(__FILE__)
  end
end
