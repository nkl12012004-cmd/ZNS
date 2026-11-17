"""Keep original GLB geometry exact while making missing-UV materials valid."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
import unittest

from openmap_server.glb_compat import repair_untextured_primitives

JSON = 0x4E4F534A
BIN = 0x004E4942
UNKNOWN = 0x54455354


def make_glb(document, chunks=((BIN, b'\x01\x02\x03\x04'),)):
    payload = json.dumps(document, separators=(',', ':')).encode()
    payload += b' ' * (-len(payload) % 4)
    parts = [(JSON, payload), *chunks]
    return struct.pack('<4sII', b'glTF', 2, 12 + sum(8 + len(data) for _, data in parts)) + b''.join(
        struct.pack('<II', len(data), kind) + data for kind, data in parts)


def read_glb(raw):
    chunks = []
    offset = 12
    while offset < len(raw):
        size, kind = struct.unpack_from('<II', raw, offset)
        chunks.append((kind, raw[offset + 8:offset + 8 + size]))
        offset += 8 + size
    return json.loads(chunks[0][1]), chunks


def fixture():
    return {'asset': {'version': '2.0'},
            'materials': [{'name': 'roof', 'doubleSided': True,
                           'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                           'baseColorFactor': [1, 1, 1, 1], 'roughnessFactor': .88}}],
            'textures': [{'source': 0}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}],
            'buffers': [{'byteLength': 4}], 'bufferViews': [{'buffer': 0, 'byteLength': 4}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 1, 'type': 'VEC3'}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1},
                                        'indices': 2, 'material': 0}]}]}


class GLBCompatibilityTests(unittest.TestCase):
    def test_valid_file_returns_identical_input_bytes(self):
        document = fixture()
        document['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0'] = 3
        raw = make_glb(document)
        actual, report = repair_untextured_primitives(raw, [[255, 0, 128, 128]])
        self.assertIs(actual, raw)
        self.assertFalse(report['changed'])
        self.assertEqual(report['corrected_primitives'], 0)
        self.assertEqual(report['raw_sha256'], sha256(raw).hexdigest())
        self.assertEqual(report['output_sha256'], report['raw_sha256'])

    def test_shared_clone_preserves_geometry_original_material_and_all_other_chunks(self):
        document = fixture()
        document['materials'][0]['extras'] = {'preserve': ['custom', 2]}
        primitive = document['meshes'][0]['primitives'][0]
        primitive['extras'] = {'preserve': 'primitive'}
        document['meshes'].append({'primitives': [deepcopy(primitive), deepcopy(primitive)]})
        document['meshes'][1]['primitives'][1]['attributes']['TEXCOORD_0'] = 3
        raw = make_glb(document, ((BIN, bytes(range(16))), (UNKNOWN, b'keep'), (0x12345678, b'more')))
        repaired, report = repair_untextured_primitives(raw, [[255, 0, 128, 128]])
        result, chunks = read_glb(repaired)
        self.assertEqual(chunks[1:], read_glb(raw)[1][1:])
        self.assertEqual(struct.unpack_from('<I', repaired, 8)[0], len(repaired))
        self.assertEqual(result['materials'][0], document['materials'][0])
        self.assertEqual(len(result['materials']), 2)
        self.assertEqual(result['meshes'][0]['primitives'][0]['material'], 1)
        self.assertEqual(result['meshes'][1]['primitives'][0]['material'], 1)
        self.assertEqual(result['meshes'][1]['primitives'][1]['material'], 0)
        clone = result['materials'][1]
        self.assertNotIn('baseColorTexture', clone['pbrMetallicRoughness'])
        self.assertEqual(clone['pbrMetallicRoughness']['baseColorFactor'], [1.0, 0.0, .21586, .502])
        self.assertEqual(clone['extras'], document['materials'][0]['extras'])
        for key in ['buffers', 'bufferViews', 'accessors', 'textures', 'images']:
            self.assertEqual(result[key], document[key])
        for before_mesh, after_mesh in zip(document['meshes'], result['meshes']):
            for before, after in zip(before_mesh['primitives'], after_mesh['primitives']):
                self.assertEqual(before['attributes'], after['attributes'])
                self.assertEqual(before['indices'], after['indices'])
        self.assertEqual(result['meshes'][0]['primitives'][0]['extras']['preserve'], 'primitive')
        self.assertEqual(report['corrected_primitives'], 2)
        self.assertEqual(report['new_materials'], 1)
        self.assertEqual(report['bin_sha256'], sha256(bytes(range(16))).hexdigest())
        self.assertEqual(result['asset']['extras']['openmap_glb_compat']['raw_sha256'], report['raw_sha256'])
        self.assertEqual(report['primitive_fixes'][0]['original_rgba'], [255., 0., 128., 128.])
        again, second = repair_untextured_primitives(repaired, [[255, 0, 128, 128]])
        self.assertIs(again, repaired)
        self.assertFalse(second['changed'])

    def test_each_original_material_gets_its_own_clone(self):
        document = fixture()
        document['materials'].append(deepcopy(document['materials'][0]))
        document['meshes'][0]['primitives'].append({'attributes': {'POSITION': 0}, 'material': 1})
        result, report = repair_untextured_primitives(make_glb(document), [[255, 0, 0], [0, 255, 0]])
        material_list = read_glb(result)[0]['materials']
        self.assertEqual(report['new_materials'], 2)
        self.assertEqual(material_list[2]['pbrMetallicRoughness']['baseColorFactor'], [1., 0., 0., 1.])
        self.assertEqual(material_list[3]['pbrMetallicRoughness']['baseColorFactor'], [0., 1., 0., 1.])

    def test_existing_color_fallback_and_extra_texture_bindings(self):
        document = fixture()
        material = document['materials'][0]
        material['pbrMetallicRoughness']['baseColorFactor'] = [.2, .3, .4, .6]
        material['pbrMetallicRoughness']['metallicRoughnessTexture'] = {'index': 0}
        for key in ['normalTexture', 'occlusionTexture', 'emissiveTexture']:
            material[key] = {'index': 0}
        document['meshes'][0]['primitives'][0]['extras'] = None
        raw, report = repair_untextured_primitives(make_glb(document))
        clone = read_glb(raw)[0]['materials'][1]
        self.assertEqual(clone['pbrMetallicRoughness']['baseColorFactor'], [.2, .3, .4, .6])
        for key in ['normalTexture', 'occlusionTexture', 'emissiveTexture']:
            self.assertNotIn(key, clone)
        self.assertNotIn('metallicRoughnessTexture', clone['pbrMetallicRoughness'])
        self.assertEqual(len(report['primitive_fixes'][0]['removed_texture_bindings']), 5)
        self.assertEqual(report['primitive_fixes'][0]['color_source'], 'existing_base_color_factor')

    def test_missing_explicit_nonzero_uv_fails_and_existing_nonzero_uv_is_untouched(self):
        document = fixture()
        document['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['texCoord'] = 1
        with self.assertRaisesRegex(ValueError, 'TEXCOORD_1'):
            repair_untextured_primitives(make_glb(document))
        document['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_1'] = 3
        raw = make_glb(document)
        self.assertIs(repair_untextured_primitives(raw)[0], raw)
        binding = document['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
        binding['texCoord'] = 0
        binding['extensions'] = {'KHR_texture_transform': {'texCoord': 2}}
        with self.assertRaisesRegex(ValueError, 'TEXCOORD_2'):
            repair_untextured_primitives(make_glb(document))

    def test_unknown_material_extensions_are_not_silently_changed(self):
        document = fixture()
        document['materials'][0]['extensions'] = {'KHR_materials_clearcoat': {'clearcoatTexture': {'index': 0}}}
        with self.assertRaisesRegex(ValueError, 'extensions'):
            repair_untextured_primitives(make_glb(document))

    def test_malformed_glb_and_material_color_are_rejected(self):
        raw = make_glb(fixture())
        malformed = [b'', b'not a GLB file at all', raw[:-1], raw[:4] + struct.pack('<I', 1) + raw[8:],
                     raw[:12] + struct.pack('<II', 3, JSON) + b'bad',
                     make_glb(fixture(), ((JSON, b'null'),)),
                     make_glb(fixture(), ((BIN, b'aaaa'), (BIN, b'bbbb')))]
        for payload in malformed:
            with self.subTest(payload=payload[:20]), self.assertRaises(ValueError):
                repair_untextured_primitives(payload)
        for rgba in [[1, 2], [1, 2, float('nan')], [1, -2, 3], [1, 2, 300]]:
            with self.subTest(rgba=rgba), self.assertRaises(ValueError):
                repair_untextured_primitives(raw, [rgba])
        with self.assertRaises(TypeError):
            repair_untextured_primitives(bytearray(raw))

    def test_original_roof_fixture_reuses_one_clone_for_two_untextured_primitives(self):
        fixture_path = Path('/workspace/work/sitecraft_validation/original_preview.glb')
        if not fixture_path.is_file():
            self.skipTest('Local original export fixture is not present')
        raw = fixture_path.read_bytes()
        document, before_chunks = read_glb(raw)
        colors = [None] * len(document['materials'])
        colors[9] = [132, 138, 146, 255]
        result, report = repair_untextured_primitives(raw, colors)
        after, after_chunks = read_glb(result)
        self.assertEqual(report['corrected_primitives'], 2)
        self.assertEqual(report['new_materials'], 1)
        self.assertEqual(after_chunks[1:], before_chunks[1:])
        self.assertEqual(after['materials'][:len(document['materials'])], document['materials'])
        self.assertEqual({fix['original_material'] for fix in report['primitive_fixes']}, {9})
        for mesh in after['meshes']:
            for primitive in mesh['primitives']:
                material = after['materials'][primitive['material']]
                if 'TEXCOORD_0' not in primitive['attributes']:
                    self.assertNotIn('baseColorTexture', material['pbrMetallicRoughness'])


if __name__ == '__main__':
    unittest.main()
