import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests

from openmap_server.net import PublicError
from openmap_server import tree_data


class Response:
    def __init__(self,document=None,*,body=None,status=200,headers=None,on_chunk=None):
        self.body=json.dumps(document if document is not None else {"elements":[]}).encode() if body is None else body
        self.status_code=status
        self.headers=headers or {}
        self.closed=False
        self.on_chunk=on_chunk

    def iter_content(self,chunk_size):
        for start in range(0,len(self.body),chunk_size):
            if self.on_chunk:self.on_chunk()
            yield self.body[start:start+chunk_size]

    def close(self):self.closed=True


class TreeDataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bbox={"south":21.,"west":105.,"north":21.01,"east":105.01}

    def fetch(self,**kwargs):
        return tree_data.fetch_tree_features(self.bbox,self.temp.name,**kwargs)

    def files(self):return list(Path(self.temp.name).rglob("*.json"))

    def test_points_rings_and_tree_rows_preserve_latitude_longitude_order(self):
        ring=[{"lat":20.999,"lon":105.002},{"lat":21.004,"lon":105.002},
              {"lat":21.004,"lon":105.006}]
        document={"elements":[
            {"type":"node","id":1,"lat":21.002,"lon":105.003,"tags":{"natural":"tree","height":"12,5 m"}},
            {"type":"node","id":2,"lat":21.002,"lon":105.003,"tags":{"natural":"tree"}},
            {"type":"node","id":1,"lat":21.006,"lon":105.003,"tags":{"natural":"tree"}},
            {"type":"node","id":3,"lat":20.9,"lon":105.003,"tags":{"natural":"tree"}},
            {"type":"node","id":4,"lat":21.003,"lon":105.003,"tags":{"natural":"tree","height":"99m"}},
            {"type":"way","geometry":ring,"tags":{"natural":"wood"}},
            {"type":"way","geometry":ring,"tags":{"landuse":"forest"}},
            {"type":"way","geometry":ring,"tags":{"leisure":"park"}},
            {"type":"way","geometry":ring,"tags":{"leisure":"garden"}},
            {"type":"way","geometry":ring[:2],"tags":{"natural":"tree_row"}},
        ]}
        response=Response(document)
        with patch.object(tree_data.requests,"get",return_value=response) as request:
            result=self.fetch()
        self.assertTrue(response.closed)
        self.assertEqual(result["status"],"ok")
        self.assertEqual(result["points"],[{"lat":21.002,"lon":105.003,"height":12.5,"id":1},
                                           {"lat":21.003,"lon":105.003,"id":4}])
        self.assertEqual([area["kind"] for area in result["areas"]],["wood","forest","park","tree_row"])
        self.assertEqual(result["areas"][0]["coordinates"],[[20.999,105.002],[21.004,105.002],
                                                               [21.004,105.006],[20.999,105.002]])
        self.assertEqual(result["areas"][-1]["coordinates"],[[20.999,105.002],[21.004,105.002]])
        endpoint=request.call_args.args[0]
        options=request.call_args.kwargs
        self.assertEqual(endpoint,tree_data.OVERPASS_ENDPOINTS[0])
        self.assertTrue(options["stream"]);self.assertFalse(options["allow_redirects"])
        self.assertEqual(options["timeout"],(3,5))
        self.assertTrue(Path(options["verify"]).is_file())
        for selector in ('node["natural"="tree"]','way["natural"="tree_row"]','way["natural"="wood"]',
                         'way["landuse"="forest"]','way["leisure"="park"]','way["leisure"="garden"]'):
            self.assertIn(selector,options["params"]["data"])
        self.assertIn("out geom",options["params"]["data"])

    def test_success_and_valid_empty_are_cached_without_a_provider_request(self):
        for document in ({"elements":[]},{"elements":[{"type":"node","id":1,"lat":21.001,"lon":105.001,
                                                        "tags":{"natural":"tree"}}]}):
            with self.subTest(document=document):
                for path in self.files():path.unlink()
                with patch.object(tree_data.requests,"get",return_value=Response(document)):
                    first=self.fetch()
                self.assertIn(first["status"],("ok","empty"))
                self.assertEqual(len(self.files()),1)
                with patch.object(tree_data.requests,"get",side_effect=AssertionError("Cache miss")) as request:
                    second=self.fetch()
                self.assertEqual(second,{**first,"status":"cache"})
                request.assert_not_called()
                self.assertFalse(list(Path(self.temp.name).rglob("*.tmp")))

    def test_expired_corrupt_wrong_bbox_and_tampered_cache_are_misses(self):
        with patch.object(tree_data.requests,"get",return_value=Response()):self.fetch()
        path=self.files()[0]
        original=json.loads(path.read_text())
        variants=[b"not JSON",
                  json.dumps({**original,"fetched_at":time.time()-tree_data.CACHE_TTL_SECONDS-1}).encode(),
                  json.dumps({**original,"bbox":{**self.bbox,"east":106.}}).encode(),
                  json.dumps({**original,"points":[{"lat":90.,"lon":105.}]}).encode()]
        for payload in variants:
            with self.subTest(payload=payload):
                path.write_bytes(payload)
                with patch.object(tree_data.requests,"get",return_value=Response()) as request:
                    self.assertEqual(self.fetch()["status"],"empty")
                request.assert_called_once()

    def test_provider_failure_is_nonfatal_not_cached_and_retries_only_fixed_endpoints(self):
        failed=Response(status=503)
        with patch.object(tree_data.requests,"get",side_effect=[requests.Timeout("timeout"),failed]) as request:
            result=self.fetch()
        self.assertEqual(result["status"],"unavailable")
        self.assertEqual(result["points"],[]);self.assertEqual(result["areas"],[])
        self.assertEqual([call.args[0] for call in request.call_args_list],list(tree_data.OVERPASS_ENDPOINTS))
        self.assertTrue(failed.closed);self.assertEqual(self.files(),[])

    def test_malformed_json_error_documents_and_oversize_bodies_are_not_cached(self):
        invalid=[Response(body=b"<html>service unavailable</html>"),Response({"elements":[],"remark":"timeout"}),
                 Response({"elements":None}),Response(body=b"{}",headers={"Content-Length":str(tree_data.MAX_RESPONSE_BYTES+1)}),
                 Response(body=b"x"*(tree_data.MAX_RESPONSE_BYTES+1))]
        for response in invalid:
            with self.subTest(response=response):
                with patch.object(tree_data.requests,"get",side_effect=[response,requests.ConnectionError("offline")]):
                    result=self.fetch()
                self.assertEqual(result["status"],"unavailable")
                self.assertTrue(response.closed);self.assertEqual(self.files(),[])

    def test_invalid_features_are_dropped_without_distorting_oversize_rings(self):
        geometries=[[],[{"lat":True,"lon":105.}],
                    [{"lat":float("nan"),"lon":105.}]*3,
                    [{"lat":21.,"lon":105.},{"lat":21.01,"lon":125.},{"lat":21.02,"lon":105.}],
                    [{"lat":21.+index*1e-7,"lon":105.} for index in range(tree_data.MAX_RING_POINTS+1)],
                    [{"lat":22.,"lon":106.},{"lat":22.01,"lon":106.},{"lat":22.01,"lon":106.01}]]
        document={"elements":[{"type":"way","tags":{"natural":"wood"},"geometry":geometry}
                               for geometry in geometries]}
        document["elements"].extend([None,{"type":"node","tags":[]},
                                    {"type":"node","lat":True,"lon":105.,"tags":{"natural":"tree"}}])
        with patch.object(tree_data.requests,"get",return_value=Response(document)):
            result=self.fetch()
        self.assertEqual(result["status"],"empty");self.assertEqual(result["areas"],[])
        self.assertEqual(result["points"],[])

    def test_point_limit_and_metre_height_validation(self):
        document={"elements":[{"type":"node","id":index+1,"lat":21.0001+index*0.0000005,
                               "lon":105.001,"tags":{"natural":"tree","height":"NaN"}}
                              for index in range(12010)]}
        payload=json.dumps(document,separators=(",", ":")).encode()
        # Exercise the parser independently: the HTTP byte cap may limit a real
        # response before the separate feature-count cap is reached.
        result=tree_data._parse_document(payload,self.bbox,None)
        self.assertEqual(len(result["points"]),tree_data.MAX_POINTS)
        self.assertNotIn("height",result["points"][0])
        for value,expected in (("1m",1.),("35 metres",35.),(True,None),("12ft",None),
                               (float("inf"),None),("36m",None),("0.5m",None)):
            self.assertEqual(tree_data._height(value),expected)

    def test_cancellation_before_request_during_download_and_during_parse_propagates(self):
        cancel=threading.Event();cancel.set()
        with patch.object(tree_data.requests,"get") as request:
            with self.assertRaises(PublicError):self.fetch(cancel=cancel)
        request.assert_not_called()
        cancel.clear()
        response=Response(on_chunk=cancel.set)
        with patch.object(tree_data.requests,"get",return_value=response) as request:
            with self.assertRaises(PublicError):self.fetch(cancel=cancel)
        self.assertTrue(response.closed);self.assertEqual(request.call_count,1)
        self.assertEqual(self.files(),[])
        class CancelDuringParse:
            calls=0
            def is_set(self):
                self.calls+=1
                return self.calls>=3
        with self.assertRaises(PublicError):
            tree_data._parse_document(json.dumps({"elements":[{}]*300}),self.bbox,CancelDuringParse())

    def test_cancelled_first_attempt_does_not_fall_back_to_another_provider(self):
        cancel=threading.Event()
        def fail(*args,**kwargs):
            cancel.set()
            raise requests.Timeout("timeout")
        with patch.object(tree_data.requests,"get",side_effect=fail) as request:
            with self.assertRaises(PublicError):self.fetch(cancel=cancel)
        self.assertEqual(request.call_count,1)

    def test_bad_bbox_is_explicit_and_cannot_enter_an_overpass_query(self):
        with patch.object(tree_data.requests,"get") as request:
            for bbox in (None,{}, {**self.bbox,"north":float("nan")},
                         {**self.bbox,"west":106.},{**self.bbox,"north":90.},
                         {**self.bbox,"east":116.}):
                with self.subTest(bbox=bbox):
                    with self.assertRaises(PublicError):tree_data.fetch_tree_features(bbox,self.temp.name)
        request.assert_not_called()

    def test_time_budget_stops_stream_and_does_not_start_another_request(self):
        response=Response(body=b"x"*20000)
        with patch.object(tree_data.time,"monotonic",side_effect=[0.,0.,0.,17.,17.]), \
             patch.object(tree_data.requests,"get",return_value=response) as request:
            result=self.fetch()
        self.assertEqual(result["status"],"unavailable")
        self.assertEqual(request.call_count,1);self.assertTrue(response.closed)
        self.assertEqual(self.files(),[])

    def test_unwritable_cache_does_not_fail_success_and_removes_partial_files(self):
        with patch.object(tree_data.requests,"get",return_value=Response()), \
             patch.object(tree_data.os,"replace",side_effect=OSError("Read-only cache")):
            result=self.fetch()
        self.assertEqual(result["status"],"empty")
        self.assertEqual(self.files(),[])
        self.assertFalse(list(Path(self.temp.name).rglob("*.tmp")))

    def test_deeply_nested_json_is_a_nonfatal_provider_error(self):
        response=Response(body=b"["*2000+b"]"*2000)
        with patch.object(tree_data.requests,"get",side_effect=[response,requests.Timeout("offline")]):
            result=self.fetch()
        self.assertEqual(result["status"],"unavailable")
        self.assertTrue(response.closed);self.assertEqual(self.files(),[])


if __name__=="__main__":unittest.main()
