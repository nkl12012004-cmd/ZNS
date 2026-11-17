from hashlib import sha256
from io import BytesIO
import re
import unittest
from unittest.mock import patch

from PIL import Image

from openmap_server import builder
from openmap_server.net import PublicError


class ImageryCoverageTests(unittest.TestCase):
    def setUp(self):
        buffer=BytesIO();Image.new('RGB',(256,256),(50,130,70)).save(buffer,'PNG');self.tile=buffer.getvalue()

    def params(self, **kwargs):
        return builder.parameters({'lat':21.028511,'lon':105.854444,'width':100,'height':100,'grid':8,'image_size':1024,'imagery':'satellite','roads':False,'buildings':False,**kwargs})

    def test_esri_caps_native_zoom_and_keeps_requested_export_size(self):
        urls=[]
        def getter(url, **_kwargs):urls.append(url);return self.tile
        result=builder.build(self.params(image_size=4096),getter=getter)
        self.assertTrue(all('?blankTile=false' in url for url in urls))
        self.assertTrue(all('/tile/19/' in url for url in urls))
        self.assertEqual(result['imagery_requested_zoom'],20)
        self.assertEqual(result['imagery_source_zoom'],19)
        self.assertTrue(result['warnings'])
        self.assertFalse(result['partial'])
        import base64
        with Image.open(BytesIO(base64.b64decode(result['materials'][0]['texture_png']))) as image:
            self.assertEqual(max(image.size),4096)

    def test_missing_coverage_uses_lower_zoom(self):
        zooms=set()
        def getter(url, **_kwargs):
            zoom=int(re.search(r'/tile/(\d+)/',url)[1]);zooms.add(zoom)
            if zoom==19:raise PublicError('provider 404',502)
            return self.tile
        result=builder.build(self.params(),getter=getter)
        self.assertEqual(zooms,{19,18})
        self.assertEqual(result['imagery_source_zoom'],18)
        self.assertFalse(result['partial'])

    def test_unavailable_coverage_retries_at_most_three_levels(self):
        zooms=set()
        def getter(url, **_kwargs):
            zooms.add(int(re.search(r'/tile/(\d+)/',url)[1]))
            raise PublicError('unavailable',502)
        with self.assertRaises(PublicError):builder.build(self.params(),getter=getter)
        self.assertEqual(zooms,{19,18,17})

    def test_http_200_no_data_image_is_rejected(self):
        # The live provider returned a real JPEG with a fixed placeholder hash.
        # Exercise the same marker path using a small valid image fixture.
        with patch.object(builder,'NO_DATA_TILES',{sha256(self.tile).hexdigest()}),self.assertRaises(PublicError) as context:
            builder.Raster(self.params()['bbox'],19,builder.SATELLITE,getter=lambda *_a,**_k:self.tile)
        self.assertEqual(context.exception.status,502)

    def test_user_cancel_does_not_trigger_lower_zoom_retry(self):
        zooms=set()
        def getter(url, **_kwargs):
            zooms.add(int(re.search(r'/tile/(\d+)/',url)[1]));raise PublicError('cancelled',400)
        with self.assertRaises(PublicError):builder.build(self.params(),getter=getter)
        self.assertEqual(zooms,{19})


if __name__=='__main__':unittest.main()
