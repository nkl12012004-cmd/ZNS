# encoding: UTF-8
# SPDX-License-Identifier: MIT
# Public metadata interoperability; no execution of source/carrier contents.
require 'json'
require 'base64'

module OpenMapSketchUp
  module Linking
    def self.ecef(anchor)
      lat, lon = anchor['lat'] * Math::PI / 180, anchor['lon'] * Math::PI / 180
      n = 6378137.0 / Math.sqrt(1 - 0.0066943799901413165 * Math.sin(lat)**2)
      [n * Math.cos(lat) * Math.cos(lon), n * Math.cos(lat) * Math.sin(lon), n * (1 - 0.0066943799901413165) * Math.sin(lat)]
    end

    def self.offset(master, source)
      a, b = ecef(master), ecef(source)
      x, y, z = b.zip(a).map { |p, q| p - q }
      lat, lon = master['lat'] * Math::PI / 180, master['lon'] * Math::PI / 180
      east = -Math.sin(lon) * x + Math.cos(lon) * y
      north = -Math.sin(lat) * Math.cos(lon) * x - Math.sin(lat) * Math.sin(lon) * y + Math.cos(lat) * z
      up = master['terrain_mode'] == 'flat' || source['terrain_mode'] == 'flat' ? 0 : source['elevation'] - master['elevation']
      raise 'Mảnh SKP cách mốc hơn 250 km.' if Math.sqrt(east**2 + north**2) > 250_000
      [east, north, up]
    end

    def self.read_json(raw, legacy = false)
      return nil unless raw.is_a?(String) && raw.bytesize <= 16_384
      value = JSON.parse(raw, max_nesting: 12)
      return nil unless value.is_a?(Hash)
      if legacy
        value = { 'lat' => value['lat'], 'lon' => value['lon'], 'elevation' => value['elevation_m'] || 0.0, 'terrain_mode' => value['terrain_mode'] == 'flat' || value['hill_patch'] ? 'flat' : 'terrain_3d' }
      end
      Importer.valid_anchor?(value) ? value : nil
    rescue JSON::ParserError
      nil
    end

    def self.definition_anchor(definition)
      native = read_json(definition.get_attribute(Importer::DICTIONARY, 'anchor'))
      return native if native
      legacy = read_json(definition.get_attribute('MapSKP_Meta', 'origin_json'), true)
      return legacy if legacy
      definition.entities.each do |entity|
        next unless entity.is_a?(Sketchup::Group) && entity.name.start_with?('__MAPSKP_META__')
        text = entity.name.sub('__MAPSKP_META__', '')
        next if text.bytesize > 16_384 || text !~ /\A[A-Za-z0-9_\-]+=*\z/
        begin
          decoded = Base64.urlsafe_decode64(text + '=' * ((4 - text.length % 4) % 4))
          anchor = read_json(decoded, true)
          return anchor if anchor
        rescue ArgumentError
          next
        end
      end
      nil
    end

    def self.frame(model)
      master = model.entities.find { |entity| entity.respond_to?(:transformation) && entity.get_attribute(Importer::DICTIONARY, 'master', false) }
      return master.transformation if master
      raw = model.get_attribute(Importer::DICTIONARY, 'frame')
      array = JSON.parse(raw) rescue nil
      if array.is_a?(Array) && array.length == 16 && array.all? { |number| Importer.finite_number?(number, 20_000_000) }
        return Geom::Transformation.new(array)
      end
      Geom::Transformation.new
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
        model.start_operation('OpenMap — Ghép mảnh SKP kéo-thả', true, false, true)
        opened = true
        prepared.each do |instance, source|
          next unless instance.valid?
          master = Importer.anchor(model)
          if master
            shift = offset(master, source).map { |metres| metres * Importer::INCHES }
            instance.transformation = frame(model) * Geom::Transformation.translation(Geom::Vector3d.new(shift))
          else
            model.set_attribute(Importer::DICTIONARY, 'anchor', JSON.generate(source))
            model.set_attribute(Importer::DICTIONARY, 'frame', JSON.generate(instance.transformation.to_a))
            instance.set_attribute(Importer::DICTIONARY, 'master', true)
          end
          instance.set_attribute(Importer::DICTIONARY, 'anchor', JSON.generate(source))
          instance.set_attribute(Importer::DICTIONARY, 'linked', true)
          instance.set_attribute(Importer::DICTIONARY, 'job_id', 'dropped_%d' % instance.persistent_id)
        end
        model.commit_operation
        opened = false
        Sketchup.status_text = 'OpenMap: đã ghép mảnh SKP theo metadata tọa độ.'
        Core.refresh_anchor if defined?(Core)
      rescue StandardError => error
        model.abort_operation if opened
        Sketchup.status_text = 'OpenMap: ' + error.message
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
