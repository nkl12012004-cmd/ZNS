"""Normal tree dimensions and child crowns supported by actual image peaks."""
from copy import deepcopy
import math
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from openmap_server import simple_trees as trees
from openmap_server.canopy_detector import detect_canopies, refine_large_canopies
from openmap_server.net import PublicError
from test_canopy_detector import crown_image, encoded_image, rectangle_image
from test_simple_trees import make_scene, params, features, project, centers


PARENT_CENTER = (126, 126)
PARENT_RADIUS = 40
VISIBLE_PEAKS = ((108, 111, 16), (146, 113, 16), (127, 147, 17))


def broad_canopy_image(*, shift=(0, 0), hole=False, peaks=VISIBLE_PEAKS):
    """Connected foliage with distinct bright domes, leaf texture and shadow.

    All coordinates come from the image, not placement points. The low green
    parent connects the visible lobes; bright peaks have intervening valleys.
    """
    size = 256
    rng = np.random.default_rng(19042)
    yy, xx = np.indices((size, size))
    cx, cy = PARENT_CENTER[0] + shift[0], PARENT_CENTER[1] + shift[1]
    parent = (xx - cx) ** 2 + (yy - cy) ** 2 <= PARENT_RADIUS ** 2
    rgb = np.full((size, size, 3), 172., dtype=np.float64)
    shadow = (xx - cx - 25) ** 2 + (yy - cy - 22) ** 2 <= (PARENT_RADIUS * 1.05) ** 2
    rgb[shadow] = (30, 32, 30)
    green = 75 + rng.normal(0, 3, (size, size))
    for px, py, radius in peaks:
        distance = np.sqrt((xx - px - shift[0]) ** 2 + (yy - py - shift[1]) ** 2) / radius
        dome = np.clip(1 - distance, 0, 1)
        green = np.maximum(green, 78 + 91 * dome + rng.normal(0, 11, (size, size)) * (dome > 0))
    rgb[parent, 0] = (green * .47)[parent]
    rgb[parent, 1] = green[parent]
    rgb[parent, 2] = (green * .38)[parent]
    if hole:
        rgb[(xx - cx) ** 2 + (yy - cy) ** 2 <= 9 ** 2] = (155, 155, 155)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def pixels(crowns):
    return [(crown['u'] * 255, (1 - crown['v']) * 255) for crown in crowns]


def detect_and_refine(image, level='medium'):
    parents = detect_canopies(image, 60., 60., level=level)
    return parents, refine_large_canopies(image, parents, 60., 60., level=level)


class TreeScaleClusterTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(trees, 'fetch_tree_features', side_effect=AssertionError('Unexpected network query'))
        self.fetch = guard.start()
        self.addCleanup(guard.stop)

    def assertNearVisiblePeaks(self, children, *, shift=(0, 0), peaks=VISIBLE_PEAKS):
        unused = [(px + shift[0], py + shift[1], radius) for px, py, radius in peaks]
        for child, (x, y) in zip(children, pixels(children)):
            near = min(unused, key=lambda peak: math.hypot(x - peak[0], y - peak[1]))
            self.assertLessEqual(math.hypot(x - near[0], y - near[1]), near[2] / 4, child)
            unused.remove(near)
            self.assertEqual(child['method'], 'crown_cluster_peak')
            self.assertLessEqual(child['radius_m'], 2.)
            self.assertGreaterEqual(child['radius_m'], 1.3)

    def assertNormalRenderedGeometry(self, scene):
        ground = trees.Ground(scene)
        total = 0
        for layer in scene['layers']:
            if layer['tag'] != trees.TREE_TAG:
                continue
            for mesh in layer['meshes']:
                material = scene['materials'][mesh['mat_idx']]
                if 'Crown' not in material['name']:
                    continue
                for crown in mesh['verts'].reshape(-1, 86, 3):
                    x, y, top = map(float, crown[0])
                    z = ground.height(x, y)
                    self.assertIsNotNone(z)
                    self.assertLessEqual(float(np.ptp(crown[:, 0])) / 2, 2.00001)
                    self.assertLessEqual(float(np.ptp(crown[:, 1])) / 2, 2.00001)
                    self.assertLessEqual(top - z, 6.50001)
                    self.assertGreaterEqual(top - z, 3.99999)
                    self.assertGreater(float(crown[:, 2].min()), z)
                    total += 1
        self.assertGreater(total, 0)
        self.assertEqual(total, len(scene['sitecraft']['detected_tree_locations']))

    def test_connected_three_peak_canopy_splits_at_visible_peaks(self):
        image = broad_canopy_image()
        parents, children = detect_and_refine(image)
        self.assertEqual(len(parents), 1)
        self.assertGreater(parents[0]['radius_m'], 9.)
        self.assertEqual(len(children), 3)
        self.assertNearVisiblePeaks(children)
        for child in children:
            self.assertEqual(child['parent_u'], parents[0]['u'])
            self.assertEqual(child['parent_v'], parents[0]['v'])
            self.assertEqual(child['parent_radius_m'], parents[0]['radius_m'])
            self.assertEqual(child['parent_canopy_id'], 0)

    def test_hole_shadow_and_non_green_parent_pixels_never_receive_children(self):
        image = broad_canopy_image(hole=True)
        parents, children = detect_and_refine(image)
        self.assertEqual(len(parents), 1)
        self.assertEqual(len(children), 3)
        self.assertNearVisiblePeaks(children)
        for x, y in pixels(children):
            self.assertGreater(math.hypot(x - 126, y - 126), 9.)
            self.assertLess(math.hypot(x - 126, y - 126), PARENT_RADIUS)
            red, green, blue = image.getpixel((round(x), round(y)))
            self.assertGreater(green, red * 1.055)
            self.assertGreater(green, blue * 1.10)

    def test_single_smooth_dome_stays_one_without_forced_area_fill(self):
        image = crown_image([(126, 123, 34)])
        parents, refined = detect_and_refine(image, 'dense')
        self.assertEqual(len(parents), 1)
        self.assertGreater(parents[0]['radius_m'], 7.5)
        self.assertEqual(refined, parents)
        self.assertNotIn('parent_canopy_id', refined[0])

    def test_positions_follow_translated_image_and_are_repeatable(self):
        first_image = broad_canopy_image()
        parents, first = detect_and_refine(first_image)
        original = deepcopy(parents)
        self.assertEqual(first, refine_large_canopies(first_image, parents, 60., 60.))
        self.assertEqual(parents, original)
        shifted_image = broad_canopy_image(shift=(23, -17))
        _, shifted = detect_and_refine(shifted_image)
        self.assertEqual(len(first), 3)
        self.assertEqual(len(shifted), 3)
        self.assertNearVisiblePeaks(shifted, shift=(23, -17))
        for x, y in pixels(first):
            self.assertLess(min(math.hypot(sx - x - 23, sy - y + 17) for sx, sy in pixels(shifted)), 2.)

    def test_parent_canopy_children_are_bounded_to_six(self):
        peak_ring = tuple((126 + 23 * math.cos(i * math.pi / 4),
                           126 + 23 * math.sin(i * math.pi / 4), 9) for i in range(8))
        image = broad_canopy_image(peaks=peak_ring)
        parents, children = detect_and_refine(image, 'dense')
        self.assertEqual(len(parents), 1)
        self.assertGreaterEqual(len(children), 2)
        self.assertLessEqual(len(children), 6)
        self.assertNearVisiblePeaks(children, peaks=peak_ring)

    def test_blank_and_grass_images_still_produce_no_refined_trees(self):
        for image in (Image.new('RGB', (256, 256), (60, 140, 50)),
                      Image.new('RGB', (256, 256), (155, 155, 155)),
                      rectangle_image(noise=True, shadow=True), rectangle_image(ribs=True, shadow=True)):
            parents, children = detect_and_refine(image, 'dense')
            self.assertEqual(parents, [])
            self.assertEqual(children, [])

    def test_refinement_caps_total_even_when_no_parent_requires_split(self):
        # A detector-output fixture tests the API resource bound, not planting.
        crowns = [{'u': (i % 60 + .5) / 60, 'v': (i // 60 + .5) / 60,
                   'radius_m': 1.5, 'confidence': .9, 'method': 'outlined_crown'} for i in range(3000)]
        refined = refine_large_canopies(Image.new('RGB', (256, 256)), crowns, 12000., 12000.)
        self.assertLessEqual(len(refined), 2500)
        self.assertEqual(crowns[0]['radius_m'], 1.5)

    def test_refinement_cancellation_before_and_during_multiple_parents(self):
        image = broad_canopy_image()
        parents = detect_canopies(image, 60., 60.) * 3
        class CancelAfterChecks:
            def __init__(self): self.calls = 0
            def is_set(self): self.calls += 1; return self.calls >= 3
        event = threading.Event()
        event.set()
        for cancel in (event, CancelAfterChecks()):
            with self.assertRaisesRegex(PublicError, 'hủy'):
                refine_large_canopies(image, parents, 60., 60., cancel=cancel)

    def test_giant_measured_canopy_and_mapped_35m_height_render_normal_size(self):
        scene = make_scene(encoded_image(Image.new('RGB', (256, 256), (155, 155, 155))), side=60., heights=(3., 3., 3., 3.))
        detector_record = {'u': .5, 'v': .5, 'radius_m': 10., 'confidence': .94, 'method': 'outlined_crown'}
        data = features([(0., 0.)])
        data['points'][0]['height'] = 35.
        with patch.object(trees, 'detect_canopies', return_value=[detector_record]):
            summary = trees.add_simple_trees(scene, params(trees_from_imagery=False), cache_dir='/unused',
                project=project, feature_data=data, allow_network=False)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['osm'], 1)
        self.assertEqual(summary['max_render_radius_m'], 2.)
        self.assertEqual(summary['max_render_height_m'], 6.5)
        self.assertEqual(summary['split_canopies'], 0)
        location = scene['sitecraft']['detected_tree_locations'][0]
        self.assertEqual(location['measured_radius_m'], 10.)
        self.assertEqual(location['radius_m'], 2.)
        self.assertEqual(location['height_m'], 6.5)
        np.testing.assert_allclose(centers(scene), [[0., 0., 3.]], atol=1e-6)
        self.assertNormalRenderedGeometry(scene)

    def test_actual_broad_image_yields_normal_children_and_preserves_scene_source(self):
        texture = encoded_image(broad_canopy_image())
        scene = make_scene(texture, side=60., heights=(2., 2., 2., 2.))
        ground_mesh = scene['layers'][0]['meshes'][0]
        before = deepcopy(ground_mesh)
        material = scene['materials'][0]
        summary = trees.add_simple_trees(scene, params(trees_from_imagery=True), cache_dir='/unused',
            project=project, feature_data=features(), allow_network=False)
        self.assertEqual(summary['detected_candidates'], 1)
        self.assertEqual(summary['refined_candidates'], 3)
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['cluster_trees'], 3)
        self.assertEqual(summary['split_canopies'], 1)
        self.assertFalse(summary['random_scattering'])
        self.assertIs(scene['materials'][0], material)
        self.assertIs(scene['materials'][0]['texture_bytes'], texture)
        for key in ('verts', 'faces', 'uvs'):
            np.testing.assert_array_equal(ground_mesh[key], before[key])
        self.assertNormalRenderedGeometry(scene)
        locations = scene['sitecraft']['detected_tree_locations']
        self.assertTrue(all(item['parent_radius_m'] > 9. and item['radius_m'] <= 2. for item in locations))
        self.fetch.assert_not_called()

if __name__ == '__main__':
    unittest.main()
