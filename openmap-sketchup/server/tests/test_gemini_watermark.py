"""Synthetic known overlays and conservative refusals; no user-image/cloud tests."""
from hashlib import sha256
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from openmap_server import gemini_watermark as gemini
from openmap_server.net import PublicError


def background(size=(1024, 768), noise=0, bright=False):
    width, height = size
    yy, xx = np.mgrid[:height, :width]
    if bright:
        values = np.full((height, width, 3), 246., dtype=np.float64)
    else:
        values = np.stack((50 + 60 * xx / width + 5 * yy / height,
                           70 + 40 * xx / width + 10 * yy / height,
                           90 + 25 * xx / width + 15 * yy / height), axis=-1)
    if noise:
        values += np.random.default_rng(42).normal(0, noise, values.shape)
    return np.clip(np.rint(values), 0, 255).astype(np.uint8)


def encode(values, exif=None):
    output = BytesIO()
    kwargs = {'exif': exif} if exif else {}
    Image.fromarray(values).save(output, format='PNG', **kwargs)
    return output.getvalue()


def overlaid(version, size=(1024, 768), noise=0, opacity=1., offset=(0, 0), bright=False):
    clean = background(size, noise, bright)
    width, height = size
    variant, edge, inset = gemini._geometry(width, height, version)
    alpha = gemini._template(variant, edge)
    x, y = width - inset - edge + offset[0], height - inset - edge + offset[1]
    marked = clean.copy()
    marked[y:y + edge, x:x + edge] = np.clip(np.rint(
        clean[y:y + edge, x:x + edge] * (1 - alpha[..., None] * opacity)
        + 255 * alpha[..., None] * opacity), 0, 255)
    return clean, marked, variant, alpha, x, y


