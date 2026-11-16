# ==============================================================================
# File: mapskp/map_importer.rb
# MapSKP v2.0.0 SaaS — Bộ Nạp Tỷ Lệ 1:1, Ghép Mảnh Mở Rộng 0.0mm & Tự Khớp File Thả Nền:
#   1. Mảnh #1 khóa gốc Master Anchor (ENU + Cao độ + Vị trí đặt trên mặt nền SketchUp)
#   2. Mảnh #2..#N (dù bấm Nạp trực tiếp hay kéo-thả file .skp xuống mặt nền SketchUp)
#      đều tự động giải mã __MAPSKP_META__ và nhảy khớp khít X-Y-Z với Mảnh #1 (0.0mm hở mép)
#   3. Tương thích Ruby 2.2 -> 3.2 (SketchUp 2017 - 2026) | 0ms UI Freeze
# ==============================================================================

require 'sketchup.rb'
require 'json'
require 'base64'
require 'fileutils'
require 'securerandom'
require 'tmpdir'

module MapSKP
  module Importer
    INCH_PER_METER = 39.37007874015748
    WGS84_A        = 6378137.0
    WGS84_F        = 1.0 / 298.257223563
    WGS84_E2       = WGS84_F * (2.0 - WGS84_F)
    META_PREFIX          = "__MAPSKP_META__".freeze
    ATTR_DICT            = "MapSKP_Meta".freeze
    MAX_CARRIER_B64_LEN  = 16_384
    VALID_TERRAIN_MODES  = %w[flat terrain_3d].freeze

    WIN_RESERVED_NAMES = %w[
      CON PRN AUX NUL
      COM1 COM2 COM3 COM4 COM5 COM6 COM7 COM8 COM9
      LPT1 LPT2 LPT3 LPT4 LPT5 LPT6 LPT7 LPT8 LPT9
    ].freeze

    def self.strict_real_number?(val)
      val.is_a?(Numeric) && !val.is_a?(Complex) && val.to_f.finite?
    end

    def self.valid_geo_meta_hash?(obj)
      return false unless obj.is_a?(Hash)
      return false unless obj.key?("lat") && obj.key?("lon")
      return false unless strict_real_number?(obj["lat"]) && strict_real_number?(obj["lon"])
      lat = obj["lat"].to_f
      lon = obj["lon"].to_f
      return false if lat < -90.0 || lat > 90.0 || lon < -180.0 || lon > 180.0

      ["width_m", "height_m"].each do |dim_k|
        next unless obj.key?(dim_k) && !obj[dim_k].nil?
        return false unless strict_real_number?(obj[dim_k])
        dv = obj[dim_k].to_f
        return false unless dv > 0.0 && dv <= 50_000.0
      end

      ["elevation_m", "anchor_elev_m"].each do |elev_k|
        next unless obj.key?(elev_k) && !obj[elev_k].nil?
        return false unless strict_real_number?(obj[elev_k])
        ev = obj[elev_k].to_f
        return false unless ev >= -12_000.0 && ev <= 20_000.0
      end

      if obj.key?("anchor_lat") && !obj["anchor_lat"].nil?
        return false unless strict_real_number?(obj["anchor_lat"])
        alat = obj["anchor_lat"].to_f
        return false if alat < -90.0 || alat > 90.0
      end

      if obj.key?("anchor_lon") && !obj["anchor_lon"].nil?
        return false unless strict_real_number?(obj["anchor_lon"])
        alon = obj["anchor_lon"].to_f
        return false if alon < -180.0 || alon > 180.0
      end

      ["south", "north"].each do |lat_k|
        next unless obj.key?(lat_k) && !obj[lat_k].nil?
        return false unless strict_real_number?(obj[lat_k])
        bv = obj[lat_k].to_f
        return false if bv < -90.0 || bv > 90.0
      end

      ["west", "east"].each do |lon_k|
        next unless obj.key?(lon_k) && !obj[lon_k].nil?
        return false unless strict_real_number?(obj[lon_k])
        bv = obj[lon_k].to_f
        return false if bv < -180.0 || bv > 180.0
      end

      if obj.key?("z_exaggeration") && !obj["z_exaggeration"].nil?
        return false unless strict_real_number?(obj["z_exaggeration"])
        zv = obj["z_exaggeration"].to_f
        return false unless zv >= 0.0 && zv <= 20.0
      end

      if obj.key?("offset_from_anchor_m") && !obj["offset_from_anchor_m"].nil?
        off = obj["offset_from_anchor_m"]
        return false unless off.is_a?(Array) && off.length == 3
        off.each do |comp|
          return false unless strict_real_number?(comp)
          return false unless comp.to_f.abs <= 500_000.0
        end
      end

      if obj.key?("terrain_mode") && !obj["terrain_mode"].nil?
        return false unless obj["terrain_mode"].is_a?(String)
        return false unless VALID_TERRAIN_MODES.include?(obj["terrain_mode"])
      end

      if obj.key?("hill_patch") && !obj["hill_patch"].nil?
        return false unless obj["hill_patch"] == true || obj["hill_patch"] == false
      end

      if obj.key?("tz_offset") && !obj["tz_offset"].nil?
        return false unless strict_real_number?(obj["tz_offset"])
        tz = obj["tz_offset"].to_f
        return false unless tz >= -14.0 && tz <= 14.0
      end

      true
    rescue StandardError
      false
    end

    def self.decode_urlsafe_b64_json(b64_str)
      cleaned = b64_str.to_s.strip.tr("-_", "+/")
      return nil if cleaned.empty? || cleaned.bytesize > MAX_CARRIER_B64_LEN
      return nil unless cleaned =~ /\A[A-Za-z0-9+\/=]+\z/
      pad = (4 - (cleaned.length % 4)) % 4
      raw = Base64.decode64(cleaned + ("=" * pad))
      raw.force_encoding("UTF-8")
      return nil unless raw.valid_encoding?
      obj = JSON.parse(raw, max_nesting: 16)
      valid_geo_meta_hash?(obj) ? obj : nil
    rescue StandardError
      nil
    end

    def self.wgs84_latlon_to_ecef(lat_deg, lon_deg)
      lat_r = lat_deg.to_f * Math::PI / 180.0
      lon_r = lon_deg.to_f * Math::PI / 180.0
      slat  = Math.sin(lat_r)
      clat  = Math.cos(lat_r)
      slon  = Math.sin(lon_r)
      clon  = Math.cos(lon_r)
      n_val = WGS84_A / Math.sqrt(1.0 - WGS84_E2 * slat * slat)
      x_val = n_val * clat * clon
      y_val = n_val * clat * slon
      z_val = n_val * (1.0 - WGS84_E2) * slat
      [x_val, y_val, z_val]
    end

    def self.wgs84_enu_delta_m(lat0, lon0, elev0, lat1, lon1, elev1, z_exag = 1.0)
      x0, y0, z0 = wgs84_latlon_to_ecef(lat0, lon0)
      x1, y1, z1 = wgs84_latlon_to_ecef(lat1, lon1)
      dx = x1 - x0
      dy = y1 - y0
      dz = z1 - z0

      lat_r = lat0.to_f * Math::PI / 180.0
      lon_r = lon0.to_f * Math::PI / 180.0
      slat  = Math.sin(lat_r)
      clat  = Math.cos(lat_r)
      slon  = Math.sin(lon_r)
      clon  = Math.cos(lon_r)

      east_m  = (-slon * dx) + (clon * dy)
      north_m = (-slat * clon * dx) - (slat * slon * dy) + (clat * dz)
      up_m    = (elev1.to_f - elev0.to_f) * z_exag.to_f
      [east_m, north_m, up_m]
    end

    # W07 (META-01): Đọc siêu dữ liệu 100% THUẦN CHỈ ĐỌC (0% sửa thuộc tính, 0% xóa Group ngoài Transaction)
    def self.peek_definition_meta(defn)
      return nil unless defn && defn.valid?

      cached_json = defn.get_attribute(ATTR_DICT, "origin_json", "").to_s
      if !cached_json.empty? && cached_json.bytesize <= MAX_CARRIER_B64_LEN
        begin
          parsed = JSON.parse(cached_json, max_nesting: 16)
          return parsed if valid_geo_meta_hash?(parsed)
        rescue StandardError
          nil
        end
      end

      defn.entities.each do |ent|
        if ent.is_a?(Sketchup::Group) && ent.name.to_s.start_with?(META_PREFIX)
          b64_part = ent.name.to_s.sub(META_PREFIX, "")
          decoded = decode_urlsafe_b64_json(b64_part)
          return decoded if decoded
        end
      end
      nil
    rescue StandardError
      nil
    end

    # W07 (META-02) + Astra #13: Chỉ gọi bên trong model.start_operation; make_unique nếu chia sẻ Definition và chỉ xóa đúng Group carrier giải mã hợp lệ
    def self.commit_definition_meta_cleanup!(defn, decoded = nil, target_inst = nil)
      return nil unless defn && defn.valid?
      meta = decoded || peek_definition_meta(defn)
      return nil unless valid_geo_meta_hash?(meta)

      if target_inst && target_inst.valid? && target_inst.respond_to?(:make_unique) &&
         defn.respond_to?(:count_used_instances) && defn.count_used_instances.to_i > 1
        target_inst.make_unique
        defn = target_inst.definition
        return nil unless defn && defn.valid?
      end

      defn.set_attribute(ATTR_DICT, "origin_json", JSON.generate(meta))
      carriers = []
      defn.entities.each do |ent|
        next unless ent.is_a?(Sketchup::Group) && ent.name.to_s.start_with?(META_PREFIX)
        b64_part = ent.name.to_s.sub(META_PREFIX, "")
        carrier_decoded = decode_urlsafe_b64_json(b64_part)
        carriers << ent if carrier_decoded
      end
      carriers.each do |cg|
        begin
          cg.erase! if cg && cg.valid?
        rescue StandardError
          nil
        end
      end
      meta
    end

    def self.extract_definition_meta!(defn)
      meta = peek_definition_meta(defn)
      return nil unless meta
      commit_definition_meta_cleanup!(defn, meta)
    end

    def self.stamp_instance_meta!(inst, origin_hash, seq_idx, job_id = "")
      return unless inst && inst.valid? && valid_geo_meta_hash?(origin_hash)

      json_str = JSON.generate(origin_hash)
      inst.set_attribute(ATTR_DICT, "linked", true)
      inst.set_attribute(ATTR_DICT, "imported_seq", seq_idx.to_i)
      inst.set_attribute(ATTR_DICT, "job_id", job_id.to_s)
      inst.set_attribute(ATTR_DICT, "origin_json", json_str)
      inst.set_attribute(ATTR_DICT, "lat", origin_hash["lat"].to_f)
      inst.set_attribute(ATTR_DICT, "lon", origin_hash["lon"].to_f)
      inst.set_attribute(ATTR_DICT, "elevation_m", (origin_hash["elevation_m"] || 0.0).to_f)
      inst.set_attribute(ATTR_DICT, "width_m", (origin_hash["width_m"] || 380.0).to_f)
      inst.set_attribute(ATTR_DICT, "height_m", (origin_hash["height_m"] || 380.0).to_f)
      inst.set_attribute(ATTR_DICT, "terrain_mode", (origin_hash["terrain_mode"] || "terrain_3d").to_s)
      inst.set_attribute(ATTR_DICT, "hill_patch", origin_hash["hill_patch"] ? true : false)

      if inst.respond_to?(:definition) && inst.definition && inst.definition.valid?
        shared_count = inst.definition.respond_to?(:count_used_instances) ? inst.definition.count_used_instances.to_i : 1
        if shared_count <= 1
          inst.definition.set_attribute(ATTR_DICT, "origin_json", json_str)
        end
      end
    end

    def self.read_instance_meta(inst)
      return nil unless inst && inst.valid?
      return nil unless inst.is_a?(Sketchup::ComponentInstance) || inst.is_a?(Sketchup::Group)

      raw_json = inst.get_attribute(ATTR_DICT, "origin_json", nil)
      if raw_json.is_a?(String) && !raw_json.empty? && raw_json.bytesize <= MAX_CARRIER_B64_LEN
        begin
          obj = JSON.parse(raw_json, max_nesting: 16)
          return obj if valid_geo_meta_hash?(obj)
        rescue StandardError
          nil
        end
      end

      raw_lat = inst.get_attribute(ATTR_DICT, "lat", nil)
      raw_lon = inst.get_attribute(ATTR_DICT, "lon", nil)
      if !raw_lat.nil? || !raw_lon.nil?
        raw_elev  = inst.get_attribute(ATTR_DICT, "elevation_m", nil)
        raw_w     = inst.get_attribute(ATTR_DICT, "width_m", nil)
        raw_h     = inst.get_attribute(ATTR_DICT, "height_m", nil)
        raw_tmode = inst.get_attribute(ATTR_DICT, "terrain_mode", nil)
        raw_hill  = inst.get_attribute(ATTR_DICT, "hill_patch", nil)
        cand = {
          "lat"          => raw_lat,
          "lon"          => raw_lon,
          "elevation_m"  => raw_elev.nil? ? 0.0 : raw_elev,
          "width_m"      => raw_w.nil? ? 380.0 : raw_w,
          "height_m"     => raw_h.nil? ? 380.0 : raw_h,
          "terrain_mode" => raw_tmode.nil? ? "terrain_3d" : raw_tmode,
          "hill_patch"   => raw_hill.nil? ? false : raw_hill
        }
        return cand if valid_geo_meta_hash?(cand)
      end

      if inst.is_a?(Sketchup::ComponentInstance)
        return peek_definition_meta(inst.definition)
      end
      nil
    end

    def self.find_linked_tiles(model, exclude_inst = nil)
      return [] unless model
      found = []
      model.active_entities.each do |ent|
        next if exclude_inst && ent == exclude_inst
        next unless ent.is_a?(Sketchup::ComponentInstance) || ent.is_a?(Sketchup::Group)
        next unless ent.get_attribute(ATTR_DICT, "linked", false) || !ent.get_attribute(ATTR_DICT, "lat", nil).nil?

        meta = read_instance_meta(ent)
        next unless meta
        seq_raw = ent.get_attribute(ATTR_DICT, "imported_seq", 999999)
        seq = seq_raw.is_a?(Integer) ? seq_raw : 999999
        found << [seq, ent.entityID.to_i, ent, meta]
      end
      found.sort_by { |row| [row[0], row[1]] }
    end

    def self.compute_linked_transform(first_inst, first_meta, target_meta)
      raise "INVALID_LINKED_INSTANCE" unless first_inst && first_inst.respond_to?(:valid?) && first_inst.valid?
      raise "INVALID_LINKED_METADATA: Mảnh gốc không hợp lệ" unless valid_geo_meta_hash?(first_meta)
      raise "INVALID_LINKED_METADATA: Mảnh ghép mới không hợp lệ" unless valid_geo_meta_hash?(target_meta)

      base_tr = first_inst.transformation

      a1_lat  = (first_meta["anchor_lat"] || first_meta["lat"]).to_f
      a1_lon  = (first_meta["anchor_lon"] || first_meta["lon"]).to_f
      a1_elev = (first_meta["anchor_elev_m"] || first_meta["elevation_m"] || 0.0).to_f
      z_exag  = (first_meta["z_exaggeration"] || target_meta["z_exaggeration"] || 1.0).to_f

      a2_lat  = (target_meta["anchor_lat"] || target_meta["lat"]).to_f
      a2_lon  = (target_meta["anchor_lon"] || target_meta["lon"]).to_f

      off1 = first_meta["offset_from_anchor_m"].is_a?(Array) ? first_meta["offset_from_anchor_m"] : [0.0, 0.0, 0.0]
      off2 = target_meta["offset_from_anchor_m"].is_a?(Array) ? target_meta["offset_from_anchor_m"] : nil

      same_anchor = ((a2_lat - a1_lat).abs < 1.0e-6) && ((a2_lon - a1_lon).abs < 1.0e-6)
      if same_anchor && off2 && off2.length == 3
        dx_m = off2[0].to_f - off1[0].to_f
        dy_m = off2[1].to_f - off1[1].to_f
        dz_m = off2[2].to_f - off1[2].to_f
      else
        # Hỗ trợ cả trường hợp người dùng xuất 2 file .skp độc lập rồi kéo thả vào cùng bản vẽ SketchUp
        t_lat  = target_meta["lat"].to_f
        t_lon  = target_meta["lon"].to_f
        t_elev = (target_meta["elevation_m"] || a1_elev).to_f
        f_lat  = first_meta["lat"].to_f
        f_lon  = first_meta["lon"].to_f
        f_elev = (first_meta["elevation_m"] || a1_elev).to_f
        dx_m, dy_m, dz_m = wgs84_enu_delta_m(f_lat, f_lon, f_elev, t_lat, t_lon, t_elev, z_exag)
        if first_meta["terrain_mode"].to_s == "flat" && (target_meta["hill_patch"] == true || target_meta["terrain_mode"].to_s == "flat")
          dz_m = 0.0
        end
      end

      unless strict_real_number?(dx_m) && strict_real_number?(dy_m) && strict_real_number?(dz_m) &&
             dx_m.abs <= MAX_COORD_ABS_M && dy_m.abs <= MAX_COORD_ABS_M && dz_m.abs <= MAX_COORD_ABS_M
        raise "LINKED_TRANSFORM_OUT_OF_RANGE: Khoảng cách ghép mảnh vượt giới hạn an toàn"
      end

      shift_vec = Geom::Vector3d.new(
        dx_m * INCH_PER_METER,
        dy_m * INCH_PER_METER,
        dz_m * INCH_PER_METER
      )
      base_tr * Geom::Transformation.translation(shift_vec)
    end

    # W07 (META-01): Quét trạng thái mảnh ghép 100% chỉ đọc, tuyệt đối không làm bẩn Undo stack của người dùng
    def self.scan_anchor_state(model)
      return { "has_anchor" => false, "anchor" => nil, "tiles" => [] } unless model

      rows = find_linked_tiles(model)
      if rows.empty?
        return { "has_anchor" => false, "anchor" => nil, "tiles" => [] }
      end

      first_meta = rows[0][3]
      anchor_obj = {
        "lat"            => (first_meta["anchor_lat"] || first_meta["lat"]).to_f,
        "lon"            => (first_meta["anchor_lon"] || first_meta["lon"]).to_f,
        "elevation_m"    => (first_meta["anchor_elev_m"] || first_meta["elevation_m"] || 0.0).to_f,
        "z_exaggeration" => (first_meta["z_exaggeration"] || 1.0).to_f,
        "terrain_mode"   => (first_meta["terrain_mode"] || "terrain_3d").to_s
      }

      tiles_out = []
      rows.each_with_index do |row, idx|
        ent  = row[2]
        meta = row[3]
        tiles_out << {
          "index"        => idx + 1,
          "name"         => ent.name.to_s,
          "lat"          => meta["lat"].to_f,
          "lon"          => meta["lon"].to_f,
          "south"        => meta["south"] ? meta["south"].to_f : nil,
          "west"         => meta["west"] ? meta["west"].to_f : nil,
          "north"        => meta["north"] ? meta["north"].to_f : nil,
          "east"         => meta["east"] ? meta["east"].to_f : nil,
          "width_m"      => meta["width_m"].to_f,
          "height_m"     => meta["height_m"].to_f,
          "terrain_mode" => (meta["terrain_mode"] || "terrain_3d").to_s,
          "hill_patch"   => (meta["hill_patch"] ? true : false)
        }
      end

      {
        "has_anchor" => true,
        "anchor"     => anchor_obj,
        "tiles"      => tiles_out
      }
    end

    def self.reset_anchor!(model)
      return scan_anchor_state(nil) unless model
      op_started = false
      begin
        model.start_operation("MapSKP — Đặt lại Gốc Tọa Độ Mở Rộng", true)
        op_started = true
        model.active_entities.each do |ent|
          if ent.respond_to?(:attribute_dictionaries) && ent.attribute_dictionaries && ent.attribute_dictionaries[ATTR_DICT]
            ent.attribute_dictionaries.delete(ATTR_DICT)
          end
        end
        if model.attribute_dictionaries && model.attribute_dictionaries["MapSKP_Anchor"]
          model.attribute_dictionaries.delete("MapSKP_Anchor")
        end
        model.commit_operation
        op_started = false
        scan_anchor_state(model)
      rescue StandardError => e
        model.abort_operation if op_started
        raise e
      end
    end

    def self.link_dropped_instance!(model, inst)
      return nil unless model && inst && inst.valid?
      return nil unless inst.is_a?(Sketchup::ComponentInstance)
      return nil if inst.get_attribute(ATTR_DICT, "linked", false)

      # W07 (META-02) + Astra #13/#14: Thăm dò & tính trước ma trận ghép mảnh hoàn toàn chỉ đọc TRƯỚC model.start_operation
      meta = peek_definition_meta(inst.definition)
      return nil unless valid_geo_meta_hash?(meta)

      existing = find_linked_tiles(model, inst)
      seq_num  = existing.length + 1
      target_tr = nil
      unless existing.empty?
        begin
          target_tr = compute_linked_transform(existing[0][2], existing[0][3], meta)
        rescue StandardError
          return nil
        end
      end

      op_started = false
      begin
        model.start_operation("MapSKP — Tự Khớp Tọa Độ File .SKP Thả Xuống Nền", true)
        op_started = true

        commit_definition_meta_cleanup!(inst.definition, meta, inst)
        master_tag = ensure_tag(model, "MapSKP_00_Master_Context", [233, 69, 96])
        inst.layer = master_tag

        if existing.empty?
          # File .skp đầu tiên thả xuống mặt nền -> khóa làm Mảnh Gốc #1 ngay tại điểm người dùng đặt!
          apply_geo_shadow!(model, meta)
          stamp_instance_meta!(inst, meta, 1, "dropped_piece_1")
          status_msg = "📌 MapSKP: Đã khóa Mảnh Gốc #1 trên mặt nền SketchUp. Các file .skp thả tiếp theo sẽ tự khớp khít 0.0mm!"
        else
          inst.transformation = target_tr
          stamp_instance_meta!(inst, meta, seq_num, "dropped_piece_#{seq_num}")
          status_msg = "🧩 MapSKP: Đã tự động khớp khít tọa độ Mảnh ##{seq_num} vào Mảnh Gốc #1 (sai số 0.0mm)!"
        end

        model.commit_operation
        op_started = false
        Sketchup.status_text = status_msg
        return {
          "ok"           => true,
          "seq"          => seq_num,
          "message"      => status_msg,
          "anchor_state" => scan_anchor_state(model)
        }
      rescue StandardError
        model.abort_operation if op_started
        return nil
      end
    end

    def self.ensure_tag(model, tag_name, rgb_arr = nil)
      clean_name = tag_name.to_s.strip[0, MAX_LABEL_CHARS]
      clean_name = "MapSKP_Context" if clean_name.empty?
      existing_layer = model.layers[clean_name]
      return existing_layer if existing_layer

      layer = model.layers.add(clean_name)
      begin
        layer.set_attribute("MapSKP_Meta", "owned", true)
      rescue StandardError
        nil
      end
      if rgb_arr.is_a?(Array) && rgb_arr.length >= 3
        begin
          r_c = [[rgb_arr[0].to_i, 0].max, 255].min
          g_c = [[rgb_arr[1].to_i, 0].max, 255].min
          b_c = [[rgb_arr[2].to_i, 0].max, 255].min
          layer.color = Sketchup::Color.new(r_c, g_c, b_c)
        rescue StandardError
          nil
        end
      end
      layer
    end

    def self.material_used_anywhere_in_model?(model, mat)
      return false unless model && mat
      scan_collection = lambda do |ents|
        next false unless ents
        ents.each do |ent|
          next unless ent && (!ent.respond_to?(:valid?) || ent.valid?)
          return true if ent.respond_to?(:material) && ent.material == mat
          return true if ent.respond_to?(:back_material) && ent.back_material == mat
        end
        false
      end
      return true if model.respond_to?(:entities) && scan_collection.call(model.entities)
      if model.respond_to?(:definitions) && model.definitions
        model.definitions.each do |defn|
          next unless defn && (!defn.respond_to?(:valid?) || defn.valid?)
          return true if defn.respond_to?(:entities) && scan_collection.call(defn.entities)
        end
      end
      false
    rescue StandardError
      true
    end

    def self.allocate_safe_material(model, raw_name, idx)
      clean_name = raw_name.to_s.strip[0, MAX_LABEL_CHARS]
      clean_name = "MapSKP_Mat_#{idx}" if clean_name.empty?
      if model.materials[clean_name]
        suffix = 1
        candidate = "#{clean_name[0, 220]}_MapSKP_#{suffix}"
        while model.materials[candidate]
          suffix += 1
          candidate = "#{clean_name[0, 220]}_MapSKP_#{suffix}"
        end
        clean_name = candidate
      end
      mat = model.materials.add(clean_name)
      begin
        mat.set_attribute("MapSKP_Meta", "owned", true)
      rescue StandardError
        nil
      end
      mat
    end

    def self.apply_geo_shadow!(model, origin_hash)
      return unless model && valid_geo_meta_hash?(origin_hash)

      lat = origin_hash["lat"].to_f
      lon = origin_hash["lon"].to_f
      tz  = origin_hash.key?("tz_offset") && !origin_hash["tz_offset"].nil? ? origin_hash["tz_offset"].to_f : 7.0
      return unless tz.finite? && tz >= -14.0 && tz <= 14.0

      si = model.shadow_info
      if si
        si["Latitude"]   = lat
        si["Longitude"]  = lon
        si["TZOffset"]   = tz
        si["NorthAngle"] = 0.0
        si["City"]       = "MapSKP (#{lat.round(4)}, #{lon.round(4)})"
        si["Country"]    = (lon >= 102.0 && lon <= 110.5) ? "Vietnam" : "GeoContext"
      end

      model.set_attribute("GeoReference", "Latitude", lat)
      model.set_attribute("GeoReference", "Longitude", lon)
      model.set_attribute("GeoReference", "GeoReferenced", true)
      model.set_attribute("GeoReference", "UsesGeoReferencing", true)
      model.set_attribute("GeoReference", "ModelTranslationX", 0.0)
      model.set_attribute("GeoReference", "ModelTranslationY", 0.0)
      model.set_attribute("GeoReference", "ModelTranslationZ", 0.0)
    end

    MAX_FALLBACK_JSON_BYTES      = 64 * 1024 * 1024 unless const_defined?(:MAX_FALLBACK_JSON_BYTES)
    MAX_FALLBACK_VERTICES        = 600_000 unless const_defined?(:MAX_FALLBACK_VERTICES)
    MAX_FALLBACK_TRIANGLES       = 600_000 unless const_defined?(:MAX_FALLBACK_TRIANGLES)
    MAX_MATERIALS_COUNT          = 256 unless const_defined?(:MAX_MATERIALS_COUNT)
    MAX_LAYERS_COUNT             = 256 unless const_defined?(:MAX_LAYERS_COUNT)
    MAX_MESHES_COUNT             = 4_096 unless const_defined?(:MAX_MESHES_COUNT)
    MAX_LABEL_CHARS              = 256 unless const_defined?(:MAX_LABEL_CHARS)
    MAX_TEXTURE_FILE_BYTES       = 128 * 1024 * 1024 unless const_defined?(:MAX_TEXTURE_FILE_BYTES)
    MAX_TOTAL_TEXTURE_FILE_BYTES = 256 * 1024 * 1024 unless const_defined?(:MAX_TOTAL_TEXTURE_FILE_BYTES)
    MAX_TEXTURE_DIM_PX           = 8_192 unless const_defined?(:MAX_TEXTURE_DIM_PX)
    MAX_TOTAL_RGBA_BUDGET        = 512 * 1024 * 1024 unless const_defined?(:MAX_TOTAL_RGBA_BUDGET)
    MAX_SKP_IMPORT_BYTES         = 256 * 1024 * 1024 unless const_defined?(:MAX_SKP_IMPORT_BYTES)
    MAX_COORD_ABS_M              = 1_000_000.0 unless const_defined?(:MAX_COORD_ABS_M)
    SNAPSHOT_COPY_CHUNK_BYTES    = 65_536 unless const_defined?(:SNAPSHOT_COPY_CHUNK_BYTES)

    def self.dev_export_roots_enabled?
      bridge_dir = File.join(__dir__, "bridge")
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.respond_to?(:dev_source_protected_bridge?)
        return MapSKP::Bootstrap.dev_source_protected_bridge?(bridge_dir) &&
               !MapSKP::Bootstrap.armored_release_bridge?(bridge_dir)
      end
      File.file?(File.join(bridge_dir, "mode1_osm_dem_builder.py")) &&
        !File.file?(File.join(bridge_dir, "core_ip.vlt"))
    rescue StandardError
      false
    end

    def self.allowed_export_roots
      roots = []
      appdata = ENV["APPDATA"].to_s.tr("\\", "/")
      roots << File.expand_path(File.join(appdata, "HiepAI_MapSKP", "exports")).tr("\\", "/").chomp("/") unless appdata.empty?
      roots << File.expand_path(File.join(Dir.tmpdir, "HiepAI_MapSKP", "exports")).tr("\\", "/").chomp("/")
      if dev_export_roots_enabled?
        dev_live = File.expand_path("../../live_session/exports", __dir__).tr("\\", "/").chomp("/")
        roots << dev_live
        custom_env = ENV["MAPSKP_ALLOWED_EXPORT_DIR"].to_s.strip
        roots << File.expand_path(custom_env).tr("\\", "/").chomp("/") unless custom_env.empty?
      end
      roots.uniq { |r| r.downcase }
    end

    def self.safe_export_path?(raw_path, allowed_exts = nil)
      s = raw_path.to_s.strip
      return false if s.empty? || s.include?("\0")
      return false if s.start_with?("\\\\") || s.start_with?("//")
      return false if s.split(/[\/\\]/).include?("..")
      return false if s =~ /[\x00-\x1F]/
      return false if s =~ /\A[\/\\]\?\?[\/\\]/
      # Chặn Alternate Data Stream (file.skp:stream) và drive-relative path (C:foo.skp không có dấu /)
      if s.include?(":")
        return false unless s =~ /\A[A-Za-z]:[\/\\][^:]*\z/
      end

      rel_segs = s.sub(/\A[A-Za-z]:[\/\\]+/, "").sub(/\A[\/\\]+/, "").split(/[\/\\]+/)
      return false if rel_segs.empty?
      rel_segs.each do |seg|
        return false if seg.empty? || seg == "." || seg == ".."
        return false if seg.end_with?(" ", ".")
        stem = seg.split(".", 2).first.to_s.upcase
        return false if WIN_RESERVED_NAMES.include?(stem)
      end

      norm = File.expand_path(s).tr("\\", "/").chomp("/")
      return false if File.symlink?(norm)
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.respond_to?(:path_has_reparse_ancestor?)
        return false if MapSKP::Bootstrap.path_has_reparse_ancestor?(norm)
      end

      matched_roots = allowed_export_roots.select do |r|
        r_low = r.downcase
        n_low = norm.downcase
        n_low == r_low || n_low.start_with?(r_low + "/")
      end
      return false if matched_roots.empty?

      # Kiểm tra realpath trên nhánh thư mục đã tồn tại để chặn junction/symlink swap
      probe = norm
      probe = File.dirname(probe) while !File.exist?(probe) && File.dirname(probe) != probe
      if File.exist?(probe)
        return false if File.symlink?(probe)
        real_probe = File.realpath(probe).tr("\\", "/").chomp("/")
        real_ok = matched_roots.any? do |r|
          real_root = (File.exist?(r) ? File.realpath(r) : r).tr("\\", "/").chomp("/")
          rp_low = real_probe.downcase
          rr_low = real_root.downcase
          rp_low == rr_low || rp_low.start_with?(rr_low + "/") || rr_low.start_with?(rp_low + "/")
        end
        return false unless real_ok
      end

      if allowed_exts && !allowed_exts.empty?
        ext = File.extname(norm).downcase
        return false unless allowed_exts.map(&:downcase).include?(ext)
      end
      true
    rescue StandardError
      false
    end

    def self.inspect_image_dimensions(img_path, max_dim = MAX_TEXTURE_DIM_PX)
      return { "ok" => false, "error" => "IMAGE_MISSING" } unless img_path && File.file?(img_path) && !File.symlink?(img_path)
      File.open(img_path, "rb") do |f|
        hdr = f.read(32).to_s.b
        return { "ok" => false, "error" => "IMAGE_TOO_SMALL" } if hdr.bytesize < 16

        w = 0
        h = 0
        fmt = nil

        if hdr.start_with?("\x89PNG\r\n\x1A\n".b) && hdr.bytesize >= 24 && hdr[12, 4] == "IHDR".b
          fmt = "png"
          w, h = hdr[16, 8].unpack("N2")
        elsif hdr.start_with?("BM".b) && hdr.bytesize >= 26
          fmt = "bmp"
          w, h_signed = hdr[18, 8].unpack("l<2")
          h = h_signed.to_i.abs
        elsif hdr.bytesize >= 30 && hdr[0, 4] == "RIFF".b && hdr[8, 4] == "WEBP".b
          fmt = "webp"
          chunk = hdr[12, 4]
          if chunk == "VP8X".b
            b = hdr[24, 6].bytes
            w = 1 + (b[0] | (b[1] << 8) | (b[2] << 16))
            h = 1 + (b[3] | (b[4] << 8) | (b[5] << 16))
          elsif chunk == "VP8 ".b && hdr.bytesize >= 30
            w_raw, h_raw = hdr[26, 4].unpack("v2")
            w = w_raw & 0x3FFF
            h = h_raw & 0x3FFF
          elsif chunk == "VP8L".b && hdr.bytesize >= 25
            bits = hdr[21, 4].unpack1("V")
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
          end
        elsif hdr.start_with?("\xFF\xD8".b)
          fmt = "jpeg"
          f.seek(2)
          steps = 0
          while steps < 4096 && !f.eof?
            steps += 1
            b = f.getbyte
            next unless b == 0xFF
            b = f.getbyte while b == 0xFF
            break if b.nil? || b == 0xD9 || b == 0xDA
            next if b == 0x00 || (b >= 0xD0 && b <= 0xD7) || b == 0x01
            len_bytes = f.read(2)
            break if !len_bytes || len_bytes.bytesize < 2
            seg_len = len_bytes.unpack1("n")
            break if seg_len < 2
            if [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF].include?(b)
              sof = f.read(5)
              if sof && sof.bytesize == 5
                h, w = sof[1, 4].unpack("n2")
              end
              break
            else
              f.seek(seg_len - 2, IO::SEEK_CUR)
            end
          end
        end

        w = w.to_i
        h = h.to_i
        if fmt.nil? || w <= 0 || h <= 0
          return { "ok" => false, "error" => "UNSUPPORTED_OR_CORRUPT_IMAGE_HEADER" }
        end
        if w > max_dim || h > max_dim
          return { "ok" => false, "error" => "IMAGE_DIMENSIONS_EXCEEDED", "width" => w, "height" => h }
        end
        {
          "ok"         => true,
          "format"     => fmt,
          "width"      => w,
          "height"     => h,
          "rgba_bytes" => w * h * 4
        }
      end
    rescue StandardError => e
      { "ok" => false, "error" => "IMAGE_INSPECT_ERROR: #{e.message}" }
    end

    def self.create_private_import_staging_dir!
      base_tmp = Dir.tmpdir
      raise "UNSAFE_TMPDIR" if File.symlink?(base_tmp)
      if defined?(MapSKP::Bootstrap) && MapSKP::Bootstrap.respond_to?(:path_has_reparse_ancestor?)
        raise "UNSAFE_TMPDIR" if MapSKP::Bootstrap.path_has_reparse_ancestor?(base_tmp)
      end
      8.times do
        cand = File.join(base_tmp, "mapskp_stage_#{Process.pid}_#{Time.now.to_i}_#{SecureRandom.hex(8)}")
        next if File.exist?(cand) || File.symlink?(cand)
        Dir.mkdir(cand, 0o700)
        raise "UNSAFE_STAGING_DIR" if File.symlink?(cand)
        return cand
      end
      raise "STAGING_DIR_CREATE_FAILED: Không tạo được thư mục đệm riêng tư"
    end

    def self.cleanup_private_staging_dir!(stage_dir)
      return unless stage_dir && !stage_dir.to_s.empty?
      return if File.symlink?(stage_dir)
      return unless File.directory?(stage_dir)
      Dir.entries(stage_dir).each do |name|
        next if name == "." || name == ".."
        fp = File.join(stage_dir, name)
        if File.symlink?(fp)
          File.unlink(fp) rescue nil
        elsif File.file?(fp)
          File.delete(fp) rescue nil
        end
      end
      Dir.rmdir(stage_dir) rescue nil
    rescue StandardError
      nil
    end

    def self.create_exclusive_bounded_snapshot!(src_path, allowed_exts, stage_dir, dst_filename, max_bytes)
      unless safe_export_path?(src_path, allowed_exts)
        raise "OUTSIDE_ALLOWED_EXPORT_DIR: Đường dẫn tệp nguồn không hợp lệ (#{src_path})"
      end
      raise "OUTSIDE_ALLOWED_EXPORT_DIR: Tệp nguồn là liên kết mềm" if File.symlink?(src_path)
      raise "INVALID_SOURCE_FILE: Không tìm thấy tệp nguồn (#{File.basename(src_path.to_s)})" unless File.file?(src_path)
      raise "UNSAFE_STAGING_DIR" unless stage_dir && File.directory?(stage_dir) && !File.symlink?(stage_dir)

      clean_dst = File.basename(dst_filename.to_s)
      raise "UNSAFE_SNAPSHOT_NAME" if clean_dst.empty? || clean_dst == "." || clean_dst == ".."
      dst_path = File.join(stage_dir, clean_dst)
      raise "SNAPSHOT_ALREADY_EXISTS" if File.exist?(dst_path) || File.symlink?(dst_path)

      written_bytes = 0
      flags_out = File::WRONLY | File::CREAT | File::EXCL | File::BINARY
      begin
        File.open(src_path, File::RDONLY | File::BINARY) do |fin|
          st = fin.stat
          raise "INVALID_SOURCE_FILE" unless st.file?
          unless safe_export_path?(src_path, allowed_exts)
            raise "OUTSIDE_ALLOWED_EXPORT_DIR: Phát hiện thay đổi đường dẫn nguồn khi mở tệp"
          end
          if st.size <= 0 || st.size > max_bytes
            raise "RESOURCE_LIMIT_EXCEEDED: Dung lượng tệp vượt ngưỡng an toàn (#{max_bytes} bytes)"
          end

          File.open(dst_path, flags_out, 0o600) do |fout|
            buf = "".b
            while fin.read(SNAPSHOT_COPY_CHUNK_BYTES, buf)
              written_bytes += buf.bytesize
              if written_bytes > max_bytes
                raise "RESOURCE_LIMIT_EXCEEDED: Tệp phình vượt ngưỡng an toàn trong lúc tạo bản chụp"
              end
              fout.write(buf)
            end
            fout.flush
          end
        end
      rescue StandardError => e
        begin
          File.delete(dst_path) if File.file?(dst_path) && !File.symlink?(dst_path)
        rescue StandardError
          nil
        end
        raise e
      end

      if written_bytes <= 0
        File.delete(dst_path) rescue nil
        raise "RESOURCE_LIMIT_EXCEEDED: Bản chụp tệp rỗng không hợp lệ"
      end
      if File.symlink?(src_path) || !safe_export_path?(src_path, allowed_exts)
        File.delete(dst_path) rescue nil
        raise "OUTSIDE_ALLOWED_EXPORT_DIR: Phát hiện đánh tráo đường dẫn nguồn trong lúc sao chép"
      end
      [dst_path, written_bytes]
    end

    def self.preflight_validate_fallback_data!(data)
      raise "INVALID_FALLBACK_SCHEMA" unless data.is_a?(Hash)

      mats_raw = data["materials"]
      raise "INVALID_FALLBACK_SCHEMA" unless mats_raw.nil? || mats_raw.is_a?(Array)
      mats_meta = mats_raw || []
      if mats_meta.length > MAX_MATERIALS_COUNT
        raise "RESOURCE_LIMIT_EXCEEDED: Số lượng vật liệu vượt giới hạn an toàn (#{MAX_MATERIALS_COUNT})"
      end

      total_rgba_budget = 0
      mats_meta.each do |m|
        raise "INVALID_FALLBACK_SCHEMA: Material item không hợp lệ" unless m.is_a?(Hash)
        if m.key?("color") && !m["color"].nil?
          col = m["color"]
          raise "INVALID_FALLBACK_SCHEMA: Màu vật liệu không hợp lệ" unless col.is_a?(Array) && col.length >= 3
          raise "INVALID_FALLBACK_SCHEMA: Kênh màu không hợp lệ" unless strict_real_number?(col[0]) && strict_real_number?(col[1]) && strict_real_number?(col[2])
        end
        tex_p = m["tex_path"].to_s.strip
        unless tex_p.empty?
          unless safe_export_path?(tex_p, [".png", ".jpg", ".jpeg", ".webp", ".bmp"])
            raise "OUTSIDE_ALLOWED_EXPORT_DIR: Đường dẫn ảnh vật liệu không hợp lệ (#{tex_p})"
          end
          unless File.file?(tex_p) && !File.symlink?(tex_p)
            raise "INVALID_TEXTURE_FILE: Không tìm thấy ảnh vật liệu (#{File.basename(tex_p)})"
          end
          tex_sz = File.size(tex_p)
          if tex_sz <= 0 || tex_sz > MAX_TEXTURE_FILE_BYTES
            raise "RESOURCE_LIMIT_EXCEEDED: Dung lượng tệp ảnh vật liệu vượt ngưỡng cho phép"
          end
          dim = inspect_image_dimensions(tex_p, MAX_TEXTURE_DIM_PX)
          unless dim["ok"]
            raise "RESOURCE_LIMIT_EXCEEDED: Ảnh vật liệu không hợp lệ hoặc vượt 8192px (#{dim['error']})"
          end
          total_rgba_budget += dim["rgba_bytes"].to_i
          if total_rgba_budget > MAX_TOTAL_RGBA_BUDGET
            raise "RESOURCE_LIMIT_EXCEEDED: Tổng bộ nhớ giải mã ảnh vật liệu vượt ngưỡng an toàn (512 MB)"
          end
        end
      end

      layers_raw = data["layers"]
      raise "INVALID_FALLBACK_SCHEMA" unless layers_raw.nil? || layers_raw.is_a?(Array)
      layers_arr = layers_raw || []
      if layers_arr.length > MAX_LAYERS_COUNT
        raise "RESOURCE_LIMIT_EXCEEDED: Số lượng layer vượt giới hạn an toàn (#{MAX_LAYERS_COUNT})"
      end

      total_meshes = 0
      total_verts  = 0
      total_tris   = 0

      layers_arr.each do |ly|
        raise "INVALID_FALLBACK_SCHEMA: Layer không hợp lệ" unless ly.is_a?(Hash)
        meshes_raw = ly["meshes"]
        raise "INVALID_FALLBACK_SCHEMA: Danh sách mesh không hợp lệ" unless meshes_raw.nil? || meshes_raw.is_a?(Array)
        meshes_arr = meshes_raw || []
        total_meshes += meshes_arr.length
        if total_meshes > MAX_MESHES_COUNT
          raise "RESOURCE_LIMIT_EXCEEDED: Tổng số mesh vượt giới hạn an toàn (#{MAX_MESHES_COUNT})"
        end

        meshes_arr.each do |ms|
          raise "INVALID_FALLBACK_SCHEMA: Mesh không hợp lệ" unless ms.is_a?(Hash)
          verts_raw = ms["verts_m"]
          faces_raw = ms["faces"]
          uvs_raw   = ms["uvs"]
          raise "INVALID_FALLBACK_SCHEMA" unless verts_raw.nil? || verts_raw.is_a?(Array)
          raise "INVALID_FALLBACK_SCHEMA" unless faces_raw.nil? || faces_raw.is_a?(Array)
          raise "INVALID_FALLBACK_SCHEMA" unless uvs_raw.nil? || uvs_raw.is_a?(Array)

          verts = verts_raw || []
          faces = faces_raw || []
          uvs   = uvs_raw || []

          if uvs.length > verts.length
            raise "RESOURCE_LIMIT_EXCEEDED: Mảng UV lớn bất thường so với số đỉnh"
          end
          unless ms["mat_idx"].nil? || ms["mat_idx"].is_a?(Integer)
            raise "INVALID_FALLBACK_SCHEMA: mat_idx phải là số nguyên"
          end

          next if verts.empty? && faces.empty?
          raise "FACE_INDEX_OUT_OF_RANGE" if verts.empty? && !faces.empty?

          total_verts += verts.length
          total_tris  += faces.length
          if total_verts > MAX_FALLBACK_VERTICES || total_tris > MAX_FALLBACK_TRIANGLES
            raise "RESOURCE_LIMIT_EXCEEDED: Số lượng đỉnh/tam giác vượt giới hạn an toàn (600.000)"
          end

          has_uvs = (uvs.length == verts.length)
          verts.each_with_index do |v, v_i|
            raise "INVALID_VERTEX_TUPLE" unless v.is_a?(Array) && v.length >= 3
            unless strict_real_number?(v[0]) && strict_real_number?(v[1]) && strict_real_number?(v[2])
              raise "INVALID_VERTEX_COORDINATE"
            end
            vx = v[0].to_f
            vy = v[1].to_f
            vz = v[2].to_f
            unless vx.abs <= MAX_COORD_ABS_M && vy.abs <= MAX_COORD_ABS_M && vz.abs <= MAX_COORD_ABS_M
              raise "INVALID_VERTEX_COORDINATE"
            end
            if has_uvs
              uv_pair = uvs[v_i]
              unless uv_pair.is_a?(Array) && uv_pair.length >= 2 && strict_real_number?(uv_pair[0]) && strict_real_number?(uv_pair[1])
                raise "INVALID_UV_COORDINATE"
              end
            end
          end

          v_len = verts.length
          faces.each do |tri|
            raise "INVALID_FACE_TUPLE" unless tri.is_a?(Array) && tri.length >= 3
            unless tri[0].is_a?(Integer) && tri[1].is_a?(Integer) && tri[2].is_a?(Integer)
              raise "INVALID_FACE_TUPLE"
            end
            idx0 = tri[0]
            idx1 = tri[1]
            idx2 = tri[2]
            if idx0 < 0 || idx1 < 0 || idx2 < 0 || idx0 >= v_len || idx1 >= v_len || idx2 >= v_len
              raise "FACE_INDEX_OUT_OF_RANGE"
            end
          end
        end
      end

      true
    end

    def self.import_manifest!(model, manifest)
      raise "Chưa có bản vẽ SketchUp đang mở" unless model
      raise "Dữ liệu manifest không hợp lệ" unless manifest.is_a?(Hash)

      origin = manifest["origin"].is_a?(Hash) ? manifest["origin"] : {}
      if !origin.empty? && !valid_geo_meta_hash?(origin)
        raise "INVALID_ORIGIN_METADATA: Tọa độ gốc trong manifest không hợp lệ"
      end
      slug = manifest["slug"].to_s.strip.gsub(/[^\p{L}\p{N}_\- ]/u, "")[0, MAX_LABEL_CHARS]
      slug = "MapSKP_Context" if slug.empty?
      job_id_str = manifest["job_id"].to_s.strip[0, 128]

      skp_path      = manifest["skp_path"].to_s.strip
      fallback_path = manifest["fallback_json_path"].to_s.strip
      if skp_path.empty? && fallback_path.empty?
        raise "Không tìm thấy tệp .skp hoặc dữ liệu lưới dự phòng để nạp"
      end

      if !skp_path.empty? && !safe_export_path?(skp_path, [".skp"])
        raise "OUTSIDE_ALLOWED_EXPORT_DIR: Đường dẫn tệp .skp nằm ngoài vùng xuất an toàn của MapSKP"
      end
      if !fallback_path.empty? && !safe_export_path?(fallback_path, [".json"])
        raise "OUTSIDE_ALLOWED_EXPORT_DIR: Đường dẫn tệp dữ liệu lưới nằm ngoài vùng xuất an toàn của MapSKP"
      end

      existing = find_linked_tiles(model)
      seq_num  = existing.length + 1
      if !existing.empty? && !valid_geo_meta_hash?(origin)
        raise "INVALID_ORIGIN_METADATA: Thiếu tọa độ gốc hợp lệ để ghép Mảnh ##{seq_num}"
      end

      op_started        = false
      private_stage_dir = nil

      begin
        target_tr = Geom::Transformation.new(ORIGIN)
        unless existing.empty?
          target_tr = compute_linked_transform(existing[0][2], existing[0][3], origin)
        end

        private_stage_dir = create_private_import_staging_dir!

        if !skp_path.empty? && File.file?(skp_path)
          defn = nil
          tmp_skp, skp_snap_bytes = create_exclusive_bounded_snapshot!(
            skp_path,
            [".skp"],
            private_stage_dir,
            "import_payload.skp",
            MAX_SKP_IMPORT_BYTES
          )
          if skp_snap_bytes < 16
            raise "INVALID_SKP_SNAPSHOT: Bản chụp .skp quá nhỏ hoặc bị cắt cụt"
          end

          model.start_operation("MapSKP — Nạp & Ghép Bối Cảnh Bản Đồ 3D (Mảnh ##{seq_num})", true)
          op_started = true

          begin
            defn = model.definitions.load(tmp_skp)
          rescue StandardError
            defn = nil
          end

          if defn
            carrier_meta = peek_definition_meta(defn)
            if !carrier_meta.nil? && !valid_geo_meta_hash?(carrier_meta)
              raise "INVALID_CARRIER_METADATA: Dữ liệu nhúng trong .skp không hợp lệ"
            end
            commit_definition_meta_cleanup!(defn, carrier_meta) if carrier_meta

            apply_geo_shadow!(model, origin) if existing.empty? && !origin.empty?
            master_tag = ensure_tag(model, "MapSKP_00_Master_Context", [233, 69, 96])

            clean_def_name = model.definitions.unique_name("#{slug}_P#{seq_num}")
            defn.name = clean_def_name

            inst = model.active_entities.add_instance(defn, target_tr)
            inst.name  = clean_def_name
            inst.layer = master_tag
            stamp_instance_meta!(inst, origin, seq_num, job_id_str)

            model.commit_operation
            op_started = false

            model.active_view.zoom_extents if model.active_view
            return {
              "ok"             => true,
              "method"         => "c_api_definitions_load",
              "component_name" => clean_def_name,
              "seq"            => seq_num,
              "triangles"      => manifest["triangles"].to_i,
              "origin"         => origin,
              "anchor_state"   => scan_anchor_state(model)
            }
          else
            # Phiên bản C SDK không tương thích (ví dụ SU cũ đọc SKP mới): hủy operation sạch trước khi chuyển sang fallback
            model.abort_operation if op_started
            op_started = false
          end
        end

        if !fallback_path.empty? && File.file?(fallback_path)
          model.start_operation("MapSKP — Nạp & Ghép Bối Cảnh Bản Đồ 3D (Mảnh ##{seq_num})", true)
          op_started = true
          res_fb = import_polygon_mesh_fallback!(
            model,
            fallback_path,
            nil,
            "#{slug}_P#{seq_num}",
            target_tr,
            origin,
            seq_num,
            job_id_str,
            existing.empty?,
            private_stage_dir
          )
          model.commit_operation
          op_started = false
          model.active_view.zoom_extents if model.active_view
          res_fb["anchor_state"] = scan_anchor_state(model)
          return res_fb
        end

        raise "Không tìm thấy tệp .skp hoặc dữ liệu lưới dự phòng để nạp"
      rescue StandardError => e
        model.abort_operation if op_started
        return {
          "ok"    => false,
          "error" => e.message
        }
      ensure
        cleanup_private_staging_dir!(private_stage_dir) if private_stage_dir
      end
    end

    def self.import_polygon_mesh_fallback!(model, json_path, master_tag, slug, target_tr, origin, seq_num, job_id, apply_shadow_if_first = false, caller_stage_dir = nil)
      owns_stage_dir = caller_stage_dir.nil?
      stage_dir = caller_stage_dir || create_private_import_staging_dir!

      begin
        snap_json, _json_sz = create_exclusive_bounded_snapshot!(
          json_path,
          [".json"],
          stage_dir,
          "fallback_mesh.json",
          MAX_FALLBACK_JSON_BYTES
        )

        raw_bytes = File.binread(snap_json)
        if raw_bytes.nil? || raw_bytes.empty? || raw_bytes.bytesize > MAX_FALLBACK_JSON_BYTES
          raise "RESOURCE_LIMIT_EXCEEDED: Tệp lưới dự phòng vượt quá giới hạn an toàn (64 MB)"
        end

        raw = raw_bytes.force_encoding("UTF-8")
        raise "INVALID_FALLBACK_ENCODING" unless raw.valid_encoding?
        data = JSON.parse(raw, max_nesting: 32)
        preflight_validate_fallback_data!(data)

        mats_meta = data["materials"].is_a?(Array) ? data["materials"] : []
        staged_tex_by_idx = {}
        cumulative_rgba_budget = 0
        cumulative_tex_bytes   = 0

        # Bước 1 (Astra #15): Chụp độc quyền toàn bộ ảnh vật liệu & kiểm định lại hạn mức lũy kế TRƯỚC khi sửa model
        mats_meta.each_with_index do |m, idx|
          tex_p = m["tex_path"].to_s.strip
          next if tex_p.empty?

          tex_ext = File.extname(tex_p).downcase
          staged_tex, actual_sz = create_exclusive_bounded_snapshot!(
            tex_p,
            [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
            stage_dir,
            format("tex_%04d%s", idx, tex_ext),
            MAX_TEXTURE_FILE_BYTES
          )
          if actual_sz <= 0 || actual_sz > MAX_TEXTURE_FILE_BYTES
            raise "RESOURCE_LIMIT_EXCEEDED: Dung lượng bản chụp ảnh vật liệu vượt ngưỡng cho phép"
          end
          cumulative_tex_bytes += actual_sz
          if cumulative_tex_bytes > MAX_TOTAL_TEXTURE_FILE_BYTES
            raise "RESOURCE_LIMIT_EXCEEDED: Tổng dung lượng tệp ảnh vật liệu vượt ngưỡng an toàn (256 MB)"
          end

          dim_check = inspect_image_dimensions(staged_tex, MAX_TEXTURE_DIM_PX)
          unless dim_check["ok"]
            raise "RESOURCE_LIMIT_EXCEEDED: Bản chụp ảnh vật liệu không hợp lệ (#{dim_check['error']})"
          end
          cumulative_rgba_budget += dim_check["rgba_bytes"].to_i
          if cumulative_rgba_budget > MAX_TOTAL_RGBA_BUDGET
            raise "RESOURCE_LIMIT_EXCEEDED: Tổng bộ nhớ giải mã bản chụp ảnh vượt ngưỡng an toàn (512 MB)"
          end

          staged_tex_by_idx[idx] = staged_tex
        end

        apply_geo_shadow!(model, origin) if apply_shadow_if_first && !origin.empty?
        master_tag ||= ensure_tag(model, "MapSKP_00_Master_Context", [233, 69, 96])

        su_mats = []
        mats_meta.each_with_index do |m, idx|
          mat = allocate_safe_material(model, m["name"], idx)
          col = m["color"].is_a?(Array) ? m["color"] : [210, 210, 210, 255]
          r_c = [[col[0].to_i, 0].max, 255].min
          g_c = [[col[1].to_i, 0].max, 255].min
          b_c = [[col[2].to_i, 0].max, 255].min
          mat.color = Sketchup::Color.new(r_c, g_c, b_c)
          mat.alpha = (col[3].to_f / 255.0) if col.length >= 4 && strict_real_number?(col[3]) && col[3].to_i < 254
          staged_tex = staged_tex_by_idx[idx]
          if staged_tex
            mat.texture = staged_tex
            raise "TEXTURE_LOAD_FAILED: SketchUp không nạp được ảnh vật liệu" unless mat.texture
            mat.texture.size = [INCH_PER_METER, INCH_PER_METER] if mat.texture
          end
          su_mats << mat
        end

        root_grp = model.active_entities.add_group
        root_grp.name  = slug.to_s[0, MAX_LABEL_CHARS]
        root_grp.layer = master_tag
        total_tris  = 0
        total_verts = 0

        layers_arr = data["layers"].is_a?(Array) ? data["layers"] : []
        layers_arr.each do |ly|
          tag_obj = ensure_tag(model, ly["tag"], ly["tag_color"])
          sub_grp = root_grp.entities.add_group
          sub_grp.name  = ly["name"].to_s[0, MAX_LABEL_CHARS]
          sub_grp.layer = tag_obj

          meshes_arr = ly["meshes"].is_a?(Array) ? ly["meshes"] : []
          meshes_arr.each do |ms|
            verts = ms["verts_m"].is_a?(Array) ? ms["verts_m"] : []
            faces = ms["faces"].is_a?(Array) ? ms["faces"] : []
            uvs   = ms["uvs"].is_a?(Array) ? ms["uvs"] : []
            next if verts.empty? || faces.empty?

            total_verts += verts.length
            if total_verts > MAX_FALLBACK_VERTICES || (total_tris + faces.length) > MAX_FALLBACK_TRIANGLES
              raise "RESOURCE_LIMIT_EXCEEDED: Số lượng đỉnh/tam giác vượt giới hạn an toàn (600.000)"
            end

            has_uvs = (uvs.length == verts.length)
            pm = Geom::PolygonMesh.new(verts.length, faces.length)
            pts_idx = []
            verts.each_with_index do |v, v_i|
              vx = v[0].to_f
              vy = v[1].to_f
              vz = v[2].to_f
              p_idx = pm.add_point(Geom::Point3d.new(vx * INCH_PER_METER, vy * INCH_PER_METER, vz * INCH_PER_METER))
              if has_uvs && p_idx
                uv_pair = uvs[v_i]
                u_val = uv_pair[0].to_f
                v_val = uv_pair[1].to_f
                uv_pt = Geom::Point3d.new(u_val, v_val, 1.0)
                pm.set_uv(p_idx, uv_pt, true)
                pm.set_uv(p_idx, uv_pt, false)
              end
              pts_idx << p_idx
            end
            faces.each do |tri|
              idx0 = tri[0]
              idx1 = tri[1]
              idx2 = tri[2]
              i0 = pts_idx[idx0]
              i1 = pts_idx[idx1]
              i2 = pts_idx[idx2]
              pm.add_polygon(i0, i1, i2) if i0 && i1 && i2
            end

            midx = ms["mat_idx"].is_a?(Integer) ? ms["mat_idx"] : -1
            use_mat = (midx >= 0 && midx < su_mats.length) ? su_mats[midx] : nil
            sub_grp.entities.fill_from_mesh(pm, true, Geom::PolygonMesh::AUTO_SOFTEN, use_mat, use_mat)
            total_tris += faces.length
          end
        end

        root_grp.transformation = target_tr
        stamp_instance_meta!(root_grp, origin, seq_num, job_id)

        {
          "ok"             => true,
          "method"         => "ruby_polygon_mesh",
          "component_name" => slug.to_s[0, MAX_LABEL_CHARS],
          "seq"            => seq_num,
          "triangles"      => total_tris,
          "origin"         => origin
        }
      ensure
        cleanup_private_staging_dir!(stage_dir) if owns_stage_dir && stage_dir
      end
    end
  end
end
