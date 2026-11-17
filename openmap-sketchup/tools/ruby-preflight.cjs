/* Execute source validation in a real Ruby VM; SketchUp geometry APIs are separate. */
const fs = require('node:fs');
const path = require('node:path');
const { DefaultRubyVM } = require('@ruby/wasm-wasi/dist/node');

(async () => {
  const root = path.resolve(__dirname, '..');
  const wasm = require.resolve('@ruby/3.3-wasm-wasi/dist/ruby+stdlib.wasm');
  const module = await WebAssembly.compile(fs.readFileSync(wasm));
  const { vm } = await DefaultRubyVM(module);
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/importer.rb'), 'utf8'));
  vm.eval('module Sketchup; class ModelObserver; end; class AppObserver; end; end');
  vm.eval(fs.readFileSync(path.join(root, 'extension/openmap_sketchup/linking.rb'), 'utf8'));
  const fixture = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], 'utf8')) : {
    schema: 'openmap.mesh.v1', anchor: { lat: 10, lon: 106, elevation: 0 }, center: { lat: 10, lon: 106 }, attribution: [],
    materials: [{ name: 'Ground', color: [160,180,160] }], meshes: [{ vertices: [[0,0,0],[100,0,0],[0,100,0]], triangles: [[0,1,2]], uv: [[0,0],[1,0],[0,1]], material: 0 }]
  };
  const encoded = Buffer.from(JSON.stringify(fixture)).toString('base64');
  vm.eval(`
    fixture = JSON.parse(Base64.strict_decode64('${encoded}'))
    raise 'Valid fixture rejected' unless OpenMapSketchUp::Importer.validate!(fixture)
    def rejected
      begin
        yield
      rescue StandardError
        return true
      end
      raise 'Invalid fixture was accepted'
    end
    copy = Marshal.load(Marshal.dump(fixture))
    copy['meshes'][0]['triangles'][0][0] = -1
    rejected { OpenMapSketchUp::Importer.validate!(copy) }
    copy = Marshal.load(Marshal.dump(fixture))
    copy['meshes'][0]['vertices'][0][0] = Float::NAN
    rejected { OpenMapSketchUp::Importer.validate!(copy) }
    copy = Marshal.load(Marshal.dump(fixture))
    copy['materials'][0] = 'invalid material'
    rejected { OpenMapSketchUp::Importer.validate!(copy) }
    jpeg = ['ffd8ffc00011080020004003011100021100031100ffd9'].pack('H*')
    raise 'JPEG size parser failed' unless OpenMapSketchUp::Importer.jpeg_size(jpeg) == [64,32]
    tile_data = {
      'center'=>{'lat'=>0,'lon'=>0},
      'bbox'=>{'south'=>-0.001,'north'=>0.001,'west'=>-0.001,'east'=>0.001},
      'parameters'=>{'width'=>222.63898158654715,'height'=>221.1485516431887},
      'hill_patch'=>false
    }
    reference = OpenMapSketchUp::Importer.tile_reference(tile_data)
    raise 'Imported tile reference was rejected' unless reference && reference['center']['lat'] == 0 && reference['width'] > 222
    tile_model = Struct.new(:stored) do
      def get_attribute(_dictionary, _key)
        stored
      end
    end.new(nil)
    raise 'Old model without reference was not accepted' unless OpenMapSketchUp::Importer.last_tile(tile_model).nil?
    tile_model.stored = JSON.generate(reference)
    raise 'Saved neighbor reference was lost' unless OpenMapSketchUp::Importer.last_tile(tile_model) == reference
    tile_data['hill_patch'] = true
    raise 'Hill patch replaced the full tile reference' unless OpenMapSketchUp::Importer.tile_reference(tile_data).nil?
    invalid = Marshal.load(Marshal.dump(reference))
    invalid['center']['lat'] = Float::NAN
    raise 'NaN tile reference was accepted' unless OpenMapSketchUp::Importer.valid_tile_reference(invalid).nil?
    invalid = Marshal.load(Marshal.dump(reference))
    invalid['bbox']['east'] = 179
    raise 'Unbounded tile reference was accepted' unless OpenMapSketchUp::Importer.valid_tile_reference(invalid).nil?
    invalid = Marshal.load(Marshal.dump(reference))
    invalid['width'] = 100_001
    tile_model.stored = JSON.generate(invalid)
    raise 'Oversized tile reference was accepted' unless OpenMapSketchUp::Importer.last_tile(tile_model).nil?
    tile_model.stored = '{broken json'
    raise 'Corrupt old tile metadata was accepted' unless OpenMapSketchUp::Importer.last_tile(tile_model).nil?
    tile_model.stored = 'x' * 4097
    raise 'Oversized old tile metadata was accepted' unless OpenMapSketchUp::Importer.last_tile(tile_model).nil?
    delta = OpenMapSketchUp::Linking.offset({'lat'=>0,'lon'=>0,'elevation'=>0,'terrain_mode'=>'flat'}, {'lat'=>0,'lon'=>0.001,'elevation'=>100,'terrain_mode'=>'terrain_3d'})
    raise 'SKP georeference projection failed' unless (delta[0]-111.31949).abs < 0.001 && delta[2] == 0
    origin = OpenMapSketchUp::Linking.read_json('{"lat":10,"lon":106,"elevation_m":15,"terrain_mode":"flat"}', true)
    raise 'Legacy SKP metadata conversion failed' unless origin['elevation'] == 15 && origin['terrain_mode'] == 'flat'
    puts 'Ruby preflight PASS: mesh validation, JPEG dimensions, last imported tile reference and corrupt/NaN/bounded metadata checks.'
  `);
  console.log('Ruby VM preflight assertions passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
