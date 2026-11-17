"""Add light architectural trees without changing the recovered map kernel.

All new tree positions come from visible crown candidates in the satellite
image. OSM points may corroborate those candidates but never create positions
without image evidence. No polygon/grid scattering is used.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .net import PublicError
from .tree_geometry import make_round_tree
from .tree_data import fetch_tree_features
from .canopy_detector import detect_canopies

GREENS = ((61, 127, 57), (72, 143, 61), (81, 154, 68), (91, 163, 76), (68, 137, 59))
TRUNK = (116, 86, 56)
TREE_TAG = 'MapSKP_05_Trees'


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise PublicError('Đã hủy tác vụ.')


class Ground:
    """Sample the actual triangle surface; tile offsets are never added here."""
    def __init__(self, scene):
        points, values, uvs = [], [], []
        for layer in scene.get('layers', []):
            if 'Terrain' not in layer.get('tag', ''):
                continue
            for mesh in layer.get('meshes', []):
                uv = mesh.get('uvs')
                vertices = np.asarray(mesh['verts'], dtype=np.float64)
                # The plinth has no UV. Trees belong to the mapped top surface.
                if uv is None or len(uv) != len(vertices):
                    continue
                faces = np.asarray(mesh['faces'], dtype=np.int64)
                points.append(vertices[faces]); values.append(vertices[:, :2]); uvs.append(np.asarray(uv, dtype=np.float64))
        if not points:
            raise ValueError('No mapped terrain surface for trees')
        triangles = np.concatenate(points)
        delta1 = triangles[:, 1, :2] - triangles[:, 0, :2]
        delta2 = triangles[:, 2, :2] - triangles[:, 0, :2]
        denominator = delta1[:, 0] * delta2[:, 1] - delta1[:, 1] * delta2[:, 0]
        valid = np.abs(denominator) > 1e-10
        self.triangles, self.d1, self.d2, self.den = triangles[valid], delta1[valid], delta2[valid], denominator[valid]
        xy = np.concatenate(values)
        uv = np.concatenate(uvs)
        self.fit = np.linalg.lstsq(np.column_stack([uv, np.ones(len(uv))]), xy, rcond=None)[0]
        self.inverse = np.linalg.inv(self.fit[:2])
        self.minimum = xy.min(axis=0); self.maximum = xy.max(axis=0)
        self.extent = np.maximum(self.maximum - self.minimum, 1e-5)
        self.bins = defaultdict(list)
        low = self.triangles[:, :, :2].min(axis=1)
        high = self.triangles[:, :, :2].max(axis=1)
        starts = np.clip(((low-self.minimum)/self.extent*32).astype(int), 0, 31)
        ends = np.clip(((high-self.minimum)/self.extent*32).astype(int), 0, 31)
        for index, (start, end) in enumerate(zip(starts, ends)):
            for ix in range(start[0], end[0]+1):
                for iy in range(start[1], end[1]+1):
                    self.bins[ix, iy].append(index)

    def from_uv(self, u, v):
        return np.asarray([u, v, 1.0]) @ self.fit

    def to_uv(self, xy):
        return (np.asarray(xy) - self.fit[2]) @ self.inverse

    def height(self, x, y):
        position = np.asarray([x, y])
        if np.any(position < self.minimum-1e-5) or np.any(position > self.maximum+1e-5):
            return None
        key = tuple(np.clip(((position-self.minimum)/self.extent*32).astype(int), 0, 31))
        indices = self.bins.get(key)
        if not indices:
            return None
        tri = self.triangles[indices]
        relative = position - tri[:, 0, :2]
        d1, d2, den = self.d1[indices], self.d2[indices], self.den[indices]
        u = (relative[:, 0]*d2[:, 1] - relative[:, 1]*d2[:, 0])/den
        v = (d1[:, 0]*relative[:, 1] - d1[:, 1]*relative[:, 0])/den
        mask = (u >= -1e-6) & (v >= -1e-6) & (u+v <= 1+1e-6)
        if not mask.any():
            return None
        z = tri[:, 0, 2] + u*(tri[:, 1, 2]-tri[:, 0, 2]) + v*(tri[:, 2, 2]-tri[:, 0, 2])
        return float(z[mask].max())


def _pixels(ground, xy, size):
    uv = ground.to_uv(xy)
    return np.column_stack([uv[:, 0]*(size[0]-1), (1-uv[:, 1])*(size[1]-1)])


def _blocked_image(scene, ground, size):
    result = Image.new('L', size, 0)
    draw = ImageDraw.Draw(result)
    for layer in scene.get('layers', []):
        tag = layer.get('tag', '')
        if not any(kind in tag for kind in ('Buildings', 'Roads', 'Water')):
            continue
        for mesh in layer.get('meshes', []):
            vertices = np.asarray(mesh['verts'], dtype=np.float64)
            faces = np.asarray(mesh['faces'], dtype=np.int64)
            pixels = _pixels(ground, vertices[:, :2], size)
            for face in faces:
                polygon = pixels[face]
                first, second = polygon[1]-polygon[0], polygon[2]-polygon[0]
                if abs(first[0]*second[1]-first[1]*second[0]) > 0.01:
                    draw.polygon([tuple(point) for point in polygon], fill=255)
    return result


def _existing_points(scene):
    result = []
    for layer in scene.get('layers', []):
        if layer.get('tag') != TREE_TAG:
            continue
        for mesh in layer.get('meshes', []):
            vertices = np.asarray(mesh['verts'])
            # The frozen recovered kernel emits six vertices per diamond tree.
            if len(vertices) % 6:
                continue
            for tree in vertices.reshape(-1, 6, 3):
                height = float((tree[0, 2]-tree[5, 2])/.72)
                if height > 0 and np.allclose(tree[0, :2], tree[5, :2], atol=.01):
                    result.append((float(tree[0, 0]), float(tree[0, 1]), height))
    return result


def _stable(x, y, salt=0):
    # Fixed integer mixing avoids Python randomized hashes and per-run jitter.
    value = ((int(round(x*10))*73856093) ^ (int(round(y*10))*19349663) ^ salt) & 0xffffffff
    value ^= value >> 16
    return ((value*2246822519) & 0xffffffff)/4294967296.0


def add_simple_trees(scene, params, *, cache_dir, project, cancel=None, feature_data=None, allow_network=True):
    """Place trees only at image-detected crown centers before all writers.

    OSM points corroborate visible crowns; mapped green areas do not seed trees.
    Original non-tree arrays/UVs/textures remain untouched. Changes scene lists
    and origin metadata in place. Trees disabled is a no-op.
    """
    enabled = bool(params.get('include_trees', False))
    summary = {'enabled': enabled, 'total': 0, 'osm': 0, 'inferred': 0, 'capped': False,
               'source_status': 'disabled' if not enabled else 'no_visible_crowns',
               'placement': 'detected_crown_centers', 'random_scattering': False,
               'detector': 'outline_texture_multiscale_v1', 'triangles': 0}
    if not enabled:
        return summary
    _check(cancel)
    old_layers = [layer for layer in scene.get('layers', []) if layer.get('tag') != TREE_TAG]
    origin = scene.setdefault('origin', {})

    def finish():
        scene['layers'] = old_layers
        origin['sitecraft_trees'] = summary
        return summary

    try:
        ground = Ground(scene)
    except (ValueError, np.linalg.LinAlgError):
        summary['source_status'] = 'no_terrain'
        return finish()
    provider = params.get('sat_provider', 'esri_sat')
    texture = None
    for layer in old_layers:
        if 'Terrain' in layer.get('tag', '') and layer.get('meshes'):
            texture = scene['materials'][layer['meshes'][0]['mat_idx']].get('texture_bytes')
            break
    if not texture or provider not in ('esri_sat', 'google_sat', 'google_hybrid'):
        summary['source_status'] = 'no_satellite_image'
        return finish()
    try:
        with Image.open(BytesIO(texture)) as raw:
            image = raw.convert('RGB')
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        summary['source_status'] = 'invalid_satellite_image'
        return finish()
    density = params.get('tree_density', 'medium')
    blocked = np.asarray(_blocked_image(scene, ground, image.size)) > 0
    physical_width = float(np.linalg.norm(ground.fit[0]))
    physical_height = float(np.linalg.norm(ground.fit[1]))
    crowns = detect_canopies(image, physical_width, physical_height, level=density, cancel=cancel)
    summary['detected_candidates'] = len(crowns)
    summary['recognition_level'] = density
    if not crowns:
        return finish()
    bbox = {key: params[key] for key in ('south', 'west', 'north', 'east')}
    if feature_data is None:
        feature_data = fetch_tree_features(bbox, cache_dir, cancel) if allow_network else {'points': [], 'areas': [], 'status': 'fixture'}
    summary['osm_status'] = feature_data.get('status', 'unknown')
    _check(cancel)
    anchor = params.get('anchor') or {'lat': params['lat'], 'lon': params['lon']}
    center_x, center_y = project(params['lat'], params['lon'], anchor['lat'], anchor['lon'])
    legacy_points = _existing_points(scene)
    known = []
    for point in feature_data.get('points', []):
        x, y = project(point['lat'], point['lon'], anchor['lat'], anchor['lon'])
        known.append((float(x-center_x), float(y-center_y), point.get('height', 5.5)))
    known.extend(legacy_points)
    unique, duplicate_bins = [], defaultdict(list)
    for point in known:
        cell = (math.floor(point[0]), math.floor(point[1]))
        if any((point[0]-old[0])**2+(point[1]-old[1])**2 < .25
               for ix in range(cell[0]-1,cell[0]+2) for iy in range(cell[1]-1,cell[1]+2)
               for old in duplicate_bins[ix,iy]):
            continue
        duplicate_bins[cell].append(point)
        unique.append(point)
    known = unique
    triangle_count = sum(len(mesh['faces']) for layer in old_layers for mesh in layer.get('meshes', []))
    maximum = min(900, max(0, (580000-triangle_count)//200))
    selected = []
    locations = []
    valid_crowns = []
    for crown in crowns:
        _check(cancel)
        x, y = ground.from_uv(crown['u'], crown['v'])
        px = min(image.width-1, max(0, int(crown['u']*(image.width-1))))
        py = min(image.height-1, max(0, int((1-crown['v'])*(image.height-1))))
        if blocked[py, px]:
            continue
        z = ground.height(x, y)
        if z is None or (origin.get('hill_patch') and z < .35):
            continue
        radius = float(crown['radius_m'])
        valid_crowns.append((crown, float(x), float(y), z, radius))
    # A mapped point corroborates only its closest visible crown. It never
    # creates another tree or marks several adjacent image peaks as mapped.
    known_bins = defaultdict(list)
    for index, (x,y,height) in enumerate(known):
        known_bins[math.floor(x/10), math.floor(y/10)].append(index)
    closest = {}
    for index, (_crown,x,y,_z,radius) in enumerate(valid_crowns):
        cell = (math.floor(x/10), math.floor(y/10))
        for ix in range(cell[0]-1,cell[0]+2):
            for iy in range(cell[1]-1,cell[1]+2):
                for node in known_bins[ix,iy]:
                    distance = math.hypot(x-known[node][0],y-known[node][1])
                    if distance <= max(1.5,radius*.8) and distance < closest.get(node,(float('inf'),None))[0]:
                        closest[node] = (distance,index)
    matches = {}
    for node, (distance,index) in closest.items():
        if distance < matches.get(index,(float('inf'),None))[0]:
            matches[index] = (distance,node)
    for index, (crown,x,y,z,radius) in enumerate(valid_crowns):
        mapped = index in matches
        if not params.get('trees_from_imagery', True) and not mapped:
            continue
        if len(selected) >= maximum:
            summary['capped'] = True
            break
        mapped_height = float(known[matches[index][1]][2]) if mapped else 0
        height = max(2*radius+.7, min(22.0, mapped_height if mapped else max(4.5, radius*2.7)))
        selected.append((float(x),float(y),z,height,radius,'osm' if mapped else 'image'))
        locations.append({'x_m':round(float(x),4), 'y_m':round(float(y),4), 'ground_z_m':round(z,4),
                          'image_u':crown['u'], 'image_v':crown['v'], 'radius_m':radius,
                          'confidence':crown['confidence'], 'method':crown['method'], 'osm_match':mapped})
    summary.update(total=len(selected), osm=sum(tree[5]=='osm' for tree in selected),
                   inferred=sum(tree[5]=='image' for tree in selected), triangles=len(selected)*200,
                   source_status='image_confirmed_crowns' if selected else 'no_confirmed_crowns',
                   image_confirmed=True)
    if not selected:
        return finish()
    material_offset = len(scene['materials'])
    scene['materials'].extend([{'name':'SiteCraft_Tree_Trunk', 'color':list(TRUNK)+[255], 'texture_bytes':None, 'ext':'jpg'}]
        + [{'name':'SiteCraft_Tree_Crown_%d'%index, 'color':list(color)+[255], 'texture_bytes':None, 'ext':'jpg'} for index,color in enumerate(GREENS)])
    parts = defaultdict(list)
    for x,y,z,height,radius,source in selected:
        tree = make_round_tree(x,y,z,height_m=height,radius_m=radius)
        parts[material_offset].append(tree['trunk'])
        color = min(len(GREENS)-1, int(_stable(x,y,167)*len(GREENS)))
        parts[material_offset+1+color].append(tree['crown'])
    meshes = []
    for material_index, group in sorted(parts.items()):
        vertices, faces, offset = [], [], 0
        for mesh in group:
            vertices.append(mesh['verts']); faces.append(mesh['faces']+offset); offset += len(mesh['verts'])
        meshes.append({'mat_idx':material_index, 'verts':np.concatenate(vertices), 'faces':np.concatenate(faces), 'uvs':None})
    scene['layers'] = old_layers+[{'name':'SiteCraft_Trees (%d)'%len(selected), 'tag':TREE_TAG, 'tag_color':[75,148,64], 'soften_cos':.65, 'meshes':meshes}]
    origin['sitecraft_trees'] = summary
    scene.setdefault('sitecraft', {})['detected_tree_locations'] = locations
    return summary
