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

    def self.validate!(data)
      raise 'Định dạng mô hình không hợp lệ.' unless data.is_a?(Hash) && data['schema'] == 'openmap.mesh.v1' && valid_anchor?(data['anchor'])
      center = data['center']
      raise 'Tâm bản đồ không hợp lệ.' unless center.is_a?(Hash) && finite_number?(center['lat'], 80) && finite_number?(center['lon'], 180)
      attribution = data['attribution']
      raise 'Thông tin nguồn không hợp lệ.' unless attribution.is_a?(Array) && attribution.length <= 16 && attribution.all? { |text| text.is_a?(String) && text.bytesize <= 4096 }
      materials, meshes = data['materials'], data['meshes']
      raise 'Danh sách vật liệu không hợp lệ.' unless materials.is_a?(Array) && materials.length.between?(1, 16)
      raise 'Danh sách lưới không hợp lệ.' unless meshes.is_a?(Array) && meshes.length.between?(1, 16)
      vertices_count, triangle_count = 0, 0
      materials.each do |material|
        raise 'Vật liệu không hợp lệ.' unless material.is_a?(Hash)
        color = material['color']
        raise 'Màu vật liệu không hợp lệ.' unless color.is_a?(Array) && color.length == 3 && color.all? { |c| c.is_a?(Integer) && c.between?(0, 255) }
        encoded = material['texture_png'] || material['texture_jpeg']
        next unless encoded
        raise 'Ảnh vật liệu quá lớn.' unless encoded.is_a?(String) && encoded.bytesize <= 96_000_000
        bytes = Base64.strict_decode64(encoded)
        raise 'Ảnh vật liệu quá lớn.' if bytes.bytesize > 72_000_000
        if material['texture_jpeg']
          size = jpeg_size(bytes)
        else
          raise 'Ảnh vật liệu không phải PNG.' unless bytes.start_with?("\x89PNG\r\n\x1a\n".b) && bytes.bytesize >= 24
          size = bytes.byteslice(16, 8).unpack('NN')
        end
        raise 'Kích thước ảnh không hợp lệ.' unless size.all? { |dimension| dimension.between?(1, 8192) }
      end
      meshes.each do |mesh|
        raise 'Lưới không hợp lệ.' unless mesh.is_a?(Hash)
        vertices, triangles, uv = mesh['vertices'], mesh['triangles'], mesh['uv']
        raise 'Đỉnh hoặc tam giác không hợp lệ.' unless vertices.is_a?(Array) && triangles.is_a?(Array) && !vertices.empty? && !triangles.empty?
        vertices_count += vertices.length
        triangle_count += triangles.length
        raise 'Mô hình quá lớn; hãy chia nhỏ vùng chọn.' if vertices_count > 350_000 || triangle_count > 650_000
        raise 'Tọa độ đỉnh không hợp lệ.' unless vertices.all? { |v| v.is_a?(Array) && v.length == 3 && v.all? { |number| finite_number?(number) } }
        raise 'Chỉ số tam giác không hợp lệ.' unless triangles.all? { |t| t.is_a?(Array) && t.length == 3 && t.uniq.length == 3 && t.all? { |index| index.is_a?(Integer) && index.between?(0, vertices.length - 1) } }
        raise 'UV không hợp lệ.' unless uv.is_a?(Array) && (uv.empty? || (uv.length == vertices.length && uv.all? { |v| v.is_a?(Array) && v.length == 2 && v.all? { |number| finite_number?(number, 65536) } }))
        raise 'Chỉ số vật liệu không hợp lệ.' unless mesh['material'].is_a?(Integer) && mesh['material'].between?(0, materials.length - 1)
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
        model.start_operation('OpenMap — Nạp bản đồ', true)
        operation = true
        materials = data['materials'].each_with_index.map do |metadata, index|
          material = model.materials.add('OpenMap_%s_%d' % [job_id[0, 8], index])
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
          root.transformation = Linking.frame(model)
          root.set_attribute(DICTIONARY, 'master', true) unless existing
        end
        label = data['name'].is_a?(String) ? data['name'][0, 80] : 'OpenMap'
        root.name = '%s_%s' % [label, job_id[0, 8]]
        data['meshes'].each do |value|
          child = root.entities.add_group
          child.name = value['name'].to_s[0, 64]
          tag_name = 'OpenMap_' + child.name
          child.layer = model.layers[tag_name] || model.layers.add(tag_name)
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
          flags = value['smooth'] ? Geom::PolygonMesh::AUTO_SOFTEN : 0
          material = materials[value['material']]
          child.entities.fill_from_mesh(geometry, true, flags, material, material)
        end
        root.set_attribute(DICTIONARY, 'job_id', job_id)
        root.set_attribute(DICTIONARY, 'anchor', JSON.generate(data['anchor']))
        root.set_attribute(DICTIONARY, 'attribution', JSON.generate(data['attribution']))
        root.set_attribute(DICTIONARY, 'bbox', JSON.generate(data['bbox']))
        model.set_attribute(DICTIONARY, 'anchor', JSON.generate(data['anchor']))
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
