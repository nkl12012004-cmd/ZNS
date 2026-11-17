"""Normal DEM must not become a trimmed hill merely after a flat first tile."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from openmap_server.builder import parameters
from openmap_server.net import PublicError
from openmap_server.original_engine import OriginalEngine


@unittest.skipUnless(sys.version_info[:2] == (3, 14) and importlib.util.find_spec('numpy'),
                     'The original terrain kernel requires CPython 3.14 and NumPy')
class TerrainModeTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        # All four corners and all border elevations differ from the center.
        self.dem = 100.0 + np.add.outer(np.linspace(0, 30, 16), np.linspace(0, 20, 16))
        self.engine = OriginalEngine({
            'OPENMAP_WORK_DIR': self.folder.name,
            'OPENMAP_ORIGINAL_FIXTURE': {'custom_dem_asl': self.dem,
                                        'mock_osm_data': {'elements': []}},
        })
        self.params = {'lat': 21.028511, 'lon': 105.854444,
                       'width': 200, 'height': 200, 'grid': 16,
                       'image_size': 1024, 'imagery': 'satellite',
                       'terrain': True, 'exaggeration': 1.25,
                       'roads': False, 'buildings': False, 'water': False,
                       'trees': False, 'project_name': 'Terrain_Modes'}
        self.flat_anchor = {'lat': 21.027, 'lon': 105.853, 'elevation': 0,
                            'terrain_mode': 'flat', 'z_exaggeration': 2.0}
        self.job = 0

    def build(self, **changes):
        self.job += 1
        payload = parameters({**self.params, **changes})
        with patch('socket.getaddrinfo', side_effect=AssertionError('Unexpected DNS')) as dns, \
             patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')) as network:
            result = self.engine.build(payload, job_id=('%032x' % self.job))
        dns.assert_not_called()
        network.assert_not_called()
        # Exercise the actual portable export path, rather than a native SDK mock.
        for key in ('fallbackpath', 'original_glb_path', 'original_manifest_path'):
            self.assertTrue(Path(result[key]).is_file(), key)
        self.assertTrue(Path(result['original_manifest']['mapskp1_path']).is_file())
        self.assertGreater(len(result['obj_zip']), 0)
        self.assertGreater(len(result['glb']), 0)
        return payload, result

    def assert_matches_original_arrays(self, payload, result):
        builder = self.engine._load()[2]
        source_params = self.engine.original_parameters(payload)
        # This is an ordinary old normal-DEM input. The adapter only chooses
        # that branch; its geometry must still be exactly the old implementation.
        source = builder.build_mode1_context_scene(source_params, self.engine.cache_dir)
        actual = result['raw_scene']
        self.assertEqual(len(source['layers']), len(actual['layers']))
        for expected_layer, actual_layer in zip(source['layers'], actual['layers']):
            self.assertEqual(expected_layer['tag'], actual_layer['tag'])
            self.assertEqual(len(expected_layer['meshes']), len(actual_layer['meshes']))
            for expected, mesh in zip(expected_layer['meshes'], actual_layer['meshes']):
                self.assertEqual(expected['mat_idx'], mesh['mat_idx'])
                for field in ('verts', 'faces', 'uvs'):
                    if expected[field] is None:
                        self.assertIsNone(mesh[field])
                    else:
                        self.assertEqual(expected[field].dtype, mesh[field].dtype)
                        self.assertEqual(expected[field].shape, mesh[field].shape)
                        self.assertEqual(expected[field].tobytes(), mesh[field].tobytes())
        self.assertEqual([material.get('texture_bytes') for material in source['materials']],
                         [material.get('texture_bytes') for material in actual['materials']])

    def assert_normal_rectangle(self, payload, result, scale):
        np = self.np
        scene = result['raw_scene']
        terrain = scene['layers'][0]
        self.assertEqual(terrain['tag'], 'MapSKP_01_Terrain')
        self.assertEqual(terrain['name'], 'MapSKP_Terrain_DEM')
        self.assertFalse(scene['origin']['hill_patch'])
        self.assertFalse(result['mesh']['hill_patch'])
        self.assertEqual(len(terrain['meshes']), 2, 'Normal DEM lost its plinth')
        top, plinth = terrain['meshes']
        self.assertEqual(top['verts'].shape, (256, 3))
        self.assertEqual(top['faces'].shape, (450, 3))
        self.assertEqual(top['uvs'].shape, (256, 2))
        center = round(float(self.dem[8, 8]), 3)
        expected = ((self.dem - center) * scale).astype(np.float32)
        np.testing.assert_array_equal(top['verts'][:, 2].reshape(16, 16), expected)
        corners = top['verts'][[0, 15, 240, 255], 2]
        self.assertTrue(np.all(np.abs(corners) > 0.01), 'Normal DEM corners were forced to zero')
        self.assertAlmostEqual(float(plinth['verts'][:, 2].min()), float(expected.min()) - 4, places=5)
        self.assert_matches_original_arrays(payload, result)

    def test_first_dem_without_anchor_retains_normal_edges_and_plinth(self):
        payload, result = self.build()
        self.assert_normal_rectangle(payload, result, 1.25)
        self.assertEqual(result['raw_scene']['origin']['offset_from_anchor_m'][2], 0.0)

    def test_normal_dem_after_flat_anchor_keeps_full_profile_and_single_height_offset(self):
        payload, result = self.build(anchor=self.flat_anchor)
        self.assert_normal_rectangle(payload, result, 2.0)
        scene = result['raw_scene']
        self.assertEqual(scene['origin']['anchor_terrain_mode'], 'flat')
        self.assertEqual(result['mesh']['anchor']['terrain_mode'], 'flat')
        self.assertEqual(result['mesh']['anchor']['elevation'], 0)
        offset = scene['origin']['offset_from_anchor_m']
        self.assertGreater(abs(offset[0]) + abs(offset[1]), 1)
        center = round(float(self.dem[8, 8]), 3)
        self.assertAlmostEqual(offset[2], center * 2.0, places=4)
        # Local shape remains centered DEM. Applying the root's constant offset
        # once gives heights in the unchanged shared datum, with no edge warp.
        actual_global = scene['layers'][0]['meshes'][0]['verts'][:, 2].astype(float) + offset[2]
        self.np.testing.assert_allclose(actual_global.reshape(16, 16), self.dem * 2.0, atol=0.0001, rtol=0)

    def test_trimmed_hill_is_available_only_when_explicitly_selected(self):
        payload, result = self.build(anchor=self.flat_anchor, hill_patch=True)
        terrain = result['raw_scene']['layers'][0]
        self.assertTrue(result['mesh']['hill_patch'])
        self.assertEqual(terrain['tag'], 'MapSKP_01B_Terrain_HillPatch')
        self.assertEqual(len(terrain['meshes']), 1)
        self.assertLess(len(terrain['meshes'][0]['faces']), 450)
        self.assertEqual(result['raw_scene']['origin']['offset_from_anchor_m'][2], 0.0)
        self.assert_matches_original_arrays(payload, result)

    def test_explicit_mode_is_validated_and_preserved_through_api_parameters(self):
        self.assertFalse(parameters(self.params)['hill_patch'])
        selected = parameters({**self.params, 'anchor': self.flat_anchor, 'hill_patch': True})
        self.assertTrue(selected['hill_patch'])
        self.assertTrue(self.engine.original_parameters(selected)['hill_patch'])
        normal = self.engine.original_parameters(parameters({**self.params, 'anchor': self.flat_anchor}))
        self.assertFalse(normal['hill_patch'])
        self.assertEqual(normal['anchor']['terrain_mode'], 'terrain_3d')
        self.assertEqual(normal['anchor']['elevation_m'], 0)
        for change in ({'hill_patch': 'false'},
                       {'hill_patch': True},
                       {'hill_patch': True, 'anchor': self.flat_anchor, 'terrain': False},
                       {'hill_patch': True, 'anchor': {**self.flat_anchor, 'terrain_mode': 'terrain_3d'}}):
            with self.subTest(change=change), self.assertRaises(PublicError):
                self.engine.original_parameters(parameters({**self.params, **change}))


if __name__ == '__main__':
    unittest.main()
