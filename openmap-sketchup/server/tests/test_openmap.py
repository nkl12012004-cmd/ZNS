import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
import threading
import struct
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from PIL import Image

from openmap_server.app import create_server
from openmap_server.auth import SupabaseAuth
from openmap_server.builder import build, export_obj, parameters, Raster, osm_data, parse_osm_xml
from openmap_server.geo import xy, triangulate, clip_polygon, bounds
from openmap_server.net import PublicError
from openmap_server.formats import export_glb, preview_mesh
from openmap_server import ocr
import subprocess


def tile_fixture(url, **_kwargs):
    stream = BytesIO()
    Image.new("RGB", (256, 256), (128, 100, 128) if "terrarium" in url else (40, 130, 70)).save(stream, "PNG")
    return stream.getvalue()


def sample_elements(b, *_args):
    x, y = (b["east"] + b["west"]) / 2, (b["north"] + b["south"]) / 2
    points = [(x - .0002, y - .0002), (x + .0002, y - .0002), (x + .0002, y + .0002), (x, y), (x - .0002, y + .0002), (x - .0002, y - .0002)]
    return [
        {"tags": {"building": "yes", "building:levels": "4"}, "geometry": [{"lon": lon, "lat": lat} for lon, lat in points]},
        {"tags": {"highway": "primary"}, "geometry": [{"lon": b["west"] - .001, "lat": y}, {"lon": b["east"] + .001, "lat": y}]},
    ]


