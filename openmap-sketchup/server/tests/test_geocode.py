import json
import math
import unittest
from unittest.mock import patch
import urllib.parse

from openmap_server.geocode import Geocoder
from openmap_server.map_links import allowed, resolve
from openmap_server.net import PublicError
from openmap_server.app import Application


ARCGIS = {"candidates": [{"address": "Hà Nội", "location": {"y": 21.028279, "x": 105.853881}, "attributes": {"LongLabel": "Hà Nội, Việt Nam"}}]}
PHOTON = {"features": [{"type": "Feature", "properties": {"name": "Hà Nội", "country": "Việt Nam"}, "geometry": {"type": "Point", "coordinates": [105.854041, 21.0283334]}}]}


class GeocodeTests(unittest.TestCase):
    def test_vietnamese_results_bias_and_cache(self):
        calls = []
        def getter(url, **kwargs):
            calls.append((url, kwargs))
            return ARCGIS
        geocoder = Geocoder(getter)
        result = geocoder.search('Hà Nội', lat=21, lon=105)
        self.assertAlmostEqual(result['results'][0]['lat'], 21.028279)
        self.assertIn('Hà Nội', result['results'][0]['label'])
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0][0]).query)
        self.assertEqual(params['SingleLine'], ['Hà Nội'])
        self.assertEqual(params['location'], ['105.000000,21.000000'])
        self.assertEqual(result, geocoder.search('hà nội', lat=21, lon=105))
        self.assertEqual(len(calls), 1)
        key = next(iter(geocoder.cache))
        geocoder.cache[key] = (0, result)
        geocoder.search('Hà Nội', lat=21, lon=105)
        self.assertEqual(len(calls), 2, 'Expired location cache must refresh')

    def test_falls_back_to_photon_when_primary_fails(self):
        calls = []
        def getter(url, **_kwargs):
            calls.append(url)
            if 'arcgis' in url: raise PublicError('Unavailable', 502)
            return PHOTON
        result = Geocoder(getter).search('Hà Nội')
        self.assertEqual(result['source'], 'photon')
        self.assertEqual(len(calls), 2)

    def test_live_suggestions_never_query_nominatim(self):
        calls = []
        def getter(url, **_kwargs):
            calls.append(url)
            raise PublicError('Unavailable', 502)
        with self.assertRaises(PublicError): Geocoder(getter).search('Hà N', suggest=True)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any('nominatim' in url for url in calls))

    def test_prefix_search_is_global_and_weak_fallback_is_hidden(self):
        calls=[]
        def photon(url, **_kwargs):
            calls.append(url)
            return PHOTON
        result=Geocoder(photon).search('Hà Nộ', lat=10.77, lon=106.7, suggest=True)
        self.assertEqual(result['source'],'photon')
        self.assertNotIn('lat=',calls[0])
        self.assertAlmostEqual(result['results'][0]['lat'],21.0283334)
        wrong={'candidates':[{'address':'Hå, Rogaland, NOR','location':{'y':58.665962,'x':5.5525425}}]}
        def fallback(url, **_kwargs):
            if 'photon' in url: raise PublicError('Unavailable',502)
            return wrong
        self.assertEqual(Geocoder(fallback).search('Hà Nộ', suggest=True)['results'],[])

    def test_submit_can_use_nominatim_fallback(self):
        def getter(url, **_kwargs):
            if 'nominatim' not in url: raise PublicError('Unavailable', 502)
            return [{'display_name':'Hà Nội, Việt Nam','lat':'21.0283334','lon':'105.854041'}]
        result = Geocoder(getter).search('Hà Nội')
        self.assertEqual(result['source'],'nominatim')
        self.assertAlmostEqual(result['results'][0]['lon'],105.854041)

    def test_bad_provider_geometry_is_skipped(self):
        bad = {'candidates':[
            {'address':'bad','location':{'y':math.nan,'x':105}},
            {'address':'bad','location':{'y':95,'x':105}},
            ARCGIS['candidates'][0], ARCGIS['candidates'][0]]}
        result = Geocoder(lambda *_a, **_kw: bad).search('Hà Nội')
        self.assertEqual(len(result['results']),1)

    def test_empty_and_transport_failure_are_distinct(self):
        def empty(url, **_kwargs):
            if 'arcgis' in url: return {'candidates':[]}
            if 'photon' in url: return {'features':[]}
            return []
        self.assertEqual(Geocoder(empty).search('none')['results'],[])
        def failed(*_args, **_kwargs): raise PublicError('Unavailable',502)
        with self.assertRaises(PublicError) as caught: Geocoder(failed).search('none')
        self.assertEqual(caught.exception.status,502)

    def test_validation_rejects_bad_inputs_before_network(self):
        def getter(*_args, **_kwargs): raise AssertionError('Should not fetch')
        geocoder=Geocoder(getter)
        for kwargs in ({'query':'a'},{'query':'Hà Nội','lat':math.nan,'lon':105},{'query':'Hà Nội','limit':True},{'query':'Hà Nội','limit':20}):
            with self.subTest(kwargs=kwargs),self.assertRaises(PublicError): geocoder.search(**kwargs)

    def test_inflight_searches_are_bounded(self):
        geocoder = Geocoder(lambda *_a, **_kw: ARCGIS)
        for _ in range(4): geocoder.inflight.acquire()
        try:
            with self.assertRaises(PublicError) as caught: geocoder.search('Hà Nội')
            self.assertEqual(caught.exception.status,503)
        finally:
            for _ in range(4): geocoder.inflight.release()

    def test_legacy_route_shapes_and_token_boundary(self):
        app=Application({'OPENMAP_LOCAL_TOKEN':'private-test-token'})
        app.geocoder=Geocoder(lambda *_a, **_kw: ARCGIS)
        headers={'X-OpenMap-Local':'private-test-token'}
        try:
            for path in ('/api/geocode','/api/search_suggest'):
                result=app.route('POST',path,{},headers,{'query':'Hà Nội','lat':21,'lon':105,'limit':6})
                self.assertTrue(result['ok']); self.assertIn('Hà Nội',result['results'][0]['title'])
            result=app.route('GET','/api/search',{'q':['Hà Nội']},headers,{})
            self.assertEqual(result['source'],'arcgis')
            with self.assertRaises(PublicError) as caught: app.route('POST','/api/geocode',{}, {}, {'query':'Hà Nội'})
            self.assertEqual(caught.exception.status,403)
        finally: app.close()


