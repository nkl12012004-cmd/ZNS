import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from openmap_server.app import create_server
from openmap_server.local_runtime import save_config, validate_public_config, write_ready
from openmap_server.net import PublicError
from test_openmap import FakeSupabase


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp.name) / 'cấu hình/config.env'
        self.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeSupabase)
        self.fake_thread = threading.Thread(target=self.fake.serve_forever, daemon=True); self.fake_thread.start()
        self.config = {'OPENMAP_LOCAL_TOKEN':'local-test-token', 'OPENMAP_INSTANCE_ID':'test-instance', 'OPENMAP_CONFIG_FILE':str(self.config_file), 'PUBLIC_BASE_URL':'http://127.0.0.1:8877'}
        self.server, self.app = create_server(self.config, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_port

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.app.close(); self.thread.join()
        self.fake.shutdown(); self.fake.server_close(); self.fake_thread.join(); self.temp.cleanup()

    def request(self, path, body=None, local='local-test-token', bearer=None):
        headers = {'Content-Type':'application/json'}
        if local is not None: headers['X-OpenMap-Local'] = local
        if bearer: headers['Authorization'] = 'Bearer ' + bearer
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response: return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            code, data = error.code, json.loads(error.read()); error.close(); return code, data

    def configure(self):
        return self.request('/api/runtime/config', {'supabase_url':'http://127.0.0.1:%d' % self.fake.server_port, 'public_key':'test-public-key'})

    def test_transport_nonce_required(self):
        self.assertEqual(self.request('/health', local=None)[0], 403)
        self.assertEqual(self.request('/health', local='wrong')[0], 403)
        status, data = self.request('/health')
        self.assertEqual(status, 200); self.assertEqual(data['instance'], 'test-instance')

    def test_nonce_is_not_a_login(self):
        self.assertEqual(self.request('/api/jobs', {'lat':10,'lon':106})[0], 401)
        self.configure()
        self.assertEqual(self.request('/api/me', bearer='fabricated-token')[0], 401)
        self.assertEqual(self.request('/api/me', bearer='user-one-token')[0], 200)

    def test_config_save_and_reload_auth(self):
        status, data = self.configure()
        self.assertEqual(status, 200); self.assertTrue(data['auth_configured'])
        self.assertTrue(self.config_file.is_file())
        saved = self.config_file.read_text()
        self.assertIn('SUPABASE_ANON_KEY=test-public-key', saved)
        self.assertNotIn('local-test-token', saved)
        self.assertEqual(self.request('/api/auth/login', {'email':'one@example.org','password':'test-password'})[0], 200)
        self.assertEqual(self.request('/api/runtime/config', local='wrong')[0], 403)

    def test_service_role_and_secret_keys_rejected(self):
        payload = base64.urlsafe_b64encode(json.dumps({'role':'service_role'}).encode()).decode().rstrip('=')
        for key in ('sb_secret_dont-use', 'header.' + payload + '.signature', 'public\nINJECTED=value'):
            status, _ = self.request('/api/runtime/config', {'supabase_url':'https://test.supabase.co','public_key':key})
            self.assertEqual(status, 400)
        self.assertFalse(self.config_file.exists())

    def test_publication_ready_file_atomic(self):
        path = Path(self.temp.name) / 'ready.json'
        write_ready(path, 43210, 'instance-one')
        data = json.loads(path.read_text())
        self.assertEqual(data['port'],43210); self.assertEqual(data['instance'],'instance-one')
        self.assertFalse(path.with_name('ready.json.tmp').exists())

    def test_local_config_not_available_in_external_mode(self):
        self.app.config.pop('OPENMAP_LOCAL_TOKEN')
        self.assertEqual(self.request('/api/runtime/config', local=None)[0], 403)

    def test_config_file_values_bounded(self):
        with self.assertRaises(PublicError): validate_public_config({'supabase_url':'http://remote.example','public_key':'public'})
        with self.assertRaises(PublicError): save_config(self.config_file, {'SUPABASE_ANON_KEY':'one\ntwo'})


if __name__ == '__main__': unittest.main()
