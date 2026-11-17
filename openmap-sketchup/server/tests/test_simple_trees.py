"""Only image-detected crowns may create trees; geometry tests use detector fixtures."""
from copy import deepcopy
from io import BytesIO
import math
import threading
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from openmap_server import geo, simple_trees as trees
from openmap_server.net import PublicError

CENTER = {'lat': 21.0285, 'lon': 105.8544}

def project(lat, lon, lat0, lon0):
    return geo.xy(lat, lon, {'lat': lat0, 'lon': lon0})

def image_bytes(kind='textured'):
    if kind == 'textured':
        rng = np.random.default_rng(606)
        rgb = np.stack([rng.integers(34,77,(256,256)), rng.integers(100,180,(256,256)), rng.integers(24,64,(256,256))], axis=2).astype(np.uint8)
    else:
        rgb = np.full((128,128,3), (60,140,50) if kind == 'uniform_green' else (140,140,140), dtype=np.uint8)
    result = BytesIO(); Image.fromarray(rgb).save(result, format='PNG')
    return result.getvalue()

def params(**changes):
    value = {'include_trees': True, 'trees_from_imagery': False, 'tree_density': 'medium', 'sat_provider': 'esri_sat', **CENTER,
             **geo.bounds(CENTER['lat'], CENTER['lon'], 100., 100.)}
    value.update(changes)
    return value

def make_scene(texture=None, side=100., heights=(0.,0.,0.,0.), transform=None, offset=None):
    uv = np.asarray([[0,0],[1,0],[1,1],[0,1]], dtype=np.float64)
    xy = (uv-.5)*side
    if transform is not None:
        matrix, translation = transform; xy = xy @ np.asarray(matrix) + np.asarray(translation)
    mesh = {'verts': np.column_stack([xy,heights]), 'faces': np.asarray([[0,1,2],[0,2,3]], dtype=np.uint32), 'uvs': uv, 'mat_idx': 0}
    return {'materials': [{'name':'ground','color':[180,185,170,255],'texture_bytes':texture,'ext':'png'}],
            'layers': [{'tag':'MapSKP_00_Terrain','name':'Terrain','meshes':[mesh]}],
            'origin': {**CENTER,'offset_from_anchor_m':offset or [0.,0.,0.]}}

def coordinate_for(x,y,config=None):
    """Invert real WGS84/ENU for a known scene-local test position."""
    config = config or params(); anchor = config.get('anchor') or CENTER
    center = np.asarray(project(config['lat'],config['lon'],anchor['lat'],anchor['lon']))
    target = center + np.asarray([x,y])
    guess = np.asarray([config['lat']+y/111000.,config['lon']+x/(111000.*math.cos(math.radians(config['lat'])))])
    for _ in range(5):
        current = np.asarray(project(*guess,anchor['lat'],anchor['lon']))
        jacobian = np.column_stack([(np.asarray(project(*(guess+delta),anchor['lat'],anchor['lon']))-current)/1e-6
                                    for delta in (np.asarray([1e-6,0]),np.asarray([0,1e-6]))])
        guess += np.linalg.solve(jacobian,target-current)
    return {'lat':float(guess[0]),'lon':float(guess[1])}

def features(points=(),areas=(),status='fixture',config=None):
    return {'points':[coordinate_for(x,y,config) for x,y in points], 'areas':list(areas), 'status':status}

def area(kind,points):
    coords = [coordinate_for(x,y) for x,y in points]
    return {'kind':kind,'coordinates':[[p['lat'],p['lon']] for p in coords]}

def old_tree_layer(x=0.,y=0.,z=0.,height=6.5):
    r=height*.34
    verts=np.asarray([(x,y,z+height),(x+r,y,z+height*.58),(x,y+r,z+height*.58),
                      (x-r,y,z+height*.58),(x,y-r,z+height*.58),(x,y,z+height*.28)],dtype=np.float32)
    faces=np.asarray([(0,1,2),(0,2,3),(0,3,4),(0,4,1),(5,2,1),(5,3,2),(5,4,3),(5,1,4)],dtype=np.uint32)
    return {'tag':trees.TREE_TAG,'meshes':[{'verts':verts,'faces':faces,'uvs':None,'mat_idx':0}]}

