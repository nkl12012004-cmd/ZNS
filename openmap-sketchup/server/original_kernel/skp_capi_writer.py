"""Readable reconstruction of the user-provided original MapSKP writer.

Functions below are reconstructed from the recovered original bytecode and
validated against its output. Original rights apply; this is not an MIT relicense.
All 14 original functions are represented as editable Python. Portable exports
are byte-exact in local oracle checks; native SDK call traces also match through
the save boundary. Actual SKP file validation requires Windows + SketchUpAPI.dll.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Dict
import numpy as np


def write_obj_bundle(scene: Dict[str, Any], out_obj_path: Path) -> Dict[str, Any]:
    t0 = time.perf_counter()
    out_obj_path.parent.mkdir(parents=True, exist_ok=True)
    stem = out_obj_path.stem
    mtl_path = out_obj_path.with_suffix('.mtl')
    maps_dir_name = f'{stem}_maps'
    maps_dir = out_obj_path.parent / maps_dir_name
    mtl_lines = [f'# MapSKP Hybrid v1.0.0 — Materials for {stem}']
    mat_names = []
    for idx, m in enumerate(scene.get('materials', [])):
        clean_m = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in str(m.get('name') or f'mat_{idx}'))
        mname = f'{clean_m}_{idx}'
        mat_names.append(mname)
        rgba = m.get('color') or [210, 210, 210, 255]
        kd_r, kd_g, kd_b = rgba[0] / 255.0, rgba[1] / 255.0, rgba[2] / 255.0
        alpha = rgba[3] / 255.0 if len(rgba) > 3 else 1.0
        tb = m.get('texture_bytes')
        if tb:
            maps_dir.mkdir(parents=True, exist_ok=True)
            ext = str(m.get('ext') or 'jpg').lstrip('.')
            tex_name = f'tex_{idx}.{ext}'
            (maps_dir / tex_name).write_bytes(tb)
            kd_r = kd_g = kd_b = 1.0
            tex_rel = f'{maps_dir_name}/{tex_name}'
        else:
            tex_rel = ''
        mtl_lines.extend([f'newmtl {mname}', 'Ka 0.0000 0.0000 0.0000',
                          f'Kd {kd_r:.4f} {kd_g:.4f} {kd_b:.4f}',
                          'Ks 0.0000 0.0000 0.0000', f'd {alpha:.3f}', 'illum 1'])
        if tex_rel:
            mtl_lines.append(f'map_Kd {tex_rel}')
        mtl_lines.append('')
    mtl_path.write_text('\n'.join(mtl_lines), encoding='utf-8')
    obj_chunks = ['# MapSKP Hybrid v1.0.0 — 1 unit = 1 meter, Y-Up (3ds Max / Blender / D5 / Lumion)', f'mtllib {mtl_path.name}', '']
    v_offset = 1
    vt_offset = 1
    total_tris = 0
    for ly in scene.get('layers', []):
        obj_name = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in str(ly.get('tag') or 'Layer'))
        obj_chunks.append(f'o {obj_name}')
        for ms in ly.get('meshes', []):
            verts = np.asarray(ms['verts'], dtype=np.float64)
            faces = np.asarray(ms['faces'], dtype=np.uint32)
            uvs = ms.get('uvs')
            if len(verts) == 0 or len(faces) == 0:
                continue
            mat_idx = int(ms.get('mat_idx', -1))
            if 0 <= mat_idx < len(mat_names):
                obj_chunks.append(f'usemtl {mat_names[mat_idx]}')
            for vx, vy, vz in verts.tolist():
                obj_chunks.append(f'v {vx:.4f} {vz:.4f} {-vy:.4f}')
            has_uv = uvs is not None and len(uvs) == len(verts)
            if has_uv:
                for u, v in uvs.tolist():
                    obj_chunks.append(f'vt {u:.5f} {v:.5f}')
                for a, b, c in faces.tolist():
                    va, vb_i, vc = a + v_offset, b + v_offset, c + v_offset
                    ta, tb_i, tc = a + vt_offset, b + vt_offset, c + vt_offset
                    obj_chunks.append(f'f {va}/{ta} {vb_i}/{tb_i} {vc}/{tc}')
                vt_offset += len(uvs)
            else:
                for a, b, c in faces.tolist():
                    obj_chunks.append(f'f {a + v_offset} {b + v_offset} {c + v_offset}')
            v_offset += len(verts)
            total_tris += len(faces)
    out_obj_path.write_text('\n'.join(obj_chunks) + '\n', encoding='utf-8')
    return {'ok': True, 'path': str(out_obj_path), 'mtl_path': str(mtl_path),
            'size_kb': round(out_obj_path.stat().st_size / 1024.0, 1),
            'triangles': total_tris, 'elapsed_sec': round(time.perf_counter() - t0, 3)}


def _srgb_to_linear(c255: float) -> float:
    x = max(0.0, min(1.0, c255 / 255.0))
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def write_ruby_fallback_json(scene: Dict[str, Any], out_json_path: Path, tex_dir: Path) -> Path:
    tex_dir.mkdir(parents=True, exist_ok=True)
    mats_out = []
    for idx, m in enumerate(scene.get('materials', [])):
        tex_path_str = ''
        tb = m.get('texture_bytes')
        if tb:
            ext = str(m.get('ext') or 'jpg').lstrip('.')
            tp = tex_dir / f'rb_tex_{idx}.{ext}'
            tp.write_bytes(tb)
            tex_path_str = tp.as_posix()
        mats_out.append({'name': m.get('name', f'Mat_{idx}'),
                         'color': list(m.get('color', [210, 210, 210, 255])), 'tex_path': tex_path_str})
    layers_out = []
    for ly in scene.get('layers', []):
        ms_out = []
        for ms in ly.get('meshes', []):
            v = np.round(np.asarray(ms['verts'], dtype=np.float64), 3).tolist()
            f = np.asarray(ms['faces'], dtype=np.uint32).tolist()
            uv_raw = ms.get('uvs')
            uv_list = np.round(np.asarray(uv_raw, dtype=np.float64), 5).tolist() if uv_raw is not None and len(uv_raw) == len(v) else []
            ms_out.append({'mat_idx': int(ms.get('mat_idx', -1)), 'verts_m': v, 'faces': f, 'uvs': uv_list})
        layers_out.append({'name': ly.get('name', 'Layer'), 'tag': ly.get('tag', 'MapSKP_Layer'),
                           'tag_color': list(ly.get('tag_color', [120, 160, 220])), 'meshes': ms_out})
    payload = {'ok': True, 'native_skp_ready': True, 'name': scene.get('name', 'MapSKP_Context'),
               'origin': scene.get('origin', {}), 'materials': mats_out, 'layers': layers_out}
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return out_json_path


def compute_soft_edges(verts, faces, cos_threshold=0.94):
    if len(faces) < 2 or cos_threshold >= 0.9999:
        return set()
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    normals = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    valid = norms[:, 0] > 1e-10
    normals[valid] /= norms[valid]
    edge_map = {}
    soft_edges = set()
    faces_list = faces.tolist()
    valid_list = valid.tolist()
    for fi, (a, b, c) in enumerate(faces_list):
        if not valid_list[fi]:
            continue
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            prev_fi = edge_map.get(key)
            if prev_fi is None:
                edge_map[key] = fi
            elif prev_fi >= 0:
                dot = float(normals[prev_fi, 0] * normals[fi, 0] +
                            normals[prev_fi, 1] * normals[fi, 1] +
                            normals[prev_fi, 2] * normals[fi, 2])
                if dot >= cos_threshold:
                    soft_edges.add(key)
                edge_map[key] = -1
    return soft_edges


# Original SketchUp C API ABI declarations. No replacement/fake SDK is used.
import ctypes as C

class _SURef(C.Structure):
    _fields_ = [('ptr', C.c_void_p)]

class _SUPoint3D(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double), ('z', C.c_double)]

class _SUPoint2D(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]

class _SUColor(C.Structure):
    _fields_ = [('r', C.c_ubyte), ('g', C.c_ubyte), ('b', C.c_ubyte), ('a', C.c_ubyte)]

class _SUMaterialInput(C.Structure):
    _fields_ = [('num_uv_coords', C.c_size_t), ('uv_coords', _SUPoint2D * 4),
                ('vertex_indices', C.c_size_t * 4), ('material', _SURef)]


import struct

def write_glb_binary(scene: Dict[str, Any], out_glb_path: Path) -> Dict[str, Any]:
    t0 = time.perf_counter()
    bin_parts = []
    cur_off = 0
    buffer_views = []
    accessors = []
    images = []
    textures = []
    materials = []
    meshes = []
    nodes = []

    def push_bv(raw: bytes, target=None) -> int:
        nonlocal cur_off
        pad = (-len(raw)) % 4
        padded = raw + b'\x00' * pad if pad else raw
        bv_obj = {'buffer': 0, 'byteOffset': cur_off, 'byteLength': len(raw)}
        if target is not None:
            bv_obj['target'] = target
        idx = len(buffer_views)
        buffer_views.append(bv_obj)
        bin_parts.append(padded)
        cur_off += len(padded)
        return idx

    for m in scene.get('materials', []):
        rgba = m.get('color') or [210, 210, 210, 255]
        alpha = rgba[3] / 255.0 if len(rgba) > 3 else 1.0
        pbr = {'metallicFactor': 0.05, 'roughnessFactor': 0.88}
        tb = m.get('texture_bytes')
        if tb:
            ext = str(m.get('ext') or 'jpg').lower().lstrip('.')
            mime = 'image/png' if ext == 'png' else 'image/jpeg'
            img_bv = push_bv(bytes(tb))
            img_idx = len(images)
            images.append({'bufferView': img_bv, 'mimeType': mime})
            tex_idx = len(textures)
            textures.append({'sampler': 0, 'source': img_idx})
            pbr['baseColorTexture'] = {'index': tex_idx}
            pbr['baseColorFactor'] = [1.0, 1.0, 1.0, alpha]
        else:
            pbr['baseColorFactor'] = [round(_srgb_to_linear(rgba[0]), 5), round(_srgb_to_linear(rgba[1]), 5),
                                      round(_srgb_to_linear(rgba[2]), 5), round(alpha, 4)]
        mat_obj = {'name': str(m.get('name') or 'Mat'), 'pbrMetallicRoughness': pbr, 'doubleSided': True}
        if alpha < 0.995:
            mat_obj['alphaMode'] = 'BLEND'
        materials.append(mat_obj)
    if not materials:
        materials.append({'name': 'Default', 'pbrMetallicRoughness': {'baseColorFactor': [0.8,0.8,0.8,1.0],
                          'metallicFactor': 0.0, 'roughnessFactor': 0.9}, 'doubleSided': True})
    child_node_indices = []
    total_tris = 0
    for ly in scene.get('layers', []):
        primitives = []
        for ms in ly.get('meshes', []):
            verts_enu = np.asarray(ms['verts'], dtype=np.float32)
            faces = np.asarray(ms['faces'], dtype=np.uint32)
            uvs = ms.get('uvs')
            if len(verts_enu) < 3 or len(faces) == 0:
                continue
            pos = np.empty_like(verts_enu, dtype='<f4')
            pos[:,0] = verts_enu[:,0]
            pos[:,1] = verts_enu[:,2]
            pos[:,2] = -verts_enu[:,1]
            nrm = np.zeros_like(pos, dtype='<f4')
            p0 = pos[faces[:,0]]
            p1 = pos[faces[:,1]]
            p2 = pos[faces[:,2]]
            fn = np.cross(p1-p0, p2-p0)
            np.add.at(nrm, faces[:,0], fn)
            np.add.at(nrm, faces[:,1], fn)
            np.add.at(nrm, faces[:,2], fn)
            nl = np.linalg.norm(nrm, axis=1, keepdims=True)
            valid_n = nl[:,0] > 1e-9
            nrm[valid_n] /= nl[valid_n]
            nrm[~valid_n] = np.array([0.0,1.0,0.0], dtype='<f4')
            pos_bv = push_bv(pos.tobytes(),34962)
            pos_acc = len(accessors)
            accessors.append({'bufferView': pos_bv, 'componentType': 5126, 'count': int(len(pos)), 'type': 'VEC3',
                              'min': [float(x) for x in pos.min(axis=0)], 'max': [float(x) for x in pos.max(axis=0)]})
            nrm_bv = push_bv(nrm.tobytes(),34962)
            nrm_acc = len(accessors)
            accessors.append({'bufferView': nrm_bv, 'componentType': 5126, 'count': int(len(nrm)), 'type': 'VEC3'})
            attrs = {'POSITION': pos_acc, 'NORMAL': nrm_acc}
            if uvs is not None and len(uvs) == len(pos):
                uv_gl = np.empty_like(uvs, dtype='<f4')
                uv_gl[:,0] = uvs[:,0]
                uv_gl[:,1] = 1.0-uvs[:,1]
                uv_bv = push_bv(uv_gl.tobytes(),34962)
                uv_acc = len(accessors)
                accessors.append({'bufferView': uv_bv, 'componentType': 5126, 'count': int(len(uv_gl)), 'type': 'VEC2'})
                attrs['TEXCOORD_0'] = uv_acc
            idx_arr = np.ascontiguousarray(faces.reshape(-1),dtype='<u4')
            idx_bv = push_bv(idx_arr.tobytes(),34963)
            idx_acc = len(accessors)
            accessors.append({'bufferView': idx_bv, 'componentType': 5125, 'count': int(len(idx_arr)), 'type': 'SCALAR'})
            mat_idx = int(ms.get('mat_idx',0))
            if not 0 <= mat_idx < len(materials):
                mat_idx = 0
            primitives.append({'attributes': attrs, 'indices': idx_acc, 'material': mat_idx})
            total_tris += len(faces)
        if not primitives:
            continue
        mesh_idx = len(meshes)
        tag_label = str(ly.get('tag') or 'MapSKP_Layer')
        meshes.append({'name': tag_label, 'primitives': primitives})
        node_idx = len(nodes)
        nodes.append({'name': tag_label, 'mesh': mesh_idx})
        child_node_indices.append(node_idx)
    root_node_idx = len(nodes)
    nodes.append({'name': str(scene.get('name') or 'MapSKP_Root'), 'children': child_node_indices})
    gltf_doc = {'asset': {'version': '2.0', 'generator': 'HiepAI MapSKP Hybrid v1.0.0'}, 'scene': 0,
                'scenes': [{'name': 'Scene', 'nodes': [root_node_idx]}], 'nodes': nodes, 'meshes': meshes,
                'materials': materials, 'accessors': accessors, 'bufferViews': buffer_views,
                'buffers': [{'byteLength': cur_off}]}
    if textures:
        gltf_doc['textures'] = textures
        gltf_doc['images'] = images
        gltf_doc['samplers'] = [{'wrapS':10497,'wrapT':10497,'minFilter':9987,'magFilter':9729}]
    json_bytes = json.dumps(gltf_doc,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    json_pad = (-len(json_bytes)) % 4
    json_chunk = json_bytes+b' '*json_pad
    bin_chunk = b''.join(bin_parts)
    total_len = 20+len(json_chunk)+8+len(bin_chunk)
    out_glb_path.parent.mkdir(parents=True,exist_ok=True)
    with open(out_glb_path,'wb') as f:
        f.write(struct.pack('<III',1179937895,2,total_len))
        f.write(struct.pack('<II',len(json_chunk),1313821514))
        f.write(json_chunk)
        f.write(struct.pack('<II',len(bin_chunk),5130562))
        f.write(bin_chunk)
    return {'ok':True,'path':str(out_glb_path),'size_kb':round(out_glb_path.stat().st_size/1024.0,1),
            'triangles':total_tris,'elapsed_sec':round(time.perf_counter()-t0,3)}


import base64
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import List, Optional, Tuple
from geo_math import INCH_PER_METER

MAGIC_MAPSKP1 = b'MAPSKP1\x00'
_SKP_DLL_LOCK = threading.Lock()


def pack_scene_to_mapskp1(scene: Dict[str, Any]) -> bytes:
    blobs = []
    cur_off = 0
    def add_blob(raw: bytes) -> Tuple[int, int]:
        nonlocal cur_off
        pad = -len(raw) % 4
        chunk = raw + b'\x00' * pad if pad else raw
        off = cur_off
        blobs.append(chunk)
        cur_off += len(chunk)
        return off, len(raw)
    hdr_mats = []
    for m in scene.get('materials', []):
        tb = m.get('texture_bytes')
        tex_meta = None
        if tb:
            off, ln = add_blob(bytes(tb))
            tex_meta = {'off': off, 'len': ln, 'ext': m.get('ext', 'jpg')}
        hdr_mats.append({'name': m.get('name', 'Material'),
                         'color': list(m.get('color', [210, 210, 210, 255])), 'tex': tex_meta})
    hdr_layers = []
    for ly in scene.get('layers', []):
        hdr_meshes = []
        for ms in ly.get('meshes', []):
            v_arr = np.ascontiguousarray(ms['verts'], dtype='<f4')
            f_arr = np.ascontiguousarray(ms['faces'], dtype='<u4')
            if v_arr.size == 0 or f_arr.size == 0:
                continue
            v_off, v_len = add_blob(v_arr.tobytes())
            f_off, f_len = add_blob(f_arr.tobytes())
            uv_meta = None
            if ms.get('uvs') is not None:
                u_arr = np.ascontiguousarray(ms['uvs'], dtype='<f4')
                u_off, u_len = add_blob(u_arr.tobytes())
                uv_meta = {'off': u_off, 'len': u_len}
            hdr_meshes.append({'mat_idx': int(ms.get('mat_idx', -1)), 'nv': int(v_arr.shape[0]),
                               'nf': int(f_arr.shape[0]), 'v': {'off': v_off, 'len': v_len},
                               'f': {'off': f_off, 'len': f_len}, 'uv': uv_meta})
        if hdr_meshes:
            hdr_layers.append({'name': ly.get('name', 'Layer'), 'tag': ly.get('tag', 'MapSKP_Layer'),
                               'tag_color': list(ly.get('tag_color', [120, 160, 220])),
                               'soften_cos': float(ly.get('soften_cos', 0.94)), 'meshes': hdr_meshes})
    header_obj = {'version': 1, 'name': scene.get('name', 'MapSKP_Context'),
                  'origin': scene.get('origin', {}), 'materials': hdr_mats, 'layers': hdr_layers}
    hdr_bytes = json.dumps(header_obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    hdr_pad = -len(hdr_bytes) % 4
    hdr_padded = hdr_bytes + b' ' * hdr_pad
    return MAGIC_MAPSKP1 + struct.pack('<I', len(hdr_padded)) + hdr_padded + b''.join(blobs)


def unpack_mapskp1_to_scene(raw_pkg: bytes) -> Dict[str, Any]:
    if len(raw_pkg) < 12 or raw_pkg[:8] != MAGIC_MAPSKP1:
        raise ValueError('Gói nhị phân không đúng chuẩn MAPSKP1')
    hdr_len = struct.unpack_from('<I', raw_pkg, 8)[0]
    hdr = json.loads(raw_pkg[12:12 + hdr_len].decode('utf-8'))
    bin_base = 12 + hdr_len
    mv = memoryview(raw_pkg)
    mats = []
    for m in hdr.get('materials', []):
        tx = m.get('tex')
        tb = bytes(mv[bin_base + tx['off']:bin_base + tx['off'] + tx['len']]) if tx else None
        mats.append({'name': m.get('name', 'Material'), 'color': m.get('color', [210, 210, 210, 255]),
                     'texture_bytes': tb, 'ext': tx.get('ext', 'jpg') if tx else 'jpg'})
    layers = []
    for ly in hdr.get('layers', []):
        meshes = []
        for ms in ly.get('meshes', []):
            vb = mv[bin_base + ms['v']['off']:bin_base + ms['v']['off'] + ms['v']['len']]
            fb = mv[bin_base + ms['f']['off']:bin_base + ms['f']['off'] + ms['f']['len']]
            verts = np.frombuffer(vb, dtype='<f4').reshape((ms['nv'], 3)).copy()
            faces = np.frombuffer(fb, dtype='<u4').reshape((ms['nf'], 3)).copy()
            uvs = None
            if ms.get('uv'):
                ub = mv[bin_base + ms['uv']['off']:bin_base + ms['uv']['off'] + ms['uv']['len']]
                uvs = np.frombuffer(ub, dtype='<f4').reshape((ms['nv'], 2)).copy()
            meshes.append({'mat_idx': int(ms.get('mat_idx', -1)), 'verts': verts, 'faces': faces, 'uvs': uvs})
        layers.append({'name': ly.get('name', 'Layer'), 'tag': ly.get('tag', 'MapSKP_Layer'),
                       'tag_color': ly.get('tag_color', [120, 160, 220]),
                       'soften_cos': float(ly.get('soften_cos', 0.94)), 'meshes': meshes})
    return {'name': hdr.get('name', 'MapSKP_Context'), 'origin': hdr.get('origin', {}),
            'materials': mats, 'layers': layers}


def _ascii_stage_root() -> Path:
    sys_tmp = Path(tempfile.gettempdir())
    if str(sys_tmp).isascii():
        return sys_tmp
    pub_dir = Path(os.environ.get('PUBLIC') or 'C:\\Users\\Public') / 'HiepAI_MapSKP_Stage'
    try:
        pub_dir.mkdir(parents=True, exist_ok=True)
        if str(pub_dir).isascii():
            return pub_dir
    except Exception:
        pass
    return sys_tmp


def _normalize_su_year(raw_year: Optional[str]) -> Optional[str]:
    if not raw_year:
        return None
    s = str(raw_year).strip()
    m4 = re.search('\\b(20(?:1[7-9]|2[0-9]))\\b', s)
    if m4:
        return m4.group(1)
    m2 = re.match('^(1[7-9]|2[0-9])(?:\\.|$)', s)
    if m2:
        return '20' + m2.group(1)
    return None


def find_sketchup_api_dll(preferred_year: Optional[str] = None,
                          su_exe_dir: Optional[str] = None) -> Optional[Path]:
    norm_year = _normalize_su_year(preferred_year)
    candidates = []
    for hint_dir in (su_exe_dir, os.environ.get('MAPSKP_SU_EXE_DIR')):
        if hint_dir:
            hd = Path(str(hint_dir).strip().strip('"'))
            for p_cand in (hd / 'SketchUpAPI.dll', hd / 'SketchUp' / 'SketchUpAPI.dll', hd.parent / 'SketchUpAPI.dll'):
                if p_cand.is_file():
                    candidates.append(p_cand)
    for env_key in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
        pf = os.environ.get(env_key)
        if not pf:
            continue
        if norm_year:
            for sub in (Path(pf) / 'SketchUp' / f'SketchUp {norm_year}' / 'SketchUpAPI.dll',
                        Path(pf) / 'SketchUp' / f'SketchUp {norm_year}' / 'SketchUp' / 'SketchUpAPI.dll'):
                if sub.is_file():
                    candidates.append(sub)
        found = sorted(glob.glob(os.path.join(pf, 'SketchUp', 'SketchUp 20*', 'SketchUpAPI.dll')), reverse=True)
        candidates.extend(Path(p) for p in found)
        found_sub = sorted(glob.glob(os.path.join(pf, 'SketchUp', 'SketchUp 20*', 'SketchUp', 'SketchUpAPI.dll')), reverse=True)
        candidates.extend(Path(p) for p in found_sub)
    for drv in ('C:\\', 'D:\\', 'E:\\', 'F:\\'):
        if os.path.isdir(drv):
            if norm_year:
                for custom_pref in (Path(drv) / f'SketchUp {norm_year}' / 'SketchUpAPI.dll',
                                    Path(drv) / 'SketchUp' / f'SketchUp {norm_year}' / 'SketchUpAPI.dll',
                                    Path(drv) / 'Program Files' / 'SketchUp' / f'SketchUp {norm_year}' / 'SketchUpAPI.dll'):
                    if custom_pref.is_file():
                        candidates.append(custom_pref)
            for pat in ('SketchUp 20*', 'SketchUp/SketchUp 20*', 'Soft/SketchUp 20*', 'Program Files/SketchUp/SketchUp 20*'):
                found_d = sorted(glob.glob(os.path.join(drv, pat, 'SketchUpAPI.dll')), reverse=True)
                candidates.extend(Path(p) for p in found_d)
    for c in candidates:
        if c.is_file():
            return c
    return None


def run_skp_worker_cli(worker_args: List[str]) -> int:
    clean_args = list(worker_args)
    while clean_args and str(clean_args[0]).startswith('--worker-skp'):
        clean_args.pop(0)
    if len(clean_args) < 4:
        return 1
    pkg_p, out_p, res_p, dll_p = (Path(clean_args[i]) for i in range(4))
    try:
        sc = unpack_mapskp1_to_scene(pkg_p.read_bytes())
        res = _write_skp_in_process(sc, out_p, dll_p)
    except Exception as e:
        res = {'ok': False, 'error': str(e)}
    res_p.parent.mkdir(parents=True, exist_ok=True)
    res_p.write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
    return 0 if res.get('ok') else 1


def _resolve_skp_worker_script() -> Path:
    try:
        import mapskp_armor as _armor
        if hasattr(_armor, 'get_bridge_dir'):
            bd = str(_armor.get_bridge_dir() or '').strip()
            if bd:
                stub_py = Path(bd).resolve() / 'map_bridge_server.py'
                if stub_py.is_file():
                    return stub_py
    except Exception:
        pass
    self_path = Path(__file__).resolve()
    if self_path.is_file():
        return self_path
    return Path.cwd() / 'map_bridge_server.py'


def _write_skp_in_process(scene: Dict[str, Any], out_skp: Path, dll_path: Path) -> Dict[str, Any]:
    """Write using the actual installed SketchUp C API, as the original does."""
    t0 = time.perf_counter()
    dll_dir = str(dll_path.resolve().parent)
    dll_dir_handle = None
    if hasattr(os, 'add_dll_directory') and os.path.isdir(dll_dir):
        try:
            dll_dir_handle = os.add_dll_directory(dll_dir)
        except Exception:
            dll_dir_handle = None
    cur_path = os.environ.get('PATH', '')
    if dll_dir and dll_dir.lower() not in cur_path.lower():
        os.environ['PATH'] = f'{dll_dir};{cur_path}'
    dll = C.CDLL(str(dll_path))
    dll.SUInitialize.argtypes = []
    dll.SUInitialize.restype = None
    dll.SUTerminate.argtypes = []
    dll.SUTerminate.restype = None
    dll.SUModelCreate.argtypes = [C.POINTER(_SURef)]
    dll.SUModelRelease.argtypes = [C.POINTER(_SURef)]
    dll.SUModelGetEntities.argtypes = [_SURef, C.POINTER(_SURef)]
    dll.SUModelAddMaterials.argtypes = [_SURef, C.c_size_t, C.POINTER(_SURef)]
    dll.SUModelAddLayers.argtypes = [_SURef, C.c_size_t, C.POINTER(_SURef)]
    dll.SUModelSaveToFile.argtypes = [_SURef, C.c_char_p]
    dll.SUModelSaveToFileWithVersion.argtypes = [_SURef, C.c_char_p, C.c_int]
    dll.SULayerCreate.argtypes = [C.POINTER(_SURef)]
    dll.SULayerSetName.argtypes = [_SURef, C.c_char_p]
    dll.SULayerGetMaterial.argtypes = [_SURef, C.POINTER(_SURef)]
    dll.SUGroupCreate.argtypes = [C.POINTER(_SURef)]
    dll.SUGroupSetName.argtypes = [_SURef, C.c_char_p]
    dll.SUGroupGetEntities.argtypes = [_SURef, C.POINTER(_SURef)]
    dll.SUEntitiesAddGroup.argtypes = [_SURef, _SURef]
    dll.SUGroupToDrawingElement.argtypes = [_SURef]
    dll.SUGroupToDrawingElement.restype = _SURef
    dll.SUDrawingElementSetLayer.argtypes = [_SURef, _SURef]
    dll.SUDrawingElementSetHidden.argtypes = [_SURef, C.c_bool]
    dll.SUMaterialCreate.argtypes = [C.POINTER(_SURef)]
    dll.SUMaterialSetName.argtypes = [_SURef, C.c_char_p]
    dll.SUMaterialSetColor.argtypes = [_SURef, C.POINTER(_SUColor)]
    dll.SUMaterialSetOpacity.argtypes = [_SURef, C.c_double]
    dll.SUMaterialSetUseOpacity.argtypes = [_SURef, C.c_bool]
    dll.SUMaterialSetTexture.argtypes = [_SURef, _SURef]
    dll.SUTextureCreateFromFile.argtypes = [C.POINTER(_SURef), C.c_char_p, C.c_double, C.c_double]
    dll.SUGeometryInputCreate.argtypes = [C.POINTER(_SURef)]
    dll.SUGeometryInputRelease.argtypes = [C.POINTER(_SURef)]
    dll.SUGeometryInputSetVertices.argtypes = [_SURef, C.c_size_t, C.POINTER(_SUPoint3D)]
    dll.SUGeometryInputAddFace.argtypes = [_SURef, C.POINTER(_SURef), C.POINTER(C.c_size_t)]
    dll.SUGeometryInputFaceSetFrontMaterial.argtypes = [_SURef, C.c_size_t, C.POINTER(_SUMaterialInput)]
    dll.SUGeometryInputFaceSetBackMaterial.argtypes = [_SURef, C.c_size_t, C.POINTER(_SUMaterialInput)]
    dll.SULoopInputCreate.argtypes = [C.POINTER(_SURef)]
    dll.SULoopInputAddVertexIndex.argtypes = [_SURef, C.c_size_t]
    dll.SULoopInputEdgeSetSoft.argtypes = [_SURef, C.c_size_t, C.c_bool]
    dll.SULoopInputEdgeSetSmooth.argtypes = [_SURef, C.c_size_t, C.c_bool]
    dll.SUEntitiesFill.argtypes = [_SURef, _SURef, C.c_bool]
    stage_root = _ascii_stage_root()
    tmp_tex_dir = Path(tempfile.mkdtemp(prefix='mapskp_tex_', dir=str(stage_root)))
    dll.SUInitialize()
    model = _SURef()
    try:
        rc = dll.SUModelCreate(C.byref(model))
        if rc != 0:
            raise RuntimeError(f'SUModelCreate lỗi mã {rc}')
        root_ents = _SURef()
        dll.SUModelGetEntities(model, C.byref(root_ents))
        origin_meta = scene.get('origin') or {}
        if isinstance(origin_meta, dict) and 'lat' in origin_meta and 'lon' in origin_meta:
            meta_json = json.dumps(origin_meta, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            meta_b64 = base64.urlsafe_b64encode(meta_json).decode('ascii').rstrip('=')
            meta_grp = _SURef()
            if dll.SUGroupCreate(C.byref(meta_grp)) == 0:
                dll.SUEntitiesAddGroup(root_ents, meta_grp)
                dll.SUGroupSetName(meta_grp, f'__MAPSKP_META__{meta_b64}'.encode('utf-8'))
                meta_de = dll.SUGroupToDrawingElement(meta_grp)
                dll.SUDrawingElementSetHidden(meta_de, True)
                meta_ents = _SURef()
                dll.SUGroupGetEntities(meta_grp, C.byref(meta_ents))
                meta_gi = _SURef()
                if dll.SUGeometryInputCreate(C.byref(meta_gi)) == 0:
                    try:
                        m_pts = (_SUPoint3D * 3)(_SUPoint3D(0.0, 0.0, -0.05),
                                               _SUPoint3D(0.01, 0.0, -0.05),
                                               _SUPoint3D(0.0, 0.01, -0.05))
                        dll.SUGeometryInputSetVertices(meta_gi, 3, m_pts)
                        m_lp = _SURef()
                        dll.SULoopInputCreate(C.byref(m_lp))
                        dll.SULoopInputAddVertexIndex(m_lp, 0)
                        dll.SULoopInputAddVertexIndex(m_lp, 1)
                        dll.SULoopInputAddVertexIndex(m_lp, 2)
                        m_fi = C.c_size_t(0)
                        if dll.SUGeometryInputAddFace(meta_gi, C.byref(m_lp), C.byref(m_fi)) == 0:
                            dll.SUEntitiesFill(meta_ents, meta_gi, True)
                    finally:
                        dll.SUGeometryInputRelease(C.byref(meta_gi))
        su_mats = []
        used_mat_names = set()
        for idx, m in enumerate(scene.get('materials', [])):
            mat_ref = _SURef()
            dll.SUMaterialCreate(C.byref(mat_ref))
            base_name = str(m.get('name') or f'MapSKP_Mat_{idx}').strip()
            if base_name in used_mat_names:
                base_name = f'{base_name}_{idx}'
            used_mat_names.add(base_name)
            dll.SUMaterialSetName(mat_ref, base_name.encode('utf-8'))
            rgba = m.get('color') or [210, 210, 210, 255]
            col = _SUColor(int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3]) if len(rgba) > 3 else 255)
            dll.SUMaterialSetColor(mat_ref, C.byref(col))
            alpha = float(rgba[3]) / 255.0 if len(rgba) > 3 else 1.0
            if alpha < 0.995:
                dll.SUMaterialSetOpacity(mat_ref, alpha)
                dll.SUMaterialSetUseOpacity(mat_ref, True)
            tb = m.get('texture_bytes')
            if tb:
                ext = str(m.get('ext') or 'jpg').lstrip('.')
                tex_file = tmp_tex_dir / f'tex_{idx}.{ext}'
                tex_file.write_bytes(tb)
                tex_ref = _SURef()
                if dll.SUTextureCreateFromFile(C.byref(tex_ref), str(tex_file).encode('utf-8'), 1.0, 1.0) == 0:
                    dll.SUMaterialSetTexture(mat_ref, tex_ref)
            dll.SUModelAddMaterials(model, 1, C.byref(mat_ref))
            su_mats.append(mat_ref)
        tag_cache = {}
        total_tris = 0
        layer_names = []
        for ly in scene.get('layers', []):
            tag_name = str(ly.get('tag') or 'MapSKP_Context').strip()
            if tag_name not in tag_cache:
                ly_ref = _SURef()
                dll.SULayerCreate(C.byref(ly_ref))
                dll.SULayerSetName(ly_ref, tag_name.encode('utf-8'))
                dll.SUModelAddLayers(model, 1, C.byref(ly_ref))
                tc = ly.get('tag_color') or [100, 160, 230]
                lmat = _SURef()
                if dll.SULayerGetMaterial(ly_ref, C.byref(lmat)) == 0 and lmat.ptr:
                    lcol = _SUColor(int(tc[0]), int(tc[1]), int(tc[2]), 255)
                    dll.SUMaterialSetColor(lmat, C.byref(lcol))
                tag_cache[tag_name] = ly_ref
            grp = _SURef()
            dll.SUGroupCreate(C.byref(grp))
            dll.SUEntitiesAddGroup(root_ents, grp)
            dll.SUGroupSetName(grp, str(ly.get('name') or tag_name).encode('utf-8'))
            de = dll.SUGroupToDrawingElement(grp)
            dll.SUDrawingElementSetLayer(de, tag_cache[tag_name])
            grp_ents = _SURef()
            dll.SUGroupGetEntities(grp, C.byref(grp_ents))
            soften_cos = float(ly.get('soften_cos', 0.94))
            for ms_idx, ms in enumerate(ly.get('meshes', [])):
                verts_m = np.asarray(ms['verts'], dtype=np.float64)
                faces = np.asarray(ms['faces'], dtype=np.uint32)
                uvs = ms.get('uvs')
                if len(verts_m) < 3 or len(faces) == 0:
                    continue
                verts_in = np.ascontiguousarray(verts_m * INCH_PER_METER, dtype=np.float64)
                nv_all = len(verts_in)
                f0, f1, f2 = faces[:, 0], faces[:, 1], faces[:, 2]
                non_eq = (f0 != f1) & (f1 != f2) & (f2 != f0) & (f0 < nv_all) & (f1 < nv_all) & (f2 < nv_all)
                faces_clean = faces[non_eq]
                if len(faces_clean) == 0:
                    continue
                u_vec = verts_in[faces_clean[:, 1]] - verts_in[faces_clean[:, 0]]
                v_vec = verts_in[faces_clean[:, 2]] - verts_in[faces_clean[:, 0]]
                cr = np.cross(u_vec, v_vec)
                area2 = np.einsum('ij,ij->i', cr, cr)
                faces_valid = faces_clean[area2 >= 1e-9]
                if len(faces_valid) == 0:
                    continue
                mat_idx = int(ms.get('mat_idx', -1))
                mat_ref = su_mats[mat_idx] if 0 <= mat_idx < len(su_mats) else None
                has_uv_all = uvs is not None and len(uvs) == nv_all
                CHUNK_TRIS = 16000
                use_subgroups = len(faces_valid) > CHUNK_TRIS
                for ch_i, f_start in enumerate(range(0, len(faces_valid), CHUNK_TRIS)):
                    f_chunk_global = faces_valid[f_start:f_start + CHUNK_TRIS]
                    if use_subgroups:
                        uniq_v, inv_idx = np.unique(f_chunk_global, return_inverse=True)
                        v_chunk_m = verts_m[uniq_v]
                        v_chunk_in = np.ascontiguousarray(verts_in[uniq_v], dtype=np.float64)
                        f_chunk = inv_idx.astype(np.uint32).reshape((-1, 3))
                        uv_chunk = np.asarray(uvs)[uniq_v] if has_uv_all else None
                        sub_grp = _SURef()
                        dll.SUGroupCreate(C.byref(sub_grp))
                        dll.SUEntitiesAddGroup(grp_ents, sub_grp)
                        dll.SUGroupSetName(sub_grp, f'{tag_name}_Part_{ms_idx}_{ch_i + 1}'.encode('utf-8'))
                        sub_de = dll.SUGroupToDrawingElement(sub_grp)
                        dll.SUDrawingElementSetLayer(sub_de, tag_cache[tag_name])
                        target_ents = _SURef()
                        dll.SUGroupGetEntities(sub_grp, C.byref(target_ents))
                    else:
                        v_chunk_m = verts_m
                        v_chunk_in = verts_in
                        f_chunk = f_chunk_global
                        uv_chunk = uvs if has_uv_all else None
                        target_ents = grp_ents
                    nv = len(v_chunk_in)
                    soft_set = compute_soft_edges(v_chunk_m, f_chunk, soften_cos)
                    pts_ptr = v_chunk_in.ctypes.data_as(C.POINTER(_SUPoint3D))
                    gi = _SURef()
                    dll.SUGeometryInputCreate(C.byref(gi))
                    try:
                        dll.SUGeometryInputSetVertices(gi, nv, pts_ptr)
                        has_uv = uv_chunk is not None and len(uv_chunk) == nv
                        uv_list = uv_chunk.tolist() if has_uv else None
                        mi = _SUMaterialInput()
                        if mat_ref is not None:
                            mi.material = mat_ref
                            mi.num_uv_coords = 3 if has_uv else 0
                        added_in_mesh = 0
                        for a, b, c in f_chunk.tolist():
                            lp = _SURef()
                            dll.SULoopInputCreate(C.byref(lp))
                            dll.SULoopInputAddVertexIndex(lp, a)
                            dll.SULoopInputAddVertexIndex(lp, b)
                            dll.SULoopInputAddVertexIndex(lp, c)
                            if soft_set:
                                for e_idx, (u_e, v_e) in enumerate(((a, b), (b, c), (c, a))):
                                    ek = (u_e, v_e) if u_e < v_e else (v_e, u_e)
                                    if ek in soft_set:
                                        dll.SULoopInputEdgeSetSoft(lp, e_idx, True)
                                        dll.SULoopInputEdgeSetSmooth(lp, e_idx, True)
                            face_idx = C.c_size_t(0)
                            if dll.SUGeometryInputAddFace(gi, C.byref(lp), C.byref(face_idx)) == 0:
                                if mat_ref is not None:
                                    if has_uv and uv_list is not None:
                                        ua, ub_uv, uc = uv_list[a], uv_list[b], uv_list[c]
                                        mi.uv_coords[0] = _SUPoint2D(float(ua[0]), float(ua[1]))
                                        mi.uv_coords[1] = _SUPoint2D(float(ub_uv[0]), float(ub_uv[1]))
                                        mi.uv_coords[2] = _SUPoint2D(float(uc[0]), float(uc[1]))
                                        mi.vertex_indices[0] = a
                                        mi.vertex_indices[1] = b
                                        mi.vertex_indices[2] = c
                                    dll.SUGeometryInputFaceSetFrontMaterial(gi, face_idx.value, C.byref(mi))
                                    dll.SUGeometryInputFaceSetBackMaterial(gi, face_idx.value, C.byref(mi))
                                added_in_mesh += 1
                        if added_in_mesh > 0:
                            dll.SUEntitiesFill(target_ents, gi, True)
                            total_tris += added_in_mesh
                    finally:
                        dll.SUGeometryInputRelease(C.byref(gi))
            layer_names.append(tag_name)
        out_skp.parent.mkdir(parents=True, exist_ok=True)
        ascii_tmp = _ascii_stage_root() / f'mapskp_out_{os.getpid()}_{int(time.time() * 1000)}.skp'
        try:
            rc_save = -1
            for ver_enum in [10, 13, 14]:
                rc_save = dll.SUModelSaveToFileWithVersion(model, str(ascii_tmp).encode('utf-8'), ver_enum)
                if rc_save == 0 and ascii_tmp.exists():
                    break
            if rc_save != 0 or not ascii_tmp.exists():
                rc_save = dll.SUModelSaveToFile(model, str(ascii_tmp).encode('utf-8'))
            if rc_save != 0 or not ascii_tmp.exists():
                raise RuntimeError(f'SUModelSaveToFile lỗi mã {rc_save}')
            shutil.move(str(ascii_tmp), str(out_skp))
        finally:
            if ascii_tmp.exists():
                ascii_tmp.unlink(missing_ok=True)
        return {'ok': True, 'path': str(out_skp), 'size_kb': round(out_skp.stat().st_size / 1024.0, 1),
                'triangles': total_tris, 'tags': layer_names, 'materials': len(su_mats),
                'dll': str(dll_path), 'elapsed_sec': round(time.perf_counter() - t0, 3)}
    finally:
        if model.ptr:
            dll.SUModelRelease(C.byref(model))
        dll.SUTerminate()
        if dll_dir_handle is not None:
            try:
                dll_dir_handle.close()
            except Exception:
                pass
        shutil.rmtree(tmp_tex_dir, ignore_errors=True)


def write_skp_subprocess(mapskp1_bytes: bytes, out_skp_path: Path,
                         preferred_year: Optional[str] = None,
                         su_exe_dir: Optional[str] = None) -> Dict[str, Any]:
    dll_path = find_sketchup_api_dll(preferred_year, su_exe_dir=su_exe_dir)
    if not dll_path:
        return {'ok': False, 'code': 'NO_DLL', 'error': 'Không tìm thấy SketchUpAPI.dll trên máy'}
    tmp_dir = Path(tempfile.mkdtemp(prefix='mapskp_job_', dir=str(_ascii_stage_root())))
    pkg_file = tmp_dir / 'scene.mapskp1'
    res_file = tmp_dir / 'result.json'
    worker_entry = _resolve_skp_worker_script()
    subproc_err = ''
    try:
        pkg_file.write_bytes(mapskp1_bytes)
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        cmd = [sys.executable, '-X', 'utf8', str(worker_entry), '--worker-skp',
               str(pkg_file), str(out_skp_path), str(res_file), str(dll_path)]
        subprocess.run(cmd, cwd=str(worker_entry.parent), capture_output=True, timeout=180, creationflags=flags)
        if res_file.exists():
            res_obj = json.loads(res_file.read_text(encoding='utf-8'))
            if res_obj.get('ok') and out_skp_path.is_file():
                return res_obj
            subproc_err = str(res_obj.get('error') or 'Worker returned ok=False')
        else:
            subproc_err = 'Tiến trình ghi .skp không tạo tệp kết quả'
    except Exception as exc:
        subproc_err = str(exc)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        with _SKP_DLL_LOCK:
            sc = unpack_mapskp1_to_scene(mapskp1_bytes)
            inproc_res = _write_skp_in_process(sc, out_skp_path, dll_path)
            inproc_res['in_process_fallback'] = True
            return inproc_res
    except Exception as inproc_exc:
        return {'ok': False, 'error': f'Subprocess: {subproc_err} | InProcess: {inproc_exc}'}


if __name__ == '__main__':
    if len(sys.argv) >= 6 and sys.argv[1] == '--worker-skp':
        sys.exit(run_skp_worker_cli(sys.argv[2:6]))