class MapLinkTests(unittest.TestCase):
    def test_direct_and_redirected_google_maps_coordinates(self):
        direct='https://www.google.com/maps/@21.0283,105.854,16z'
        self.assertEqual(resolve(direct),(21.0283,105.854))
        calls=[]
        def redirect(url, timeout):
            calls.append(url)
            self.assertLessEqual(timeout,3)
            return direct
        self.assertEqual(resolve('https://maps.app.goo.gl/example',redirect),(21.0283,105.854))
        self.assertEqual(len(calls),1)

    def test_redirect_host_and_private_address_are_rejected(self):
        for url in ('http://maps.app.goo.gl/example','https://google.com@127.0.0.1/maps','https://www.google.com:444/maps','https://127.0.0.1/maps'):
            with self.subTest(url=url): self.assertFalse(allowed(url))
        for location in ('https://127.0.0.1/private','https://evil.example/maps','http://www.google.com/maps/@21,105'):
            with self.subTest(location=location), self.assertRaises(PublicError): resolve('https://maps.app.goo.gl/example',lambda *_:location)

    def test_redirect_cycles_and_missing_coordinates_are_bounded(self):
        calls=[]
        def repeat(url, _timeout): calls.append(url); return url
        with self.assertRaises(PublicError): resolve('https://maps.app.goo.gl/example',repeat)
        self.assertEqual(len(calls),1)
        with self.assertRaises(PublicError): resolve('https://www.google.com/maps/place/Hanoi',lambda *_:None)

    def test_suggestions_do_not_resolve_short_urls(self):
        geocoder=Geocoder(lambda *_a, **_kw: ARCGIS)
        with patch('openmap_server.map_links.resolve',side_effect=AssertionError('No redirects during typing')):
            self.assertEqual(geocoder.search('https://maps.app.goo.gl/example',suggest=True)['results'],[])
        result=geocoder.search('https://www.google.com/maps/@21.0283,105.854,16z',suggest=True)
        self.assertTrue(result['is_direct_coords'])
        self.assertEqual(result['results'][0]['source'],'coordinates')
