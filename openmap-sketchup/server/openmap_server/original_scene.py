"""Lossless transport adapter for an unchanged original MapSKP scene.

Geometry, UVs and texture bytes are preserved. The implementation here is the
new adapter; original kernel implementations retain their original rights.
"""
from __future__ import annotations
import base64
from hashlib import sha256
import json
import math
from typing import Any

def _json_ready(value: Any):
    if hasattr(value, 'tolist'):
        return _json_ready(value.tolist())
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('Unsupported scene metadata type: ' + type(value).__name__)


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid ' + name)
    return value


def adapt_scene(scene: dict, *, anchor=None, center=None, bbox=None,
                parameters=None, attribution=None) -> dict:
    """Convert the transport schema without changing vertices, faces, UVs or JPGs.

    Original meshes are already Z-up metres. No translation, axis rotation,
    resampling, welding, re-triangulation, UV rewrite, or texture encoding occurs.
    The caller must handle origin.offset_from_anchor_m ONCE at group placement
    when linking original per-tile geometry into an existing anchored model.
    """
    import numpy as np
    if not isinstance(scene, dict):
        raise TypeError('Original scene must be a dictionary')
    origin = _json_ready(scene.get('origin', {}))
    params = _json_ready(parameters or {})
    center = _json_ready(center or {'lat': origin.get('lat'), 'lon': origin.get('lon')})
    _number(center.get('lat'), 'center latitude', -80, 80)
    _number(center.get('lon'), 'center longitude', -180, 180)
    anchor = _json_ready(anchor or {
        'lat': center['lat'], 'lon': center['lon'],
        'elevation': origin.get('elevation_m', 0),
        'terrain_mode': origin.get('terrain_mode', 'terrain_3d'),
    })
    _number(anchor.get('lat'), 'anchor latitude', -80, 80)
    _number(anchor.get('lon'), 'anchor longitude', -180, 180)
    _number(anchor.get('elevation'), 'anchor elevation', -12000, 20000)
    if bbox is None:
        if all(key in origin for key in ('south', 'north', 'west', 'east')):
            bbox = {key: origin[key] for key in ('south', 'north', 'west', 'east')}
        elif isinstance(params.get('bbox'), dict):
            bbox = params['bbox']
        else:
            # Do not infer a new projection from mesh bounds: that would change
            # the original coordinate/data pipeline.
            raise ValueError('Explicit original geographic bbox is required')
    bbox = _json_ready(bbox)
    for key in ('south', 'north'):
        _number(bbox.get(key), 'bbox ' + key, -80, 80)
    for key in ('west', 'east'):
        _number(bbox.get(key), 'bbox ' + key, -180, 180)
    if not bbox['south'] < bbox['north'] or not bbox['west'] < bbox['east']:
        raise ValueError('Inverted original bounding box')

    materials = []
    for index, source in enumerate(scene.get('materials', [])):
        rgba = _json_ready(source.get('color', [210, 210, 210, 255]))
        if not isinstance(rgba, list) or len(rgba) not in (3, 4):
            raise ValueError('Invalid original RGBA material')
        for channel in rgba:
            _number(channel, 'RGBA channel', 0, 255)
        color = rgba[:3]
        if any(int(channel) != channel for channel in color):
            raise ValueError('Current transport requires integer RGB channels')
        ext = str(source.get('ext') or 'jpg').lstrip('.').lower()
        value = {'name': str(source.get('name', 'Material_' + str(index))),
                 'color': [int(channel) for channel in color],
                 'original_rgba': rgba, 'original_material_index': index,
                 'original_texture_ext': ext}
        if len(rgba) == 4:
            value['alpha'] = rgba[3] / 255.0
        texture = source.get('texture_bytes')
        if texture:
            texture = bytes(texture)
            if texture.startswith(b'\xff\xd8'):
                field = 'texture_jpeg'
            elif texture.startswith(b'\x89PNG\r\n\x1a\n'):
                field = 'texture_png'
            else:
                raise ValueError('Original texture must be JPEG or PNG for current transport')
            value[field] = base64.b64encode(texture).decode('ascii')
            value['original_texture_sha256'] = sha256(texture).hexdigest()
        materials.append(value)

    meshes, layers = [], []
    for layer_index, layer in enumerate(scene.get('layers', [])):
        layer_meta = {'layer_index': layer_index,
                      'name': str(layer.get('name', 'Layer')),
                      'tag': str(layer.get('tag', 'MapSKP_Layer')),
                      'tag_color': _json_ready(layer.get('tag_color', [120, 160, 220])),
                      'soften_cos': layer.get('soften_cos', 0.94), 'mesh_indices': []}
        for mesh_index, source in enumerate(layer.get('meshes', [])):
            vertices = np.asarray(source['verts'])
            faces = np.asarray(source['faces'])
            if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
                raise ValueError('Invalid original vertex array')
            if faces.ndim != 2 or faces.shape[1] != 3 or not np.issubdtype(faces.dtype, np.integer):
                raise ValueError('Invalid original triangle array')
            if faces.size and (int(faces.min()) < 0 or int(faces.max()) >= len(vertices)):
                raise ValueError('Original triangle index out of range')
            material_index = source.get('mat_idx')
            if not isinstance(material_index, (int, np.integer)) or not 0 <= int(material_index) < len(materials):
                raise ValueError('Original material index out of range')
            original_uv = source.get('uvs')
            if original_uv is None:
                uvs = []
            else:
                uv_array = np.asarray(original_uv)
                if uv_array.shape != (len(vertices), 2) or not np.isfinite(uv_array).all():
                    raise ValueError('Invalid original UV array; refusing a lossy conversion')
                uvs = uv_array.tolist()
            layer_meta['mesh_indices'].append(len(meshes))
            meshes.append({'name': layer_meta['name'],
                           'vertices': vertices.tolist(), 'triangles': faces.tolist(),
                           'uv': uvs, 'material': int(material_index),
                           # Compatibility with old Ruby AUTO_SOFTEN; retain the
                           # exact threshold for a dedicated original importer.
                           'smooth': True, 'soften_cos': layer_meta['soften_cos'],
                           'layer_index': layer_index, 'layer_name': layer_meta['name'],
                           'tag': layer_meta['tag'], 'tag_color': layer_meta['tag_color'],
                           'original_mesh_index': mesh_index,
                           'original_vertex_dtype': str(vertices.dtype),
                           'original_face_dtype': str(faces.dtype)})
        layers.append(layer_meta)

    result = {'schema': 'openmap.mesh.v1', 'name': str(scene.get('name', 'MapSKP_Context')),
              'anchor': anchor, 'center': center, 'bbox': bbox,
              'hill_patch': bool(origin.get('hill_patch')), 'materials': materials,
              'meshes': meshes, 'parameters': params,
              'attribution': list(attribution or []),
              'warnings': [], 'partial': False, 'missing_layers': [],
              'triangles': sum(len(mesh['triangles']) for mesh in meshes),
              'original_layers': layers, 'original_origin': origin,
              'original_coordinate_frame': 'scene-local-metres-Z-up',
              'original_geometry_preserved': True}
    json.dumps(result, allow_nan=False)
    return result

