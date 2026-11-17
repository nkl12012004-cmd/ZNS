# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'json'
require 'tmpdir'
require 'fileutils'
require 'base64'

module OpenMapSketchUp
  # Loads the file produced by the original SketchUp SDK writer. Geometry,
  # embedded materials, UVs and component hierarchy are not reconstructed here.
  module OriginalSKPImporter
    MAX_SKP_BYTES = 140_000_000
    MAX_METADATA_BYTES = 262_144
    class NativeLoadError < StandardError; end

    def self.validate_payload!(bytes)
      raise NativeLoadError, 'Bộ ghi SDK chưa trả tệp SKP.' unless bytes.is_a?(String) && !bytes.empty?
      raise 'Tệp SKP vượt giới hạn 140 MB. Hãy chia nhỏ vùng chọn.' if bytes.bytesize > MAX_SKP_BYTES
      true
    end

    def self.validate_manifest!(data)
      raise 'Manifest SKP gốc không hợp lệ.' unless data.is_a?(Hash) && data['engine'] == 'original' && data['native_skp_ready'] == true
      raise 'Metadata SKP vượt giới hạn.' if JSON.generate(data).bytesize > MAX_METADATA_BYTES
      anchor, origin = data['anchor'], data['origin']
      raise 'Mốc SKP gốc không hợp lệ.' unless Importer.valid_anchor?(anchor)
      raise 'Origin SKP gốc không hợp lệ.' unless origin.is_a?(Hash) && Importer.finite_number?(origin['lat'], 80) && Importer.finite_number?(origin['lon'], 180)
      shift = origin['offset_from_anchor_m']
      raise 'Độ dịch SKP gốc không hợp lệ.' unless shift.is_a?(Array) && shift.length == 3 && shift.all? { |value| Importer.finite_number?(value) }
      box = data['bbox']
      raise 'Vùng SKP gốc không hợp lệ.' unless box.is_a?(Hash) && %w[south north].all? { |key| Importer.finite_number?(box[key], 80) } && %w[west east].all? { |key| Importer.finite_number?(box[key], 180) } && box['south'] < box['north'] && box['west'] < box['east']
      center = data['center'] || { 'lat' => origin['lat'], 'lon' => origin['lon'] }
      raise 'Tâm SKP gốc không hợp lệ.' unless center.is_a?(Hash) && Importer.finite_number?(center['lat'], 80) && Importer.finite_number?(center['lon'], 180)
      raise 'Số tam giác SKP gốc không hợp lệ.' unless data['triangles'].is_a?(Integer) && data['triangles'].between?(0, 2_000_000)
      %w[warnings attribution missing_layers].each do |key|
        next if data[key].nil?
        raise 'Metadata văn bản SKP gốc không hợp lệ.' unless data[key].is_a?(Array) && data[key].length <= 64 && data[key].all? { |value| value.is_a?(String) && value.bytesize <= 4096 }
      end
      raise 'Tham số SKP gốc không hợp lệ.' unless data['parameters'].nil? || data['parameters'].is_a?(Hash)
      data
    end

    def self.ensure_model!(model, data)
      raise 'Bạn đã chuyển mô hình trong lúc tải. Quay lại mô hình ban đầu.' unless Sketchup.active_model.equal?(model)
      existing = Importer.anchor(model)
      if existing && !Importer.same_anchor?(existing, data['anchor'])
        raise 'Mốc mô hình đã thay đổi. Hãy dựng lại mảnh với mốc hiện tại.'
      end
      existing
    end

    def self.placement(model, data)
      Linking.transform_for(model, data['origin'])
    end

    def self.stamp(entity, data, job_id)
      dictionary = Importer::DICTIONARY
      entity.set_attribute(dictionary, 'job_id', job_id)
      entity.set_attribute(dictionary, 'engine', 'original')
      entity.set_attribute(dictionary, 'anchor', JSON.generate(data['anchor']))
      entity.set_attribute(dictionary, 'original_origin', JSON.generate(data['origin']))
      entity.set_attribute(dictionary, 'bbox', JSON.generate(data['bbox']))
      entity.set_attribute(dictionary, 'attribution', JSON.generate(data['attribution'] || []))
      entity.set_attribute(dictionary, 'warnings', JSON.generate(data['warnings'] || []))
      entity.set_attribute(dictionary, 'partial', !!data['partial'])
      entity.set_attribute(dictionary, 'missing_layers', JSON.generate(data['missing_layers'] || []))
    end

    def self.carrier_origin(entity)
      return nil unless entity.is_a?(Sketchup::Group) && entity.entities.length.zero?
      text = entity.name.to_s.sub(/\A__MAPSKP_META__/, '')
      return nil unless entity.name.to_s.start_with?('__MAPSKP_META__') && text.bytesize.between?(1, 32_768) && text =~ /\A[A-Za-z0-9_\-]+=*\z/
      decoded = Base64.urlsafe_decode64(text + '=' * ((4 - text.length % 4) % 4))
      return nil if decoded.bytesize > MAX_METADATA_BYTES
      value = JSON.parse(decoded, max_nesting: 16)
      return nil unless value.is_a?(Hash) && Importer.finite_number?(value['lat'], 80) && Importer.finite_number?(value['lon'], 180)
      value
    rescue ArgumentError, JSON::ParserError, EncodingError
      nil
    end

    def self.same_origin?(candidate, origin)
      return false unless candidate
      %w[lat lon elevation_m anchor_lat anchor_lon anchor_elev_m].all? do |key|
        !candidate.key?(key) || (origin[key].is_a?(Numeric) && candidate[key].is_a?(Numeric) && (candidate[key] - origin[key]).abs < 1e-8)
      end && (!candidate.key?('offset_from_anchor_m') || candidate['offset_from_anchor_m'] == origin['offset_from_anchor_m'])
    end

    def self.strip_legacy_carriers(definition, origin)
      # This is only called on a new/private definition. Preserve the raw origin
      # in OpenMap attributes, then prevent a concurrently installed old plugin
      # from applying its automatic geographic translation a second time.
      definition.delete_attribute('MapSKP_Meta', 'origin_json')
      definition.entities.to_a.each do |entity|
        entity.erase! if same_origin?(carrier_origin(entity), origin)
      end
    end

    def self.import!(model, bytes, data, job_id, &validate_context)
      validate_payload!(bytes)
      validate_manifest!(data)
      validate_context.call if validate_context
      existing = ensure_model!(model, data)
      directory = Dir.mktmpdir('openmap_original_skp_')
      operation = false
      begin
        path = File.join(directory, 'original.skp')
        File.open(path, File::WRONLY | File::CREAT | File::EXCL, 0600) { |file| file.binmode; file.write(bytes) }
        ensure_model!(model, data)
        validate_context.call if validate_context
        before = model.definitions.to_a
        frame = Linking.frame(model)
        transform = placement(model, data)
        model.start_operation('SiteCraft — Nạp SKP gốc', true)
        operation = true
        begin
          definition = model.definitions.load(path)
          raise 'Không đọc được định nghĩa SKP.' unless definition && (!definition.respond_to?(:valid?) || definition.valid?)
        rescue StandardError => error
          raise NativeLoadError, 'SketchUp không nạp được SKP SDK: ' + error.message
        end
        ensure_model!(model, data)
        validate_context.call if validate_context
        instance = model.entities.add_instance(definition, transform)
        if before.include?(definition)
          instance.make_unique
          definition = instance.definition
          if before.include?(definition)
            raise NativeLoadError, 'Không tách được định nghĩa SKP riêng; giữ nguyên định nghĩa đã có.'
          end
        end
        ensure_model!(model, data)
        validate_context.call if validate_context
        label = data['name'].is_a?(String) ? data['name'][0, 80] : 'SiteCraft'
        instance.name = '%s_%s' % [label, job_id[0, 8]]
        stamp(definition, data, job_id)
        stamp(instance, data, job_id)
        instance.set_attribute(Importer::DICTIONARY, 'linked', true)
        instance.set_attribute(Importer::DICTIONARY, 'master', true) unless existing
        strip_legacy_carriers(definition, data['origin'])
        model.set_attribute(Importer::DICTIONARY, 'anchor', JSON.generate(data['anchor']))
        model.set_attribute(Importer::DICTIONARY, 'frame', JSON.generate(frame.to_a)) unless existing
        center = data['center'] || { 'lat' => data['origin']['lat'], 'lon' => data['origin']['lon'] }
        reference = Importer.tile_reference({ 'center' => center, 'bbox' => data['bbox'], 'parameters' => data['parameters'] || {},
                                               'hill_patch' => data.key?('hill_patch') ? data['hill_patch'] : data['origin']['hill_patch'] })
        model.set_attribute(Importer::DICTIONARY, 'last_tile', JSON.generate(reference)) if reference
        model.shadow_info['Latitude'] = center['lat']
        model.shadow_info['Longitude'] = center['lon']
        model.shadow_info['NorthAngle'] = 0
        model.commit_operation
        operation = false
        warnings = (data['warnings'] || []).dup
        begin
          if Sketchup.active_model.equal?(model)
            model.selection.clear
            model.selection.add(instance)
            model.active_view.zoom(instance)
          end
        rescue StandardError
          warnings << 'Đã nạp SKP gốc; không cập nhật được vùng chọn/góc nhìn.'
        end
        { 'name' => instance.name, 'triangles' => data['triangles'], 'warnings' => warnings, 'engine' => 'original', 'native_skp' => true }
      rescue StandardError
        model.abort_operation if operation
        raise
      ensure
        begin
          FileUtils.remove_entry(directory) if File.directory?(directory)
        rescue SystemCallError
          # A cleanup error must not report a committed import as failed and
          # prompt a duplicate import. The private OS temp directory may remain.
          warn('SiteCraft: không xóa được thư mục SKP tạm sau khi nạp.')
        end
      end
    end
  end
end

