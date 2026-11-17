"""Private original-kernel integration tests; no public/vendor network calls."""
import base64
import http.client
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from openmap_server.net import PublicError
from openmap_server.app import create_server
from openmap_server.original_engine import OriginalEngine


class OriginalAvailabilityTests(unittest.TestCase):
    def test_wrong_python_is_explicitly_unavailable(self):
        if sys.version_info[:2] == (3,14):
            self.skipTest('This check is for the unsupported interpreter path')
        with tempfile.TemporaryDirectory() as folder:
            status=OriginalEngine({'OPENMAP_WORK_DIR':folder}).availability()
        self.assertFalse(status['available'])
        self.assertIn('3.14',status['reason'])


@unittest.skipUnless(sys.version_info[:2] == (3,14) and importlib.util.find_spec('numpy') is not None,
                     'The unchanged recovered kernel requires CPython3.14 and NumPy')
class OriginalEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine=OriginalEngine({'OPENMAP_WORK_DIR':self.temp.name,'OPENMAP_ORIGINAL_FIXTURE':{}})
        self.params={'lat':21.028511,'lon':105.854444,'width':200,'height':200,'grid':16,
                     'image_size':1024,'imagery':'satellite','terrain':True,
                     'roads':True,'buildings':True,'water':True,'trees':True,
                     'building_style':'textured','roof_style':'parapet_vietnam',
                     'project_name':'Original_Test'}

    def build_offline(self, **overrides):
        params={**self.params,**overrides}
        with patch('socket.getaddrinfo',side_effect=AssertionError('Unexpected DNS')) as dns, \
             patch('socket.socket.connect',side_effect=AssertionError('Unexpected network')) as connection:
            result=self.engine.build(params,job_id='a'*32)
        dns.assert_not_called();connection.assert_not_called()
        return result

    def test_full_original_builder_and_original_exports_preserve_arrays_and_textures(self):
        import numpy as np
        result=self.build_offline()
        raw,mesh=result['raw_scene'],result['mesh']
        self.assertTrue(mesh['original_geometry_preserved'])
        self.assertEqual(mesh['engine'],'original')
        self.assertTrue(mesh['original_fixture'])
        self.assertGreater(mesh['triangles'],0)
        sources=[part for layer in raw['layers'] for part in layer['meshes']]
        self.assertEqual(len(sources),len(mesh['meshes']))
        for source,adapted in zip(sources,mesh['meshes']):
            self.assertTrue(np.array_equal(source['verts'],np.asarray(adapted['vertices'])))
            self.assertTrue(np.array_equal(source['faces'],np.asarray(adapted['triangles'])))
            if source.get('uvs') is not None:
                self.assertTrue(np.array_equal(source['uvs'],np.asarray(adapted['uv'])))
        for source,adapted in zip(raw['materials'],mesh['materials']):
            if source.get('texture_bytes'):
                self.assertEqual(bytes(source['texture_bytes']),base64.b64decode(adapted.get('texture_jpeg') or adapted['texture_png']))
        self.assertFalse(result['native_skp_ready']);self.assertIsNone(result['skp_path'])
        self.assertTrue(Path(result['fallbackpath']).is_file())
        with zipfile.ZipFile(BytesIO(result['obj_zip'])) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('Y-Up',archive.read('Original_Test.obj').decode())
            self.assertIn('Original_Test.mtl',archive.namelist())
            self.assertTrue(any(name.endswith('.jpg') for name in archive.namelist()))
            manifest=json.loads(archive.read('Original_Test_original_manifest.json'))
        self.assertTrue(manifest['fully_editable_original_source'])
        self.assertEqual(struct.unpack_from('<4sI',result['glb']),(b'glTF',2))

    def test_unchanged_raw_scene_writers_match_bundle_bytes(self):
        result=self.build_offline()
        writer=self.engine._load()[3]
        comparison=Path(self.temp.name)/'comparison';comparison.mkdir()
        writer.write_obj_bundle(result['raw_scene'],comparison/'Original_Test.obj')
        writer.write_glb_binary(result['raw_scene'],comparison/'Original_Test.glb')
        with zipfile.ZipFile(BytesIO(result['obj_zip'])) as archive:
            self.assertEqual(archive.read('Original_Test.obj'),(comparison/'Original_Test.obj').read_bytes())
            self.assertEqual(archive.read('Original_Test.mtl'),(comparison/'Original_Test.mtl').read_bytes())
        self.assertEqual(Path(result['original_glb_path']).read_bytes(),(comparison/'Original_Test.glb').read_bytes())
        self.assertEqual(result['glb'],(Path(result['exportdir'])/'Original_Test.glb').read_bytes())

    def test_anchor_offset_is_retained_without_translating_vertices(self):
        import numpy as np
        result=self.build_offline(anchor={'lat':21.027,'lon':105.853,'elevation':0,'terrain_mode':'flat'})
        mesh=result['mesh']
        self.assertTrue(mesh['hill_patch'])
        self.assertEqual(mesh['anchor']['lat'],21.027)
        self.assertEqual(mesh['anchor']['lon'],105.853)
        offset=mesh['original_origin']['offset_from_anchor_m']
        self.assertGreater(abs(offset[0])+abs(offset[1]),1)
        self.assertTrue(np.array_equal(result['raw_scene']['layers'][0]['meshes'][0]['verts'],np.asarray(mesh['meshes'][0]['vertices'])))

    def test_public_payload_cannot_enable_fixture_or_forge_projection(self):
        engine=OriginalEngine({'OPENMAP_WORK_DIR':self.temp.name})
        mapped=engine.original_parameters({**self.params,'offline_synthetic':True,'__verified_projection__':{'fake':True},'mock_osm_data':{'elements':[]}})
        self.assertNotIn('offline_synthetic',mapped)
        self.assertNotIn('__verified_projection__',mapped)
        self.assertNotIn('mock_osm_data',mapped)
        self.assertEqual(mapped['sat_provider'],'esri_sat')
        self.assertEqual(mapped['building_style'],'textured')

    def test_original_geo_bbox_and_layer_switches(self):
        mapped=self.engine.original_parameters({**self.params,'roads':False,'building_style':'white','anchor':{'lat':21,'lon':105,'elevation':12,'terrain_mode':'flat'}})
        geo=self.engine._load()[0]
        actual=geo.bbox_from_center_meters(self.params['lat'],self.params['lon'],200,200)
        self.assertEqual(tuple(mapped[key] for key in ('south','west','north','east')),actual)
        self.assertFalse(mapped['include_roads']);self.assertFalse(mapped['include_roads_main']);self.assertFalse(mapped['include_roads_alley'])
        self.assertEqual(mapped['building_style'],'white_box')
        self.assertEqual(mapped['anchor']['elevation_m'],12)
        self.assertTrue(mapped['hill_patch'])

    def test_production_image_none_and_oversized_region_are_explicit_errors(self):
        engine=OriginalEngine({'OPENMAP_WORK_DIR':self.temp.name})
        with self.assertRaises(PublicError):engine.original_parameters({**self.params,'imagery':'none'})
        with self.assertRaises(PublicError):engine.original_parameters({**self.params,'width':5000})

    def test_cancel_before_and_during_original_build(self):
        stopped=threading.Event();stopped.set()
        with self.assertRaises(PublicError):self.engine.build(self.params,cancel=stopped,job_id='b'*32)
        stopped.clear()
        def progress(_percent,_message):stopped.set()
        with self.assertRaises(PublicError):self.engine.build(self.params,progress=progress,cancel=stopped,job_id='c'*32)
        self.assertFalse(any(Path(self.temp.name).rglob('*.obj')))

    def test_job_directory_cannot_escape_work_root(self):
        with self.assertRaises(PublicError):self.engine.build(self.params,job_id='../not-a-job')