def blocking_layer(tag,rect):
    x0,y0,x1,y1=rect
    return {'tag':tag,'meshes':[{'verts':np.asarray([[x0,y0,40.],[x1,y0,40.],[x1,y1,40.],[x0,y1,40.]]),
            'faces':np.asarray([[0,1,2],[0,2,3]],dtype=np.uint32),'uvs':None,'mat_idx':0}]}

def trunks(scene):
    meshes=[m for layer in scene['layers'] if layer['tag']==trees.TREE_TAG for m in layer['meshes']
            if scene['materials'][m['mat_idx']]['name']=='SiteCraft_Tree_Trunk']
    return np.concatenate([m['verts'].reshape(-1,18,3) for m in meshes]) if meshes else np.empty((0,18,3),dtype=np.float32)

def centers(scene): return trunks(scene)[:,16]
def face_count(scene): return sum(len(m['faces']) for layer in scene['layers'] for m in layer.get('meshes',[]))

from test_canopy_detector import crown_image, encoded_image, rectangle_image

class SimpleTreesTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(trees,'fetch_tree_features',side_effect=AssertionError('Unexpected network query'))
        self.fetch=guard.start();self.addCleanup(guard.stop)

    def add(self,scene,points=None,*,config=None,data=None,radius=2.,detections=None,**kw):
        """Isolate placement/geometry from vision with explicit detector records."""
        if detections is None:
            detections=[]
            if points:
                uv=trees.Ground(scene).to_uv(points)
                detections=[{'u':float(u),'v':float(v),'radius_m':radius,'confidence':.91,'method':'outlined_crown'} for u,v in uv]
        with patch.object(trees,'detect_canopies',return_value=detections) as detector:
            self.detector=detector
            return trees.add_simple_trees(scene,config or params(trees_from_imagery=True),cache_dir='/unused-tree-fixture',project=project,
                                         feature_data=data if data is not None else features(),allow_network=False,**kw)

    def actual_add(self,scene,config=None,data=None,**kw):
        return trees.add_simple_trees(scene,config or params(trees_from_imagery=True),cache_dir='/unused-tree-fixture',project=project,
                                     feature_data=data if data is not None else features(),allow_network=False,**kw)

    def photo_scene(self,**kw):
        return make_scene(encoded_image(crown_image()),**kw)

    def assertSceneEqual(self,a,b):
        if isinstance(a,np.ndarray):
            self.assertEqual(a.dtype,b.dtype);np.testing.assert_array_equal(a,b)
        elif isinstance(a,dict):
            self.assertEqual(a.keys(),b.keys())
            for k in a:self.assertSceneEqual(a[k],b[k])
        elif isinstance(a,(list,tuple)):
            self.assertEqual(type(a),type(b));self.assertEqual(len(a),len(b))
            for x,y in zip(a,b):self.assertSceneEqual(x,y)
        else:self.assertEqual(a,b)

    def test_real_visible_crown_creates_one_tree_at_measured_image_center(self):
        scene=self.photo_scene(side=60.)
        summary=self.actual_add(scene)
        self.assertEqual(summary['total'],1);self.assertEqual(summary['osm'],0);self.assertEqual(summary['inferred'],1)
        self.assertEqual(summary['placement'],'detected_crown_centers');self.assertFalse(summary['random_scattering'])
        expected=np.asarray([(100/255-.5)*60,(.5-100/255)*60])
        self.assertLess(np.linalg.norm(centers(scene)[0,:2]-expected),14*60/256/4)
        location=scene['sitecraft']['detected_tree_locations'][0]
        self.assertEqual(location['method'],'outlined_crown');self.assertGreater(location['confidence'],.5)
        self.assertAlmostEqual(location['measured_radius_m'],14*60/256,delta=.5)
        self.assertLessEqual(location['radius_m'],2.)
        self.assertLessEqual(location['height_m'],6.5)

    def test_blank_photo_osm_points_forests_parks_and_rows_never_create_trees(self):
        outline=[(-40.,-40.),(40.,-40.),(40.,40.),(-40.,40.),(-40.,-40.)]
        data=features([(0.,0.),(20.,20.)],areas=[area(kind,outline) for kind in ('park','wood','forest','tree_row')])
        for texture in (None,image_bytes('uniform_green'),image_bytes('gray'),encoded_image(rectangle_image(noise=True)),b'corrupt'):
            scene=make_scene(texture);scene['layers'].append(old_tree_layer())
            summary=self.actual_add(scene,data=data)
            self.assertEqual(summary['total'],0);self.assertEqual(summary['triangles'],0)
            self.assertFalse(any(layer['tag']==trees.TREE_TAG for layer in scene['layers']))
            self.fetch.assert_not_called()

    def test_no_detector_candidates_means_no_grid_area_row_or_old_osm_placement(self):
        scene=self.photo_scene();scene['layers'].append(old_tree_layer())
        outline=[(-40.,-40.),(40.,-40.),(40.,40.),(-40.,40.)]
        data=features([(0.,0.)],areas=[area(kind,outline) for kind in ('wood','forest','park','tree_row')])
        summary=self.add(scene,data=data)
        self.assertEqual(summary['total'],0);self.assertEqual(summary['source_status'],'no_visible_crowns')
        self.assertEqual(summary['detected_candidates'],0);self.assertEqual(len(scene['materials']),1)
        self.assertFalse(any(layer['tag']==trees.TREE_TAG for layer in scene['layers']))

    def test_osm_only_corroborates_detected_center_and_never_moves_it(self):
        scene=self.photo_scene();scene['layers'].append(old_tree_layer(5.8,6.3,height=7.))
        data=features([(5.8,6.3),(-30.,35.)])
        data['points'][0]['height']=7.
        summary=self.add(scene,[(5.,6.)],data=data,config=params(trees_from_imagery=False))
        self.assertEqual(summary['total'],1);self.assertEqual(summary['osm'],1);self.assertEqual(summary['inferred'],0)
        np.testing.assert_allclose(centers(scene),[[5.,6.,0.]],atol=2e-6)
        location=scene['sitecraft']['detected_tree_locations'][0]
        self.assertTrue(location['osm_match']);self.assertEqual(location['radius_m'],2.)
        crown=next(m for m in scene['layers'][-1]['meshes'] if 'Crown' in scene['materials'][m['mat_idx']]['name'])
        self.assertAlmostEqual(float(crown['verts'][:,2].max()),6.5,places=5)

    def test_osm_node_only_corroborates_its_closest_visible_small_crown(self):
        scene=self.photo_scene()
        summary=self.add(scene,[(-1.3,0.),(1.4,0.)],radius=1.1,data=features([(0.,0.),(0.,0.)]),config=params(trees_from_imagery=False))
        self.assertEqual(summary['total'],1);self.assertEqual(summary['osm'],1)
        np.testing.assert_allclose(centers(scene)[:,:2],[[-1.3,0.]],atol=2e-6)

    def test_imagery_toggle_off_keeps_only_visible_osm_matched_crowns(self):
        for enabled,total in ((False,1),(True,2)):
            scene=self.photo_scene()
            summary=self.add(scene,[(-20.,10.),(25.,-15.)],data=features([(-20.4,10.3),(45.,45.)]),config=params(trees_from_imagery=enabled))
            self.assertEqual(summary['total'],total);self.assertEqual(summary['osm'],1)
            self.assertEqual(summary['inferred'],total-1)

    def test_roadmap_osm_unknown_providers_never_run_canopy_detector(self):
        for provider in ('google_street','google_street_nolabel','osm_clean','other'):
            scene=self.photo_scene();summary=self.add(scene,[(0.,0.)],config=params(trees_from_imagery=True,sat_provider=provider))
            self.assertEqual(summary['total'],0);self.assertEqual(summary['source_status'],'no_satellite_image');self.detector.assert_not_called()
        for provider in ('esri_sat','google_sat','google_hybrid'):
            scene=self.photo_scene();self.assertEqual(self.add(scene,[(0.,0.)],config=params(trees_from_imagery=True,sat_provider=provider))['total'],1)

    def test_disabled_is_complete_noop(self):
        scene=self.photo_scene();scene['layers'].append(old_tree_layer());before=deepcopy(scene)
        self.assertFalse(self.add(scene,config=params(include_trees=False))['enabled'])
        self.assertSceneEqual(scene,before);self.detector.assert_not_called();self.fetch.assert_not_called()

    def test_ground_triangle_height_not_bilinear_and_trunks_follow_surface(self):
        scene=self.photo_scene(side=20.,heights=(0.,0.,20.,0.));ground=trees.Ground(scene)
        self.assertAlmostEqual(ground.height(5.,-5.),5.,places=10);self.assertNotAlmostEqual(ground.height(5.,-5.),3.75)
        self.assertIsNone(ground.height(11.,0.))
        self.assertEqual(self.add(scene,[(5.,-5.),(-5.,5.)])['total'],2)
        np.testing.assert_allclose(centers(scene),[[5.,-5.,5.],[-5.,5.,5.]],atol=2e-6)

    def test_affine_uv_and_physical_dimensions_ignore_rotation_and_origin_offset(self):
        angle=math.pi/4;matrix=np.asarray([[math.cos(angle),math.sin(angle)],[-math.sin(angle),math.cos(angle)]])
        scene=self.photo_scene(transform=(matrix,[135.,-220.]),heights=(2.,4.,10.,8.),offset=[900000.,-800000.,5000.])
        ground=trees.Ground(scene);expected=(np.asarray([.2,.3])-.5)*100@matrix+np.asarray([135.,-220.])
        np.testing.assert_allclose(ground.from_uv(.2,.3),expected,atol=1e-10)
        self.assertAlmostEqual(ground.height(*expected),4.2,places=9)
        self.assertEqual(self.add(scene,[tuple(expected)])['total'],1)
        np.testing.assert_allclose(centers(scene)[0],list(expected)+[4.2],atol=2e-5)
        self.assertAlmostEqual(self.detector.call_args.args[1],100.,places=7)
        self.assertAlmostEqual(self.detector.call_args.args[2],100.,places=7)

    def test_roof_road_water_detected_centers_are_rejected(self):
        scene=self.photo_scene()
        for tag,rect in [('MapSKP_02_Buildings',(-40.,-35.,-20.,-15.)),('MapSKP_01_Roads',(-10.,-35.,10.,-15.)),('MapSKP_04_Water',(20.,-35.,40.,-15.))]:
            scene['layers'].append(blocking_layer(tag,rect))
        wanted=[(-30.,25.),(0.,25.),(30.,25.)]
        summary=self.add(scene,[(-30.,-25.),(0.,-25.),(30.,-25.),*wanted])
        self.assertEqual(summary['total'],3);np.testing.assert_allclose(centers(scene)[:,:2],wanted,atol=2e-6)

    def test_non_tree_arrays_uv_material_image_bytes_and_identity_unchanged(self):
        scene=self.photo_scene();scene['layers'].append(blocking_layer('MapSKP_02_Buildings',(20.,20.,30.,30.)))
        old_layers=scene['layers'][:];old_materials=scene['materials'][:];before=deepcopy((old_layers,old_materials))
        self.assertEqual(self.add(scene,[(-10.,-10.)])['total'],1)
        for i,layer in enumerate(old_layers):self.assertIs(scene['layers'][i],layer);self.assertSceneEqual(layer,before[0][i])
        for i,material in enumerate(old_materials):self.assertIs(scene['materials'][i],material);self.assertSceneEqual(material,before[1][i])

    def test_closed_cylinder_and_round_crown_replace_old_diamond_only_with_evidence(self):
        scene=self.photo_scene(heights=(3.,3.,3.,3.));old=old_tree_layer(8.,-9.,3.,7.);scene['layers'].append(old)
        self.assertEqual(self.add(scene,[(8.,-9.)])['total'],1)
        self.assertNotIn(id(old),[id(layer) for layer in scene['layers']]);self.assertEqual(face_count(scene),202)
        np.testing.assert_allclose(centers(scene),[[8.,-9.,3.]],atol=1e-6)
        trunk=trunks(scene)[0];self.assertEqual(len(trunk),18);self.assertGreater(np.ptp(trunk[:,2]),1.)
        crown=next(m for m in scene['layers'][-1]['meshes'] if 'Crown' in scene['materials'][m['mat_idx']]['name'])
        self.assertEqual(len(crown['verts']),86);self.assertEqual(len(crown['faces']),168)
        self.assertAlmostEqual(float(np.ptp(crown['verts'][:,0])),float(np.ptp(crown['verts'][:,2])),places=5)

    def test_repeated_detected_centers_geometry_metadata_and_five_colors_are_deterministic(self):
        points=[(float(x),float(y)) for x in range(-40,41,10) for y in range(-40,41,10)]
        one,two=self.photo_scene(),self.photo_scene()
        self.assertEqual(self.add(one,points),self.add(two,points));self.assertSceneEqual(one,two)
        colors={tuple(one['materials'][m['mat_idx']]['color'][:3]) for m in one['layers'][-1]['meshes'] if 'Crown' in one['materials'][m['mat_idx']]['name']}
        self.assertEqual(colors,set(trees.GREENS))
        np.testing.assert_allclose(centers(one)[:,:2],points,atol=2e-6)
        self.assertEqual(len(one['sitecraft']['detected_tree_locations']),len(points))
        self.assertTrue(all(item['radius_m']==2. and item['confidence']==.91 for item in one['sitecraft']['detected_tree_locations']))

    def test_recognition_level_passed_to_detector_never_replaces_measured_positions(self):
        for level in ('sparse','medium','dense'):
            scene=self.photo_scene();self.assertEqual(self.add(scene,[(7.,11.)],config=params(tree_density=level,trees_from_imagery=True))['total'],1)
            self.assertEqual(self.detector.call_args.kwargs['level'],level)
            np.testing.assert_allclose(centers(scene)[:,:2],[[7.,11.]],atol=2e-6)

    def test_osm_projection_anchor_cannot_move_detected_center(self):
        config=params(anchor={'lat':CENTER['lat']-.04,'lon':CENTER['lon']+.03},trees_from_imagery=False)
        scene=self.photo_scene(offset=[3000.,-4000.,100.]);wanted=[(-15.,8.),(20.,-13.)]
        self.assertEqual(self.add(scene,wanted,config=config,data=features(wanted,config=config))['osm'],2)
        np.testing.assert_allclose(centers(scene)[:,:2],wanted,atol=2e-6)

    def test_hill_patch_cut_low_border_and_outside_detected_centers_rejected(self):
        scene=self.photo_scene(heights=(0.,1.,1.,0.));scene['layers'][0]['meshes'][0]['faces']=np.asarray([[0,1,3]],dtype=np.uint32);scene['origin']['hill_patch']=True
        self.assertEqual(self.add(scene,[(0.,-20.),(30.,30.),(-40.,-40.),(60.,0.)])['total'],1)
        np.testing.assert_allclose(centers(scene),[[0.,-20.,.5]],atol=2e-6)

    def test_900_detected_crown_cap_and_triangle_budget(self):
        points=[(float(x),float(y)) for x in range(-48,49,3) for y in range(-48,49,3)]
        scene=self.photo_scene();summary=self.add(scene,points)
        self.assertEqual(summary['total'],900);self.assertTrue(summary['capped']);self.assertEqual(face_count(scene),180002)
        for count in (579700,600000):
            scene=self.photo_scene();mesh={'verts':np.asarray([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]]),
                'faces':np.tile(np.asarray([[0,1,2]],dtype=np.uint32),(count-2,1)),'uvs':None,'mat_idx':0}
            scene['layers'].append({'tag':'Existing_Detail','meshes':[mesh]});summary=self.add(scene,points[:20])
            self.assertLessEqual(face_count(scene),600000);self.assertTrue(summary['capped'])
            if count==600000:self.assertEqual(summary['total'],0)

    def test_cancellation_before_or_during_placement_preserves_scene(self):
        class CancelAfterChecks:
            def __init__(self):self.calls=0
            def is_set(self):self.calls+=1;return self.calls>=5
        event=threading.Event();event.set()
        for cancel in (event,CancelAfterChecks()):
            scene=self.photo_scene();before=deepcopy(scene)
            with self.assertRaisesRegex(PublicError,'hủy'):self.add(scene,[(-20.,0.),(0.,0.),(20.,0.),(30.,0.)],cancel=cancel)
            self.assertSceneEqual(scene,before)

    def test_unavailable_osm_source_cannot_create_but_does_not_remove_visible_evidence(self):
        scene=self.photo_scene();summary=self.add(scene,[(-12.,13.)],data=features(status='unavailable'))
        self.assertEqual(summary['total'],1);self.assertEqual(summary['inferred'],1)
        self.assertEqual(summary['source_status'],'image_confirmed_crowns');self.assertEqual(summary['osm_status'],'unavailable')
        self.fetch.assert_not_called()
        scene=self.photo_scene();summary=self.add(scene,[(-12.,13.)],data=features(status='unavailable'),config=params(trees_from_imagery=False))
        self.assertEqual(summary['total'],0)

    def test_no_terrain_returns_no_unverified_original_trees(self):
        scene=self.photo_scene();scene['layers']=[old_tree_layer()]
        summary=self.add(scene)
        self.assertEqual(summary['source_status'],'no_terrain');self.assertEqual(summary['total'],0)
        self.assertFalse(any(layer['tag']==trees.TREE_TAG for layer in scene['layers']));self.detector.assert_not_called()

if __name__=='__main__':unittest.main()
