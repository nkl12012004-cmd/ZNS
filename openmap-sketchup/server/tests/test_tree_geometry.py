"""Geometric requirements for the new cylindrical/spherical SiteCraft tree."""
from collections import Counter
import math
import unittest

import numpy as np

from openmap_server.tree_geometry import make_round_tree


class RoundTreeTests(unittest.TestCase):
    def assert_closed_outward(self, mesh):
        vertices, faces = mesh['verts'], mesh['faces']
        self.assertEqual(vertices.dtype, np.float32)
        self.assertEqual(faces.dtype, np.uint32)
        self.assertIsNone(mesh['uvs'])
        self.assertEqual(vertices.shape[1], 3)
        self.assertEqual(faces.shape[1], 3)
        self.assertTrue(np.isfinite(vertices).all())
        self.assertTrue((faces < len(vertices)).all())
        directed, edges = Counter(), Counter()
        for a, b, c in faces.tolist():
            self.assertEqual(len({a, b, c}), 3)
            for start, end in ((a, b), (b, c), (c, a)):
                directed[start, end] += 1
                edges[tuple(sorted((start, end)))] += 1
        self.assertTrue(all(count == 2 for count in edges.values()), 'Open or nonmanifold mesh')
        self.assertTrue(all(directed[b, a] == count for (a, b), count in directed.items()), 'Inconsistent face winding')
        points = vertices[faces].astype(np.float64)
        normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        self.assertTrue((np.linalg.norm(normals, axis=1) > 0).all(), 'Degenerate triangle')
        center = (vertices.min(axis=0).astype(np.float64) + vertices.max(axis=0).astype(np.float64)) / 2
        self.assertTrue((np.einsum('ij,ij->i', normals, points.mean(axis=1) - center) > 0).all(), 'An inward face remains')
        centered = points - center
        return np.einsum('ij,ij->i', centered[:, 0], np.cross(centered[:, 1], centered[:, 2])).sum() / 6

    def test_round_crown_and_grounded_overlapping_trunk(self):
        for x, y, z, height, radius in [(0., 0., 0., 5.5, 1.7),
                                       (-1200., 800., -23.7, 8., 2.5),
                                       (3500., -3990., 140.3, 4., 1.2)]:
            with self.subTest(origin=(x, y, z)):
                tree = make_round_tree(x, y, z, height, radius)
                trunk, crown = tree['trunk'], tree['crown']
                crown_volume = self.assert_closed_outward(crown)
                trunk_volume = self.assert_closed_outward(trunk)
                self.assertGreater(trunk_volume, 0)
                self.assertLessEqual(sum(len(mesh['faces']) for mesh in tree.values()), 210)
                center = np.array([x, y, z + height - radius])
                distances = np.linalg.norm(crown['verts'].astype(np.float64) - center, axis=1)
                np.testing.assert_allclose(distances, radius, rtol=0, atol=0.0004)
                # More than half the analytic sphere's volume rules out a diamond
                # crown, while a closed inscribed faceted sphere approaches it.
                self.assertGreater(crown_volume, 0.85 * 4 / 3 * math.pi * radius ** 3)
                self.assertLess(crown_volume, 4 / 3 * math.pi * radius ** 3 * 1.001)
                self.assertAlmostEqual(float(crown['verts'][:, 2].max()), z + height, delta=0.0001)
                self.assertAlmostEqual(float(crown['verts'][:, 2].min()), z + height - 2 * radius, delta=0.0001)
                self.assertAlmostEqual(float(trunk['verts'][:, 2].min()), z, delta=0.0001)
                self.assertGreater(trunk['verts'][:, 2].max(), crown['verts'][:, 2].min())
                self.assertLess(trunk['verts'][:, 2].max(), z + height - radius)
                self.assertGreater(crown['verts'][:, 2].min(), z)

    def test_deterministic_and_poles_have_no_duplicate_vertices(self):
        first = make_round_tree(10, -10, 42)
        second = make_round_tree(10, -10, 42)
        for part in first:
            self.assertEqual(first[part]['verts'].tobytes(), second[part]['verts'].tobytes())
            self.assertEqual(first[part]['faces'].tobytes(), second[part]['faces'].tobytes())
        crown = first['crown']['verts']
        self.assertEqual(len(np.unique(crown, axis=0)), len(crown))
        self.assertEqual(sum(crown[:, 2] == crown[:, 2].max()), 1)
        self.assertEqual(sum(crown[:, 2] == crown[:, 2].min()), 1)

    def test_bad_dimensions_and_nonfinite_coordinates_are_rejected(self):
        cases = [(0, 0, 0, 3, 1.5), (0, 0, 0, 2, 2),
                 (0, 0, 0, 5, 0), (0, 0, 0, 5, -1),
                 (math.nan, 0, 0, 5, 1), (0, math.inf, 0, 5, 1),
                 (0, 0, 0, math.inf, 1), (True, 0, 0, 5, 1),
                 ('10', 0, 0, 5, 1), (1e30, 0, 0, 5, 1)]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                make_round_tree(*values)


if __name__ == '__main__':
    unittest.main()
