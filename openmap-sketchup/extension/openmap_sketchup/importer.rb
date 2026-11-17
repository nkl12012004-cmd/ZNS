# encoding: UTF-8
# SPDX-License-Identifier: MIT
require 'json'
require 'base64'
require 'tmpdir'
require 'fileutils'

module OpenMapSketchUp
  module Importer
    DICTIONARY = 'OpenMapSketchUp'.freeze
    INCHES = 39.37007874015748

    def self.finite_number?(number, maximum = 500_000)
      number.is_a?(Numeric) && !number.is_a?(Complex) && number.to_f.finite? && number.abs <= maximum
    end

    def self.valid_anchor?(value)
      value.is_a?(Hash) && finite_number?(value['lat'], 80) && finite_number?(value['lon'], 180) && finite_number?(value['elevation'], 20_000)
    end

    def self.image_bytes(material)
      Base64.strict_decode64(material['texture_png'] || material['texture_jpeg'])
    end

    def self.jpeg_size(bytes)
      raise 'Ảnh JPEG không hợp lệ.' unless bytes.byteslice(0, 2) == "\xff\xd8".b
      offset = 2
      while offset + 4 <= bytes.bytesize
        offset += 1 while offset < bytes.bytesize && bytes.getbyte(offset) != 255
        offset += 1 while offset < bytes.bytesize && bytes.getbyte(offset) == 255
        marker = bytes.getbyte(offset)
        offset += 1
        next if marker == 1 || (marker && marker.between?(208, 215))
        break if marker.nil? || [217, 218].include?(marker) || offset + 2 > bytes.bytesize
        length = bytes.byteslice(offset, 2).unpack('n')[0]
        raise 'Đoạn JPEG không hợp lệ.' if length < 2 || offset + length > bytes.bytesize
        return bytes.byteslice(offset + 3, 4).unpack('nn').reverse if [192, 193, 194].include?(marker) && length >= 7
        offset += length
      end
      raise 'Không đọc được kích thước JPEG.'
    end

    def self.anchor(model)
      raw = model.get_attribute(DICTIONARY, 'anchor')
      return nil unless raw.is_a?(String)
      value = JSON.parse(raw)
      valid_anchor?(value) ? value : nil
    rescue JSON::ParserError
      nil
    end

    def self.valid_tile_reference(value)
      return nil unless value.is_a?(Hash)
      center, bbox = value['center'], value['bbox']
      width, height = value['width'], value['height']
      return nil unless center.is_a?(Hash) && bbox.is_a?(Hash)
      return nil unless finite_number?(center['lat'], 80) && finite_number?(center['lon'], 180)
      return nil unless [width, height].all? { |number| finite_number?(number, 10_000) && number >= 10 }
      return nil unless %w[south north].all? { |key| finite_number?(bbox[key], 80) }
      return nil unless %w[west east].all? { |key| finite_number?(bbox[key], 180) }
      return nil unless bbox['south'] < bbox['north'] && bbox['west'] < bbox['east']
      return nil unless (center['lat'] - (bbox['north'] + bbox['south']) / 2.0).abs < 1e-7
      return nil unless (center['lon'] - (bbox['east'] + bbox['west']) / 2.0).abs < 1e-7
      latitude = center['lat'] * Math::PI / 180.0
      ellipsoid = 1 - 0.0066943799901413165 * Math.sin(latitude)**2
      lat_scale = Math::PI / 180.0 * 6_378_137 * (1 - 0.0066943799901413165) / ellipsoid**1.5
      lon_scale = Math::PI / 180.0 * 6_378_137 * Math.cos(latitude) / Math.sqrt(ellipsoid)
      return nil unless ((bbox['east'] - bbox['west']) * lon_scale - width).abs <= [1.0, width * 0.01].max
      return nil unless ((bbox['north'] - bbox['south']) * lat_scale - height).abs <= [1.0, height * 0.01].max
      { 'center' => center.select { |key, _| %w[lat lon].include?(key) },
        'bbox' => bbox.select { |key, _| %w[south north west east].include?(key) },
        'width' => width, 'height' => height }
    end

    def self.tile_reference(data)
      return nil unless data.is_a?(Hash) && !data['hill_patch'] && data['parameters'].is_a?(Hash)
      valid_tile_reference({ 'center' => data['center'], 'bbox' => data['bbox'],
                             'width' => data['parameters']['width'], 'height' => data['parameters']['height'] })
    end

    def self.last_tile(model)
      raw = model.get_attribute(DICTIONARY, 'last_tile')
      return nil unless raw.is_a?(String) && raw.bytesize <= 4096 && raw.valid_encoding?
      valid_tile_reference(JSON.parse(raw, max_nesting: 8))
    rescue JSON::ParserError, EncodingError, TypeError
      nil
    end

    def self.validate!(data)
      raise 'Định dạng mô hình không hợp lệ.' unless data.is_a?(Hash) && data['schema'] == 'openmap.mesh.v1' && valid_anchor?(data['anchor'])
      center = data['center']
      raise 'Tâm bản đồ không hợp lệ.' unless center.is_a?(Hash) && finite_number?(center['lat'], 80) && finite_number?(center['lon'], 180)
      attribution = data['attribution']
      raise 'Thông tin nguồn không hợp lệ.' unless attribution.is_a?(Array) && attribution.length <= 16 && attribution.all? { |text| text.is_a?(String) && text.bytesize <= 4096 }
      materials, meshes = data['materials'], data['meshes']
      raise 'Danh sách vật liệu không hợp lệ.' unless materials.is_a?(Array) && materials.length.between?(1, 256)
      raise 'Danh sách lưới không hợp lệ.' unless meshes.is_a?(Array) && meshes.length.between?(1, 4096)
      vertices_count, triangle_count, texture_bytes, decoded_rgba = 0, 0, 0, 0
      materials.each do |material|
        raise 'Vật liệu không hợp lệ.' unless material.is_a?(Hash)
        color = material['color']
        raise 'Màu vật liệu không hợp lệ.' unless color.is_a?(Array) && color.length == 3 && color.all? { |c| c.is_a?(Integer) && c.between?(0, 255) }
        encoded = material['texture_png'] || material['texture_jpeg']
        next unless encoded
        raise 'Ảnh vật liệu quá lớn.' unless encoded.is_a?(String) && encoded.bytesize <= 96_000_000
        bytes = Base64.strict_decode64(encoded)
        texture_bytes += bytes.bytesize
        raise 'Tổng ảnh vật liệu vượt giới hạn 256 MB.' if texture_bytes > 256 * 1024 * 1024
        raise 'Ảnh vật liệu quá lớn.' if bytes.bytesize > 72_000_000
        if material['texture_jpeg']
          size = jpeg_size(bytes)
        else
          raise 'Ảnh vật liệu không phải PNG.' unless bytes.start_with?("\x89PNG\r\n\x1a\n".b) && bytes.bytesize >= 24
          size = bytes.byteslice(16, 8).unpack('NN')
        end
        raise 'Kích thước ảnh không hợp lệ.' unless size.all? { |dimension| dimension.between?(1, 8192) }
        decoded_rgba += size[0] * size[1] * 4
        raise 'Tổng ảnh giải mã vượt giới hạn 512 MB.' if decoded_rgba > 512 * 1024 * 1024
      end
      meshes.each do |mesh|
        raise 'Lưới không hợp lệ.' unless mesh.is_a?(Hash)
        vertices, triangles, uv = mesh['vertices'], mesh['triangles'], mesh['uv']
        raise 'Đỉnh hoặc tam giác không hợp lệ.' unless vertices.is_a?(Array) && triangles.is_a?(Array) && !vertices.empty? && !triangles.empty?
        vertices_count += vertices.length
        triangle_count += triangles.length
        raise 'Mô hình quá lớn; hãy chia nhỏ vùng chọn.' if vertices_count > 600_000 || triangle_count > 600_000
        raise 'Tọa độ đỉnh không hợp lệ.' unless vertices.all? { |v| v.is_a?(Array) && v.length == 3 && v.all? { |number| finite_number?(number) } }
        raise 'Chỉ số tam giác không hợp lệ.' unless triangles.all? { |t| t.is_a?(Array) && t.length == 3 && t.uniq.length == 3 && t.all? { |index| index.is_a?(Integer) && index.between?(0, vertices.length - 1) } }
        raise 'UV không hợp lệ.' unless uv.is_a?(Array) && (uv.empty? || (uv.length == vertices.length && uv.all? { |v| v.is_a?(Array) && v.length == 2 && v.all? { |number| finite_number?(number, 65536) } }))
        raise 'Chỉ số vật liệu không hợp lệ.' unless mesh['material'].is_a?(Integer) && mesh['material'].between?(0, materials.length - 1)
        if mesh.key?('layer_index')
          raise 'Chỉ số lớp gốc không hợp lệ.' unless mesh['layer_index'].is_a?(Integer) && mesh['layer_index'].between?(0, 255)
          raise 'Tên lớp gốc không hợp lệ.' unless mesh['layer_name'].is_a?(String) && mesh['layer_name'].bytesize <= 256 && mesh['tag'].is_a?(String) && mesh['tag'].bytesize <= 256
          raise 'Màu tag không hợp lệ.' unless mesh['tag_color'].is_a?(Array) && mesh['tag_color'].length == 3 && mesh['tag_color'].all? { |v| v.is_a?(Integer) && v.between?(0, 255) }
        end
      end
      if data['original_geometry_preserved']
        origin = data['original_origin']
        offset = origin.is_a?(Hash) ? origin['offset_from_anchor_m'] : nil
        raise 'Độ dịch mảnh gốc không hợp lệ.' unless offset.is_a?(Array) && offset.length == 3 && offset.all? { |v| finite_number?(v) }
      end
      true
    end

    def self.same_anchor?(a, b)
      valid_anchor?(a) && valid_anchor?(b) && %w[lat lon elevation].all? { |key| (a[key] - b[key]).abs < 1e-8 }
    end

    def self.import!(model, data, job_id)
      validate!(data)
      existing = anchor(model)
      raise 'Mốc mô hình đã thay đổi. Hãy dựng lại mảnh với mốc hiện tại.' if existing && !same_anchor?(existing, data['anchor'])
      directory = Dir.mktmpdir('openmap_texture_')
      operation = false
      begin
        model.start_operation('SiteCraft — Nạp bản đồ', true)
        operation = true
        materials = data['materials'].each_with_index.map do |metadata, index|
          material_name = data['original_geometry_preserved'] ? metadata['name'].to_s[0, 96] : 'OpenMap_%s_%d' % [job_id[0, 8], index]
          material_name = 'OpenMap_%s_%d' % [job_id[0, 8], index] if material_name.empty? || model.materials[material_name]
          material = model.materials.add(material_name)
          material.color = Sketchup::Color.new(*metadata['color'])
          material.alpha = metadata['alpha'].to_f if metadata['alpha'] && finite_number?(metadata['alpha'], 1) && metadata['alpha'] >= 0
          if metadata['texture_png'] || metadata['texture_jpeg']
            path = File.join(directory, 'texture_%d.%s' % [index, metadata['texture_jpeg'] ? 'jpg' : 'png'])
            File.binwrite(path, image_bytes(metadata))
            material.texture = path
            raise 'SketchUp không nạp được ảnh vật liệu.' unless material.texture
            material.texture.size = [INCHES, INCHES]
          end
          material
        end
        root = model.entities.add_group
        if defined?(Linking)
          root.transformation = if data['original_geometry_preserved']
                                  Linking.transform_for(model, data['original_origin'])
                                else
                                  Linking.frame(model)
                                end
          root.set_attribute(DICTIONARY, 'master', true) unless existing
        end
        label = data['name'].is_a?(String) ? data['name'][0, 80] : 'SiteCraft'
        root.name = '%s_%s' % [label, job_id[0, 8]]
        original_groups = {}
        data['meshes'].each do |value|
          group_key = value['layer_index']
          child = group_key.nil? ? nil : original_groups[group_key]
          unless child
            child = root.entities.add_group
            child.name = (value['layer_name'] || value['name']).to_s[0, 96]
            tag_name = value['tag'] || 'OpenMap_' + child.name
            child.layer = model.layers[tag_name] || model.layers.add(tag_name)
            child.layer.color = Sketchup::Color.new(*value['tag_color']) if value['tag_color']
            original_groups[group_key] = child unless group_key.nil?
          end
          geometry = Geom::PolygonMesh.new(value['vertices'].length, value['triangles'].length)
          lookup = value['vertices'].map do |v|
            geometry.add_point(Geom::Point3d.new(v.map { |coordinate| coordinate * INCHES }))
          end
          unless value['uv'].empty?
            value['uv'].each_with_index do |pair, index|
              uv = Geom::Point3d.new(pair[0], pair[1], 1)
              geometry.set_uv(lookup[index], uv, true)
              geometry.set_uv(lookup[index], uv, false)
            end
          end
          value['triangles'].each { |triangle| geometry.add_polygon(triangle.map { |index| lookup[index] }) }
          flags = data['original_geometry_preserved'] || value['smooth'] ? Geom::PolygonMesh::AUTO_SOFTEN : 0
          material = materials[value['material']]
          child.entities.fill_from_mesh(geometry, true, flags, material, material)
        end
        root.set_attribute(DICTIONARY, 'job_id', job_id)
        root.set_attribute(DICTIONARY, 'anchor', JSON.generate(data['anchor']))
        root.set_attribute(DICTIONARY, 'attribution', JSON.generate(data['attribution']))
        root.set_attribute(DICTIONARY, 'bbox', JSON.generate(data['bbox']))
        root.set_attribute(DICTIONARY, 'partial', !!data['partial'])
        root.set_attribute(DICTIONARY, 'missing_layers', JSON.generate(data['missing_layers'] || []))
        root.set_attribute(DICTIONARY, 'warnings', JSON.generate(data['warnings'] || []))
        root.set_attribute(DICTIONARY, 'original_origin', JSON.generate(data['original_origin'])) if data['original_origin']
        %w[imagery_requested_zoom imagery_source_zoom].each do |key|
          root.set_attribute(DICTIONARY, key, data[key]) if data[key].is_a?(Integer) && data[key].between?(0, 24)
        end
        model.set_attribute(DICTIONARY, 'anchor', JSON.generate(data['anchor']))
        reference = tile_reference(data)
        model.set_attribute(DICTIONARY, 'last_tile', JSON.generate(reference)) if reference
        model.shadow_info['Latitude'] = data['center']['lat']
        model.shadow_info['Longitude'] = data['center']['lon']
        model.shadow_info['NorthAngle'] = 0
        model.commit_operation
        operation = false
        model.selection.clear
        model.selection.add(root)
        model.active_view.zoom(root)
        { 'name' => root.name, 'triangles' => data['triangles'], 'warnings' => data['warnings'] || [] }
      rescue StandardError
        model.abort_operation if operation
        raise
      ensure
        FileUtils.remove_entry(directory) if File.directory?(directory)
      end
    end
  end
end
