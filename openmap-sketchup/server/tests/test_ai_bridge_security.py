"""Loopback pairing, authentication and lifecycle checks without Google calls."""
import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

from openmap_server.ai_render import AIRenderService
from openmap_server.app import create_server


ORIGIN = 'chrome-extension://' + 'a' * 32
OTHER_ORIGIN = 'chrome-extension://' + 'b' * 32
CLIENT = 'c' * 32
PRIVATE_TOKEN = 'private-map-worker-transport-must-never-leak'


def image_url(color=(30, 100, 60)):
    output = BytesIO()
    Image.new('RGB', (4, 3), color).save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def request(port, method, path, body=None, origin=None, token=None, headers=None):
    values = {'Content-Type': 'application/json'}
    if origin is not None:
        values['Origin'] = origin
    if token is not None:
        values['Authorization'] = 'Bearer ' + token
    if headers:
        values.update(headers)
    payload = None if body is None else json.dumps(body).encode('utf-8')
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request(method, path, body=payload, headers=values)
        response = connection.getresponse()
        data = response.read()
        answer = json.loads(data) if data else None
        return response.status, dict(response.getheaders()), answer
    finally:
        connection.close()


class AIBridgeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'OPENMAP_AI_DIR': self.temp.name,
                       'OPENMAP_AUTH_MODE': 'local', 'OPENMAP_LOCAL_TOKEN': PRIVATE_TOKEN}
        self.service = AIRenderService(self.config)
        self.addCleanup(self.service.close)
        self.port = self.service.status()['bridge']['port']

    def pair(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        self.assertEqual(offer['port'], self.port)
        self.assertGreater(offer['expires_in'], 0)
        self.assertLessEqual(offer['expires_in'], 600)
        status, headers, result = request(self.port, 'POST', '/pair',
                                         {'code': offer['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['protocol'], 1)
        self.assertEqual(result['port'], self.port)
        self.assertIsInstance(result['token'], str)
        self.assertGreaterEqual(len(result['token']), 32)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), ORIGIN)
        return result['token']

    def create_job(self, request_id='1' * 32):
        asset = self.service.route('POST', '/api/ai/assets', {'data_url': image_url()})
        return self.service.create_job({'client_request_id': request_id, 'operation': 'render',
                                       'source_id': asset['id'], 'reference_ids': [],
                                       'prompt': 'Natural daylight, keep the existing camera and design.',
                                       'options': {'keep_design': True, 'keep_camera': True}})

    def test_bridge_uses_dedicated_loopback_port_and_health_exposes_no_credentials(self):
        self.assertIn(self.port, range(17865, 17873))
        status, headers, health = request(self.port, 'GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(health['name'], 'SiteCraft AI Bridge')
        self.assertEqual(health['protocol'], 1)
        self.assertFalse(health['paired'])
        self.assertNotIn('token', health)
        self.assertNotIn('code', health)
        self.assertNotIn(PRIVATE_TOKEN, json.dumps(health))
        self.assertNotEqual(headers.get('Access-Control-Allow-Origin'), '*')

    def test_pairing_rejects_websites_and_invalid_extension_ids(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        for origin in ['https://example.org', 'chrome-extension://' + 'q' * 32, ORIGIN + '/']:
            with self.subTest(origin=origin):
                status, headers, body = request(self.port, 'POST', '/pair',
                                               {'code': offer['code'], 'client_id': CLIENT}, origin=origin)
                self.assertIn(status, (400, 401, 403))
                self.assertNotIn('token', body)
                self.assertNotEqual(headers.get('Access-Control-Allow-Origin'), origin)
        self.assertFalse(self.service.status()['bridge']['paired'])

    def test_pair_code_is_single_use_and_worker_api_never_returns_bridge_token(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        status, _, response = request(self.port, 'POST', '/pair',
                                     {'code': offer['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 200, response)
        token = response['token']
        status, _, again = request(self.port, 'POST', '/pair',
                                   {'code': offer['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertIn(status, (400, 401, 403, 409))
        self.assertNotIn('token', again)
        summary = self.service.route('GET', '/api/ai/status', {})
        self.assertTrue(summary['bridge']['paired'])
        serialized = json.dumps(summary)
        self.assertNotIn(token, serialized)
        self.assertNotIn(PRIVATE_TOKEN, serialized)

    def test_pair_code_expires_before_it_can_issue_credentials(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        after_expiry = time.monotonic() + offer['expires_in'] + 1
        with patch('openmap_server.ai_render.time.monotonic', return_value=after_expiry):
            status, _, body = request(self.port, 'POST', '/pair',
                                       {'code': offer['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 403, body)
        self.assertNotIn('token', body)
        self.assertFalse(self.service.status()['bridge']['paired'])

    def test_five_failed_pair_attempts_require_a_new_private_code(self):
        offer = self.service.route('POST', '/api/ai/pair', {})
        wrong = '000000' if offer['code'] != '000000' else '111111'
        for attempt in range(5):
            status, _, body = request(self.port, 'POST', '/pair',
                                       {'code': wrong, 'client_id': CLIENT}, origin=ORIGIN)
            self.assertEqual(status, 403, (attempt, body))
        status, _, body = request(self.port, 'POST', '/pair',
                                   {'code': offer['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 403, body)
        self.assertNotIn('token', body)
        self.assertFalse(self.service.status()['bridge']['paired'])
        replacement = self.service.route('POST', '/api/ai/pair', {})
        status, _, body = request(self.port, 'POST', '/pair',
                                   {'code': replacement['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 200, body)

    def test_new_private_pair_offer_invalidates_previous_code(self):
        with patch('openmap_server.ai_render.secrets.randbelow', side_effect=[123456, 654321]):
            previous = self.service.route('POST', '/api/ai/pair', {})
            replacement = self.service.route('POST', '/api/ai/pair', {})
        self.assertNotEqual(previous['code'], replacement['code'])
        status, _, body = request(self.port, 'POST', '/pair',
                                   {'code': previous['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 403, body)
        self.assertNotIn('token', body)
        status, _, body = request(self.port, 'POST', '/pair',
                                   {'code': replacement['code'], 'client_id': CLIENT}, origin=ORIGIN)
        self.assertEqual(status, 200, body)

    def test_paired_token_is_bound_to_the_original_client_id(self):
        token = self.pair()
        for path in ('/heartbeat', '/jobs/claim'):
            status, _, body = request(self.port, 'POST', path, {'client_id': 'd' * 32},
                                       origin=ORIGIN, token=token)
            self.assertEqual(status, 403, body)
        status, _, body = request(self.port, 'POST', '/heartbeat', {'client_id': CLIENT},
                                   origin=ORIGIN, token=token)
        self.assertEqual(status, 200, body)

    def test_rebinding_host_is_rejected_even_with_paired_origin_and_token(self):
        token = self.pair()
        for host in ('evil.example', 'localhost:%d' % self.port, '127.0.0.1:1'):
            with self.subTest(host=host):
                status, headers, body = request(self.port, 'POST', '/heartbeat', {'client_id': CLIENT},
                                                 origin=ORIGIN, token=token, headers={'Host': host})
                self.assertEqual(status, 403, body)
                self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(request(self.port, 'POST', '/heartbeat', {'client_id': CLIENT},
                                 origin=ORIGIN, token=token)[0], 200)

    def test_bearer_and_exact_paired_origin_are_both_required(self):
        token = self.pair()
        for origin, bearer in [(ORIGIN, None), (ORIGIN, 'wrong'), (None, token),
                               (OTHER_ORIGIN, token), ('https://example.org', token)]:
            with self.subTest(origin=origin, bearer=bearer):
                status, headers, body = request(self.port, 'POST', '/heartbeat',
                                               {'client_id': CLIENT}, origin=origin, token=bearer)
                self.assertIn(status, (401, 403))
                self.assertNotIn('token', body)
                if origin is None:
                    self.assertNotIn('Access-Control-Allow-Origin', headers)
                elif origin != ORIGIN:
                    self.assertNotEqual(headers.get('Access-Control-Allow-Origin'), origin)
        status, headers, body = request(self.port, 'POST', '/heartbeat', {'client_id': CLIENT},
                                       origin=ORIGIN, token=token)
        self.assertEqual(status, 200, body)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), ORIGIN)
        self.assertTrue(self.service.status()['bridge']['connected'])

    def test_preflight_allows_only_the_paired_extension(self):
        self.pair()
        for origin, expected in [(ORIGIN, 204), (OTHER_ORIGIN, 403), ('https://example.org', 403)]:
            status, headers, _ = request(self.port, 'OPTIONS', '/jobs/claim', origin=origin,
                                        headers={'Access-Control-Request-Method': 'POST',
                                                 'Access-Control-Request-Headers': 'authorization,content-type'})
            if origin == ORIGIN:
                self.assertIn(status, (200, 204))
                self.assertEqual(headers.get('Access-Control-Allow-Origin'), ORIGIN)
                self.assertIn('POST', headers.get('Access-Control-Allow-Methods', ''))
                self.assertIn('authorization', headers.get('Access-Control-Allow-Headers', '').lower())
            else:
                self.assertEqual(status, expected)
                self.assertNotEqual(headers.get('Access-Control-Allow-Origin'), origin)

    def test_oversized_content_length_is_rejected_before_reading_body(self):
        token = self.pair()
        status, _, body = request(self.port, 'POST', '/jobs/claim', body=None, origin=ORIGIN, token=token,
                                  headers={'Content-Length': str(64 * 1024 * 1024 + 1)})
        self.assertEqual(status, 413, body)

    def test_parallel_claims_do_not_submit_one_generation_twice(self):
        token = self.pair()
        job = self.create_job()
        def claim(_):
            return request(self.port, 'POST', '/jobs/claim', {'client_id': CLIENT}, origin=ORIGIN, token=token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))
        self.assertTrue(all(item[0] == 200 for item in results), results)
        claimed = [item[2]['job'] for item in results if item[2].get('job') is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]['id'], job['id'])
        self.assertIn('lease', claimed[0])
        self.assertIn('data_url', claimed[0]['source'])
        self.assertNotIn(PRIVATE_TOKEN, json.dumps(claimed[0]))

    def test_completion_is_idempotent_and_cancel_cannot_be_revived(self):
        token = self.pair()
        job = self.create_job()
        status, _, response = request(self.port, 'POST', '/jobs/claim', {'client_id': CLIENT},
                                      origin=ORIGIN, token=token)
        self.assertEqual(status, 200)
        lease = response['job']['lease']
        payload = {'lease': lease, 'images': [image_url((80, 90, 100))],
                   'flow': {'url': 'https://labs.google/fx/tools/flow'}}
        path = '/jobs/%s/complete' % job['id']
        first = request(self.port, 'POST', path, payload, origin=ORIGIN, token=token)
        self.assertEqual(first[0], 200, first[2])
        results = self.service.route('GET', '/api/ai/jobs/' + job['id'], {})['result_ids']
        second = request(self.port, 'POST', path, payload, origin=ORIGIN, token=token)
        self.assertEqual(second[0], 200, second[2])
        complete = self.service.route('GET', '/api/ai/jobs/' + job['id'], {})
        self.assertEqual(complete['state'], 'complete')
        self.assertEqual(complete['result_ids'], results)
        another = self.create_job('2' * 32)
        _, _, claimed = request(self.port, 'POST', '/jobs/claim', {'client_id': CLIENT}, origin=ORIGIN, token=token)
        self.service.route('DELETE', '/api/ai/jobs/' + another['id'], {})
        late = request(self.port, 'POST', '/jobs/%s/complete' % another['id'],
                       {'lease': claimed['job']['lease'], 'images': [image_url()]}, origin=ORIGIN, token=token)
        self.assertIn(late[0], (400, 403, 409))
        self.assertEqual(self.service.route('GET', '/api/ai/jobs/' + another['id'], {})['state'], 'cancelled')

    def test_wrong_lease_and_external_result_urls_cannot_trigger_fetch(self):
        token = self.pair()
        job = self.create_job()
        _, _, response = request(self.port, 'POST', '/jobs/claim', {'client_id': CLIENT}, origin=ORIGIN, token=token)
        lease = response['job']['lease']
        status, _, _ = request(self.port, 'POST', '/jobs/%s/progress' % job['id'],
                               {'lease': 'wrong-lease', 'state': 'running', 'message': 'untrusted'},
                               origin=ORIGIN, token=token)
        self.assertIn(status, (400, 403, 409))
        with patch('urllib.request.urlopen', side_effect=AssertionError('Result URL was fetched')) as fetch:
            status, _, _ = request(self.port, 'POST', '/jobs/%s/complete' % job['id'],
                                   {'lease': lease, 'images': ['https://example.org/image.png']},
                                   origin=ORIGIN, token=token)
        self.assertIn(status, (400, 413, 415, 422))
        fetch.assert_not_called()
        self.assertNotEqual(self.service.route('GET', '/api/ai/jobs/' + job['id'], {})['state'], 'complete')

    def test_unpair_invalidates_credentials_and_active_lease(self):
        token = self.pair()
        job = self.create_job()
        _, _, response = request(self.port, 'POST', '/jobs/claim', {'client_id': CLIENT}, origin=ORIGIN, token=token)
        lease = response['job']['lease']
        self.service.route('POST', '/api/ai/unpair', {})
        self.assertFalse(self.service.status()['bridge']['paired'])
        late = request(self.port, 'POST', '/jobs/%s/progress' % job['id'],
                       {'lease': lease, 'state': 'running', 'message': 'late'}, origin=ORIGIN, token=token)
        self.assertIn(late[0], (401, 403))
        self.assertEqual(self.service.route('GET', '/api/ai/jobs/' + job['id'], {})['state'], 'waiting_user')

    def test_close_releases_port_and_invalidates_connection(self):
        self.pair()
        self.service.close()
        with self.assertRaises((ConnectionError, OSError, TimeoutError)):
            request(self.port, 'GET', '/health')


class AIApplicationTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'OPENMAP_AI_DIR': self.temp.name, 'OPENMAP_AUTH_MODE': 'local',
                       'OPENMAP_LOCAL_TOKEN': PRIVATE_TOKEN}
        self.server, self.app = create_server(self.config, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.app.close()
        self.thread.join(timeout=5); self.temp.cleanup()

    def call(self, method, path, body=None, token=PRIVATE_TOKEN, origin=None, headers=None):
        values = {} if token is None else {'X-OpenMap-Local': token}
        if headers:
            values.update(headers)
        return request(self.server.server_port, method, path, body, origin=origin, headers=values)

    def test_ai_is_available_only_with_private_transport_in_managed_mode(self):
        for token in (None, 'wrong'):
            self.assertEqual(self.call('GET', '/api/ai/status', token=token)[0], 403)
        status, _, body = self.call('GET', '/api/ai/status')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['protocol'], 1)
        self.assertNotIn(PRIVATE_TOKEN, json.dumps(body))
        self.app.config['OPENMAP_AUTH_MODE'] = 'supabase'
        self.assertEqual(self.call('GET', '/api/ai/status')[0], 403)

    def test_main_worker_does_not_allow_browser_origin_even_with_token(self):
        status, headers, _ = self.call('GET', '/api/ai/status', origin=ORIGIN)
        self.assertEqual(status, 403)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_ai_body_limit_is_64_mib_and_enforced_before_body_read(self):
        status, _, body = self.call('POST', '/api/ai/assets',
                                    headers={'Content-Length': str(64 * 1024 * 1024 + 1)})
        self.assertEqual(status, 413, body)

    def test_app_close_stops_lazily_started_bridge(self):
        status, _, data = self.call('GET', '/api/ai/status')
        self.assertEqual(status, 200)
        port = data['bridge']['port']
        self.app.close()
        with self.assertRaises((ConnectionError, OSError, TimeoutError)):
            request(port, 'GET', '/health')