def original_osm_fixture():
    """Small deterministic public-format input, with each original layer present."""
    lat,lon=21.028511,105.854444
    elements=[]
    def way(identifier,points,tags):
        ids=[]
        for index,(north,east) in enumerate(points):
            node=identifier*10+index
            ids.append(node)
            elements.append({'type':'node','id':node,'lat':lat+north,'lon':lon+east})
        if points[0]==points[-1]:ids[-1]=ids[0]
        elements.append({'type':'way','id':identifier,'nodes':ids,'tags':tags})
    way(10,[(-.0003,-.0005),(-.0003,-.0002),(.0001,-.0002),(.0001,-.0005),(-.0003,-.0005)],
        {'building':'apartments','building:levels':'8'})
    way(20,[(.0002,-.0005),(.0002,-.0002),(.0004,-.0002),(.0004,-.0005),(.0002,-.0005)],
        {'building':'residential','building:levels':'3'})
    way(30,[(0,-.0015),(0,.0015)],{'highway':'primary'})
    way(40,[(-.0007,.0002),(.0007,.0002)],{'highway':'residential'})
    way(50,[(.0003,.0004),(.0003,.0007),(.0006,.0007),(.0006,.0004),(.0003,.0004)],
        {'natural':'water'})
    elements.append({'type':'node','id':900,'lat':lat-.0004,'lon':lon+.0005,'tags':{'natural':'tree'}})
    return {'elements':elements,'all_subtiles_ok':True}


