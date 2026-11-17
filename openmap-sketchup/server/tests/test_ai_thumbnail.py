"""Local gallery thumbnails and clean comparison-source lifetime contracts."""
import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from openmap_server import ai_render
from openmap_server.ai_render import AIRenderService
from openmap_server.net import PublicError


def image_url(size=(1600, 900), color=(30, 80, 120), mode='RGB', exif=None):
    output = BytesIO()
    image = Image.new(mode, size, color)
    options = {'format': 'JPEG', 'exif': exif} if exif is not None else {'format': 'PNG'}
    image.save(output, **options)
    return 'data:image/' + ('jpeg' if exif is not None else 'png') + ';base64,' + base64.b64encode(output.getvalue()).decode()


class AIThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = {'OPENMAP_AI_DIR': self.folder.name, 'OPENMAP_LOCAL_TOKEN': 'private-thumbnail-worker'}
        self.service = AIRenderService(self.config)
        self.addCleanup(lambda: self.service.close())

    def upload(self, value=None, role='source'):
        return self.service.route('POST', '/api/ai/assets', {'data_url': value or image_url(), 'role': role})

    def thumb(self, asset_id):
        return self.service.route('GET', '/api/ai/assets/' + asset_id + '/thumbnail', {})

    def decode(self, item):
        raw = base64.b64decode(item['data_url'].split(',', 1)[1])
        image = Image.open(BytesIO(raw)); image.load()
        self.addCleanup(image.close)
        self.assertEqual((item['width'], item['height']), image.size)
        self.assertEqual(item['sha256'], sha256(raw).hexdigest())
        return raw, image

    def job(self, source, comparison=None, request_id='1' * 32, **updates):
        body = {'client_request_id': request_id, 'operation': 'render', 'source_id': source,
                'prompt': 'Render the existing building.', 'reference_ids': [], 'options': {}, **updates}
        if comparison is not None:
            body['comparison_source_id'] = comparison
        return body, self.service.create_job(body)

    def test_gallery_thumbnail_is_small_and_keeps_original_asset_and_metadata(self):
        asset = self.upload()
        before, metadata = self.service.asset_bytes(asset['id'])
        state_before = (Path(self.folder.name) / 'state.json').read_bytes()
        preview = self.thumb(asset['id'])
        raw, image = self.decode(preview)
        self.assertEqual(image.size, (512, 288))
        self.assertEqual(preview['mime'], 'image/jpeg')
        self.assertEqual(preview['id'], asset['id'])
        self.assertTrue(preview['thumbnail'])
        self.assertEqual((preview['original_width'], preview['original_height']), (1600, 900))
        self.assertEqual(preview['original_mime'], 'image/png')
        self.assertEqual(preview['original_sha256'], metadata['sha256'])
        self.assertLess(len(raw), len(before))
        self.assertEqual(self.service.asset_bytes(asset['id']), (before, metadata))
        self.assertEqual(state_before, (Path(self.folder.name) / 'state.json').read_bytes())
        self.assertEqual(len(list((Path(self.folder.name) / 'assets').iterdir())), 1)

    def test_portrait_small_and_transparent_previews(self):
        portrait = self.thumb(self.upload(image_url((300, 900)))['id'])
        self.assertEqual(max(portrait['width'], portrait['height']), 512)
        self.assertAlmostEqual(portrait['width'] / portrait['height'], 1 / 3, delta=.002)
        small = self.thumb(self.upload(image_url((12, 8)))['id'])
        self.assertEqual((small['width'], small['height']), (12, 8))
        transparent = self.thumb(self.upload(image_url((800, 400), (10, 50, 90, 0), 'RGBA'))['id'])
        _, image = self.decode(transparent)
        self.assertEqual(transparent['mime'], 'image/png')
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.getpixel((100, 100))[3], 0)

    def test_exif_orientation_is_applied_only_to_the_preview(self):
        exif = Image.Exif(); exif[274] = 6
        asset = self.upload(image_url((900, 300), exif=exif))
        preview = self.thumb(asset['id'])
        _, image = self.decode(preview)
        self.assertEqual((preview['original_width'], preview['original_height']), (900, 300))
        self.assertGreater(preview['height'], preview['width'])
        self.assertEqual(image.getexif().get(274), None)
        self.assertEqual((asset['width'], asset['height']), (900, 300))

    def test_bounded_lru_cache_reuses_decode_and_clears_on_close(self):
        asset = self.upload()
        first = self.thumb(asset['id'])
        with patch.object(ai_render.Image, 'open', side_effect=AssertionError('Repeated thumbnail decoded the full source')):
            self.assertEqual(self.thumb(asset['id']), first)
        weight = self.service._thumbnail_bytes
        with patch.object(ai_render, 'THUMBNAIL_CACHE_BYTES', weight + 100):
            other = self.upload(image_url((1600, 900), (200, 100, 50)))
            self.thumb(other['id'])
            self.assertLessEqual(self.service._thumbnail_bytes, weight + 100)
            self.assertNotIn(asset['id'], self.service._thumbnails)
            self.assertIn(other['id'], self.service._thumbnails)
        self.assertLessEqual(self.service._thumbnail_bytes, 8 * 1024 * 1024)
        self.service.close()
        self.assertEqual(self.service._thumbnail_bytes, 0)
        self.assertEqual(len(self.service._thumbnails), 0)

    def test_cache_does_not_hide_changed_or_corrupt_source_and_unknown_ids(self):
        asset = self.upload(); self.thumb(asset['id'])
        path = self.service._asset_path(self.service._state['assets'][asset['id']])
        path.write_bytes(b'not the original file')
        with self.assertRaises(PublicError) as failure:
            self.thumb(asset['id'])
        self.assertEqual(failure.exception.status, 500)
        self.assertNotIn(asset['id'], self.service._thumbnails)
        with self.assertRaises(PublicError) as failure:
            self.thumb('f' * 32)
        self.assertEqual(failure.exception.status, 404)
        with self.assertRaises(PublicError):
            self.service.route('GET', '/api/ai/assets/../../etc/passwd/thumbnail', {})

    def test_thumbnail_rechecks_pixel_bound_without_changing_original(self):
        asset = self.upload(image_url((80, 60)))
        before = self.service.asset_bytes(asset['id'])[0]
        with patch.object(ai_render, 'MAX_PIXELS', 100), self.assertRaises(PublicError):
            self.thumb(asset['id'])
        self.assertEqual(before, self.service.asset_bytes(asset['id'])[0])
        self.assertNotIn(asset['id'], self.service._thumbnails)

    def test_restart_regenerates_same_thumbnail_from_persistent_source(self):
        asset = self.upload(); first = self.thumb(asset['id'])
        self.service.close(); self.service = AIRenderService(self.config)
        self.assertFalse(self.service._thumbnails)
        second = self.thumb(asset['id'])
        self.assertEqual(first, second)
        self.assertEqual(len(list((Path(self.folder.name) / 'assets').iterdir())), 1)

    def test_comparison_source_is_persisted_fingerprinted_and_gc_protected(self):
        marked = self.upload(image_url((30, 20), (255, 50, 10)), role='annotation')
        clean = self.upload(image_url((30, 20), (20, 60, 90)))
        body, first = self.job(marked['id'], clean['id'])
        detail = self.service.route('GET', '/api/ai/jobs/' + first['id'], {})
        self.assertEqual(detail['comparison_source_id'], clean['id'])
        self.assertEqual(self.service.create_job(body)['id'], first['id'])
        with self.assertRaises(PublicError) as failure:
            self.service.create_job({**body, 'comparison_source_id': marked['id']})
        self.assertEqual(failure.exception.status, 409)
        with self.service.lock, patch.object(ai_render, 'MAX_ASSETS', 2), self.assertRaises(PublicError):
            self.upload(image_url((30, 20), (0, 0, 0)))
        self.service.asset_bytes(clean['id'])
        self.service.route('DELETE', '/api/ai/jobs/' + first['id'], {})
        result = self.upload(image_url((30, 20), (20, 90, 60)), role='manual_result')
        _, second = self.job(result['id'], clean['id'], request_id='2' * 32)
        self.service.route('DELETE', '/api/ai/history/' + first['id'], {})
        self.service.asset_bytes(clean['id'])
        self.thumb(clean['id'])
        self.service.route('DELETE', '/api/ai/jobs/' + second['id'], {})
        self.service.route('DELETE', '/api/ai/history/' + second['id'], {})
        self.assertNotIn(clean['id'], self.service._thumbnails)
        with self.assertRaises(PublicError):
            self.service.asset_bytes(clean['id'])

    def test_comparison_defaults_to_source_and_validates_existing_asset(self):
        asset = self.upload()
        _, job = self.job(asset['id'])
        self.assertEqual(job['comparison_source_id'], asset['id'])
        with self.assertRaises(PublicError):
            self.job(asset['id'], 'f' * 32, request_id='2' * 32)
        with self.assertRaises(PublicError):
            self.job(asset['id'], '../../outside', request_id='3' * 32)

    def test_complete_prompt_flag_is_boolean_fingerprinted_and_forwarded_verbatim(self):
        asset = self.upload(image_url((30, 20)))
        final_prompt = '\nPreserve the camera and design.\n1. Edit only the marked garden.\n'
        body, job = self.job(asset['id'], prompt=final_prompt,
            options={'keep_design': True, 'keep_camera': True, 'prompt_is_complete': True},
            annotation_notes='1. Edit only the marked garden.')
        self.assertEqual(self.service.route('GET', '/api/ai/jobs/' + job['id'], {})['prompt'], final_prompt)
        offer = self.service.route('POST', '/api/ai/pair', {})
        origin = 'chrome-extension://' + 'a' * 32
        client = 'c' * 32
        token = self.service._bridge_route('/pair', {'code': offer['code'], 'client_id': client}, origin, None)['token']
        claimed = self.service._bridge_route('/jobs/claim', {'client_id': client}, origin, 'Bearer ' + token)['job']
        self.assertEqual(claimed['prompt'], final_prompt)
        self.assertTrue(claimed['options']['prompt_is_complete'])
        self.assertEqual(claimed['annotation_notes'], '1. Edit only the marked garden.')
        self.assertEqual(claimed['prompt'].count('1. Edit only the marked garden.'), 1)
        with self.assertRaises(PublicError) as failure:
            self.service.create_job({**body, 'options': {**body['options'], 'prompt_is_complete': False}})
        self.assertEqual(failure.exception.status, 409)
        for value in [1, 'true', None]:
            with self.subTest(value=value), self.assertRaises(PublicError):
                self.job(asset['id'], request_id='f' * 32, options={'prompt_is_complete': value})

    def test_unpaired_manual_handoff_waits_without_claim_and_imports_explicit_result(self):
        source = self.upload(image_url((30, 20)))
        body, manual = self.job(source['id'], prompt='Complete preview prompt.',
            options={'manual_handoff': True, 'prompt_is_complete': True})
        self.assertIsNone(self.service._server)
        self.assertEqual(manual['state'], 'waiting_user')
        self.assertEqual(manual['message'], 'Đang chờ bạn tạo ảnh trên Flow và nhập kết quả.')
        detail = self.service.route('GET', '/api/ai/jobs/' + manual['id'], {})
        self.assertEqual(detail['prompt'], 'Complete preview prompt.')
        self.assertEqual(detail['source_id'], source['id'])
        with self.assertRaises(PublicError) as failure:
            self.service.create_job({**body, 'options': {**body['options'], 'manual_handoff': False}})
        self.assertEqual(failure.exception.status, 409)
        _, legacy = self.job(source['id'], request_id='2' * 32, options={'manual_handoff': False})
        self.assertEqual(legacy['state'], 'queued')
        offer = self.service.route('POST', '/api/ai/pair', {})
        origin = 'chrome-extension://' + 'a' * 32; client = 'c' * 32
        token = self.service._bridge_route('/pair', {'code': offer['code'], 'client_id': client}, origin, None)['token']
        self.assertIsNone(self.service._bridge_route('/jobs/claim', {'client_id': client}, origin, 'Bearer ' + token)['job'])
        imported = self.upload(image_url((30, 20), (90, 130, 60)), role='manual_result')
        completed = self.service.route('POST', '/api/ai/jobs/' + manual['id'] + '/import', {'asset_id': imported['id']})
        self.assertEqual(completed['state'], 'complete')
        self.assertEqual(completed['result_ids'], [imported['id']])
        claimed = self.service._bridge_route('/jobs/claim', {'client_id': client}, origin, 'Bearer ' + token)['job']
        self.assertEqual(claimed['id'], legacy['id'])

    def test_manual_handoff_is_boolean_and_cancel_cannot_be_imported(self):
        source = self.upload(image_url((30, 20)))
        for value in ['true', 1, None]:
            with self.subTest(value=value), self.assertRaises(PublicError):
                self.job(source['id'], options={'manual_handoff': value})
        _, legacy = self.job(source['id'], request_id='b' * 32)
        self.assertEqual(legacy['state'], 'queued')
        _, manual = self.job(source['id'], request_id='c' * 32, options={'manual_handoff': True})
        self.service.route('DELETE', '/api/ai/jobs/' + manual['id'], {})
        with self.assertRaises(PublicError) as failure:
            self.service.route('POST', '/api/ai/jobs/' + manual['id'] + '/import', {'asset_id': source['id']})
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.service.route('GET', '/api/ai/jobs/' + manual['id'], {})['state'], 'cancelled')

    def test_custom_aspect_accepts_bounded_large_integers_and_rejects_extremes(self):
        asset = self.upload()
        for index, aspect in enumerate(['1000:1000', '9999:500', '1:20', '20:1', 'original']):
            _, job = self.job(asset['id'], request_id='%032x' % (index + 1), options={'aspect': aspect})
            self.assertEqual(self.service.route('GET', '/api/ai/jobs/' + job['id'], {})['options']['aspect'], aspect)
        for aspect in ['10000:10000', '1:9999', '9999:1', '0:1', '1:0', '1.5:1', True, None, '01:2']:
            with self.subTest(aspect=aspect), self.assertRaises(PublicError):
                self.job(asset['id'], request_id='f' * 32, options={'aspect': aspect})


if __name__ == '__main__':
    unittest.main()