class GeometryTests(unittest.TestCase):
    def params(self, **values):
        return parameters({"lat": 10.77, "lon": 106.7, "width": 500, "height": 500, "imagery": "none", "roads": False, "buildings": False, **values})

    def test_wgs84_projection_in_metres(self):
        anchor = {"lat": 0, "lon": 0, "elevation": 0}
        self.assertEqual(xy(0, 0, anchor), (0, 0))
        self.assertAlmostEqual(xy(0, .001, anchor)[0], 111.31949, places=4)
        self.assertAlmostEqual(xy(.001, 0, anchor)[1], 110.57427, places=4)

    def test_reject_invalid_parameters(self):
        for values in ({"lat": math.nan}, {"width": True}, {"height": -1}, {"grid": 4.5}, {"image_size": 999}, {"terrain": "false"}, {"anchor": {"lat": 0, "lon": 0, "elevation": 0}}):
            with self.subTest(values=values), self.assertRaises(PublicError):
                self.params(**values)

    def test_concave_roof_and_clip(self):
        points = [(0, 0), (4, 0), (4, 4), (2, 2), (0, 4)]
        tris = triangulate(points)
        area = sum(abs((points[t[1]][0] - points[t[0]][0]) * (points[t[2]][1] - points[t[0]][1]) - (points[t[1]][1] - points[t[0]][1]) * (points[t[2]][0] - points[t[0]][0])) / 2 for t in tris)
        self.assertEqual(area, 12)
        clipped = clip_polygon(points, {"west": 1, "east": 3, "south": 1, "north": 3})
        self.assertTrue(all(1 <= p[0] <= 3 and 1 <= p[1] <= 3 for p in clipped))

    def test_flat_mesh_normals_dimensions_and_uv(self):
        result = build(self.params())
        ground = result["meshes"][0]
        self.assertEqual(len(ground["triangles"]), 32)
        self.assertTrue(all(v[2] == 0 for v in ground["vertices"]))
        self.assertAlmostEqual(max(v[0] for v in ground["vertices"]) - min(v[0] for v in ground["vertices"]), 500, delta=.02)
        for tri in ground["triangles"]:
            a, b, c = [ground["vertices"][i] for i in tri]
            self.assertGreater((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]), 0)
        self.assertAlmostEqual(ground["uv"][0][1], 0)
        self.assertAlmostEqual(ground["uv"][-1][1], 1)

    def test_terrain_texture_roads_buildings_and_obj(self):
        result = build(self.params(terrain=True, grid=8, imagery="satellite", roads=True, buildings=True), getter=tile_fixture, osm_getter=sample_elements)
        self.assertAlmostEqual(result["anchor"]["elevation"], 100.5)
        self.assertEqual({m["name"] for m in result["meshes"]}, {"Ground", "Roads_main", "Buildings_lowrise", "Building_roofs"})
        buildings = next(m for m in result["meshes"] if m["name"] == "Buildings_lowrise")
        self.assertEqual(max(v[2] for v in buildings["vertices"]), 12)
        edges = {}
        for triangle in buildings["triangles"]:
            for a, b in zip(triangle, triangle[1:] + triangle[:1]):
                edge = tuple(sorted((a, b)))
                edges[edge] = edges.get(edge, 0) + 1
        self.assertTrue(all(n == 2 for n in edges.values()), "building must be a closed triangulated solid")
        with zipfile.ZipFile(BytesIO(export_obj(result))) as archive:
            self.assertIn("texture_0.png", archive.namelist())
            obj = archive.read("model.obj").decode()
            self.assertEqual(sum(line.startswith("f ") for line in obj.splitlines()), result["triangles"])
            vertices = sum(line.startswith("v ") for line in obj.splitlines())
            for line in obj.splitlines():
                if line.startswith("f "):
                    self.assertTrue(all(1 <= int(token.split('/')[0]) <= vertices for token in line.split()[1:]))
            self.assertTrue(json.loads(archive.read("metadata.json"))["attribution"])

    def test_glb_embedded_images_and_preview(self):
        result = build(self.params(imagery='satellite', image_size=1024), getter=tile_fixture)
        data = export_glb(result)
        magic, version, length = struct.unpack_from('<4sII', data)
        self.assertEqual((magic, version, length), (b'glTF', 2, len(data)))
        text_length, kind = struct.unpack_from('<I4s', data, 12)
        self.assertEqual(kind, b'JSON')
        document = json.loads(data[20:20 + text_length])
        self.assertTrue(document['images'])
        binary_length, kind = struct.unpack_from('<I4s', data, 20 + text_length)
        self.assertEqual(kind, b'BIN\x00')
        for view in document['bufferViews']:
            self.assertLessEqual(view.get('byteOffset', 0) + view['byteLength'], binary_length)
        uv_accessor = document['accessors'][document['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0']]
        uv_view = document['bufferViews'][uv_accessor['bufferView']]
        uv = struct.unpack_from('<2f', data, 28 + text_length + uv_view.get('byteOffset', 0))
        self.assertEqual(uv, (0.0, 1.0), 'glTF UV origin is top-left')
        preview = preview_mesh(result)
        self.assertIn('texture_jpeg', preview['materials'][0])
        self.assertIn('texture_png', result['materials'][0], 'preview must not mutate original')

    def test_flat_base_hill_patch_has_zero_boundary(self):
        p = self.params(terrain=True, grid=8, anchor={'lat':10.77,'lon':106.7,'elevation':0,'terrain_mode':'flat'})
        b = p['bbox']
        class Dem:
            def sample(self, lat, lon):
                return 100 + 10 * math.sin((lat-b['south'])/(b['north']-b['south'])*math.pi) * math.sin((lon-b['west'])/(b['east']-b['west'])*math.pi)
        with patch('openmap_server.builder.Raster', return_value=Dem()): result = build(p)
        self.assertTrue(result['hill_patch'])
        ground = result['meshes'][0]
        self.assertEqual(ground['name'], 'Terrain_hill_patch')
        self.assertGreater(max(v[2] for v in ground['vertices']), 9.9)
        for row in range(9):
            for col in range(9):
                if row in (0,8) or col in (0,8): self.assertAlmostEqual(ground['vertices'][row*9+col][2], 0)

    def test_water_trees_roof_and_building_options(self):
        def elements(b, *_):
            existing = sample_elements(b)
            existing[0]['tags']['building:levels'] = '8'
            existing.append({'tags':{'natural':'water'},'geometry':existing[0]['geometry']})
            existing.append({'type':'node','lat':10.77,'lon':106.7,'tags':{'natural':'tree','height':'9'}})
            return existing
        result = build(self.params(roads=True, roads_main=False, buildings=True, water=True, trees=True, building_style='textured', roof_style='parapet_concrete'), osm_getter=elements)
        names = {m['name'] for m in result['meshes']}
        self.assertNotIn('Roads_main', names)
        self.assertTrue({'Buildings_highrise','Water','Tree_trunks','Tree_crowns','Roof_parapets'}.issubset(names))
        self.assertIn('texture_png', result['materials'][4])

    def test_ocr_dependency_required(self):
        with patch('openmap_server.ocr.binary', return_value=None), self.assertRaises(PublicError) as error:
            ocr.recognize({'image':base64.b64encode(tile_fixture('image')).decode()})
        self.assertEqual(error.exception.status, 503)

    def test_ocr_uses_fixed_argv_and_returns_text(self):
        with patch('openmap_server.ocr.binary', return_value='/test/tesseract'), patch('openmap_server.ocr.subprocess.run', return_value=subprocess.CompletedProcess([],0,stdout=b'10.77, 106.7',stderr=b'')) as run:
            result = ocr.recognize({'image':base64.b64encode(tile_fixture('image')).decode()})
            self.assertEqual(result['text'], '10.77, 106.7')
            self.assertEqual(run.call_args.args[0], ['/test/tesseract','stdin','stdout','-l','eng','--psm','6'])
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_same_anchor_shared_seam(self):
        first = build(self.params(terrain=True, grid=4), getter=tile_fixture)
        anchor = first["anchor"]
        second_params = self.params(lon=106.7 + (first["bbox"]["east"] - first["bbox"]["west"]), terrain=True, grid=4, anchor=anchor)
        second = build(second_params, getter=tile_fixture)
        a = first["meshes"][0]["vertices"]
        b = second["meshes"][0]["vertices"]
        for row in range(5):
            self.assertEqual(a[row * 5 + 4], b[row * 5])

    def test_cancel_and_bad_tile(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(PublicError):
            build(self.params(), cancel=cancel)
        with self.assertRaises(PublicError):
            Raster(self.params()["bbox"], 12, "https://example.org/{z}/{x}/{y}", lambda *_a, **_k: b"invalid")

    def test_osm_xml_fallback_and_reject_entity_documents(self):
        raw = b'<osm><node id="1" lat="10" lon="106"/><node id="2" lat="10.001" lon="106"/><node id="3" lat="10" lon="106.001"/><way id="4"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="building" v="yes"/></way></osm>'
        elements = parse_osm_xml(raw, False, True)
        self.assertEqual(len(elements), 1)
        self.assertEqual(len(elements[0]['geometry']), 4)
        self.assertEqual(parse_osm_xml(raw, True, False), [])
        with patch('openmap_server.builder.fetch_json', side_effect=PublicError('provider offline', 502)), patch('openmap_server.builder.fetch', return_value=raw) as fallback:
            self.assertEqual(osm_data(self.params()['bbox'], False, True, 'https://example.org/interpreter'), elements)
            self.assertTrue(fallback.call_args.args[0].startswith('https://api.openstreetmap.org/'))
        with self.assertRaises(PublicError):
            parse_osm_xml(b'<!DOCTYPE osm [<!ENTITY x "bad">]><osm/>', True, True)


class FakeSupabase(BaseHTTPRequestHandler):
    seen_verifier = None

    def log_message(self, *_):
        pass

    def respond(self, status, result):
        data = json.dumps(result).encode()
        self.send_response(status); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        token = self.headers.get("Authorization", "")
        if self.path == "/auth/v1/user" and token in ("Bearer user-one-token", "Bearer user-two-token"):
            who = "one" if "one" in token else "two"
            return self.respond(200, {"id": who, "email": who + "@example.org"})
        self.respond(401, {"error": "invalid token"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        good = (self.path.endswith("grant_type=password") and body == {"email": "one@example.org", "password": "test-password"})
        good = good or (self.path.endswith("grant_type=refresh_token") and body.get("refresh_token") == "refresh-one")
        if self.path.endswith("grant_type=pkce"):
            FakeSupabase.seen_verifier = body.get("code_verifier")
            good = body.get("auth_code") == "valid-code" and len(body.get("code_verifier", "")) >= 43
        if good:
            return self.respond(200, {"access_token": "user-one-token", "refresh_token": "refresh-one", "expires_in": 3600, "user": {"id": "one", "email": "one@example.org"}})
        if self.path.endswith("/logout"):
            return self.respond(200, {})
        self.respond(400, {"error": "invalid credentials"})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeSupabase)
        cls.fake_thread = threading.Thread(target=cls.fake.serve_forever, daemon=True); cls.fake_thread.start()
        cls.server, cls.app = create_server({"SUPABASE_URL": "http://127.0.0.1:%d" % cls.fake.server_port, "SUPABASE_ANON_KEY": "test-public-key"}, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.app.close()
        cls.fake.shutdown(); cls.fake.server_close()
        cls.thread.join(); cls.fake_thread.join()

    def request(self, path, body=None, token=None, headers=None, method=None):
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {}), **(headers or {})}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as result:
                return result.status, result.read()
        except urllib.error.HTTPError as error:
            result = error.read(); error.close(); return error.code, result

    def test_no_anonymous_or_forged_access(self):
        self.assertEqual(self.request('/api/me')[0], 401)
        self.assertEqual(self.request('/api/me', token='forged-token')[0], 401)
        self.assertEqual(self.request('/api/auth/login', {'email': 'one@example.org', 'password': 'wrong'})[0], 401)
        self.assertEqual(self.request('/api/ocr', {'image':'invalid'})[0], 401)

    def test_real_login_refresh_and_job_owner(self):
        status, raw = self.request('/api/auth/login', {'email': 'one@example.org', 'password': 'test-password'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['access_token'], 'user-one-token')
        self.assertEqual(self.request('/api/auth/refresh', {'refresh_token': 'refresh-one'})[0], 200)
        status, raw = self.request('/api/jobs', {'lat': 10, 'lon': 106, 'imagery': 'none', 'roads': False, 'buildings': False}, token='user-one-token')
        self.assertEqual(status, 200); job_id = json.loads(raw)['id']
        self.assertEqual(self.request('/api/jobs/' + job_id, token='user-two-token')[0], 404)
        for _ in range(100):
            state = json.loads(self.request('/api/jobs/' + job_id, token='user-one-token')[1])
            if state['state'] == 'complete': break
            time.sleep(.01)
        self.assertEqual(state['state'], 'complete')
        status, data = self.request('/api/jobs/' + job_id + '/mesh', token='user-one-token')
        self.assertEqual(status, 200); self.assertEqual(json.loads(data)['schema'], 'openmap.mesh.v1')
        status, data = self.request('/api/jobs/' + job_id + '/export', token='user-one-token')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(BytesIO(data)) as archive: self.assertIsNone(archive.testzip())
        status, data = self.request('/api/jobs/' + job_id + '/glb', token='user-one-token')
        self.assertEqual(status, 200); self.assertEqual(data[:4], b'glTF')
        status, data = self.request('/api/jobs/' + job_id + '/preview', token='user-one-token')
        self.assertEqual(status, 200); self.assertEqual(json.loads(data)['schema'], 'openmap.mesh.v1')
        for suffix in ('mesh','export','glb','preview'):
            self.assertEqual(self.request('/api/jobs/' + job_id + '/' + suffix, token='user-two-token')[0], 404)

    def test_google_pkce_secret_and_single_delivery(self):
        status, data = self.request('/api/auth/google/start', {})
        self.assertEqual(status, 200); flow = json.loads(data)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(flow['authorize_url']).query)
        self.assertEqual(query['code_challenge_method'], ['s256'])
        self.assertNotIn('refresh_token', flow['authorize_url'])
        path = '/api/auth/google/status?flow_id=' + flow['flow_id']
        self.assertEqual(self.request(path, headers={'X-Flow-Secret': 'wrong'})[0], 404)
        self.assertEqual(json.loads(self.request(path, headers={'X-Flow-Secret': flow['poll_secret']})[1])['state'], 'pending')
        status, _ = self.request('/auth/callback?flow=' + flow['flow_id'] + '&code=valid-code')
        self.assertEqual(status, 200)
        status, result = self.request(path, headers={'X-Flow-Secret': flow['poll_secret']})
        self.assertEqual(status, 200); self.assertEqual(json.loads(result)['session']['access_token'], 'user-one-token')
        self.assertEqual(self.request(path, headers={'X-Flow-Secret': flow['poll_secret']})[0], 404)
        self.assertIsNotNone(FakeSupabase.seen_verifier)

    def test_browser_origin_rejected(self):
        self.assertEqual(self.request('/api/me', token='user-one-token', headers={'Origin': 'https://unrelated.example'})[0], 403)

    def test_no_supabase_configuration_is_closed(self):
        auth = SupabaseAuth('', '', 'http://127.0.0.1:8877')
        with self.assertRaises(PublicError) as context:
            auth.login({'email': 'one@example.org', 'password': 'test-password'})
        self.assertEqual(context.exception.status, 503)
        with self.assertRaises(ValueError): SupabaseAuth('http://remote.example', 'public', 'http://127.0.0.1:8877')


if __name__ == '__main__':
    unittest.main()