@unittest.skipUnless(sys.version_info[:2] == (3,14) and importlib.util.find_spec('numpy') is not None,
                     'The recovered source kernel requires CPython3.14 and NumPy')
class OriginalApplicationTests(unittest.TestCase):
    """Real HTTP jobs exercise only the bundled readable kernel and its writers."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config={'OPENMAP_ENGINE':'original','OPENMAP_LOCAL_TOKEN':'original-http-test',
                     'OPENMAP_WORK_DIR':self.temp.name,
                     'OPENMAP_ORIGINAL_FIXTURE':{'mock_osm_data':original_osm_fixture()}}
        self.server,self.app=create_server(self.config,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.params={'lat':21.028511,'lon':105.854444,'width':200,'height':200,'grid':16,
                     'image_size':1024,'imagery':'satellite','terrain':True,'roads':True,
                     'buildings':True,'water':True,'trees':True,'building_style':'textured',
                     'roof_style':'parapet_vietnam','project_name':'HTTP_Original'}
        self.network=patch('requests.sessions.Session.send',side_effect=AssertionError('Unexpected provider request')).start()
        self.authentication=patch.object(self.app.auth,'user',side_effect=AssertionError('Local mode called Supabase')).start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.thread.join()
        patch.stopall()
        self.temp.cleanup()

    def request(self,path,body=None,*,method=None,token='original-http-test',headers=None):
        request_headers={'Content-Type':'application/json'}
        if token is not None:request_headers['X-OpenMap-Local']=token
        request_headers.update(headers or {})
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            connection.request(method or ('POST' if body is not None else 'GET'),path,
                               None if body is None else json.dumps(body).encode(),request_headers)
            response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()

    def json_request(self,*args,**kwargs):
        status,headers,payload=self.request(*args,**kwargs)
        return status,json.loads(payload)

    def complete(self,**overrides):
        status,created=self.json_request('/api/jobs',{**self.params,**overrides})
        self.assertEqual(status,200,created)
        self.assertRegex(created['id'],r'^[a-f0-9]{32}$')
        self.assertEqual(created['state'],'queued')
        path='/api/jobs/'+created['id']
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            status,state=self.json_request(path)
            self.assertEqual(status,200,state)
            if state['state'] not in ('queued','running'):break
            time.sleep(.01)
        self.assertEqual(state['state'],'complete',state)
        self.assertEqual(state['progress'],100)
        return path,state

    def test_readable_source_and_private_local_transport_without_login(self):
        for token in (None,'wrong'):
            self.assertEqual(self.json_request('/health',token=token)[0],403)
            self.assertEqual(self.json_request('/api/jobs',self.params,token=token)[0],403)
        status,health=self.json_request('/health')
        self.assertEqual(status,200);self.assertEqual(health['engine'],'original')
        self.assertEqual(health['auth_mode'],'local');self.assertFalse(health['auth_configured'])
        self.assertTrue(health['engine_status']['available'])
        self.assertTrue(health['engine_status']['fully_editable_source'])
        status,user=self.json_request('/api/me')
        self.assertEqual(status,200);self.assertEqual(user['id'],'local-device')
        self.assertEqual(self.json_request('/api/auth/login',{'email':'unused@example.org','password':'unused'})[0],400)
        self.assertEqual(self.json_request('/api/me',headers={'Origin':'https://unrelated.example'})[0],403)
        for module in self.app.original_engine._load():
            self.assertEqual(Path(module.__file__).resolve().parent,self.app.original_engine.kernel_dir)
            self.assertEqual(Path(module.__file__).suffix,'.py')
            source=Path(module.__file__).read_text(encoding='utf-8')
            self.assertNotIn('marshal.loads(',source)
            self.assertNotIn('exec(',source)
        self.network.assert_not_called();self.authentication.assert_not_called()

    def test_http_job_mesh_manifest_original_obj_glb_and_explicit_skp_unavailable(self):
        import numpy as np
        engine=self.app.original_engine
        _geo,_textures,builder,writer=engine._load()
        original_build=builder.build_mode1_context_scene
        scenes=[]
        def capture(*args,**kwargs):
            scene=original_build(*args,**kwargs)
            scenes.append(scene)
            return scene
        with patch.object(builder,'build_mode1_context_scene',side_effect=capture):
            path,state=self.complete()
        self.assertEqual(len(scenes),1)
        raw=scenes[0]
        self.assertFalse(state['partial']);self.assertFalse(state['source_degraded'])
        self.assertEqual(state['missing_layers'],[]);self.assertEqual(state['warnings'],[])
        status,mesh=self.json_request(path+'/mesh')
        self.assertEqual(status,200);self.assertEqual(mesh['schema'],'openmap.mesh.v1')
        self.assertEqual(mesh['engine'],'original');self.assertTrue(mesh['original_geometry_preserved'])
        self.assertTrue(mesh['original_fixture'])
        sources=[(layer,part) for layer in raw['layers'] for part in layer['meshes']]
        self.assertEqual(len(sources),len(mesh['meshes']))
        for (layer,source),adapted in zip(sources,mesh['meshes']):
            self.assertTrue(np.array_equal(source['verts'],np.asarray(adapted['vertices'])))
            self.assertTrue(np.array_equal(source['faces'],np.asarray(adapted['triangles'])))
            if source.get('uvs') is not None:
                self.assertTrue(np.array_equal(source['uvs'],np.asarray(adapted['uv'])))
            else:self.assertEqual(adapted['uv'],[])
            self.assertEqual(adapted['tag'],layer['tag'])
            self.assertEqual(adapted['tag_color'],layer['tag_color'])
            self.assertEqual(adapted['soften_cos'],layer['soften_cos'])
            self.assertEqual(adapted['material'],int(source['mat_idx']))
        for source,adapted in zip(raw['materials'],mesh['materials']):
            self.assertEqual(source['name'],adapted['name'])
            self.assertEqual(source['color'],adapted['original_rgba'])
            if source.get('texture_bytes'):
                encoded=adapted.get('texture_jpeg') or adapted['texture_png']
                self.assertEqual(bytes(source['texture_bytes']),base64.b64decode(encoded))
        tags={layer['tag'] for layer in mesh['original_layers']}
        for tag in ('MapSKP_01_Terrain','MapSKP_02A_Buildings_Highrise','MapSKP_02B_Buildings_Lowrise',
                    'MapSKP_03A_Roads_Main','MapSKP_03B_Roads_Alley','MapSKP_04_Water','MapSKP_05_Trees'):
            self.assertIn(tag,tags)
        status,manifest=self.json_request(path+'/manifest')
        self.assertEqual(status,200);self.assertEqual(manifest['engine'],'original')
        self.assertEqual(manifest['origin'],mesh['original_origin'])
        self.assertEqual(manifest['center'],mesh['center'])
        self.assertEqual(manifest['bbox'],mesh['bbox'])
        self.assertEqual(manifest['parameters'],mesh['parameters'])
        self.assertEqual(manifest['triangles'],mesh['triangles'])
        self.assertFalse(manifest['native_skp_ready']);self.assertFalse(manifest['source_degraded'])
        comparison=Path(self.temp.name)/'writer_comparison';comparison.mkdir()
        writer.write_obj_bundle(raw,comparison/'HTTP_Original.obj')
        writer.write_glb_binary(raw,comparison/'HTTP_Original.glb')
        status,headers,exported=self.request(path+'/export')
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/zip')
        with zipfile.ZipFile(BytesIO(exported)) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                if name.endswith('_original_manifest.json'):continue
                self.assertEqual(archive.read(name),(comparison/name).read_bytes(),name)
            saved_manifest=json.loads(archive.read('HTTP_Original_original_manifest.json'))
            self.assertTrue(saved_manifest['fully_editable_original_source'])
            self.assertTrue(saved_manifest['geometry_preserved'])
            self.assertTrue(saved_manifest['texture_bytes_preserved'])
        status,headers,glb=self.request(path+'/glb')
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'model/gltf-binary')
        bundle=self.app.jobs[path.rsplit('/',1)[-1]]['original_bundle']
        self.assertEqual(Path(bundle['original_glb_path']).read_bytes(),(comparison/'HTTP_Original.glb').read_bytes())
        self.assertEqual(glb,(Path(bundle['exportdir'])/'HTTP_Original.glb').read_bytes())
        status,error=self.json_request(path+'/skp')
        self.assertEqual(status,409);self.assertIn('SKP',error['error'])
        self.assertEqual(self.json_request(path+'/preview')[0],200)
        self.assertEqual(self.json_request('/api/jobs/'+'0'*32+'/mesh')[0],404)
        self.network.assert_not_called();self.authentication.assert_not_called()

    def test_original_anchor_vertical_scale_and_building_filters_survive_job_normalization(self):
        path,_state=self.complete(exaggeration=1,buildings_high=False,buildings_low=True,
                                 anchor={'lat':21.028,'lon':105.854,'elevation':9,
                                         'terrain_mode':'terrain_3d','z_exaggeration':2.5})
        status,manifest=self.json_request(path+'/manifest')
        self.assertEqual(status,200)
        self.assertEqual(manifest['parameters']['anchor']['z_exaggeration'],2.5)
        self.assertEqual(manifest['origin']['z_exaggeration'],2.5)
        self.assertEqual(manifest['origin']['buildings_highrise_count'],0)
        self.assertEqual(manifest['origin']['buildings_lowrise_count'],1)
        self.assertFalse(manifest['parameters']['buildings_high'])
        self.assertTrue(manifest['parameters']['buildings_low'])
        self.network.assert_not_called()

    def test_degraded_original_source_preserves_built_layers_without_marking_them_missing(self):
        osm=original_osm_fixture()
        osm.update(all_subtiles_ok=False,peak_hour_degraded=True,overpass_overloaded=True)
        self.config['OPENMAP_ORIGINAL_FIXTURE']={'mock_osm_data':osm}
        path,state=self.complete()
        status,mesh=self.json_request(path+'/mesh')
        self.assertEqual(status,200)
        status,manifest=self.json_request(path+'/manifest')
        self.assertEqual(status,200)
        for result in (state,mesh,manifest):
            self.assertTrue(result['source_degraded'])
            self.assertFalse(result['partial'])
            self.assertEqual(result['missing_layers'],[])
            self.assertTrue(result['warnings'])
        self.assertEqual(manifest['origin']['buildings_count'],2)
        self.assertGreater(manifest['origin']['roads_count'],0)
        self.assertTrue(mesh['original_geometry_preserved'])
        self.network.assert_not_called()

    def test_original_limits_and_bad_inputs_are_rejected_before_queuing(self):
        for override in ({'width':20},{'height':4500},{'buildings_high':'false'},
                         {'anchor':{'lat':21,'lon':105,'elevation':0,'z_exaggeration':float('inf')}}):
            with self.subTest(override=override):
                status,error=self.json_request('/api/jobs',{**self.params,**override})
                self.assertEqual(status,400,error)
        self.assertEqual(self.app.jobs,{})
        self.assertEqual(self.json_request('/api/does-not-exist')[0],404)
        self.network.assert_not_called()

    def test_pending_and_cancelled_original_jobs_do_not_expose_exports(self):
        builder=self.app.original_engine._load()[2]
        original_build=builder.build_mode1_context_scene
        entered,released,finished=threading.Event(),threading.Event(),threading.Event()
        def pause(*args,**kwargs):
            entered.set()
            try:
                if not released.wait(5):raise AssertionError('Test did not release original build')
                return original_build(*args,**kwargs)
            finally:finished.set()
        with patch.object(builder,'build_mode1_context_scene',side_effect=pause):
            try:
                status,created=self.json_request('/api/jobs',self.params)
                self.assertEqual(status,200)
                self.assertTrue(entered.wait(5))
                path='/api/jobs/'+created['id']
                status,state=self.json_request(path)
                self.assertEqual(status,200);self.assertEqual(state['state'],'running')
                for suffix in ('mesh','manifest','export','glb','skp','preview'):
                    self.assertEqual(self.json_request(path+'/'+suffix)[0],409,suffix)
                status,cancelled=self.json_request(path,method='DELETE')
                self.assertEqual(status,200);self.assertTrue(cancelled['ok'])
            finally:released.set()
            self.assertTrue(finished.wait(5))
        status,state=self.json_request(path)
        self.assertEqual(status,200);self.assertEqual(state['state'],'cancelled')
        for suffix in ('mesh','manifest','export','glb','skp','preview'):
            self.assertEqual(self.json_request(path+'/'+suffix)[0],409,suffix)
        self.assertFalse(any(Path(self.temp.name).rglob('*.obj')))
        self.network.assert_not_called()


if __name__=='__main__':unittest.main()
