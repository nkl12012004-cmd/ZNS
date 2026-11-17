import json
import struct
import time
import unittest
from unittest.mock import patch

from openmap_server.app import Application
from openmap_server.net import PublicError


class PartialJobTests(unittest.TestCase):
    def setUp(self):
        self.app = Application({'OPENMAP_LOCAL_TOKEN':'test-private-worker'})
        self.headers = {'X-OpenMap-Local':'test-private-worker'}

    def tearDown(self):
        self.app.close()

    def build_job(self, result=None, failure=None):
        with patch('openmap_server.builder.osm_data', return_value=result, side_effect=failure):
            job = self.app.route('POST','/api/jobs',{},self.headers,{'lat':21.0285,'lon':105.8542,'width':20,'height':20,'grid':8,'imagery':'none','roads':True,'buildings':True,'water':True,'trees':True})
            path = '/api/jobs/' + job['id']
            for _ in range(200):
                status = self.app.route('GET',path,{},self.headers,{})
                if status['state'] in ('complete','error'): break
                time.sleep(.01)
            self.assertEqual(status['state'],'complete')
            return path,status

    def test_osm_failure_exposes_partial_status_and_glb_metadata(self):
        path,status = self.build_job(failure=PublicError('OSM unavailable',502))
        self.assertTrue(status['partial'])
        self.assertEqual(set(status['missing_layers']),{'roads','buildings','water','trees'})
        self.assertTrue(status['warnings'])
        self.assertIn('thiếu',status['message'])
        mesh = json.loads(self.app.route('GET',path+'/mesh',{},self.headers,{})[0])
        self.assertTrue(mesh['partial'])
        glb = self.app.route('GET',path+'/glb',{},self.headers,{})[0]
        length = struct.unpack_from('<I',glb,12)[0]
        metadata = json.loads(glb[20:20+length])['extras']
        self.assertTrue(metadata['partial'])
        self.assertEqual(metadata['missing_layers'],status['missing_layers'])

    def test_valid_empty_osm_is_complete_without_missing_layers(self):
        _,status = self.build_job(result=[])
        self.assertFalse(status['partial'])
        self.assertEqual(status['missing_layers'],[])


if __name__ == '__main__': unittest.main()
