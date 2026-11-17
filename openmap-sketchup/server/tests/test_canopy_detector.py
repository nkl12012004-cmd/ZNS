"""Visible-crown evidence fixtures; no land-use/grid scattering expectations."""
from io import BytesIO
import math
import threading
import unittest
import numpy as np
from PIL import Image
from openmap_server.canopy_detector import detect_canopies
from openmap_server.net import PublicError


def crown_image(crowns=((100,100,14),), *, size=256, seed=924, shadow=True):
    """Textured round crowns with a bright dome and a one-sided cast shadow."""
    rng=np.random.default_rng(seed)
    yy,xx=np.indices((size,size))
    rgb=np.full((size,size,3),172.,dtype=np.float64)
    for x,y,radius in crowns:
        if shadow:
            shade=((xx-(x+radius*.65))**2+(yy-(y+radius*.55))**2)<=(radius*1.06)**2
            rgb[shade]=(34.,36.,34.)
        distance=np.sqrt((xx-x)**2+(yy-y)**2)/radius
        mask=distance<=1
        dome=1-np.clip(distance,0,1)
        green=91+58*dome+rng.normal(0,15,(size,size))
        rgb[mask,0]=(green*.47)[mask]
        rgb[mask,1]=green[mask]
        rgb[mask,2]=(green*.38)[mask]
    return Image.fromarray(np.clip(rgb,0,255).astype(np.uint8))


def encoded_image(image):
    output=BytesIO();image.save(output,format='PNG');return output.getvalue()


def rectangle_image(*, noise=False, ribs=False, shadow=False):
    rng=np.random.default_rng(220)
    yy,xx=np.indices((256,256))
    rgb=np.full((256,256,3),172.,dtype=np.float64)
    if shadow:rgb[45:230,55:225]=(35,36,34)
    mask=(xx>=40)&(xx<211)&(yy>=35)&(yy<216)
    green=np.full((256,256),128.)
    if noise:green+=rng.normal(0,21,green.shape)
    if ribs:green+=np.sin(xx*.9+yy*.2)*32
    rgb[mask,0]=(green*.47)[mask];rgb[mask,1]=green[mask];rgb[mask,2]=(green*.38)[mask]
    return Image.fromarray(np.clip(rgb,0,255).astype(np.uint8))


class CanopyDetectorTests(unittest.TestCase):
    def assertCenters(self, actual, expected, image_size=256):
        self.assertEqual(len(actual),len(expected),actual)
        remaining=list(actual)
        for x,y,radius in expected:
            candidate=min(remaining,key=lambda value:(value['u']*(image_size-1)-x)**2+((1-value['v'])*(image_size-1)-y)**2)
            remaining.remove(candidate)
            distance=math.hypot(candidate['u']*(image_size-1)-x,(1-candidate['v'])*(image_size-1)-y)
            self.assertLessEqual(distance,radius/4,candidate)
            self.assertTrue(0<candidate['confidence']<=1)
            self.assertGreater(candidate['radius_m'],0)
            self.assertIn(candidate['method'],('outlined_crown','textured_crown_peak'))

    def test_single_round_textured_crown_center_measured_from_pixels(self):
        expected=[(100,100,14)]
        actual=detect_canopies(crown_image(expected),60.,60.)
        self.assertCenters(actual,expected)
        self.assertAlmostEqual(actual[0]['radius_m'],14*60/256,delta=.5)

    def test_two_separated_crowns_preserve_distinct_off_grid_centers(self):
        expected=[(73,87,14),(178,169,18)]
        self.assertCenters(detect_canopies(crown_image(expected),60.,60.),expected)

    def test_detected_position_follows_image_translation_without_random_jitter(self):
        first=detect_canopies(crown_image([(81,95,16)]),60.,60.)
        second=detect_canopies(crown_image([(119,122,16)]),60.,60.)
        self.assertCenters(first,[(81,95,16)]);self.assertCenters(second,[(119,122,16)])
        self.assertAlmostEqual((second[0]['u']-first[0]['u'])*255,38,delta=1)
        self.assertAlmostEqual((first[0]['v']-second[0]['v'])*255,27,delta=1)

    def test_identical_image_is_deterministic_and_not_mutated(self):
        image=crown_image([(73,87,14),(178,169,18)]);before=image.tobytes()
        first=detect_canopies(image,60.,60.)
        self.assertEqual(first,detect_canopies(image,60.,60.))
        self.assertEqual(image.tobytes(),before)

    def test_uniform_green_gray_and_absent_image_return_no_crowns(self):
        for image in (None,Image.new('RGB',(256,256),(60,140,50)),Image.new('RGB',(256,256),(140,140,140))):
            for level in ('sparse','medium','dense'):
                with self.subTest(level=level,color=image.getpixel((0,0)) if image else None):
                    self.assertEqual(detect_canopies(image,60.,60.,level=level),[])

    def test_noisy_rectangular_grass_and_green_roofs_are_not_canopies(self):
        for image in (rectangle_image(),rectangle_image(noise=True),rectangle_image(ribs=True,shadow=True),rectangle_image(noise=True,shadow=True)):
            for level in ('sparse','medium','dense'):
                with self.subTest(level=level):self.assertEqual(detect_canopies(image,60.,60.,level=level),[])

    def test_untextured_round_green_mark_without_crown_evidence_rejected(self):
        yy,xx=np.indices((256,256));rgb=np.full((256,256,3),172,dtype=np.uint8)
        rgb[(xx-100)**2+(yy-100)**2<=18**2]=(60,135,50)
        self.assertEqual(detect_canopies(Image.fromarray(rgb),60.,60.),[])

    def test_fully_blocked_crown_is_not_returned(self):
        image=crown_image();blocked=np.zeros((256,256),dtype=bool);blocked[60:145,60:145]=True
        self.assertEqual(detect_canopies(image,60.,60.,blocked=blocked),[])

    def test_large_domed_crown_does_not_create_duplicate_scale_leaf_trees(self):
        expected=[(126,123,34)]
        actual=detect_canopies(crown_image(expected),60.,60.,level='dense')
        self.assertCenters(actual,expected)

    def test_too_low_resolution_and_invalid_extent_skip_instead_of_fill(self):
        image=crown_image()
        self.assertEqual(detect_canopies(image,2000.,2000.),[])
        self.assertEqual(detect_canopies(image,0.,60.),[])
        self.assertEqual(detect_canopies(image,60.,-2.),[])

    def test_cancellation_before_and_during_component_scan(self):
        class CancelAfterChecks:
            def __init__(self):self.calls=0
            def is_set(self):self.calls+=1;return self.calls>=4
        event=threading.Event();event.set()
        for cancel in (event,CancelAfterChecks()):
            with self.assertRaisesRegex(PublicError,'hủy'):detect_canopies(crown_image(),60.,60.,cancel=cancel)

if __name__=='__main__':unittest.main()