class GeminiWatermarkTests(unittest.TestCase):
    def assert_unchanged(self, raw, mode='auto'):
        result, info = gemini.remove_gemini(raw, mode)
        self.assertIs(result, raw)
        self.assertFalse(info['applied'])
        self.assertIsNone(info['variant'])
        self.assertEqual(info['confidence_kind'], 'heuristic_not_probability')
        return info

    def assert_cleaned(self, version, size=(1024, 768), noise=0, offset=(0, 0)):
        clean, marked, variant, alpha, x, y = overlaid(version, size, noise, offset=offset)
        raw = encode(marked)
        result, info = gemini.remove_gemini(raw)
        self.assertTrue(info['applied'], (variant, size, noise, info))
        self.assertEqual(info['variant'], variant)
        self.assertEqual(info['region'], {'x': x, 'y': y, 'width': len(alpha), 'height': len(alpha)})
        self.assertEqual(info['confidence_kind'], 'heuristic_not_probability')
        self.assertGreater(info['confidence'], .7)
        self.assertLessEqual(info['confidence'], 1)
        self.assertTrue(result.startswith(b'\x89PNG\r\n\x1a\n'))
        with Image.open(BytesIO(result)) as image:
            actual = np.asarray(image)
        support = np.zeros(marked.shape[:2], dtype=bool)
        support[y:y + len(alpha), x:x + len(alpha)] = alpha >= .002
        self.assertTrue(np.array_equal(actual[~support], marked[~support]))
        before_error = float(np.mean((marked[support].astype(float) - clean[support]) ** 2))
        after_error = float(np.mean((actual[support].astype(float) - clean[support]) ** 2))
        self.assertLess(after_error, before_error * .03)
        # Quantized inputs cannot promise mathematically perfect restoration.
        self.assertLess(float(np.max(np.abs(actual[support].astype(float) - clean[support]))), 3)
        return info

    def test_all_four_known_masks_on_smooth_gradient_background(self):
        for version, size in [('v1', (1024, 768)), ('v1', (1536, 1152)), ('v2', (1024, 768)), ('v2', (1536, 1152))]:
            with self.subTest(version=version, size=size):
                self.assert_cleaned(version, size)

    def test_known_masks_on_mild_noise_and_v2_half_resolution_geometry(self):
        for version, size in [('v1', (1024, 768)), ('v2', (1024, 768)), ('v2', (1376, 768))]:
            with self.subTest(version=version, size=size):
                self.assert_cleaned(version, size, noise=2)

    def test_v2_rounding_search_is_narrow_and_exact_position_is_reported(self):
        self.assert_cleaned('v2', offset=(2, -1))
        _, marked, *_ = overlaid('v2', offset=(10, 10))
        self.assert_unchanged(encode(marked))

    def test_plain_gradients_bright_corners_and_noise_are_exact_noops(self):
        for values in [background(), background(bright=True), background(noise=25),
                       np.zeros((768, 1024, 3), dtype=np.uint8), np.full((768, 1024, 3), 255, dtype=np.uint8)]:
            with self.subTest(mean=float(values.mean())):
                self.assert_unchanged(encode(values))

    def test_non_logo_scene_content_and_wrong_position_are_refused(self):
        image = Image.fromarray(background())
        painter = ImageDraw.Draw(image)
        painter.ellipse((938, 688, 990, 740), fill=(210, 210, 210))
        self.assert_unchanged(encode(np.asarray(image)))
        _, marked, *_ = overlaid('v1', offset=(-15, -12))
        self.assert_unchanged(encode(marked))

    def test_wrong_opacity_negative_inverse_ghost_and_bright_supported_mark_are_refused(self):
        for opacity in [.6, 1.35]:
            _, marked, *_ = overlaid('v1', opacity=opacity)
            self.assert_unchanged(encode(marked))
        # .92 fits the initial opacity range but would create negative pixels
        # when the known full-opacity template is subtracted from dark content.
        _, marked, variant, alpha, x, y = overlaid('v1')
        marked[:] = 2
        edge = len(alpha)
        marked[y:y + edge, x:x + edge] = np.rint(2 * (1 - alpha[..., None] * .92) + 255 * alpha[..., None] * .92)
        self.assert_unchanged(encode(marked))
        _, marked, *_ = overlaid('v2', bright=True)
        self.assert_unchanged(encode(marked))

    def test_profile_selection_does_not_override_signature_gates(self):
        _, marked, *_ = overlaid('v2')
        raw = encode(marked)
        self.assert_unchanged(raw, 'legacy')
        result, info = gemini.remove_gemini(raw, 'current')
        self.assertTrue(info['applied'])
        self.assertEqual(info['variant'], 'v2_small')
        self.assert_unchanged(encode(background()), 'current')

    def test_exif_is_only_oriented_on_applied_output_and_outside_mask_stays_equal(self):
        _, marked, _, alpha, x, y = overlaid('v1')
        logical = Image.fromarray(marked)
        stored = logical.transpose(Image.Transpose.ROTATE_90)
        exif = Image.Exif(); exif[274] = 6; exif[315] = 'Synthetic fixture'
        output = BytesIO(); stored.save(output, format='PNG', exif=exif)
        result, info = gemini.remove_gemini(output.getvalue())
        self.assertTrue(info['applied']); self.assertTrue(info['orientation_applied'])
        with Image.open(BytesIO(result)) as restored:
            self.assertEqual(restored.size, logical.size)
            self.assertIsNone(restored.getexif().get(274))
            self.assertEqual(restored.getexif().get(315), 'Synthetic fixture')
            values = np.asarray(restored)
        support = np.zeros(marked.shape[:2], dtype=bool); support[y:y + len(alpha), x:x + len(alpha)] = alpha >= .002
        self.assertTrue(np.array_equal(values[~support], marked[~support]))
        output = BytesIO(); Image.fromarray(background()).save(output, format='PNG', exif=exif)
        self.assert_unchanged(output.getvalue())

    def test_rgba_alpha_and_all_pixels_outside_mask_are_unchanged(self):
        _, marked, _, alpha, x, y = overlaid('v2')
        values = np.concatenate((marked, np.full((*marked.shape[:2], 1), 255, dtype=np.uint8)), axis=-1)
        values[0, 0, 3] = 0
        result, info = gemini.remove_gemini(encode(values))
        self.assertTrue(info['applied'])
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.mode, 'RGBA')
            actual = np.asarray(image)
        support = np.zeros(marked.shape[:2], dtype=bool)
        support[y:y + len(alpha), x:x + len(alpha)] = alpha >= .002
        self.assertTrue(np.array_equal(actual[~support], values[~support]))
        self.assertTrue(np.array_equal(actual[..., 3], values[..., 3]))
        values[y + len(alpha) // 2, x + len(alpha) // 2, 3] = 0
        self.assert_unchanged(encode(values))

    def test_corrupt_inputs_and_bounds_are_rejected_without_cloud_calls(self):
        for raw in [b'', b'not an image', bytearray(b'not bytes')]:
            with self.subTest(raw=raw), self.assertRaises(PublicError):
                gemini.remove_gemini(raw)
        raw = encode(background((100, 100)))
        with patch.object(gemini, 'MAX_BYTES', 10), self.assertRaises(PublicError):
            gemini.remove_gemini(raw)
        with patch.object(gemini, 'MAX_PIXELS', 10), self.assertRaises(PublicError):
            gemini.remove_gemini(raw)
        with self.assertRaises(PublicError):
            gemini.remove_gemini(raw, 'force')
        with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')) as network:
            self.assert_unchanged(raw)
        network.assert_not_called()

    def test_assets_have_pinned_hashes_and_complete_public_mit_notices(self):
        provenance = json.loads((gemini.ASSETS / 'provenance.json').read_text())
        self.assertEqual(provenance['source_commit'], '7c6a99f2c3df97eb3c430ef87a0c962aea5cb80e')
        self.assertEqual(len(provenance['masks']), 4)
        total = 0
        for item in provenance['masks']:
            raw = (gemini.ASSETS / (item['name'] + '.png')).read_bytes()
            self.assertEqual(sha256(raw).hexdigest(), item['sha256'])
            total += len(raw)
        self.assertEqual(total, 13_870)
        license_text = (gemini.ASSETS / 'LICENSE.txt').read_text()
        self.assertIn('Copyright (c) 2024 AllenK (Kwyshell)', license_text)
        self.assertIn('Copyright (c) 2025 Jad', license_text)
        self.assertIn('Permission is hereby granted', license_text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', license_text)


if __name__ == '__main__':
    unittest.main()
