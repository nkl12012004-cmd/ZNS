"""Persistent AI jobs/media, explicit recovery, and bounded waits; no Google calls."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from openmap_server import ai_render
from openmap_server.ai_render import AIRenderService
from openmap_server.net import PublicError

ORIGIN = 'chrome-extension://' + 'a' * 32
CLIENT = 'c' * 32


def picture(color=(20, 70, 120), size=(12, 8)):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()


class AIRenderPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'OPENMAP_AI_DIR': self.temp.name, 'OPENMAP_LOCAL_TOKEN': 'private-map-token', 'OPENMAP_AUTH_MODE': 'local'}
        self.service = AIRenderService(self.config)
        self.addCleanup(lambda: self.service.close())
        self.counter = 0

    def upload(self, value=None, role='source'):
        return self.service.route('POST', '/api/ai/assets', {'data_url': value or picture(), 'role': role})

    def body(self, source=None, **updates):
        self.counter += 1
        return {'client_request_id': '%032x' % self.counter, 'operation': 'render',
                'source_id': source or self.upload()['id'], 'reference_ids': [], 'prompt': 'Retain the building and camera.',
                'options': {'keep_design': True, 'keep_camera': True, 'aspect': 'original', 'preset': 'map'}, **updates}

    def pair(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        self.token = self.service._bridge_route('/pair', {'code': offer['code'], 'client_id': CLIENT}, ORIGIN, None)['token']

    def bridge(self, path, body):
        return self.service._bridge_route(path, body, ORIGIN, 'Bearer ' + self.token)

    def claim(self):
        return self.bridge('/jobs/claim', {'client_id': CLIENT})['job']

    def detail(self, job):
        return self.service.route('GET', '/api/ai/jobs/' + job['id'], {})

    def complete(self, claim, value=None, **more):
        return self.bridge('/jobs/' + claim['id'] + '/complete', {'lease': claim['lease'], 'images': [value or picture((90, 110, 40))], **more})

    def test_construction_is_lazy_without_external_calls_or_state_files(self):
        with tempfile.TemporaryDirectory() as folder, patch('socket.socket.connect', side_effect=AssertionError('network')), patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            root = Path(folder) / 'not-created'
            service = AIRenderService({**self.config, 'OPENMAP_AI_DIR': str(root)})
            self.assertFalse(root.exists())
            self.assertIsNone(service._server)
            service.close()
            self.assertFalse(root.exists())

    def test_upload_deduplicates_exact_bytes_and_role_across_restart(self):
        first = self.upload()
        same = self.upload()
        reference = self.upload(role='reference')
        self.assertEqual(first['id'], same['id'])
        self.assertNotEqual(first['id'], reference['id'])
        raw, metadata = self.service.asset_bytes(first['id'])
        self.assertEqual(metadata['width'], 12)
        self.assertEqual(metadata['height'], 8)
        self.assertEqual(self.service.route('GET', '/api/ai/assets/' + first['id'], {})['data_url'], picture())
        self.assertEqual(len(list((Path(self.temp.name) / 'assets').glob('*.png'))), 2)
        self.service.close()
        self.service = AIRenderService(self.config)
        self.assertEqual(first['id'], self.upload()['id'])
        self.assertEqual(raw, self.service.asset_bytes(first['id'])[0])
        self.assertNotIn('private-map-token', json.dumps(metadata))

    def test_persistent_request_id_is_idempotent_and_conflicting_payload_fails(self):
        body = self.body()
        job = self.service.create_job(body)
        self.assertEqual(job, self.service.create_job(deepcopy(body)))
        self.service.close(); self.service = AIRenderService(self.config)
        self.assertEqual(job['id'], self.service.create_job(body)['id'])
        with self.assertRaises(PublicError) as error:
            self.service.create_job({**body, 'prompt': 'Different generation'})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(len(self.service.route('GET', '/api/ai/jobs', {})['jobs']), 1)

    def test_restart_never_requeues_ambiguous_claim_and_preserves_pairing_hash_only(self):
        self.pair()
        job = self.service.create_job(self.body(annotation_notes='1. Only edit marked garden.'))
        claim = self.claim()
        self.assertEqual(claim['annotation_notes'], '1. Only edit marked garden.')
        self.bridge('/jobs/' + job['id'] + '/progress', {'lease': claim['lease'], 'state': 'running', 'message': 'Clicked the visible Generate button.'})
        self.service.close()
        saved = (Path(self.temp.name) / 'state.json').read_text()
        self.assertNotIn(self.token, saved)
        self.assertNotIn('private-map-token', saved)
        self.service = AIRenderService(self.config)
        detail = self.detail(job)
        self.assertEqual(detail['state'], 'waiting_user')
        self.assertNotIn('_lease', detail)
        self.service.status()
        self.service.create_job(self.body())
        self.assertIsNone(self.claim())
        with self.assertRaises(PublicError) as error:
            self.complete(claim)
        self.assertEqual(error.exception.status, 409)

    def test_stale_running_lease_requires_explicit_resolution(self):
        self.pair(); job = self.service.create_job(self.body()); claim = self.claim()
        with self.service.lock:
            self.service._state['jobs'][job['id']]['_touched'] = time.time() - 1000
        self.assertEqual(self.detail(job)['state'], 'waiting_user')
        self.assertIsNone(self.claim())
        with self.assertRaises(PublicError):
            self.complete(claim)
        chosen = self.upload(picture((30, 120, 40)), role='manual_result')
        imported = self.service.route('POST', '/api/ai/jobs/' + job['id'] + '/import', {'asset_id': chosen['id']})
        self.assertEqual(imported['state'], 'complete')
        self.assertEqual(imported['result_ids'], [chosen['id']])
        self.assertTrue(self.detail(job)['manual_import'])

    def test_completion_is_bound_to_image_bytes_and_lease(self):
        self.pair(); job = self.service.create_job(self.body()); claim = self.claim()
        image = picture((100, 120, 140))
        first = self.complete(claim, image)
        prefix, data = image.split(',', 1)
        wrapped = prefix + ',' + '\r\n'.join(data[i:i + 40] for i in range(0, len(data), 40))
        self.assertEqual(first, self.complete(claim, wrapped))
        with self.assertRaises(PublicError) as error:
            self.complete(claim, picture((200, 110, 70)))
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(PublicError):
            self.complete({**claim, 'lease': 'wrong'}, image)
        self.assertEqual(self.detail(job)['result_ids'], first['job']['result_ids'])

    def test_invalid_second_result_image_does_not_commit_any_result_asset(self):
        self.pair(); job = self.service.create_job(self.body()); claim = self.claim()
        before = set(self.service._state['assets'])
        with self.assertRaises(PublicError):
            self.bridge('/jobs/' + job['id'] + '/complete', {'lease': claim['lease'], 'images': [picture((90, 130, 60)), 'data:image/png;base64,bm90LXBuZw==']})
        self.assertEqual(before, set(self.service._state['assets']))
        self.assertNotEqual(self.detail(job)['state'], 'complete')
        self.assertEqual(self.detail(job)['result_ids'], [])

    def test_history_deletion_preserves_assets_used_by_another_job(self):
        self.pair(); source = self.upload(); first_body = self.body(source['id'])
        first = self.service.create_job(first_body); first_claim = self.claim()
        result_id = self.complete(first_claim)['job']['result_ids'][0]
        second = self.service.create_job(self.body(result_id, reference_ids=[source['id']]))
        outsider = Path(self.temp.name) / 'keep-user-file.txt'; outsider.write_text('user content')
        self.service.route('DELETE', '/api/ai/history/' + first['id'], {})
        self.service.asset_bytes(result_id); self.service.asset_bytes(source['id'])
        self.assertEqual(outsider.read_text(), 'user content')
        with self.assertRaises(PublicError):
            self.service.create_job(first_body)
        self.service.route('DELETE', '/api/ai/jobs/' + second['id'], {})
        self.service.route('DELETE', '/api/ai/history/' + second['id'], {})
        with self.assertRaises(PublicError):
            self.service.asset_bytes(result_id)
        self.assertEqual(outsider.read_text(), 'user content')

    def test_history_pruning_keeps_source_selected_for_new_job(self):
        self.pair(); first = self.service.create_job(self.body()); result_id = self.complete(self.claim())['job']['result_ids'][0]
        with patch.object(ai_render, 'MAX_HISTORY', 1):
            second = self.service.create_job(self.body(result_id))
        self.service.asset_bytes(result_id)
        self.assertEqual(self.detail(second)['source_id'], result_id)
        with self.assertRaises(PublicError):
            self.detail(first)

    def test_image_validation_limits_and_no_path_inputs(self):
        for data in ['https://example.org/a.png', 'data:image/png;base64,bm90IGFuIGltYWdl', picture().replace('image/png', 'image/jpeg')]:
            with self.subTest(data=data[:30]), self.assertRaises(PublicError):
                self.upload(data)
        with patch.object(ai_render, 'MAX_PIXELS', 20), self.assertRaises(PublicError):
            self.upload(picture(size=(6, 5)))
        with patch.object(ai_render, 'MAX_IMAGE', 20), self.assertRaises(PublicError):
            self.upload(picture())
        with self.assertRaises(PublicError):
            self.service.asset_bytes('../../etc/passwd')
        with self.assertRaises(PublicError):
            self.service.route('POST', '/api/ai/assets', {'data_url': picture(), 'role': 'arbitrary'})
        self.assertEqual(self.service._state['assets'], {})

    def test_storage_limit_never_evicts_job_owned_media(self):
        source = self.upload(); self.service.create_job(self.body(source['id']))
        with patch.object(ai_render, 'MAX_ASSETS', 1), self.assertRaises(PublicError) as error:
            self.upload(picture((90, 90, 90)))
        self.assertEqual(error.exception.status, 413)
        self.service.asset_bytes(source['id'])

    def test_source_with_exact_flow_provenance_is_bound_to_upscale_job(self):
        self.pair(); self.service.create_job(self.body()); claim = self.claim()
        flow = {'page_url': 'https://flow.google.com/project/ABC-12/edit/DEF-34?discard=1#secret', 'media_id': 'DEF-34'}
        result_id = self.complete(claim, flow=flow)['job']['result_ids'][0]
        upscale = self.service.create_job(self.body(result_id, operation='upscale', prompt=''))
        received = self.claim()
        self.assertEqual(received['operation'], 'upscale')
        self.assertEqual(received['flow'], {'page_url': 'https://flow.google.com/project/ABC-12/edit/DEF-34', 'media_id': 'DEF-34'})
        self.assertEqual(self.detail(upscale)['flow'], received['flow'])

    def test_flow_metadata_rejects_untrusted_hosts_credentials_and_media_urls(self):
        self.pair(); self.service.create_job(self.body()); claim = self.claim()
        for flow in [{'page_url': 'https://example.org/a'}, {'url': 'https://user:secret@labs.google/fx/tools/flow'}, {'page_url': 'https://labs.google/fx/tools/flow', 'image_url': 'https://example.org/a'}, {'url': 'https://labs.google.evil/fx/tools/flow'}, {'url': 'https://flow.google.com/project/../secret'}]:
            with self.subTest(flow=flow), self.assertRaises(PublicError):
                self.complete(claim, flow=flow)
        self.assertEqual(self.service._state['jobs'][claim['id']]['state'], 'claimed')

    def test_wait_success_cancel_timeout_and_close_wake_waiter(self):
        self.pair(); job = self.service.create_job(self.body()); claim = self.claim()
        result = {}
        def wait():
            try:
                result['job'] = self.service.wait_for_job(job['id'], threading.Event(), timeout=10)
            except Exception as exc:
                result['error'] = exc
        thread = threading.Thread(target=wait); thread.start()
        self.complete(claim); thread.join(timeout=3)
        self.assertFalse(thread.is_alive()); self.assertEqual(result['job']['state'], 'complete')
        cancelled = self.service.create_job(self.body()); old_claim = self.claim(); cancel = threading.Event(); cancel.set()
        with self.assertRaises(PublicError):
            self.service.wait_for_job(cancelled['id'], cancel, timeout=10)
        self.assertEqual(self.detail(cancelled)['state'], 'cancelled')
        with self.assertRaises(PublicError):
            self.complete(old_claim)
        timed = self.service.create_job(self.body())
        with self.assertRaises(PublicError) as error:
            self.service.wait_for_job(timed['id'], threading.Event(), timeout=0)
        self.assertEqual(error.exception.status, 408)
        self.assertEqual(self.detail(timed)['state'], 'waiting_user')
        self.service.route('DELETE', '/api/ai/jobs/' + timed['id'], {})
        job = self.service.create_job(self.body()); result.clear(); thread = threading.Thread(target=wait); thread.start()
        self.service.close(); thread.join(timeout=3)
        self.assertFalse(thread.is_alive()); self.assertIsInstance(result.get('error'), PublicError)

    def test_manual_import_is_explicit_and_cannot_revive_cancelled_job(self):
        asset = self.upload(role='manual_result'); job = self.service.create_job(self.body())
        with self.assertRaises(PublicError):
            self.service.route('POST', '/api/ai/jobs/' + job['id'] + '/import', {'asset_id': asset['id']})
        self.service.route('DELETE', '/api/ai/jobs/' + job['id'], {})
        with self.assertRaises(PublicError):
            self.service.route('POST', '/api/ai/jobs/' + job['id'] + '/import', {'asset_id': asset['id']})
        self.assertEqual(self.detail(job)['state'], 'cancelled')

    def test_generic_heartbeats_cannot_keep_an_abandoned_lease_alive(self):
        self.pair(); job = self.service.create_job(self.body()); claim = self.claim()
        with self.service.lock:
            original_touch = self.service._state['jobs'][job['id']]['_touched']
        with patch.object(ai_render.time, 'time', return_value=original_touch + 40):
            self.bridge('/heartbeat', {'client_id': CLIENT})
            self.assertIsNone(self.claim())
        self.assertEqual(self.service._state['jobs'][job['id']]['_touched'], original_touch)
        with patch.object(ai_render.time, 'time', return_value=original_touch + 100):
            self.bridge('/heartbeat', {'client_id': CLIENT})
            self.assertIsNone(self.claim())
        self.assertEqual(self.detail(job)['state'], 'waiting_user')

    def test_aggregate_images_are_bounded_before_job_creation_or_claim(self):
        source = self.upload()
        reference = self.upload(picture((40, 90, 30)), role='reference')
        body = self.body(source['id'], reference_ids=[reference['id']] * 4)
        with patch.object(ai_render, 'MAX_CLAIM_BYTES', 1500), self.assertRaises(PublicError) as error:
            self.service.create_job(body)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.service.route('GET', '/api/ai/jobs', {})['jobs'], [])
        self.assertEqual(self.service._state['requests'], {})

    def test_close_releases_bridge_and_state_lock_even_when_disk_write_fails(self):
        self.pair(); self.service.create_job(self.body()); self.claim()
        server = self.service._server
        with patch.object(self.service, '_atomic', side_effect=OSError('disk unavailable')):
            self.service.close()
        self.assertEqual(server.fileno(), -1)
        self.assertIsNone(self.service._file_lock)
        self.service = AIRenderService(self.config)
        jobs = self.service.route('GET', '/api/ai/jobs', {})['jobs']
        self.assertEqual(jobs[0]['state'], 'waiting_user')

    def test_only_one_service_can_mutate_one_state_folder(self):
        self.upload()
        other = AIRenderService(self.config)
        self.addCleanup(other.close)
        with self.assertRaises(PublicError) as error:
            other.create_job(self.body())
        self.assertEqual(error.exception.status, 409)
        self.service.close()
        self.assertEqual(other.route('GET', '/api/ai/jobs', {}), {'jobs': []})


class AILargePrivateUploadTests(unittest.TestCase):
    def test_valid_upload_larger_than_legacy_64k_body_limit(self):
        import http.client
        import random
        from openmap_server.app import create_server
        with tempfile.TemporaryDirectory() as folder:
            server, app = create_server({'OPENMAP_LOCAL_TOKEN': 'private-upload-token', 'OPENMAP_AI_DIR': folder}, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                output = BytesIO()
                Image.frombytes('RGB', (256, 256), random.Random(42).randbytes(256 * 256 * 3)).save(output, format='PNG')
                payload = json.dumps({'data_url': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()}).encode()
                self.assertGreater(len(payload), 65_536)
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                try:
                    connection.request('POST', '/api/ai/assets', body=payload,
                        headers={'X-OpenMap-Local': 'private-upload-token', 'Content-Type': 'application/json'})
                    response = connection.getresponse(); result = json.loads(response.read())
                    self.assertEqual(response.status, 200, result)
                    self.assertEqual((result['width'], result['height']), (256, 256))
                finally:
                    connection.close()
            finally:
                server.shutdown(); server.server_close(); app.close(); thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
