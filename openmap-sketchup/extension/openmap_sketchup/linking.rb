# encoding: UTF-8
# SPDX-License-Identifier: MIT
# Public metadata interoperability; no execution of source/carrier contents.
require 'json'
require 'base64'

module OpenMapSketchUp
  module Linking
    MAX_METADATA_BYTES = 16_384
    MAX_LINK_METRES = 1_000_000
    MAX_OFFSET_METRES = 500_000

    def self.real_number?(value, minimum, maximum)
      value.is_a?(Numeric) && !value.is_a?(Complex) && value.to_f.finite? && value >= minimum && value <= maximum
    end

    # Retain validated origin fields: the anchor alone does not describe a tile's
    # center, exaggerated height or existing translation relative to that anchor.
    def self.valid_origin?(value)
      return false unless value.is_a?(Hash) && real_number?(value['lat'], -90, 90) && real_number?(value['lon'], -180, 180)
      ranges = {
        'elevation' => [-20_000, 20_000], 'elevation_m' => [-12_000, 20_000],
        'anchor_elev_m' => [-12_000, 20_000], 'anchor_lat' => [-90, 90],
        'anchor_lon' => [-180, 180], 'south' => [-90, 90], 'north' => [-90, 90],
        'west' => [-180, 180], 'east' => [-180, 180],
        'z_exaggeration' => [0, 20], 'tz_offset' => [-14, 14]
      }
      return false unless ranges.all? { |key, bounds| value[key].nil? || real_number?(value[key], *bounds) }
      return false unless %w[width_m height_m].all? { |key| value[key].nil? || (real_number?(value[key], 0, 50_000) && value[key] > 0) }
      return false unless value['terrain_mode'].nil? || %w[flat terrain_3d].include?(value['terrain_mode'])
      return false unless value['anchor_terrain_mode'].nil? || %w[flat terrain_3d].include?(value['anchor_terrain_mode'])
      return false unless value['hill_patch'].nil? || [true, false].include?(value['hill_patch'])
      shift = value['offset_from_anchor_m']
      shift.nil? || (shift.is_a?(Array) && shift.length == 3 && shift.all? { |n| real_number?(n, -MAX_OFFSET_METRES, MAX_OFFSET_METRES) })
    end

    def self.elevation(origin, fallback = 0.0)
      origin['elevation_m'] || origin['elevation'] || fallback
    end

    def self.origin_anchor(origin)
      return nil unless valid_origin?(origin)
      { 'lat' => origin['anchor_lat'] || origin['lat'],
        'lon' => origin['anchor_lon'] || origin['lon'],
        'elevation' => origin['anchor_elev_m'] || elevation(origin),
        'terrain_mode' => origin['anchor_terrain_mode'] || origin['terrain_mode'] || 'terrain_3d',
        'z_exaggeration' => origin['z_exaggeration'] || 1.0 }
    end

    def self.ecef(origin)
      latitude = origin['lat'].to_f * Math::PI / 180.0
      longitude = origin['lon'].to_f * Math::PI / 180.0
      sine, cosine = Math.sin(latitude), Math.cos(latitude)
      radius = 6_378_137.0 / Math.sqrt(1.0 - 0.0066943799901413165 * sine * sine)
      [radius * cosine * Math.cos(longitude), radius * cosine * Math.sin(longitude), radius * (1.0 - 0.0066943799901413165) * sine]
    end

    # The first group's transformation already contains its own offset. Return
    # the target's displacement from that first tile, never its absolute offset.
    def self.offset(master, source)
      raise 'Metadata tọa độ mảnh SKP không hợp lệ.' unless valid_origin?(master) && valid_origin?(source)
      first_anchor, target_anchor = origin_anchor(master), origin_anchor(source)
      same_anchor = %w[lat lon].all? { |key| (target_anchor[key] - first_anchor[key]).abs < 1.0e-6 }
      target_shift = source['offset_from_anchor_m']
      if same_anchor && target_shift
        first_shift = master['offset_from_anchor_m'] || [0.0, 0.0, 0.0]
        result = target_shift.zip(first_shift).map { |target, first| target.to_f - first.to_f }
      else
        first_xyz, target_xyz = ecef(master), ecef(source)
        x, y, z = target_xyz.zip(first_xyz).map { |target, first| target - first }
        latitude = master['lat'].to_f * Math::PI / 180.0
        longitude = master['lon'].to_f * Math::PI / 180.0
        east = -Math.sin(longitude) * x + Math.cos(longitude) * y
        north = -Math.sin(latitude) * Math.cos(longitude) * x - Math.sin(latitude) * Math.sin(longitude) * y + Math.cos(latitude) * z
        exaggeration = master['z_exaggeration'] || source['z_exaggeration'] || 1.0
        fallback_elevation = first_anchor['elevation']
        up = (elevation(source, fallback_elevation).to_f - elevation(master, fallback_elevation).to_f) * exaggeration.to_f
        up = 0.0 if master['terrain_mode'] == 'flat' && (source['terrain_mode'] == 'flat' || source['hill_patch'] == true)
        result = [east, north, up]
      end
      raise 'Khoảng cách ghép mảnh SKP vượt giới hạn.' unless result.all? { |n| real_number?(n, -MAX_LINK_METRES, MAX_LINK_METRES) }
      result
    end

    def self.read_json(raw, _legacy = false)
      return nil unless raw.is_a?(String) && raw.bytesize <= MAX_METADATA_BYTES && raw.valid_encoding?
      value = JSON.parse(raw, max_nesting: 12)
      valid_origin?(value) ? value : nil
    rescue JSON::ParserError, EncodingError, TypeError
      nil
    end

    def self.definition_anchor(definition)
      original = read_json(definition.get_attribute(Importer::DICTIONARY, 'original_origin'))
      return original if original
      native = read_json(definition.get_attribute(Importer::DICTIONARY, 'anchor'))
      return native if native
      legacy = read_json(definition.get_attribute('MapSKP_Meta', 'origin_json'), true)
      return legacy if legacy
      definition.entities.each do |entity|
        next unless entity.is_a?(Sketchup::Group) && entity.name.to_s.start_with?('__MAPSKP_META__')
        encoded = entity.name.to_s.sub('__MAPSKP_META__', '')
        next if encoded.bytesize > MAX_METADATA_BYTES || encoded !~ /\A[A-Za-z0-9_\-]+=*\z/
        begin
          decoded = Base64.urlsafe_decode64(encoded + '=' * ((4 - encoded.length % 4) % 4))
          origin = read_json(decoded, true)
          return origin if origin
        rescue ArgumentError
          next
        end
      end
      nil
    end

    def self.instance_origin(instance)
      original = read_json(instance.get_attribute(Importer::DICTIONARY, 'original_origin'))
      return original if original
      native = read_json(instance.get_attribute(Importer::DICTIONARY, 'anchor'))
      return native if native
      legacy = read_json(instance.get_attribute('MapSKP_Meta', 'origin_json'), true)
      return legacy if legacy
      instance.respond_to?(:definition) ? definition_anchor(instance.definition) : nil
    end

    def self.master_instance(model)
      roots = model.entities.select { |entity| entity.respond_to?(:transformation) && entity.respond_to?(:get_attribute) }
      marked = roots.find { |entity| entity.get_attribute(Importer::DICTIONARY, 'master', false) && instance_origin(entity) }
      return marked if marked
      roots.find do |entity|
        (entity.get_attribute(Importer::DICTIONARY, 'linked', false) || entity.get_attribute(Importer::DICTIONARY, 'job_id')) && instance_origin(entity)
      end
    end

    def self.master_origin(model)
      master = master_instance(model)
      master ? instance_origin(master) : Importer.anchor(model)
    end

    def self.frame(model)
      master = master_instance(model)
      return master.transformation if master
      raw = model.get_attribute(Importer::DICTIONARY, 'frame')
      array = raw.is_a?(String) && raw.bytesize <= 4096 ? (JSON.parse(raw, max_nesting: 2) rescue nil) : nil
      if array.is_a?(Array) && array.length == 16 && array.all? { |number| Importer.finite_number?(number, 20_000_000) }
        return Geom::Transformation.new(array)
      end
      Geom::Transformation.new
    end

    # Used for newly generated local geometry. A dropped SKP's first placement is
    # already set by SketchUp and is deliberately retained by scan instead.
    def self.transform_for(model, source)
      raise 'Metadata tọa độ mảnh SKP không hợp lệ.' unless valid_origin?(source)
      master = master_origin(model)
      metres = master ? offset(master, source) : (source['offset_from_anchor_m'] || [0.0, 0.0, 0.0])
      shift = metres.map { |number| number.to_f * Importer::INCHES }
      frame(model) * Geom::Transformation.translation(Geom::Vector3d.new(shift))
    end

    def self.scan(model)
      return if @busy || !model.equal?(Sketchup.active_model)
      components = model.entities.grep(Sketchup::ComponentInstance)
      @known ||= {}
      known = @known[model.object_id] || {}
      candidates = components.reject { |instance| known[instance.persistent_id] || instance.get_attribute(Importer::DICTIONARY, 'linked', false) }
      @known[model.object_id] = components.each_with_object({}) { |instance, ids| ids[instance.persistent_id] = true }
      prepared = candidates.filter_map do |instance|
        source = definition_anchor(instance.definition)
        source ? [instance, source] : nil
      end
      return if prepared.empty?
      @busy = true
      opened = false
      begin
        model.start_operation('SiteCraft — Ghép mảnh SKP kéo-thả', true, false, true)
        opened = true
        prepared.each do |instance, source|
          next unless instance.valid?
          if master_origin(model)
            instance.transformation = transform_for(model, source)
          else
            model.set_attribute(Importer::DICTIONARY, 'anchor', JSON.generate(origin_anchor(source)))
            model.set_attribute(Importer::DICTIONARY, 'frame', JSON.generate(instance.transformation.to_a))
            instance.set_attribute(Importer::DICTIONARY, 'master', true)
          end
          instance.set_attribute(Importer::DICTIONARY, 'original_origin', JSON.generate(source))
          instance.set_attribute(Importer::DICTIONARY, 'anchor', JSON.generate(origin_anchor(source)))
          instance.set_attribute(Importer::DICTIONARY, 'linked', true)
          instance.set_attribute(Importer::DICTIONARY, 'job_id', 'dropped_%d' % instance.persistent_id)
        end
        model.commit_operation
        opened = false
        Sketchup.status_text = 'SiteCraft: đã ghép mảnh SKP theo metadata tọa độ.'
        Core.refresh_anchor if defined?(Core)
      rescue StandardError => error
        model.abort_operation if opened
        Sketchup.status_text = 'SiteCraft: ' + error.message
      ensure
        @busy = false
      end
    end

    class Observer < Sketchup::ModelObserver
      def onTransactionCommit(model)
        return if @queued
        @queued = true
        UI.start_timer(0.08, false) do
          @queued = false
          Linking.scan(model)
        end
      end
    end

    class ApplicationObserver < Sketchup::AppObserver
      def onNewModel(model)
        Linking.attach(model)
      end

      def onOpenModel(model)
        Linking.attach(model)
      end
    end

    def self.attach(model)
      @attached ||= {}
      return if !model || @attached.key?(model.object_id)
      observer = Observer.new
      model.add_observer(observer)
      @attached[model.object_id] = observer
      @known ||= {}
      @known[model.object_id] = model.entities.grep(Sketchup::ComponentInstance).each_with_object({}) { |instance, ids| ids[instance.persistent_id] = true }
    end

    def self.install
      return if @application_observer
      @application_observer = ApplicationObserver.new
      Sketchup.add_observer(@application_observer)
      attach(Sketchup.active_model)
    end
  end
end
