from io import BytesIO
import json
import threading
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from openmap_server import builder
from openmap_server.geo import bounds
from openmap_server.net import PublicError


XML = b'<osm><node id="1" lat="10.77" lon="106.7"/><node id="2" lat="10.771" lon="106.7"/><node id="3" lat="10.77" lon="106.701"/><way id="4"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="building" v="yes"/></way></osm>'


class OsmProviderTests(unittest.TestCase):
    def setUp(self):
        self.bbox = bounds(10.77, 106.7, 350, 350)

    def read(self, endpoint=builder.DEFAULT_OVERPASS, **kwargs):
        return builder.osm_data(self.bbox, True, True, endpoint, **kwargs)

    def test_small_area_uses_map_xml_before_busy_overpass(self):
        with patch.object(builder, 'fetch', return_value=XML) as xml, patch.object(builder, 'fetch_json') as overpass:
            self.assertEqual(len(self.read()), 1)
            self.assertTrue(xml.call_args.args[0].startswith('https://api.openstreetmap.org/api/0.6/map?'))
            self.assertLessEqual(xml.call_args.kwargs['timeout'],9)
            overpass.assert_not_called()

    def test_map_api_alternate_hostname(self):
        with patch.object(builder, 'fetch', side_effect=[PublicError('unavailable',502), XML]) as xml, patch.object(builder, 'fetch_json') as overpass:
            self.assertEqual(len(self.read()),1)
            self.assertTrue(xml.call_args_list[1].args[0].startswith('https://www.openstreetmap.org/api/0.6/map?'))
            overpass.assert_not_called()

    def test_custom_operator_endpoint_keeps_priority(self):
        with patch.object(builder, 'fetch') as xml, patch.object(builder, 'fetch_json', return_value={'elements':[]}) as overpass:
            self.assertEqual(self.read('https://operator.example/interpreter'),[])
            self.assertEqual(overpass.call_args.args[0],'https://operator.example/interpreter')
            self.assertEqual(overpass.call_args.kwargs['method'],'POST')
            xml.assert_not_called()

    def test_overpass_mirror_and_get_fallback(self):
        with patch.object(builder, 'fetch', side_effect=PublicError('unavailable',502)), patch.object(builder, 'fetch_json', side_effect=[PublicError('busy',502),{'elements':[{'type':'node','id':1}]}]) as overpass:
            self.assertEqual(self.read(),[{'type':'node','id':1}])
            call=overpass.call_args
            self.assertTrue(call.args[0].startswith(builder.OVERPASS_FALLBACKS[0]+'?data='))
            self.assertEqual(call.kwargs['method'],'GET')
            self.assertIsNone(call.kwargs['data'])

    def test_malformed_payload_is_not_mistaken_for_empty_data(self):
        with patch.object(builder, 'fetch', side_effect=PublicError('unavailable',502)), patch.object(builder, 'fetch_json', side_effect=[{}, {'elements':[]}]) as overpass:
            self.assertEqual(self.read(),[])
            self.assertEqual(overpass.call_count,2)

    def test_no_requested_layers_do_not_call_provider(self):
        with patch.object(builder, 'fetch') as xml, patch.object(builder, 'fetch_json') as overpass:
            self.assertEqual(builder.osm_data(self.bbox,False,False,builder.DEFAULT_OVERPASS),[])
            xml.assert_not_called(); overpass.assert_not_called()

    def test_cancellation_stops_fallbacks(self):
        cancel=threading.Event();cancel.set()
        with patch.object(builder, 'fetch') as xml, self.assertRaises(PublicError) as context:
            self.read(cancel=cancel)
        self.assertEqual(context.exception.status,400);xml.assert_not_called()

    def test_retry_budget_is_bounded(self):
        with patch.object(builder.time, 'monotonic', side_effect=[0,0,40]), patch.object(builder, 'fetch', side_effect=PublicError('unavailable',502)) as xml, patch.object(builder, 'fetch_json') as overpass:
            with self.assertRaises(PublicError) as context:self.read()
            self.assertEqual(context.exception.status,502)
            self.assertEqual(xml.call_count,1);overpass.assert_not_called()


class PartialMapTests(unittest.TestCase):
    def params(self, **kwargs):
        return builder.parameters({'lat':10.77,'lon':106.7,'width':100,'height':100,'grid':8,'imagery':'none','roads':True,'buildings':True,**kwargs})

    @staticmethod
    def tile(_url, **_kwargs):
        data=BytesIO();Image.new('RGB',(256,256),(128,100,128)).save(data,'PNG');return data.getvalue()

    def offline(self, *_args, **_kwargs):
        raise PublicError('OSM service unavailable',502)

    def test_osm_outage_preserves_imagery_and_terrain_with_missing_flags(self):
        result=builder.build(self.params(terrain=True,imagery='satellite',water=True,trees=True),getter=self.tile,osm_getter=self.offline)
        self.assertTrue(result['partial'])
        self.assertEqual(result['missing_layers'],['roads','buildings','water','trees'])
        self.assertEqual([mesh['name'] for mesh in result['meshes']],['Ground'])
        self.assertGreater(result['triangles'],0)
        self.assertIn('texture_png',result['materials'][0])
        self.assertTrue(result['warnings'])
        self.assertTrue(any('còn thiếu' in warning for warning in result['warnings']))
        self.assertNotIn(builder.ATTRIBUTIONS['osm'],result['attribution'])
        with zipfile.ZipFile(BytesIO(builder.export_obj(result))) as archive:
            metadata=json.loads(archive.read('metadata.json'))
        self.assertTrue(metadata['partial']);self.assertEqual(metadata['missing_layers'],result['missing_layers'])

    def test_valid_empty_osm_response_is_not_service_outage(self):
        result=builder.build(self.params(),osm_getter=lambda *_:[])
        self.assertFalse(result['partial']);self.assertEqual(result['missing_layers'],[])
        self.assertEqual(result['warnings'],[])

    def test_only_requested_layers_are_marked_missing(self):
        result=builder.build(self.params(roads=False,buildings=False,water=True),osm_getter=self.offline)
        self.assertTrue(result['partial']);self.assertEqual(result['missing_layers'],['water'])

    def test_cancel_and_data_limits_are_not_partial_success(self):
        def rejected(*_args):raise PublicError('selection too dense',400)
        with self.assertRaises(PublicError):builder.build(self.params(),osm_getter=rejected)

    def test_imagery_failure_is_not_misreported_as_osm_partial(self):
        with self.assertRaises(PublicError):builder.build(self.params(imagery='satellite'),getter=self.offline,osm_getter=lambda *_:[])


if __name__=='__main__':unittest.main()
