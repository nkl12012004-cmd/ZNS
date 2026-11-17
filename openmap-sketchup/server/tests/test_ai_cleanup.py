"""Offline image cleanup fixtures; no user images, models or cloud requests."""
import base64
from io import BytesIO
import unittest
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw,ImageOps

from openmap_server.ai_cleanup import cleanup
from openmap_server.net import PublicError


class Store:
    def __init__(self,image):
        stream=BytesIO();image.save(stream,format='PNG');self.original=stream.getvalue();self.result=None;self.calls=[]
    def asset_bytes(self,identifier):return self.original,{'id':identifier,'name':'fixture.png'}
    def route(self,method,path,body):
        self.calls.append((method,path,body['role']));self.result=base64.b64decode(body['data_url'].split(',')[1])
        return {'id':'b'*32,'width':256,'height':192,'mime':'image/png'}


class CleanupTests(unittest.TestCase):
    def test_slow_cleanup_does_not_block_flow_queue_requests(self):
        from openmap_server.ai_render import AIRenderService
        from openmap_server.ai_cleanup import _fill
        store=Store(Image.new('RGB',(128,96),(40,90,130)))
        with tempfile.TemporaryDirectory() as folder:
            service=AIRenderService({'OPENMAP_AI_DIR':folder,'OPENMAP_LOCAL_TOKEN':'cleanup-fixture-only'})
            entered,release=threading.Event(),threading.Event()
            def delayed(*args):
                entered.set()
                if not release.wait(3):raise RuntimeError('Test cleanup timed out')
                return _fill(*args)
            try:
                source=service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(store.original).decode()})
                with ThreadPoolExecutor(max_workers=2) as executor, patch('openmap_server.ai_cleanup._fill',side_effect=delayed):
                    processing=executor.submit(service.route,'POST','/api/ai/cleanup',{'asset_id':source['id'],'regions':[{'x':.8,'y':.8,'width':.1,'height':.1}]})
                    try:
                        self.assertTrue(entered.wait(1))
                        listing=executor.submit(service.route,'GET','/api/ai/jobs',{})
                        self.assertEqual(listing.result(timeout=1)['jobs'],[])
                    finally:release.set()
                    self.assertNotEqual(processing.result(timeout=3)['id'],source['id'])
            finally:
                release.set();service.close()

    def test_small_text_on_smooth_background_and_outside_pixels_unchanged(self):
        yy,xx=np.indices((192,256));background=np.stack((100+xx//8,130+yy//8,170+xx//16),axis=-1).astype(np.uint8)
        image=Image.fromarray(background).convert('RGBA');draw=ImageDraw.Draw(image);draw.text((206,163),'LOGO',fill='white')
        before=np.asarray(image);store=Store(image)
        result=cleanup(store,{'asset_id':'a'*32,'regions':[{'x':.78,'y':.81,'width':.19,'height':.16}]})
        after=np.asarray(Image.open(BytesIO(store.result)).convert('RGBA'))
        mask=np.zeros((192,256),bool);mask[155:187,199:249]=True
        np.testing.assert_array_equal(after[~mask],before[~mask])
        self.assertLess(float(np.mean(np.abs(after[mask,:3].astype(float)-background[mask].astype(float)))),3)
        self.assertTrue(result['cleanup']['original_preserved']);self.assertNotEqual(result['id'],result['source_id'])
        self.assertEqual(store.original,store.asset_bytes('a'*32)[0]);self.assertEqual(store.calls,[('POST','/api/ai/assets','result')])

    def test_corner_zone_stays_bounded_and_preserves_alpha_elsewhere(self):
        image=Image.new('RGBA',(256,192),(60,90,120,180));ImageDraw.Draw(image).rectangle((232,177,255,191),fill=(255,255,255,255))
        before=np.asarray(image);store=Store(image)
        result=cleanup(store,{'asset_id':'a'*32,'regions':[{'x':.9,'y':.9,'width':.1,'height':.1}]})
        after=np.asarray(Image.open(BytesIO(store.result)))
        np.testing.assert_array_equal(after[:172],before[:172]);self.assertLess(result['cleanup']['masked_fraction'],.02)
        self.assertLessEqual(result['cleanup']['iterations'],240)
        self.assertLess(float(np.abs(after[-8:,-8:].astype(float)-np.array([60,90,120,180])).mean()),3)

    def test_phone_exif_orientation_uses_the_displayed_mask_coordinates(self):
        logical=Image.new('RGB',(80,120),(40,90,130));ImageDraw.Draw(logical).rectangle((55,10,70,23),fill=(240,240,240))
        physical=logical.transpose(Image.Transpose.ROTATE_90)
        exif=Image.Exif();exif[274]=6
        stream=BytesIO();physical.save(stream,format='JPEG',exif=exif,quality=100,subsampling=0)
        store=Store(logical);store.original=stream.getvalue();original=store.original
        expected=np.asarray(ImageOps.exif_transpose(Image.open(BytesIO(original))).convert('RGBA'))
        result=cleanup(store,{'asset_id':'a'*32,'regions':[{'x':.675,'y':.075,'width':.225,'height':.13333333333333333}]})
        output=Image.open(BytesIO(store.result));after=np.asarray(output)
        self.assertEqual(output.size,(80,120));self.assertTrue(result['cleanup']['orientation_applied'])
        mask=np.zeros((120,80),bool);mask[9:25,54:72]=True
        np.testing.assert_array_equal(after[~mask],expected[~mask])
        self.assertLess(float(after[12:21,58:68,0].mean()),80)
        self.assertEqual(store.original,original)

    def test_invalid_or_large_masks_never_upload_a_result(self):
        for regions in [[],[{'x':0,'y':0,'width':.5,'height':.5}],
                        [{'x':True,'y':0,'width':.1,'height':.1}],
                        [{'x':.99,'y':0,'width':.1,'height':.1}],
                        [{'x':0,'y':0,'width':float('nan'),'height':.1}],
                        [{'x':0,'y':0,'width':-.1,'height':.1}],
                        [{'x':10**1000,'y':0,'width':.1,'height':.1}]]:
            with self.subTest(regions=regions):
                store=Store(Image.new('RGB',(256,192),'gray'))
                with self.assertRaises(PublicError):cleanup(store,{'asset_id':'a'*32,'regions':regions})
                self.assertEqual(store.calls,[])
        with self.assertRaises(PublicError):cleanup(Store(Image.new('RGB',(32,32))),{'asset_id':'../file','regions':[]})

    def test_absolute_mask_and_merged_roi_limits_are_enforced(self):
        fixtures=[((2000,1500),[{'x':.1,'y':.1,'width':.3,'height':.3}]),
                  ((1600,1600),[{'x':.1,'y':.5,'width':.8,'height':.002},
                                {'x':.5,'y':.1,'width':.002,'height':.8}])]
        for size,regions in fixtures:
            with self.subTest(size=size):
                store=Store(Image.new('RGB',size,'gray'))
                with self.assertRaises(PublicError):cleanup(store,{'asset_id':'a'*32,'regions':regions})
                self.assertEqual(store.calls,[])

    def test_actual_managed_service_route_keeps_original_asset_immutable(self):
        from openmap_server.ai_render import AIRenderService
        store=Store(Image.new('RGB',(128,96),(40,90,130)))
        with tempfile.TemporaryDirectory() as folder:
            service=AIRenderService({'OPENMAP_AI_DIR':folder,'OPENMAP_AUTH_MODE':'local','OPENMAP_LOCAL_TOKEN':'cleanup-fixture-only'})
            try:
                source=service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(store.original).decode(),'name':'fixture.png'})
                answer=service.route('POST','/api/ai/cleanup',{'asset_id':source['id'],'regions':[{'x':.8,'y':.8,'width':.1,'height':.1}]})
                self.assertNotEqual(answer['id'],source['id']);self.assertEqual(answer['source_id'],source['id'])
                original,_=service.asset_bytes(source['id']);result,meta=service.asset_bytes(answer['id'])
                self.assertEqual(original,store.original);self.assertEqual(meta['mime'],'image/png')
                np.testing.assert_array_equal(np.asarray(Image.open(BytesIO(result)).convert('RGB')),np.asarray(Image.open(BytesIO(original))))
            finally:service.close()

    def test_overlapping_rectangles_count_union_once_and_fill_is_deterministic(self):
        body={'asset_id':'a'*32,'regions':[{'x':.1,'y':.1,'width':.2,'height':.2}]*2}
        first,second=Store(Image.new('RGB',(256,192),(30,80,100))),Store(Image.new('RGB',(256,192),(30,80,100)))
        result=cleanup(first,body);cleanup(second,body)
        self.assertLess(result['cleanup']['masked_fraction'],.05);self.assertEqual(first.result,second.result)

    def test_explicit_gemini_mode_no_match_returns_original_without_new_asset(self):
        from openmap_server.ai_render import AIRenderService
        store=Store(Image.new('RGB',(1024,768),(70,100,130)))
        with tempfile.TemporaryDirectory() as folder:
            service=AIRenderService({'OPENMAP_AI_DIR':folder,'OPENMAP_LOCAL_TOKEN':'cleanup-fixture-only'})
            try:
                source=service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(store.original).decode(),'name':'no-mark.png'})
                before=set(service._state['assets'])
                with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected cloud request')):
                    answer=service.route('POST','/api/ai/cleanup',{'asset_id':source['id'],'mode':'gemini'})
                self.assertEqual(answer['id'],source['id']);self.assertEqual(answer['source_id'],source['id'])
                self.assertFalse(answer['cleanup']['applied'])
                self.assertEqual(answer['cleanup']['confidence_kind'],'heuristic_not_probability')
                self.assertEqual(set(service._state['assets']),before)
                self.assertEqual(service.asset_bytes(source['id'])[0],store.original)
            finally:service.close()

    def test_explicit_gemini_mode_detected_mark_creates_png_and_preserves_original(self):
        from openmap_server.ai_render import AIRenderService
        from openmap_server import gemini_watermark as gemini
        yy,xx=np.mgrid[:768,:1024]
        clean=np.stack((50+60*xx/1024+5*yy/768,70+40*xx/1024+10*yy/768,90+25*xx/1024+15*yy/768),axis=-1)
        clean=np.rint(clean).astype(np.uint8)
        variant,size,inset=gemini._geometry(1024,768,'v1');alpha=gemini._template(variant,size)
        x,y=1024-inset-size,768-inset-size
        marked=clean.copy();marked[y:y+size,x:x+size]=np.rint(clean[y:y+size,x:x+size]*(1-alpha[...,None])+255*alpha[...,None])
        store=Store(Image.fromarray(marked));original=store.original
        with tempfile.TemporaryDirectory() as folder:
            service=AIRenderService({'OPENMAP_AI_DIR':folder,'OPENMAP_LOCAL_TOKEN':'cleanup-fixture-only'})
            try:
                source=service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(original).decode(),'name':'known-mark.png'})
                with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected cloud request')):
                    answer=service.route('POST','/api/ai/cleanup',{'asset_id':source['id'],'mode':'gemini'})
                self.assertTrue(answer['cleanup']['applied']);self.assertEqual(answer['cleanup']['variant'],variant)
                self.assertNotEqual(answer['id'],source['id']);self.assertEqual(answer['source_id'],source['id'])
                result,metadata=service.asset_bytes(answer['id'])
                self.assertEqual(metadata['mime'],'image/png');self.assertEqual(metadata['role'],'result')
                self.assertEqual(service.asset_bytes(source['id'])[0],original)
                after=np.asarray(Image.open(BytesIO(result)).convert('RGB'))
                mask=np.zeros((768,1024),bool);mask[y:y+size,x:x+size]=alpha>=.002
                np.testing.assert_array_equal(after[~mask],marked[~mask])
                self.assertLess(float(np.abs(after[mask].astype(float)-clean[mask]).mean()),1)
            finally:service.close()

    def test_unknown_cleanup_mode_or_mixed_gemini_mask_is_rejected(self):
        for extra in ({'mode':'force'},{'mode':True},{'mode':'gemini','regions':[]}):
            with self.subTest(extra=extra):
                store=Store(Image.new('RGB',(128,96),'gray'))
                with self.assertRaises(PublicError):cleanup(store,{'asset_id':'a'*32,**extra})
                self.assertEqual(store.calls,[])


if __name__=='__main__':unittest.main()
