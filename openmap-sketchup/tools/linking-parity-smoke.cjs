/* Local pure-Ruby checks for original tile linking; no SketchUp or network needed. */
const fs = require('node:fs');
const path = require('node:path');
const { DefaultRubyVM } = require('@ruby/wasm-wasi/dist/node');
const root = path.resolve(__dirname, '..');
(async () => {
  const wasm = require.resolve('@ruby/3.3-wasm-wasi/dist/ruby+stdlib.wasm');
  const { vm } = await DefaultRubyVM(await WebAssembly.compile(fs.readFileSync(wasm)));
  vm.eval(`
    require 'json'
    require 'base64'
    module Geom
      class Vector3d
        attr_reader :values
        def initialize(*values); @values = values.length == 1 ? values[0] : values; end
      end
      class Transformation
        def initialize(values = nil)
          @values = values || [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
        end
        def to_a; @values.dup; end
        def self.translation(vector)
          values = new.to_a
          values[12,3] = vector.values
          new(values)
        end
        def *(other)
          b = other.to_a
          result = Array.new(16,0.0)
          4.times { |col| 4.times { |row| 4.times { |k| result[col*4+row] += @values[k*4+row] * b[col*4+k] } } }
          self.class.new(result)
        end
      end
    end
    module Sketchup
      class ModelObserver; end
      class AppObserver; end
      class << self; attr_accessor :active_model, :status_text; end
      class Item
        attr_accessor :transformation, :name
        attr_reader :attributes
        def initialize
          @attributes = {}; @transformation = Geom::Transformation.new; @name = ''
        end
        def get_attribute(dictionary, key, default = nil); @attributes.fetch([dictionary,key],default); end
        def set_attribute(dictionary, key, value); @attributes[[dictionary,key]]=value; end
        def valid?; true; end
        def persistent_id; object_id; end
      end
      class Group < Item; end
      class ComponentInstance < Item
        attr_accessor :definition
        def initialize(definition); super(); @definition=definition; end
      end
    end
    class TestDefinition < Sketchup::Item
      attr_reader :entities
      def initialize; super(); @entities=[]; end
      def set_attribute(*); raise 'Definition metadata must remain read-only'; end
    end
    class TestModel < Sketchup::Item
      attr_reader :entities, :operations
      def initialize; super(); @entities=[]; @operations=[]; end
      def start_operation(*); @operations << 'start'; end
      def commit_operation; @operations << 'commit'; end
      def abort_operation; @operations << 'abort'; end
    end
  `);
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/importer.rb'), 'utf8'));
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/linking.rb'), 'utf8'));
  const original = fs.readFileSync(path.join(root, 'reference/mapskp_original_readable/mapskp/map_importer.rb'), 'utf8');
  const selected = ['strict_real_number?', 'valid_geo_meta_hash?', 'wgs84_latlon_to_ecef', 'wgs84_enu_delta_m', 'compute_linked_transform'];
  const methods = selected.map(name => {
    const start = original.indexOf('    def self.' + name + '(');
    if (start < 0) throw new Error('Missing original oracle: ' + name);
    const next = original.indexOf('\n    def self.', start + 1);
    return original.slice(start, next < 0 ? original.length : next);
  }).join('\n');
  vm.eval(`module OriginalLinkOracle
    INCH_PER_METER=39.37007874015748
    WGS84_A=6378137.0
    WGS84_F=1.0/298.257223563
    WGS84_E2=WGS84_F*(2.0-WGS84_F)
    MAX_COORD_ABS_M=1_000_000.0
    VALID_TERRAIN_MODES=%w[flat terrain_3d].freeze
    ${methods}
  end`);
  vm.eval(`
    $checks = 0
    def verify(condition, message)
      raise message unless condition
      $checks += 1
    end
    def close_arrays(a,b,message)
      verify(a.length == b.length && a.zip(b).all? { |x,y| (x-y).abs < 1e-7 },message + ': ' + a.inspect + ' != ' + b.inspect)
    end
    def base_origin
      {'lat'=>19.14507,'lon'=>105.6364,'elevation_m'=>35.0,'terrain_mode'=>'terrain_3d','anchor_lat'=>19.14,'anchor_lon'=>105.63,'anchor_elev_m'=>30.0,'z_exaggeration'=>2.0,'offset_from_anchor_m'=>[100.0,200.0,10.0]}
    end
    def compare_original(first,target)
      instance = Sketchup::Group.new
      expected = OriginalLinkOracle.compute_linked_transform(instance,first,target).to_a[12,3]
      actual = OpenMapSketchUp::Linking.offset(first,target).map { |x| x * OpenMapSketchUp::Importer::INCHES }
      close_arrays(actual,expected,'Original georeference mismatch')
    end
    linking = OpenMapSketchUp::Linking
    native_a={'lat'=>0.0,'lon'=>0.0,'elevation'=>0.0,'terrain_mode'=>'terrain_3d'}
    native_b={'lat'=>0.0,'lon'=>0.001,'elevation'=>100.0,'terrain_mode'=>'flat'}
    native_shift=linking.offset(native_a,native_b)
    verify((native_shift[0]-111.31949).abs < 0.001 && native_shift[1].abs < 0.001 && native_shift[2]==100.0,'Independent engine anchor compatibility failed')
    first=base_origin
    target=first.merge('offset_from_anchor_m'=>[250.0,180.0,30.0])
    close_arrays(linking.offset(first,target),[150.0,-20.0,20.0],'Absolute offset added twice')
    compare_original(first,target)
    compare_original(first.merge('offset_from_anchor_m'=>[-500000.0,0.0,0.0]),target.merge('offset_from_anchor_m'=>[500000.0,0.0,0.0]))
    compare_original(first.reject { |k,_| k=='offset_from_anchor_m' },target)
    compare_original(first,target.merge('anchor_lat'=>first['anchor_lat'] + 0.0000005))
    fallback=target.merge('lat'=>19.146,'lon'=>105.638,'elevation_m'=>45.0,'anchor_lat'=>20.0)
    [first,first.merge('z_exaggeration'=>0.0),first.reject { |k,_| k=='z_exaggeration' }].each do |master|
      compare_original(master,fallback.merge('z_exaggeration'=>4.0))
      %w[flat terrain_3d].each do |first_mode|
        %w[flat terrain_3d].each do |target_mode|
          [true,false].each do |hill|
            compare_original(master.merge('terrain_mode'=>first_mode),fallback.merge('terrain_mode'=>target_mode,'hill_patch'=>hill))
          end
        end
      end
    end
    close_arrays(linking.offset(first.merge('terrain_mode'=>'flat'),fallback),linking.offset(first,fallback),'Terrain target incorrectly flattened')
    compare_original(first,target.reject { |k,_| k=='offset_from_anchor_m' }.merge('lat'=>19.146))
    rng=Random.new(12345)
    250.times do |i|
      a=base_origin.merge('lat'=>rng.rand(-75.0..75.0),'lon'=>rng.rand(-175.0..175.0),'elevation_m'=>rng.rand(-300.0..3000.0),'z_exaggeration'=>rng.rand(0.0..20.0))
      b=a.merge('lat'=>a['lat']+rng.rand(-0.01..0.01),'lon'=>a['lon']+rng.rand(-0.01..0.01),'elevation_m'=>rng.rand(-300.0..3000.0),'terrain_mode'=>i.even? ? 'flat' : 'terrain_3d')
      b.delete('offset_from_anchor_m') if i.even?
      b['offset_from_anchor_m'] = [rng.rand(-1000.0..1000.0),rng.rand(-1000.0..1000.0),rng.rand(-100.0..100.0)] unless i.even?
      b['anchor_lon'] += 1.0 if i%3==0
      compare_original(a,b)
    end
    raw=base_origin.merge('opaque_note'=>'Do not execute: system(anything)','hill_patch'=>true,'custom'=>{'a'=>[1,2,3]})
    parsed=linking.read_json(JSON.generate(raw),true)
    verify(parsed==raw,'Validated raw metadata was reduced')
    verify(linking.origin_anchor(parsed)=={'lat'=>19.14,'lon'=>105.63,'elevation'=>30.0,'terrain_mode'=>'terrain_3d','z_exaggeration'=>2.0},'Canonical anchor not separated from center')
    hill_origin=first.merge('terrain_mode'=>'terrain_3d','anchor_terrain_mode'=>'flat','hill_patch'=>true)
    verify(linking.origin_anchor(hill_origin)['terrain_mode']=='flat' && linking.origin_anchor(hill_origin)['z_exaggeration']==2.0,'Hill patch canonical anchor mode/scale was lost')
    compare_original(first.merge('terrain_mode'=>'flat'),hill_origin.merge('offset_from_anchor_m'=>[150.0,200.0,0.0]))
    ['lat','lon','z_exaggeration','offset_from_anchor_m'].each do |key|
      bad=base_origin.merge(key=>key=='offset_from_anchor_m' ? [1,2,'3'] : '1')
      verify(!linking.valid_origin?(bad),'Invalid number accepted: '+key)
    end
    [base_origin.merge('hill_patch'=>'true'),base_origin.merge('terrain_mode'=>'unknown'),base_origin.merge('z_exaggeration'=>21),base_origin.merge('width_m'=>0)].each do |bad|
      verify(linking.read_json(JSON.generate(bad)).nil?,'Invalid optional metadata accepted')
    end
    verify(linking.read_json('x'*16385).nil?,'Oversized metadata read')
    verify(linking.read_json('{broken').nil?,'Malformed metadata accepted')
    verify(linking.read_json(JSON.generate({'lat'=>0,'lon'=>0,'x'=>[[[[[[[[[[[[[0]]]]]]]]]]]]]})).nil?,'Nested metadata bound ignored')
    defn=TestDefinition.new
    defn.attributes[[OpenMapSketchUp::Importer::DICTIONARY,'original_origin']]=JSON.generate(raw)
    defn.attributes[[OpenMapSketchUp::Importer::DICTIONARY,'anchor']]=JSON.generate({'lat'=>0,'lon'=>0,'elevation'=>0})
    verify(linking.definition_anchor(defn)==raw,'Original origin lost to canonical definition anchor')
    legacy=TestDefinition.new
    legacy.attributes[['MapSKP_Meta','origin_json']]=JSON.generate(raw)
    verify(linking.definition_anchor(legacy)==raw,'MapSKP dictionary fallback failed')
    carrier_def=TestDefinition.new
    carrier=Sketchup::Group.new
    carrier.name='__MAPSKP_META__'+Base64.urlsafe_encode64(JSON.generate(raw),padding:false)
    carrier_def.entities << carrier
    verify(linking.definition_anchor(carrier_def)==raw,'Carrier fallback failed')
    # Geometry is local to the tile; first generated placement adds its offset.
    model=TestModel.new
    close_arrays(linking.transform_for(model,first).to_a[12,3],first['offset_from_anchor_m'].map { |v| v*OpenMapSketchUp::Importer::INCHES },'First generated origin not applied once')
    # The saved model anchor is canonical. The first root retains its actual
    # center and offset; preserve user rotation/scale when adding relative delta.
    master=Sketchup::Group.new
    master.set_attribute(OpenMapSketchUp::Importer::DICTIONARY,'master',true)
    master.set_attribute(OpenMapSketchUp::Importer::DICTIONARY,'original_origin',JSON.generate(first))
    master.transformation=Geom::Transformation.new([0,2,0,0,-2,0,0,0,0,0,2,0,7,8,9,1])
    model.entities << master
    model.set_attribute(OpenMapSketchUp::Importer::DICTIONARY,'anchor',JSON.generate(linking.origin_anchor(first)))
    verify(linking.master_origin(model)==first,'Canonical anchor replaced actual first tile origin')
    expected=OriginalLinkOracle.compute_linked_transform(master,first,target)
    close_arrays(linking.transform_for(model,target).to_a,expected.to_a,'Relative rotated/scaled first frame failed')
    # Dropping the first SKP retains its existing placement, despite nonzero raw
    # offset. Subsequent drops use target minus first, without mutating a def.
    dropped=TestModel.new
    Sketchup.active_model=dropped
    one=Sketchup::ComponentInstance.new(defn)
    one.transformation=Geom::Transformation.translation(Geom::Vector3d.new([7.0,8.0,9.0]))
    dropped.entities << one
    linking.scan(dropped)
    close_arrays(one.transformation.to_a[12,3],[7.0,8.0,9.0],'First dropped offset applied twice')
    verify(JSON.parse(one.get_attribute(OpenMapSketchUp::Importer::DICTIONARY,'original_origin'))==raw,'First drop raw origin lost')
    second_def=TestDefinition.new
    second_def.attributes[['MapSKP_Meta','origin_json']]=JSON.generate(target)
    two=Sketchup::ComponentInstance.new(second_def)
    dropped.entities << two
    linking.scan(dropped)
    close_arrays(two.transformation.to_a,OriginalLinkOracle.compute_linked_transform(one,raw,target).to_a,'Second dropped relative placement failed')
    verify(dropped.operations==['start','commit','start','commit'],'Drop linking transaction failed')
    verify(defn.entities.empty? && defn.attributes.length==2,'Definition metadata mutated')
    $linking_report={'linking_parity'=>'PASS','checks'=>$checks,'original_oracle'=>true,'raw_metadata_preserved'=>true,'first_drop_offset_once'=>true,'rotated_scaled_frame'=>true,'no_definition_mutation'=>true,'hill_patch_anchor_mode_and_scale'=>true}
  `);
  const report = vm.eval('JSON.generate($linking_report)').toString();
  fs.mkdirSync(path.join(root, 'test-artifacts'), { recursive: true });
  fs.writeFileSync(path.join(root, 'test-artifacts/linking-parity-report.json'), report + '\n');
  console.log(report);
})().catch(error => { console.error(error); process.exitCode = 1; });
