"""Readable recovery of the original MapSKP 2.8.1 OSM/DEM geometry builder.

Reconstructed from the user-provided original runtime and verified against the
unchanged original. Original attribution and rights are retained. This is not
relicensed under the independent OpenMap implementation's MIT license.

This module contains ordinary editable Python, including every original top-level
function. It does not load marshal/pyc payloads or require source fragments.
The original optional native policy import and its scene-builder guard remain.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import requests
from PIL import Image, ImageEnhance, ImageFilter

from facade_texture_gen import (
    FACADE_SPECS, PARAPET_TRIM_COLOR, PARAPET_TRIM_SPEC,
    PENTHOUSE_FACADE_INDEX, PODIUM_FACADE_INDEX, ROOF_CONCRETE_COLOR, ROOF_SPECS,
    get_facade_jpeg_bytes_list, get_parapet_trim_jpeg_bytes,
    get_roof_jpeg_bytes_list, select_facade_variant_index,
    select_lowrise_roof_variant_index,
)
from geo_math import (
    WGS84_A, WGS84_E2, bbox_dimensions_meters, bbox_from_center_meters,
    estimate_tz_offset, latlon_array_to_local_xy, latlon_to_ecef,
    latlon_to_local_xy, latlon_to_tile_float, optimal_satellite_zoom,
    tile_xy_to_latlon,
)

try:
    import mapskp_armor as _ARMOR_MOD
except Exception:
    _ARMOR_MOD = None

USER_AGENT = 'HiepAI-MapSKP-Studio/2.0 (SketchUp Architectural Context SaaS)'

OVERPASS_ENDPOINTS = ['https://overpass.private.coffee/api/interpreter',
 'https://overpass-api.de/api/interpreter',
 'https://maps.mail.ru/osm/tools/overpass/api/interpreter']

ROAD_MAIN_WIDTH_VN: Dict[str, float] = {'motorway': 18.0,
 'motorway_link': 9.5,
 'trunk': 15.0,
 'trunk_link': 8.5,
 'primary': 13.0,
 'primary_link': 8.0,
 'secondary': 10.5,
 'secondary_link': 7.5,
 'tertiary': 8.0,
 'tertiary_link': 6.8}

ROAD_ALLEY_WIDTH_VN: Dict[str, float] = {'unclassified': 5.8,
 'residential': 5.2,
 'living_street': 4.2,
 'pedestrian': 4.0,
 'road': 5.0,
 'construction': 5.5,
 'service': 3.5,
 'alley': 3.0,
 'track': 3.2,
 'cycleway': 2.6,
 'footway': 2.5,
 'path': 2.4}

ROAD_WIDTH_VN: Dict[str, float] = {'motorway': 18.0,
 'motorway_link': 9.5,
 'trunk': 15.0,
 'trunk_link': 8.5,
 'primary': 13.0,
 'primary_link': 8.0,
 'secondary': 10.5,
 'secondary_link': 7.5,
 'tertiary': 8.0,
 'tertiary_link': 6.8,
 'unclassified': 5.8,
 'residential': 5.2,
 'living_street': 4.2,
 'pedestrian': 4.0,
 'road': 5.0,
 'construction': 5.5,
 'service': 3.5,
 'alley': 3.0,
 'track': 3.2,
 'cycleway': 2.6,
 'footway': 2.5,
 'path': 2.4}

_OPENFREEMAP_TPL_MEM: Tuple[float, str] = (0.0, '')

def classify_vietnam_road_tier(tags: Dict[str, Any]) -> Optional[Tuple[str, float]]:
    hw = str(tags.get('highway') or '').strip().lower()
    if not hw:
        return None
    if hw == 'footway' and str(tags.get('footway') or '').strip().lower() in ('sidewalk', 'crossing'):
        return None
    explicit_w = None
    raw_w = str(tags.get('width') or '').strip().lower()
    if raw_w:
        try:
            num_s = ''.join(ch for ch in raw_w.split()[0] if ch.isdigit() or ch == '.')
            if num_s:
                val = float(num_s)
                if 1.8 <= val <= 38.0:
                    explicit_w = val
        except Exception:
            explicit_w = None
    lanes_n = 0
    raw_lanes = str(tags.get('lanes') or '').strip()
    if raw_lanes:
        try:
            lanes_n = int(float(raw_lanes.split(';')[0]))
        except Exception:
            lanes_n = 0
    if hw in ROAD_MAIN_WIDTH_VN:
        return 'main', explicit_w if explicit_w is not None else ROAD_MAIN_WIDTH_VN[hw]
    if hw in ROAD_ALLEY_WIDTH_VN:
        if (explicit_w is not None and explicit_w >= 7.0) or (lanes_n >= 2 and hw in ('residential', 'unclassified', 'road', 'construction')):
            return 'main', explicit_w if explicit_w is not None else max(7.5, lanes_n * 3.5)
        base_w = ROAD_ALLEY_WIDTH_VN[hw]
        if hw == 'service':
            srv = str(tags.get('service') or '').strip().lower()
            if srv == 'alley':
                base_w = 3.0
            elif srv in ('driveway', 'parking_aisle'):
                base_w = 2.8
        return 'alley', explicit_w if explicit_w is not None else base_w
    return None


def _fetch_tile_bytes(url: str, cache_path: Path, timeout: float = 12.0) -> Optional[bytes]:
    if cache_path.is_file() and cache_path.stat().st_size > 128:
        return cache_path.read_bytes()
    try:
        resp = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 128:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)
            return resp.content
    except Exception:
        pass
    return None


def _satellite_tile_url(provider: str, z: int, x: int, y: int) -> str:
    srv_idx = (x + y) & 3
    if provider == 'google_sat':
        return f'https://mt{srv_idx}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'
    if provider == 'google_hybrid':
        return f'https://mt{srv_idx}.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}'
    if provider == 'google_street':
        return f'https://mt{srv_idx}.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}'
    if provider == 'google_street_nolabel':
        return f'https://mt{srv_idx}.google.com/vt/lyrs=m&apistyle=s.t:all%7Cs.e:l%7Cp.v:off&x={x}&y={y}&z={z}'
    if provider == 'osm_clean':
        return f'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
    return f'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'


def download_stitched_satellite(south: float, west: float, north: float, east: float, cache_dir: Path, provider: str = 'esri_sat', target_px: int = 4096, sharpen: bool = True) -> bytes:
    lat0, _, w_m, h_m = bbox_dimensions_meters(south, west, north, east)
    zoom = optimal_satellite_zoom(w_m, h_m, lat0, target_px=target_px)
    x_min_f, y_min_f = latlon_to_tile_float(north, west, zoom)
    x_max_f, y_max_f = latlon_to_tile_float(south, east, zoom)
    tx0, tx1 = int(math.floor(x_min_f)), int(math.floor(x_max_f))
    ty0, ty1 = int(math.floor(y_min_f)), int(math.floor(y_max_f))
    nx = max(1, tx1 - tx0 + 1)
    ny = max(1, ty1 - ty0 + 1)
    canvas = Image.new('RGB', (nx * 256, ny * 256), (218, 224, 214))
    tasks = []
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = _satellite_tile_url(provider, zoom, tx, ty)
            ext = 'png' if provider in ('osm_clean', 'google_street', 'google_street_nolabel') else 'jpg'
            cpath = cache_dir / 'sat_tiles' / provider / str(zoom) / str(tx) / f'{ty}.{ext}'
            tasks.append((tx - tx0, ty - ty0, url, cpath))

    def _job(item):
        ix, iy, u, cp = item
        data = _fetch_tile_bytes(u, cp)
        if data is None and provider == 'google_street_nolabel':
            fb_u = _satellite_tile_url('google_street', zoom, tx0 + ix, ty0 + iy)
            fb_cp = cache_dir / 'sat_tiles' / 'google_street' / str(zoom) / str(tx0 + ix) / f'{ty0 + iy}.png'
            data = _fetch_tile_bytes(fb_u, fb_cp)
        elif data is None and provider not in ('esri_sat', 'google_street', 'osm_clean'):
            fb_u = _satellite_tile_url('esri_sat', zoom, tx0 + ix, ty0 + iy)
            fb_cp = cache_dir / 'sat_tiles' / 'esri_sat' / str(zoom) / str(tx0 + ix) / f'{ty0 + iy}.jpg'
            data = _fetch_tile_bytes(fb_u, fb_cp)
        return ix, iy, data

    with ThreadPoolExecutor(max_workers=8) as pool:
        for ix, iy, raw in pool.map(_job, tasks):
            if not raw:
                continue
            try:
                tile_im = Image.open(io.BytesIO(raw)).convert('RGB')
                canvas.paste(tile_im, (ix * 256, iy * 256))
            except Exception:
                pass
    px_left = int(round((x_min_f - tx0) * 256.0))
    px_top = int(round((y_min_f - ty0) * 256.0))
    px_right = max(px_left + 16, int(round((x_max_f - tx0) * 256.0)))
    px_bottom = max(px_top + 16, int(round((y_max_f - ty0) * 256.0)))
    cropped = canvas.crop((px_left, px_top, min(canvas.width, px_right), min(canvas.height, px_bottom)))
    cw, ch = cropped.size
    max_side = min(8192, max(1024, int(target_px)))
    scale = max_side / float(max(cw, ch, 1))
    if abs(scale - 1.0) > 0.08:
        out_w = max(256, int(round(cw * scale)))
        out_h = max(256, int(round(ch * scale)))
        cropped = cropped.resize((out_w, out_h), Image.Resampling.LANCZOS)
    if sharpen:
        cropped = cropped.filter(ImageFilter.UnsharpMask(radius=1.3, percent=130, threshold=2))
        cropped = ImageEnhance.Contrast(cropped).enhance(1.05)
    buf = io.BytesIO()
    cropped.save(buf, format='JPEG', quality=92, optimize=True)
    return buf.getvalue()


def download_terrarium_dem_grid(south: float, west: float, north: float, east: float, grid_res: int, cache_dir: Path, z_exaggeration: float = 1.0) -> Tuple[np.ndarray, float]:
    zoom = 14
    x_min_f, y_min_f = latlon_to_tile_float(north, west, zoom)
    x_max_f, y_max_f = latlon_to_tile_float(south, east, zoom)
    tx0, tx1 = int(math.floor(x_min_f)), int(math.floor(x_max_f))
    ty0, ty1 = int(math.floor(y_min_f)), int(math.floor(y_max_f))
    nx = max(1, tx1 - tx0 + 1)
    ny = max(1, ty1 - ty0 + 1)
    dem_mosaic = np.zeros((ny * 256, nx * 256), dtype=np.float32)
    any_loaded = False
    tasks = []
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            url = f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{zoom}/{tx}/{ty}.png'
            cpath = cache_dir / 'dem_terrarium' / str(zoom) / str(tx) / f'{ty}.png'
            tasks.append((tx - tx0, ty - ty0, url, cpath))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda it: (it[0], it[1], _fetch_tile_bytes(it[2], it[3], 10.0)), tasks))
    for ix, iy, raw in results:
        if not raw:
            continue
        try:
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            rgb = np.asarray(im, dtype=np.float32)
            elev = rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0
            elev = np.clip(elev, -500.0, 9000.0)
            dem_mosaic[iy * 256:(iy + 1) * 256, ix * 256:(ix + 1) * 256] = elev
            any_loaded = True
        except Exception:
            pass
    if not any_loaded:
        return np.zeros((grid_res, grid_res), dtype=np.float32), 0.0
    lats = np.linspace(south, north, grid_res)
    lons = np.linspace(west, east, grid_res)
    out_grid = np.zeros((grid_res, grid_res), dtype=np.float32)
    mh, mw = dem_mosaic.shape
    for r_idx, lat in enumerate(lats):
        _, yf = latlon_to_tile_float(float(lat), west, zoom)
        py = np.clip((yf - ty0) * 256.0 - 0.5, 0.0, mh - 1.001)
        y0 = int(math.floor(py))
        wy = py - y0
        for c_idx, lon in enumerate(lons):
            xf, _ = latlon_to_tile_float(float(lat), float(lon), zoom)
            px = np.clip((xf - tx0) * 256.0 - 0.5, 0.0, mw - 1.001)
            x0 = int(math.floor(px))
            wx = px - x0
            v00 = dem_mosaic[y0, x0]
            v01 = dem_mosaic[y0, x0 + 1]
            v10 = dem_mosaic[y0 + 1, x0]
            v11 = dem_mosaic[y0 + 1, x0 + 1]
            val = (1 - wy) * ((1 - wx) * v00 + wx * v01) + wy * ((1 - wx) * v10 + wx * v11)
            out_grid[r_idx, c_idx] = float(val)
    mid = grid_res // 2
    center_elev = round(float(out_grid[mid, mid]), 4)
    rel_grid = (out_grid - center_elev) * float(z_exaggeration)
    return rel_grid, center_elev


def sample_dem_bilinear(x_east: float, y_north: float, half_w: float, half_h: float, dem_grid: np.ndarray) -> float:
    nrows, ncols = dem_grid.shape
    u = float(np.clip((x_east + half_w) / max(2.0 * half_w, 1e-6), 0.0, 1.0)) * (ncols - 1)
    v = float(np.clip((y_north + half_h) / max(2.0 * half_h, 1e-6), 0.0, 1.0)) * (nrows - 1)
    c0 = min(ncols - 2, max(0, int(math.floor(u))))
    r0 = min(nrows - 2, max(0, int(math.floor(v))))
    du = u - c0
    dv = v - r0
    z00 = float(dem_grid[r0, c0])
    z01 = float(dem_grid[r0, c0 + 1])
    z10 = float(dem_grid[r0 + 1, c0])
    z11 = float(dem_grid[r0 + 1, c0 + 1])
    return (1.0 - dv) * ((1.0 - du) * z00 + du * z01) + dv * ((1.0 - du) * z10 + du * z11)


def build_terrain_mesh_with_plinth(width_m: float, height_m: float, dem_grid: np.ndarray, plinth_depth_m: float = 4.0, grid_xy: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    nrows, ncols = dem_grid.shape
    half_w = width_m * 0.5
    half_h = height_m * 0.5
    if grid_xy is not None:
        xx = np.asarray(grid_xy[0], dtype=np.float32)
        yy = np.asarray(grid_xy[1], dtype=np.float32)
    else:
        xs = np.linspace(-half_w, half_w, ncols, dtype=np.float32)
        ys = np.linspace(-half_h, half_h, nrows, dtype=np.float32)
        xx, yy = np.meshgrid(xs, ys)
    verts_top = np.stack([xx.ravel(), yy.ravel(), dem_grid.ravel()], axis=-1).astype(np.float32)
    us = np.linspace(0.0, 1.0, ncols, dtype=np.float32)
    vs = np.linspace(0.0, 1.0, nrows, dtype=np.float32)
    uu, vv = np.meshgrid(us, vs)
    uvs_top = np.stack([uu.ravel(), vv.ravel()], axis=-1).astype(np.float32)
    faces_top = []
    for r in range(nrows - 1):
        row0 = r * ncols
        row1 = (r + 1) * ncols
        for c in range(ncols - 1):
            i00 = row0 + c
            i10 = row0 + c + 1
            i01 = row1 + c
            i11 = row1 + c + 1
            faces_top.append((i00, i10, i11))
            faces_top.append((i00, i11, i01))
    top_mesh = {'verts': verts_top, 'faces': np.asarray(faces_top, dtype=np.uint32), 'uvs': uvs_top}
    z_floor = float(dem_grid.min()) - abs(plinth_depth_m)
    perimeter_idx = []
    perimeter_idx.extend([0 * ncols + c for c in range(ncols - 1)])
    perimeter_idx.extend([r * ncols + (ncols - 1) for r in range(nrows - 1)])
    perimeter_idx.extend([(nrows - 1) * ncols + c for c in range(ncols - 1, 0, -1)])
    perimeter_idx.extend([r * ncols + 0 for r in range(nrows - 1, 0, -1)])
    np_perim = len(perimeter_idx)
    p_verts = np.zeros((np_perim * 2 + 4, 3), dtype=np.float32)
    for k, tidx in enumerate(perimeter_idx):
        vx, vy, vz = verts_top[tidx]
        p_verts[k] = (vx, vy, vz)
        p_verts[np_perim + k] = (vx, vy, z_floor)
    base_c = np_perim * 2
    p_verts[base_c + 0] = (float(xx[0, 0]), float(yy[0, 0]), z_floor)
    p_verts[base_c + 1] = (float(xx[0, -1]), float(yy[0, -1]), z_floor)
    p_verts[base_c + 2] = (float(xx[-1, -1]), float(yy[-1, -1]), z_floor)
    p_verts[base_c + 3] = (float(xx[-1, 0]), float(yy[-1, 0]), z_floor)
    p_faces = []
    for k in range(np_perim):
        kn = (k + 1) % np_perim
        t0, t1 = k, kn
        b0, b1 = np_perim + k, np_perim + kn
        p_faces.append((t0, b0, b1))
        p_faces.append((t0, b1, t1))
    p_faces.append((base_c + 0, base_c + 2, base_c + 1))
    p_faces.append((base_c + 0, base_c + 3, base_c + 2))
    plinth_mesh = {'verts': p_verts, 'faces': np.asarray(p_faces, dtype=np.uint32), 'uvs': None}
    return top_mesh, plinth_mesh


def build_flat_sheet_mesh(xx_local: np.ndarray, yy_local: np.ndarray, z_flat: float = 0.0) -> Dict[str, Any]:
    z0 = float(z_flat)
    verts_flat = np.asarray([
        (float(xx_local[0, 0]), float(yy_local[0, 0]), z0),
        (float(xx_local[0, -1]), float(yy_local[0, -1]), z0),
        (float(xx_local[-1, 0]), float(yy_local[-1, 0]), z0),
        (float(xx_local[-1, -1]), float(yy_local[-1, -1]), z0),
    ], dtype=np.float32)
    uvs_flat = np.asarray([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], dtype=np.float32)
    faces_flat = np.asarray([(0, 1, 3), (0, 3, 2)], dtype=np.uint32)
    return {'verts': verts_flat, 'faces': faces_flat, 'uvs': uvs_flat}


def build_trimmed_hill_patch_mesh(dem_grid_centered: np.ndarray, center_elev_asl: float, z_exag: float, xx_local: np.ndarray, yy_local: np.ndarray, min_relief_cutoff_m: float = 0.35, toe_contact_z_m: float = 0.015) -> Tuple[Dict[str, Any], np.ndarray, float, float]:
    nrows, ncols = dem_grid_centered.shape
    top_edge = dem_grid_centered[-1, :]
    bot_edge = dem_grid_centered[0, :]
    left_edge = dem_grid_centered[:, 0]
    right_edge = dem_grid_centered[:, -1]
    border_ring = np.concatenate([top_edge, bot_edge, left_edge, right_edge])
    z_foot_rel = float(np.percentile(border_ring, 12))
    z_foot_asl = float(center_elev_asl + z_foot_rel / max(1e-6, float(z_exag)))
    hill_raw = np.maximum(0.0, dem_grid_centered.astype(np.float32) - z_foot_rel)
    margin = max(2, int(round(min(nrows, ncols) * 0.1)))
    rr = np.minimum(np.arange(nrows, dtype=np.float32), np.arange(nrows - 1, -1, -1, dtype=np.float32))
    cc = np.minimum(np.arange(ncols, dtype=np.float32), np.arange(ncols - 1, -1, -1, dtype=np.float32))
    dist_cells = np.minimum(rr[:, None], cc[None, :])
    t_edge = np.clip(dist_cells / float(margin), 0.0, 1.0)
    feather = (0.5 - 0.5 * np.cos(np.pi * t_edge)).astype(np.float32)
    hill_dem = (hill_raw * feather).astype(np.float32)
    peak_rel_m = float(np.max(hill_dem))
    if peak_rel_m > 0.08:
        eff_cutoff = min(float(min_relief_cutoff_m), max(0.06, peak_rel_m * 0.1))
    else:
        eff_cutoff = 0.0
    us = np.linspace(0.0, 1.0, ncols, dtype=np.float32)
    vs = np.linspace(0.0, 1.0, nrows, dtype=np.float32)
    uu, vv = np.meshgrid(us, vs)
    z_flat_arr = hill_dem.ravel().copy()
    kept_tris_grid = []
    for r in range(nrows - 1):
        row0 = r * ncols
        row1 = (r + 1) * ncols
        for c in range(ncols - 1):
            i00 = row0 + c
            i10 = row0 + c + 1
            i01 = row1 + c
            i11 = row1 + c + 1
            if max(float(z_flat_arr[i00]), float(z_flat_arr[i10]), float(z_flat_arr[i11])) >= eff_cutoff:
                kept_tris_grid.append((i00, i10, i11))
            if max(float(z_flat_arr[i00]), float(z_flat_arr[i11]), float(z_flat_arr[i01])) >= eff_cutoff:
                kept_tris_grid.append((i00, i11, i01))
    if not kept_tris_grid:
        r_mid0 = max(0, nrows // 4)
        r_mid1 = min(nrows - 1, nrows * 3 // 4)
        c_mid0 = max(0, ncols // 4)
        c_mid1 = min(ncols - 1, ncols * 3 // 4)
        for r in range(r_mid0, r_mid1):
            row0 = r * ncols
            row1 = (r + 1) * ncols
            for c in range(c_mid0, c_mid1):
                i00, i10, i01, i11 = row0 + c, row0 + c + 1, row1 + c, row1 + c + 1
                kept_tris_grid.append((i00, i10, i11))
                kept_tris_grid.append((i00, i11, i01))
    z_mesh_arr = np.where(z_flat_arr <= max(eff_cutoff, toe_contact_z_m), float(toe_contact_z_m), z_flat_arr).astype(np.float32)
    xx_r = xx_local.ravel()
    yy_r = yy_local.ravel()
    uu_r = uu.ravel()
    vv_r = vv.ravel()
    remap = {}
    out_verts = []
    out_uvs = []
    out_faces = []
    for a, b, d in kept_tris_grid:
        tri_mapped = []
        for gi in (a, b, d):
            ni = remap.get(gi)
            if ni is None:
                ni = len(out_verts)
                remap[gi] = ni
                out_verts.append((float(xx_r[gi]), float(yy_r[gi]), float(z_mesh_arr[gi])))
                out_uvs.append((float(uu_r[gi]), float(vv_r[gi])))
            tri_mapped.append(ni)
        out_faces.append((tri_mapped[0], tri_mapped[1], tri_mapped[2]))
    mesh_out = {'verts': np.asarray(out_verts, dtype=np.float32),
                'faces': np.asarray(out_faces, dtype=np.uint32),
                'uvs': np.asarray(out_uvs, dtype=np.float32)}
    return mesh_out, hill_dem, z_foot_asl, peak_rel_m


def _signed_area_2d(pts: List[Tuple[float, float]]) -> float:
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def triangulate_polygon_2d(pts_in: List[Tuple[float, float]]) -> Tuple[List[Tuple[float, float]], List[Tuple[int, int, int]]]:
    pts = []
    for p in pts_in:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 0.05:
            pts.append(p)
    if len(pts) >= 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 0.05:
        pts.pop()
    if len(pts) > 220:
        pts = _rdp_simplify_2d(pts, 0.85)
    if len(pts) < 3:
        return pts, []
    if _signed_area_2d(pts) < 0:
        pts = list(reversed(pts))
    idxs = list(range(len(pts)))
    tris = []

    def _cross(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    def _pt_in_tri(px: float, py: float, ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
        c1 = _cross(ax, ay, bx, by, px, py)
        c2 = _cross(bx, by, cx, cy, px, py)
        c3 = _cross(cx, cy, ax, ay, px, py)
        return c1 >= -1e-7 and c2 >= -1e-7 and c3 >= -1e-7

    guard = 0
    max_guard = len(idxs) * len(idxs) + 20
    while len(idxs) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        m = len(idxs)
        for k in range(m):
            i_prev = idxs[(k - 1) % m]
            i_curr = idxs[k]
            i_next = idxs[(k + 1) % m]
            ax, ay = pts[i_prev]
            bx, by = pts[i_curr]
            cx, cy = pts[i_next]
            if _cross(ax, ay, bx, by, cx, cy) <= 1e-6:
                continue
            has_inside = False
            for j in idxs:
                if j in (i_prev, i_curr, i_next):
                    continue
                if _pt_in_tri(pts[j][0], pts[j][1], ax, ay, bx, by, cx, cy):
                    has_inside = True
                    break
            if has_inside:
                continue
            tris.append((i_prev, i_curr, i_next))
            idxs.pop(k)
            ear_found = True
            break
        if not ear_found:
            for k in range(1, len(idxs) - 1):
                tris.append((idxs[0], idxs[k], idxs[k + 1]))
            return pts, tris
    if len(idxs) == 3:
        tris.append((idxs[0], idxs[1], idxs[2]))
    return pts, tris


def _parse_osm_meters(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().lower().replace(',', '.')
    s = s.replace('m', '').strip()
    try:
        v = float(s.split()[0])
        if 1.5 <= v <= 600.0:
            return v
    except Exception:
        pass
    return None


def infer_vietnam_building_height(tags: Dict[str, Any], area_m2: float, way_id: int, default_floors: float = 3.5) -> float:
    h_direct = _parse_osm_meters(tags.get('height'))
    if h_direct is not None:
        return h_direct
    lv_raw = tags.get('building:levels')
    if lv_raw is not None:
        try:
            lv = float(str(lv_raw).strip().split(';')[0])
            if 0.5 <= lv <= 120.0:
                return lv * 3.45
        except Exception:
            pass
    btype = str(tags.get('building') or 'yes').lower()
    jitter = ((way_id * 2654435761) & 255) / 255.0
    if btype in ('apartments', 'hotel', 'commercial', 'office', 'hospital', 'university'):
        return round((7.0 + int(jitter * 5.0)) * 3.5, 2)
    if btype in ('industrial', 'warehouse', 'retail', 'supermarket'):
        return 8.5 + round(jitter * 2.5, 2)
    if btype in ('hut', 'shed', 'garage', 'roof', 'kiosk'):
        return 3.6
    if area_m2 < 135.0:
        floors = max(1.0, default_floors + round(jitter * 2.0) - 1.0)
        return round(floors * 3.4, 2)
    if area_m2 > 600.0:
        return round((default_floors + 2.0 + int(jitter * 3.0)) * 3.5, 2)
    return round(max(1.0, default_floors) * 3.4, 2)


def is_vietnam_peak_map_hour(now_utc: Optional[float] = None) -> bool:
    ts = time.time() if now_utc is None else float(now_utc)
    vn_hour = (ts / 3600.0 + 7.0) % 24.0
    return 17.5 <= vn_hour <= 23.5


def _mvt_read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    res = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        res |= (b & 127) << shift
        if not (b & 128):
            return res, pos
        shift += 7
    return res, pos


def _mvt_parse_value(chunk: bytes) -> Any:
    pos = 0
    end = len(chunk)
    while pos < end:
        tag, pos = _mvt_read_varint(chunk, pos)
        fn, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, pos = _mvt_read_varint(chunk, pos)
            raw = chunk[pos:pos + ln]
            pos += ln
            if fn == 1:
                return raw.decode('utf-8', errors='replace')
        elif wt == 0:
            v, pos = _mvt_read_varint(chunk, pos)
            if fn in (4, 5):
                return v
            if fn == 6:
                return (v >> 1) ^ -(v & 1)
            if fn == 7:
                return bool(v)
        elif wt == 5:
            if fn == 2 and pos + 4 <= end:
                return struct.unpack_from('<f', chunk, pos)[0]
            pos += 4
        elif wt == 1:
            if fn == 3 and pos + 8 <= end:
                return struct.unpack_from('<d', chunk, pos)[0]
            pos += 8
        else:
            break
    return None


def _decode_mvt_tile_elements(raw_bytes: bytes, z: int, tx: int, ty: int, include_roads: bool = True, include_buildings: bool = True, include_water: bool = True) -> List[Dict[str, Any]]:
    if not raw_bytes:
        return []
    if raw_bytes[:2] == b'\x1f\x8b':
        raw_bytes = gzip.decompress(raw_bytes)
    elif len(raw_bytes) > 2 and raw_bytes[0] == 120 and raw_bytes[1] in (1, 156, 218):
        raw_bytes = zlib.decompress(raw_bytes)
    wanted_layers = set()
    if include_roads:
        wanted_layers.add('transportation')
    if include_buildings:
        wanted_layers.add('building')
    if include_water:
        wanted_layers.update(('water', 'waterway'))
    if not wanted_layers:
        return []
    out_els = []
    pos = 0
    end = len(raw_bytes)
    two_pow_z = float(2 ** z)
    seq_id = ((tx & 65535) << 24) | ((ty & 65535) << 8)
    while pos < end:
        tag, pos = _mvt_read_varint(raw_bytes, pos)
        fn, wt = tag >> 3, tag & 7
        if wt == 2:
            ln, pos = _mvt_read_varint(raw_bytes, pos)
            sub = raw_bytes[pos:pos + ln]
            pos += ln
            if fn != 3:
                continue
            lp = 0
            lend = len(sub)
            lname = ''
            extent = 4096
            feats_raw = []
            keys_list = []
            vals_list = []
            skip_layer = False
            while lp < lend:
                lt, lp = _mvt_read_varint(sub, lp)
                lfn, lw = lt >> 3, lt & 7
                if lw == 2:
                    lln, lp = _mvt_read_varint(sub, lp)
                    lch = sub[lp:lp + lln]
                    lp += lln
                    if lfn == 1:
                        lname = lch.decode('utf-8', errors='replace')
                        if lname not in wanted_layers:
                            skip_layer = True
                            break
                    elif lfn == 2:
                        feats_raw.append(lch)
                    elif lfn == 3:
                        keys_list.append(lch.decode('utf-8', errors='replace'))
                    elif lfn == 4:
                        vals_list.append(_mvt_parse_value(lch))
                elif lw == 0:
                    lv, lp = _mvt_read_varint(sub, lp)
                    if lfn == 5 and lv > 0:
                        extent = int(lv)
                elif lw == 5:
                    lp += 4
                elif lw == 1:
                    lp += 8
                else:
                    break
            if skip_layer or lname not in wanted_layers or not feats_raw:
                continue
            inv_ext = 1.0 / float(extent)
            for f_idx, fb in enumerate(feats_raw):
                fp = 0
                fend = len(fb)
                gtype = 0
                ftags_raw = b''
                fgeom_raw = b''
                while fp < fend:
                    ft, fp = _mvt_read_varint(fb, fp)
                    ffn, fw = ft >> 3, ft & 7
                    if fw == 0:
                        fv, fp = _mvt_read_varint(fb, fp)
                        if ffn == 3:
                            gtype = int(fv)
                    elif fw == 2:
                        fln, fp = _mvt_read_varint(fb, fp)
                        fch = fb[fp:fp + fln]
                        fp += fln
                        if ffn == 2:
                            ftags_raw = fch
                        elif ffn == 4:
                            fgeom_raw = fch
                    elif fw == 5:
                        fp += 4
                    elif fw == 1:
                        fp += 8
                    else:
                        break
                if not fgeom_raw or gtype not in (2, 3):
                    continue
                props = {}
                tp = 0
                tend = len(ftags_raw)
                while tp < tend:
                    k_i, tp = _mvt_read_varint(ftags_raw, tp)
                    if tp >= tend:
                        break
                    v_i, tp = _mvt_read_varint(ftags_raw, tp)
                    if k_i < len(keys_list) and v_i < len(vals_list):
                        props[keys_list[k_i]] = vals_list[v_i]
                gp = 0
                gend = len(fgeom_raw)
                cx_i = 0
                cy_i = 0
                rings_px = []
                cur_ring = []
                while gp < gend:
                    cmd_int, gp = _mvt_read_varint(fgeom_raw, gp)
                    cmd_id = cmd_int & 7
                    cmd_cnt = cmd_int >> 3
                    if cmd_id == 1:
                        for _ in range(cmd_cnt):
                            if cur_ring:
                                rings_px.append(cur_ring)
                                cur_ring = []
                            dx_u, gp = _mvt_read_varint(fgeom_raw, gp)
                            dy_u, gp = _mvt_read_varint(fgeom_raw, gp)
                            cx_i += (dx_u >> 1) ^ -(dx_u & 1)
                            cy_i += (dy_u >> 1) ^ -(dy_u & 1)
                            cur_ring.append((cx_i, cy_i))
                    elif cmd_id == 2:
                        for _ in range(cmd_cnt):
                            dx_u, gp = _mvt_read_varint(fgeom_raw, gp)
                            dy_u, gp = _mvt_read_varint(fgeom_raw, gp)
                            cx_i += (dx_u >> 1) ^ -(dx_u & 1)
                            cy_i += (dy_u >> 1) ^ -(dy_u & 1)
                            cur_ring.append((cx_i, cy_i))
                    elif cmd_id == 7:
                        if cur_ring:
                            if cur_ring[0] != cur_ring[-1]:
                                cur_ring.append(cur_ring[0])
                            rings_px.append(cur_ring)
                            cur_ring = []
                    else:
                        break
                if cur_ring:
                    rings_px.append(cur_ring)

                def _ring_to_latlon_geom(rg: List[Tuple[int, int]]) -> List[Dict[str, float]]:
                    pts_out = []
                    for gx_p, gy_p in rg:
                        xt_f = (tx + gx_p * inv_ext) / two_pow_z
                        yt_f = (ty + gy_p * inv_ext) / two_pow_z
                        lon_d = xt_f * 360.0 - 180.0
                        lat_d = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * yt_f))))
                        pts_out.append({'lat': lat_d, 'lon': lon_d})
                    return pts_out

                if lname == 'transportation' and gtype == 2:
                    cls = str(props.get('class') or '').lower()
                    subcls = str(props.get('subclass') or '').lower()
                    brunnel = str(props.get('brunnel') or '').lower()
                    if brunnel == 'tunnel' or cls in ('ferry', 'aerialway', 'pier', 'rail', 'transit', 'raceway'):
                        continue
                    is_ramp = bool(props.get('ramp'))
                    hw_map = {'motorway': 'motorway_link' if is_ramp else 'motorway',
                              'trunk': 'trunk_link' if is_ramp else 'trunk',
                              'primary': 'primary_link' if is_ramp else 'primary',
                              'secondary': 'secondary_link' if is_ramp else 'secondary',
                              'tertiary': 'tertiary_link' if is_ramp else 'tertiary',
                              'minor': 'residential', 'service': 'service', 'track': 'track'}
                    hw_val = hw_map.get(cls, '')
                    if not hw_val and cls == 'path':
                        if subcls in ('steps', 'sidewalk', 'crossing', 'platform', 'corridor'):
                            continue
                        hw_val = subcls if subcls in ('footway', 'cycleway', 'path') else 'path'
                    if not hw_val:
                        continue
                    r_tags = {'highway': hw_val}
                    if hw_val == 'service':
                        srv_v = str(props.get('service') or ('alley' if subcls == 'alley' else '')).strip()
                        if srv_v:
                            r_tags['service'] = srv_v
                    for rg in rings_px:
                        if len(rg) >= 2:
                            seq_id += 1
                            out_els.append({'type': 'way', 'id': 900000000000 + seq_id + f_idx, 'tags': r_tags, 'geometry': _ring_to_latlon_geom(rg)})
                elif lname == 'building' and gtype == 3:
                    if str(props.get('hide_3d') or '').lower() in ('true', '1'):
                        continue
                    b_tags = {'building': 'yes'}
                    rh = props.get('render_height')
                    if isinstance(rh, (int, float)) and 2.2 <= float(rh) <= 500.0:
                        b_tags['height'] = f'{float(rh):.1f}'
                    for rg in rings_px:
                        if len(rg) < 4:
                            continue
                        area2 = 0
                        for k_i in range(len(rg) - 1):
                            area2 += rg[k_i][0] * rg[k_i + 1][1] - rg[k_i + 1][0] * rg[k_i][1]
                        if area2 <= 0:
                            continue
                        seq_id += 1
                        out_els.append({'type': 'way', 'id': 920000000000 + seq_id + f_idx, 'tags': b_tags, 'geometry': _ring_to_latlon_geom(rg)})
                elif lname == 'water' and gtype == 3:
                    for rg in rings_px:
                        if len(rg) < 4:
                            continue
                        area2 = sum(rg[k_i][0] * rg[k_i + 1][1] - rg[k_i + 1][0] * rg[k_i][1] for k_i in range(len(rg) - 1))
                        if area2 <= 0:
                            continue
                        seq_id += 1
                        out_els.append({'type': 'way', 'id': 940000000000 + seq_id + f_idx, 'tags': {'natural': 'water'}, 'geometry': _ring_to_latlon_geom(rg)})
        elif wt == 0:
            _, pos = _mvt_read_varint(raw_bytes, pos)
        elif wt == 5:
            pos += 4
        elif wt == 1:
            pos += 8
        else:
            break
    return out_els


def _get_openfreemap_tile_template(cache_dir: Path) -> str:
    global _OPENFREEMAP_TPL_MEM
    now = time.time()
    if _OPENFREEMAP_TPL_MEM[1] and now - _OPENFREEMAP_TPL_MEM[0] < 3600.0:
        return _OPENFREEMAP_TPL_MEM[1]
    tpl_cache_file = cache_dir / 'mvt_openfreemap' / 'planet_tpl.txt'
    try:
        resp = requests.get('https://tiles.openfreemap.org/planet', headers={'User-Agent': USER_AGENT}, timeout=(2.5, 4.5))
        if resp.status_code == 200:
            tj = resp.json()
            tiles = tj.get('tiles') or []
            if tiles and isinstance(tiles[0], str) and '{z}' in tiles[0]:
                tpl = str(tiles[0])
                _OPENFREEMAP_TPL_MEM = (now, tpl)
                tpl_cache_file.parent.mkdir(parents=True, exist_ok=True)
                tpl_cache_file.write_text(tpl, encoding='utf-8')
                return tpl
    except Exception:
        pass
    if tpl_cache_file.is_file():
        try:
            cached = tpl_cache_file.read_text(encoding='utf-8').strip()
            if '{z}' in cached:
                _OPENFREEMAP_TPL_MEM = (now, cached)
                return cached
        except Exception:
            pass
    return ''


def fetch_mvt_openfreemap(south: float, west: float, north: float, east: float, cache_dir: Path, include_roads: bool = True, include_buildings: bool = True, include_water: bool = True) -> Tuple[bool, List[Dict[str, Any]]]:
    tpl = _get_openfreemap_tile_template(cache_dir)
    if not tpl:
        return False, []
    zoom = 14
    x_min_f, y_min_f = latlon_to_tile_float(north, west, zoom)
    x_max_f, y_max_f = latlon_to_tile_float(south, east, zoom)
    tx0, tx1 = int(math.floor(x_min_f)), int(math.floor(x_max_f))
    ty0, ty1 = int(math.floor(y_min_f)), int(math.floor(y_max_f))
    ver_slug = hashlib.md5(tpl.encode('utf-8')).hexdigest()[:10]
    coords = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)][:16]

    def _dl_one(item: Tuple[int, int]) -> Tuple[int, int, Optional[bytes]]:
        tx_i, ty_i = item
        u = tpl.replace('{z}', str(zoom)).replace('{x}', str(tx_i)).replace('{y}', str(ty_i))
        cp = cache_dir / 'mvt_openfreemap' / ver_slug / str(zoom) / str(tx_i) / f'{ty_i}.pbf'
        raw = _fetch_tile_bytes(u, cp, timeout=6.5)
        return tx_i, ty_i, raw

    all_els = []
    ok_tiles = 0
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(coords)))) as pool:
        for tx_i, ty_i, raw_pbf in pool.map(_dl_one, coords):
            if not raw_pbf:
                continue
            ok_tiles += 1
            try:
                all_els.extend(_decode_mvt_tile_elements(raw_pbf, zoom, tx_i, ty_i, include_roads=include_roads, include_buildings=include_buildings, include_water=include_water))
            except Exception:
                pass
    return ok_tiles == len(coords) and ok_tiles > 0, all_els


def _fetch_single_overpass_subtile(south: float, west: float, north: float, east: float, cache_dir: Path, tile_seed: int = 0, roads_only: bool = False) -> Tuple[bool, List[Dict[str, Any]], bool]:
    mode_tag = 'rd' if roads_only else 'full'
    key_str = f'v221_{mode_tag}_{south:.5f}_{west:.5f}_{north:.5f}_{east:.5f}'
    cache_hash = hashlib.md5(key_str.encode('utf-8')).hexdigest()[:16]
    cache_file = cache_dir / 'osm_overpass' / f'osm_v221_{mode_tag}_{cache_hash}.json'
    if cache_file.is_file() and cache_file.stat().st_size > 32:
        try:
            doc = json.loads(cache_file.read_text(encoding='utf-8'))
            if isinstance(doc, dict) and isinstance(doc.get('elements'), list) and 'remark' not in doc:
                return True, doc['elements'], False
        except Exception:
            pass
    bb = f'{south:.6f},{west:.6f},{north:.6f},{east:.6f}'
    if roads_only:
        query = (f'[out:json][timeout:7];(way["highway"]({bb});way["natural"="water"]({bb});'
                 f'way["waterway"="riverbank"]({bb}););out geom qt;')
        read_to = 6.5
    else:
        query = (f'[out:json][timeout:9];(way["highway"]({bb});way["building"]({bb});'
                 f'relation["building"]({bb});way["natural"="water"]({bb});'
                 f'way["waterway"="riverbank"]({bb});way["leisure"="park"]({bb});'
                 f'node["natural"="tree"]({bb}););out geom qt;')
        read_to = 8.5
    n_eps = len(OVERPASS_ENDPOINTS)
    ordered_eps = [OVERPASS_ENDPOINTS[(tile_seed + i) % n_eps] for i in range(n_eps)]
    saw_overload = False

    def _call_ep(ep_url: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        try:
            resp = requests.post(ep_url, data={'data': query}, headers={'User-Agent': USER_AGENT}, timeout=(2.5, read_to))
            if resp.status_code == 200:
                parsed = resp.json()
                if isinstance(parsed, dict) and isinstance(parsed.get('elements'), list) and 'remark' not in parsed:
                    return parsed, False
                return None, True
            if resp.status_code in (429, 502, 503, 504):
                return None, True
        except Exception:
            return None, True
        return None, False

    best_doc = None
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futs = [pool.submit(_call_ep, ep) for ep in ordered_eps[:2]]
        for fut in as_completed(futs):
            res, overloaded = fut.result()
            if overloaded:
                saw_overload = True
            if res is None:
                continue
            if best_doc is None or len(res['elements']) > len(best_doc['elements']):
                best_doc = res
            if len(best_doc['elements']) > 0:
                break
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if best_doc is None and not saw_overload:
        for ep in ordered_eps[2:]:
            res, overloaded = _call_ep(ep)
            if overloaded:
                saw_overload = True
            if res is None:
                continue
            best_doc = res
            break
    if best_doc is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(best_doc, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
        return True, best_doc['elements'], False
    return False, [], saw_overload


def fetch_osm_overpass(south: float, west: float, north: float, east: float, cache_dir: Path, include_roads: bool = True, include_buildings: bool = True, include_water: bool = True) -> Dict[str, Any]:
    osm_cache_dir = cache_dir / 'osm_overpass'
    if osm_cache_dir.is_dir():
        for old_f in list(osm_cache_dir.glob('osm_*.json'))[:24]:
            if old_f.name.startswith('osm_v22'):
                continue
            try:
                txt = old_f.read_text(encoding='utf-8', errors='ignore')
                if '"remark"' in txt or '"elements": []' in txt or '"elements":[]' in txt:
                    old_f.unlink(missing_ok=True)
            except Exception:
                pass
    peak_window = is_vietnam_peak_map_hour()
    mvt_ok, mvt_elements = fetch_mvt_openfreemap(south, west, north, east, cache_dir=cache_dir, include_roads=include_roads, include_buildings=include_buildings, include_water=include_water)
    mvt_roads_n = sum(1 for e in mvt_elements if 'highway' in (e.get('tags') or {}))
    mvt_bldgs_n = sum(1 for e in mvt_elements if 'building' in (e.get('tags') or {}))
    if mvt_ok and mvt_roads_n >= 18 and (not include_buildings or mvt_bldgs_n >= 25):
        return {'elements': mvt_elements, 'all_subtiles_ok': True, 'mvt_used': True, 'peak_hour_window': peak_window, 'peak_hour_degraded': False}
    _, _, w_m, h_m = bbox_dimensions_meters(south, west, north, east)
    max_side_m = max(w_m, h_m)
    use_roads_only_overpass = max_side_m >= 1600.0 or peak_window or not include_buildings
    nx = max(1, min(2, int(math.ceil(w_m / 1800.0))))
    ny = max(1, min(2, int(math.ceil(h_m / 1800.0))))
    lat_edges = np.linspace(south, north, ny + 1)
    lon_edges = np.linspace(west, east, nx + 1)
    pad_lat = (north - south) * 0.008
    pad_lon = (east - west) * 0.008
    sub_jobs = []
    idx = 0
    for iy in range(ny):
        for ix in range(nx):
            s_i = float(lat_edges[iy]) - (pad_lat if iy > 0 else 0.0)
            n_i = float(lat_edges[iy + 1]) + (pad_lat if iy < ny - 1 else 0.0)
            w_i = float(lon_edges[ix]) - (pad_lon if ix > 0 else 0.0)
            e_i = float(lon_edges[ix + 1]) + (pad_lon if ix < nx - 1 else 0.0)
            sub_jobs.append((idx, s_i, w_i, n_i, e_i))
            idx += 1
    overpass_map = {}
    ok_count = 0
    any_overload = False
    with ThreadPoolExecutor(max_workers=min(2, len(sub_jobs))) as pool:
        fut_map = {pool.submit(_fetch_single_overpass_subtile, s_i, w_i, n_i, e_i, cache_dir, seed_i, use_roads_only_overpass): seed_i for seed_i, s_i, w_i, n_i, e_i in sub_jobs}
        for fut in as_completed(fut_map):
            ok_sub, els_sub, ov_flag = fut.result()
            if ov_flag:
                any_overload = True
            if ok_sub:
                ok_count += 1
            for el in els_sub:
                et = str(el.get('type') or '')
                eid = int(el.get('id') or 0)
                if not et or not eid:
                    continue
                overpass_map[(et, eid)] = el
    if mvt_elements and overpass_map:
        combined = list(overpass_map.values())
        if use_roads_only_overpass:
            combined.extend([e for e in mvt_elements if 'building' in (e.get('tags') or {})])
        final_els = combined
    elif overpass_map:
        final_els = list(overpass_map.values())
    else:
        final_els = mvt_elements
    degraded_bldg = bool(include_buildings and (any_overload or use_roads_only_overpass and mvt_bldgs_n < 15))
    return {'elements': final_els, 'all_subtiles_ok': ok_count == len(sub_jobs) or mvt_ok, 'mvt_used': mvt_ok, 'peak_hour_window': peak_window, 'peak_hour_degraded': degraded_bldg, 'overpass_overloaded': any_overload}


def _morph_dilate3(mask: np.ndarray, iters: int = 1) -> np.ndarray:
    cur = mask.astype(bool)
    for _ in range(max(1, iters)):
        p = np.pad(cur, 1, mode='constant', constant_values=False)
        cur = (
            p[:-2, :-2] | p[:-2, 1:-1] | p[:-2, 2:]
            | p[1:-1, :-2] | p[1:-1, 1:-1] | p[1:-1, 2:]
            | p[2:, :-2] | p[2:, 1:-1] | p[2:, 2:]
        )
    return cur


def _morph_erode3(mask: np.ndarray, iters: int = 1) -> np.ndarray:
    cur = mask.astype(bool)
    for _ in range(max(1, iters)):
        p = np.pad(cur, 1, mode='constant', constant_values=False)
        cur = (
            p[:-2, :-2] & p[:-2, 1:-1] & p[:-2, 2:]
            & p[1:-1, :-2] & p[1:-1, 1:-1] & p[1:-1, 2:]
            & p[2:, :-2] & p[2:, 1:-1] & p[2:, 2:]
        )
    return cur


def _thin_zhang_suen_numpy(binary_mask: np.ndarray, max_iters: int = 12) -> np.ndarray:
    skel = np.pad(binary_mask.astype(np.uint8), 1, mode='constant', constant_values=0)
    for _ in range(max_iters):
        changed = False
        for step in (1, 2):
            p1 = skel[1:-1, 1:-1]
            p2 = skel[:-2, 1:-1]
            p3 = skel[:-2, 2:]
            p4 = skel[1:-1, 2:]
            p5 = skel[2:, 2:]
            p6 = skel[2:, 1:-1]
            p7 = skel[2:, :-2]
            p8 = skel[1:-1, :-2]
            p9 = skel[:-2, :-2]
            b_sum = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            a_trans = (
                ((p2 == 0) & (p3 == 1)).astype(np.uint8)
                + ((p3 == 0) & (p4 == 1)).astype(np.uint8)
                + ((p4 == 0) & (p5 == 1)).astype(np.uint8)
                + ((p5 == 0) & (p6 == 1)).astype(np.uint8)
                + ((p6 == 0) & (p7 == 1)).astype(np.uint8)
                + ((p7 == 0) & (p8 == 1)).astype(np.uint8)
                + ((p8 == 0) & (p9 == 1)).astype(np.uint8)
                + ((p9 == 0) & (p2 == 1)).astype(np.uint8)
            )
            cond = (p1 == 1) & (b_sum >= 2) & (b_sum <= 6) & (a_trans == 1)
            if step == 1:
                cond &= (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond &= (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            if np.any(cond):
                skel[1:-1, 1:-1][cond] = 0
                changed = True
        if not changed:
            break
    return skel[1:-1, 1:-1].astype(bool)


def _rdp_simplify_2d(pts: List[Tuple[float, float]], eps: float) -> List[Tuple[float, float]]:
    if len(pts) <= 2:
        return pts
    stack = [(0, len(pts) - 1)]
    keep = [False] * len(pts)
    keep[0] = True
    keep[-1] = True
    eps2 = eps * eps
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 <= 1:
            continue
        x0, y0 = pts[i0]
        x1, y1 = pts[i1]
        dx, dy = x1 - x0, y1 - y0
        seg_len2 = dx * dx + dy * dy
        max_d2 = -1.0
        max_idx = i0
        for k in range(i0 + 1, i1):
            px, py = pts[k]
            if seg_len2 < 1e-12:
                d2 = (px - x0) ** 2 + (py - y0) ** 2
            else:
                t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg_len2))
                proj_x = x0 + t * dx
                proj_y = y0 + t * dy
                d2 = (px - proj_x) ** 2 + (py - proj_y) ** 2
            if d2 > max_d2:
                max_d2 = d2
                max_idx = k
        if max_d2 > eps2:
            keep[max_idx] = True
            stack.append((i0, max_idx))
            stack.append((max_idx, i1))
    return [pt for pt, flg in zip(pts, keep) if flg]


def _trace_skeleton_chains(skel: np.ndarray) -> List[List[Tuple[int, int]]]:
    ys, xs = np.nonzero(skel)
    if len(xs) == 0:
        return []
    px_set = set(zip(xs.tolist(), ys.tolist()))
    nbr_offsets = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
    adj = {}
    for x, y in px_set:
        adj[(x, y)] = [(x + dx, y + dy) for dx, dy in nbr_offsets if (x + dx, y + dy) in px_set]
    visited_edges = set()
    chains = []

    def _edge_key(a: Tuple[int, int], b: Tuple[int, int]):
        return (a, b) if a <= b else (b, a)

    seeds = [pt for pt, nbs in adj.items() if len(nbs) != 2] + [pt for pt, nbs in adj.items() if len(nbs) == 2]
    for start in seeds:
        for nb in adj[start]:
            ek = _edge_key(start, nb)
            if ek in visited_edges:
                continue
            visited_edges.add(ek)
            chain = [start, nb]
            prev, cur = start, nb
            while len(adj[cur]) == 2:
                n0, n1 = adj[cur]
                nxt = n1 if n0 == prev else n0
                ek2 = _edge_key(cur, nxt)
                if ek2 in visited_edges:
                    break
                visited_edges.add(ek2)
                chain.append(nxt)
                prev, cur = cur, nxt
                if cur == start:
                    break
            if len(chain) >= 4:
                chains.append(chain)
    return chains


def _rasterize_osm_polylines_mask(polylines_xy: List[List[Tuple[float, float]]], xmin_l: float, xmax_l: float, ymin_l: float, ymax_l: float, grid_w: int, grid_h: int, buffer_m: float = 16.0) -> np.ndarray:
    mask = np.zeros((grid_h, grid_w), dtype=bool)
    span_x = max(1.0, xmax_l - xmin_l)
    span_y = max(1.0, ymax_l - ymin_l)
    for chain in polylines_xy:
        for i in range(len(chain) - 1):
            x0, y0 = chain[i]
            x1, y1 = chain[i + 1]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            steps = max(2, int(seg_len / max(2.0, span_x / grid_w)) + 1)
            ts = np.linspace(0.0, 1.0, steps)
            xs = x0 + (x1 - x0) * ts
            ys = y0 + (y1 - y0) * ts
            cols = np.clip(((xs - xmin_l) / span_x * (grid_w - 1)).astype(np.int32), 0, grid_w - 1)
            rows = np.clip(((ymax_l - ys) / span_y * (grid_h - 1)).astype(np.int32), 0, grid_h - 1)
            mask[rows, cols] = True
    m_per_px = max(0.5, span_x / grid_w)
    dil_iters = max(1, min(10, int(round(buffer_m / m_per_px))))
    return _morph_dilate3(mask, iters=dil_iters)


def _download_lossless_roadmap_rgb(south: float, west: float, north: float, east: float, cache_dir: Path, max_work_px: int = 1792) -> Optional[np.ndarray]:
    _, _, w_m, h_m = bbox_dimensions_meters(south, west, north, east)
    max_side_m = max(w_m, h_m)
    if max_side_m <= 1650.0:
        zoom = 17
    elif max_side_m <= 3400.0:
        zoom = 16
    else:
        zoom = 15
    x_min_f, y_min_f = latlon_to_tile_float(north, west, zoom)
    x_max_f, y_max_f = latlon_to_tile_float(south, east, zoom)
    tx0, tx1 = int(math.floor(x_min_f)), int(math.floor(x_max_f))
    ty0, ty1 = int(math.floor(y_min_f)), int(math.floor(y_max_f))
    nx = max(1, tx1 - tx0 + 1)
    ny = max(1, ty1 - ty0 + 1)
    while nx * ny > 144 and zoom > 15:
        zoom -= 1
        x_min_f, y_min_f = latlon_to_tile_float(north, west, zoom)
        x_max_f, y_max_f = latlon_to_tile_float(south, east, zoom)
        tx0, tx1 = int(math.floor(x_min_f)), int(math.floor(x_max_f))
        ty0, ty1 = int(math.floor(y_min_f)), int(math.floor(y_max_f))
        nx = max(1, tx1 - tx0 + 1)
        ny = max(1, ty1 - ty0 + 1)
    canvas = Image.new('RGB', (nx * 256, ny * 256), (246, 245, 245))
    tasks = [(tx - tx0, ty - ty0, tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]

    def _fetch_rm(item: Tuple[int, int, int, int]) -> Tuple[int, int, Optional[bytes]]:
        ix, iy, tx_i, ty_i = item
        for prov in ('google_street_nolabel', 'google_street'):
            u = _satellite_tile_url(prov, zoom, tx_i, ty_i)
            cp = cache_dir / 'sat_tiles' / prov / str(zoom) / str(tx_i) / f'{ty_i}.png'
            raw = _fetch_tile_bytes(u, cp, timeout=7.5)
            if raw:
                return ix, iy, raw
        return ix, iy, None

    loaded = 0
    with ThreadPoolExecutor(max_workers=12) as pool:
        for ix, iy, raw in pool.map(_fetch_rm, tasks):
            if not raw:
                continue
            try:
                canvas.paste(Image.open(io.BytesIO(raw)).convert('RGB'), (ix * 256, iy * 256))
                loaded += 1
            except Exception:
                pass
    if loaded == 0:
        return None
    px_l = int(round((x_min_f - tx0) * 256.0))
    px_t = int(round((y_min_f - ty0) * 256.0))
    px_r = max(px_l + 16, int(round((x_max_f - tx0) * 256.0)))
    px_b = max(px_t + 16, int(round((y_max_f - ty0) * 256.0)))
    cropped = canvas.crop((px_l, px_t, min(canvas.width, px_r), min(canvas.height, px_b)))
    cw, ch = cropped.size
    if max(cw, ch) > max_work_px:
        sc = max_work_px / float(max(cw, ch))
        cropped = cropped.resize((max(256, int(round(cw * sc))), max(256, int(round(ch * sc)))), Image.Resampling.NEAREST)
    return np.asarray(cropped, dtype=np.uint8)


def extract_google_street_vectors(south: float, west: float, north: float, east: float, cache_dir: Path, xmin_local: float, xmax_local: float, ymin_local: float, ymax_local: float, existing_osm_roads_xy: List[List[Tuple[float, float]]], existing_osm_bldgs_xy: List[Tuple[float, float]], need_roads: bool = True, need_buildings: bool = True, custom_roadmap_rgb: Optional[np.ndarray] = None) -> Tuple[List[List[Tuple[float, float]]], List[List[Tuple[float, float]]], List[List[Tuple[float, float]]]]:
    if custom_roadmap_rgb is not None:
        rgb = np.asarray(custom_roadmap_rgb, dtype=np.uint8)
    else:
        max_span_m = max(abs(xmax_local - xmin_local), abs(ymax_local - ymin_local))
        work_px = 1792 if max_span_m > 1600.0 else 1152
        rgb_dl = _download_lossless_roadmap_rgb(south, west, north, east, cache_dir=cache_dir, max_work_px=work_px)
        if rgb_dl is None:
            return [], [], []
        rgb = rgb_dl
    gh, gw = rgb.shape[:2]
    span_x = max(1.0, xmax_local - xmin_local)
    span_y = max(1.0, ymax_local - ymin_local)
    m_per_px = 0.5 * (span_x / gw + span_y / gh)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    c_max = np.maximum(np.maximum(r, g), b)
    c_min = np.minimum(np.minimum(r, g), b)
    chroma = c_max - c_min
    is_water = ((b - r) >= 42) & (g >= 190) & (r <= 178)
    is_park = (g - r) >= 15
    is_water_or_park = is_water | is_park
    cool_slate_road = ((r >= 198) & (r <= 222) & (g >= 208) & (g <= 228) & (b >= 217) & (b <= 236)
                       & ((b - r) >= 11) & ((b - r) <= 28) & ((g - r) >= 5) & ((b - g) >= 4) & ~is_water_or_park)
    slate_arterial_border = ((r >= 126) & (r <= 168) & (g >= 150) & (g <= 188) & (b >= 178) & (b <= 212)
                             & ((b - r) >= 32) & ~is_water)
    yellow_arterial = (r >= 232) & (g >= 162) & (g <= 236) & ((r - b) >= 28) & ~is_water_or_park
    white_px = (r >= 251) & (g >= 250) & (b >= 250) & (chroma <= 5) & ~is_water_or_park
    max_ribbon_half = max(3, min(9, int(round(13.0 / max(1.0, m_per_px)))))
    large_white_land = _morph_dilate3(_morph_erode3(white_px, iters=max_ribbon_half), iters=max_ribbon_half + 2)
    white_road_ribbon = white_px & ~large_white_land
    all_road_cand = _morph_erode3(_morph_dilate3(cool_slate_road | white_road_ribbon | yellow_arterial, iters=1), iters=1)
    wide_iters = max(2, int(round(5.6 / max(1.0, m_per_px))))
    wide_core = _morph_erode3(all_road_cand, iters=wide_iters)
    wide_main = _morph_dilate3(wide_core, iters=wide_iters + 1) & all_road_cand
    bordered_main = _morph_dilate3(slate_arterial_border, iters=max(3, int(round(6.5 / max(1.0, m_per_px))))) & cool_slate_road
    raw_main_mask = _morph_erode3(_morph_dilate3(yellow_arterial | wide_main | bordered_main, iters=1), iters=1)
    raw_alley_mask = all_road_cand & ~_morph_dilate3(raw_main_mask, iters=1)
    main_chains_xy = []
    alley_chains_xy = []
    bldg_polys_xy = []

    def _px_to_local(col_f: float, row_f: float) -> Tuple[float, float]:
        lx = xmin_local + col_f / max(1, gw - 1) * span_x
        ly = ymax_local - row_f / max(1, gh - 1) * span_y
        return lx, ly

    def _polyline_len(pts: List[Tuple[float, float]]) -> float:
        return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))

    if need_roads:
        osm_road_cov = (_rasterize_osm_polylines_mask(existing_osm_roads_xy, xmin_local, xmax_local, ymin_local, ymax_local, gw, gh, buffer_m=15.0)
                        if existing_osm_roads_xy else np.zeros((gh, gw), dtype=bool))
        gap_main = raw_main_mask & ~osm_road_cov
        gap_alley = raw_alley_mask & ~osm_road_cov
        min_road_len_m = max(18.0, 4.2 * m_per_px)
        simp_eps_m = max(1.3, 0.7 * m_per_px)
        if np.count_nonzero(gap_main) >= 6:
            skel_m = _thin_zhang_suen_numpy(gap_main)
            for ch_px in _trace_skeleton_chains(skel_m):
                pts_l = _rdp_simplify_2d([_px_to_local(float(cx), float(cy)) for cx, cy in ch_px], simp_eps_m)
                if len(pts_l) >= 2 and _polyline_len(pts_l) >= min_road_len_m:
                    main_chains_xy.append(pts_l)
        if np.count_nonzero(gap_alley) >= 6:
            skel_a = _thin_zhang_suen_numpy(gap_alley)
            for ch_px in _trace_skeleton_chains(skel_a):
                pts_l = _rdp_simplify_2d([_px_to_local(float(cx), float(cy)) for cx, cy in ch_px], simp_eps_m)
                if len(pts_l) >= 2 and _polyline_len(pts_l) >= min_road_len_m:
                    alley_chains_xy.append(pts_l)
    if need_buildings and m_per_px <= 5.8:
        bldg_cov = np.zeros((gh, gw), dtype=bool)
        if existing_osm_bldgs_xy:
            bx = np.asarray([p[0] for p in existing_osm_bldgs_xy], dtype=np.float64)
            by = np.asarray([p[1] for p in existing_osm_bldgs_xy], dtype=np.float64)
            bcols = np.clip(((bx - xmin_local) / span_x * (gw - 1)).astype(np.int32), 0, gw - 1)
            brows = np.clip(((ymax_local - by) / span_y * (gh - 1)).astype(np.int32), 0, gh - 1)
            bldg_cov[brows, bcols] = True
            bldg_cov = _morph_dilate3(bldg_cov, iters=max(2, int(round(20.0 / max(1.0, m_per_px)))))
        any_road_px = raw_main_mask | raw_alley_mask
        road_border_px = _morph_dilate3(any_road_px | slate_arterial_border, iters=2)
        near_any_road = _morph_dilate3(any_road_px, iters=max(3, int(round(36.0 / max(1.0, m_per_px)))))
        neutral_bldg = ((r >= 224) & (r <= 240) & (g >= 224) & (g <= 240) & (b >= 222) & (b <= 243)
                        & ((b - r) >= -2) & ((b - r) <= 10) & (chroma <= 11))
        cream_comm_bldg = ((r >= 247) & (r <= 254) & (g >= 242) & (g <= 250) & (b >= 230) & (b <= 240)
                           & ((r - b) >= 10) & ((r - b) <= 22))
        bldg_px = (neutral_bldg | cream_comm_bldg) & ~is_water_or_park & ~road_border_px & near_any_road & ~bldg_cov
        if np.count_nonzero(bldg_px) >= 10:
            visited_b = np.zeros((gh, gw), dtype=bool)
            rys, rxs = np.nonzero(bldg_px)
            px_area_m2 = m_per_px * m_per_px
            candidates_b = []
            for sy, sx in zip(rys.tolist(), rxs.tolist()):
                if visited_b[sy, sx]:
                    continue
                q = [(sx, sy)]
                visited_b[sy, sx] = True
                comp_x = [sx]
                comp_y = [sy]
                while q and len(comp_x) < 950:
                    cx, cy = q.pop()
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nx_p, ny_p = cx + dx, cy + dy
                        if 0 <= nx_p < gw and 0 <= ny_p < gh and bldg_px[ny_p, nx_p] and not visited_b[ny_p, nx_p]:
                            visited_b[ny_p, nx_p] = True
                            comp_x.append(nx_p)
                            comp_y.append(ny_p)
                            q.append((nx_p, ny_p))
                area_est = len(comp_x) * px_area_m2
                if 20.0 <= area_est <= 2200.0:
                    c0, c1 = min(comp_x), max(comp_x)
                    r0, r1 = min(comp_y), max(comp_y)
                    if c1 - c0 >= 2 and r1 - r0 >= 2:
                        p_bl = _px_to_local(float(c0), float(r1))
                        p_br = _px_to_local(float(c1), float(r1))
                        p_tr = _px_to_local(float(c1), float(r0))
                        p_tl = _px_to_local(float(c0), float(r0))
                        candidates_b.append((area_est, [p_bl, p_br, p_tr, p_tl]))
            if len(candidates_b) > 3200:
                step_b = max(1, len(candidates_b) // 3200)
                bldg_polys_xy = [it[1] for it in candidates_b[::step_b][:3200]]
            else:
                bldg_polys_xy = [it[1] for it in candidates_b]
    return main_chains_xy, alley_chains_xy, bldg_polys_xy


def _clip_triangles_to_rect_2d(pts: List[Tuple[float, float]], tris: List[Tuple[int, int, int]], xmin: float, xmax: float, ymin: float, ymax: float) -> Tuple[List[Tuple[float, float]], List[Tuple[int, int, int]]]:
    if not pts or not tris:
        return [], []

    def _clip_poly_halfplane(poly, inside_fn, intersect_fn):
        if not poly:
            return []
        out = []
        s = poly[-1]
        s_in = inside_fn(s)
        for e in poly:
            e_in = inside_fn(e)
            if e_in:
                if not s_in:
                    out.append(intersect_fn(s, e))
                out.append(e)
            elif s_in:
                out.append(intersect_fn(s, e))
            s = e
            s_in = e_in
        return out

    def _ix_x(a, b, x_bound):
        dx = b[0] - a[0]
        t = 0.0 if abs(dx) < 1e-12 else (x_bound - a[0]) / dx
        return x_bound, a[1] + t * (b[1] - a[1])

    def _ix_y(a, b, y_bound):
        dy = b[1] - a[1]
        t = 0.0 if abs(dy) < 1e-12 else (y_bound - a[1]) / dy
        return a[0] + t * (b[0] - a[0]), y_bound

    out_pts = []
    out_tris = []
    vert_map = {}

    def _add_v(pt):
        key = (int(round(pt[0] * 1000.0)), int(round(pt[1] * 1000.0)))
        idx = vert_map.get(key)
        if idx is None:
            idx = len(out_pts)
            out_pts.append((float(pt[0]), float(pt[1])))
            vert_map[key] = idx
        return idx

    for ia, ib, ic in tris:
        p0, p1, p2 = pts[ia], pts[ib], pts[ic]
        if ((p0[0] < xmin and p1[0] < xmin and p2[0] < xmin) or
            (p0[0] > xmax and p1[0] > xmax and p2[0] > xmax) or
            (p0[1] < ymin and p1[1] < ymin and p2[1] < ymin) or
            (p0[1] > ymax and p1[1] > ymax and p2[1] > ymax)):
            continue
        if (xmin <= p0[0] <= xmax and ymin <= p0[1] <= ymax and
            xmin <= p1[0] <= xmax and ymin <= p1[1] <= ymax and
            xmin <= p2[0] <= xmax and ymin <= p2[1] <= ymax):
            v0, v1, v2 = _add_v(p0), _add_v(p1), _add_v(p2)
            if v0 != v1 and v1 != v2 and v2 != v0:
                out_tris.append((v0, v1, v2))
            continue
        poly = [p0, p1, p2]
        poly = _clip_poly_halfplane(poly, lambda p: p[0] >= xmin, lambda a,b: _ix_x(a,b,xmin))
        poly = _clip_poly_halfplane(poly, lambda p: p[0] <= xmax, lambda a,b: _ix_x(a,b,xmax))
        poly = _clip_poly_halfplane(poly, lambda p: p[1] >= ymin, lambda a,b: _ix_y(a,b,ymin))
        poly = _clip_poly_halfplane(poly, lambda p: p[1] <= ymax, lambda a,b: _ix_y(a,b,ymax))
        if len(poly) < 3:
            continue
        v_indices = [_add_v(p) for p in poly]
        v0 = v_indices[0]
        for k in range(1, len(v_indices) - 1):
            v1, v2 = v_indices[k], v_indices[k + 1]
            if v0 != v1 and v1 != v2 and v2 != v0:
                p_a, p_b, p_c = out_pts[v0], out_pts[v1], out_pts[v2]
                area2 = abs((p_b[0] - p_a[0]) * (p_c[1] - p_a[1]) - (p_b[1] - p_a[1]) * (p_c[0] - p_a[0]))
                if area2 > 1e-4:
                    out_tris.append((v0, v1, v2))
    return out_pts, out_tris


def _extrude_polygon_on_terrain(poly_xy: List[Tuple[float, float]], height_m: float, half_w: float, half_h: float, dem_grid: np.ndarray, skirt_depth_m: float = 2.5, min_z_base: Optional[float] = None) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    pts, roof_tris = triangulate_polygon_2d(poly_xy)
    if len(pts) < 3 or not roof_tris:
        return None
    zs_ground = [sample_dem_bilinear(x, y, half_w, half_h, dem_grid) for x, y in pts]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    z_center = sample_dem_bilinear(cx, cy, half_w, half_h, dem_grid)
    z_roof = z_center + max(2.8, height_m)
    z_base = min(zs_ground) - abs(skirt_depth_m)
    if min_z_base is not None:
        z_base = min(z_roof - 0.5, max(float(min_z_base), z_base))
    n = len(pts)
    verts = np.zeros((2 * n, 3), dtype=np.float32)
    for i, (x, y) in enumerate(pts):
        verts[i] = (x, y, z_base)
        verts[n + i] = (x, y, z_roof)
    faces = []
    for i in range(n):
        inext = (i + 1) % n
        b0, b1 = i, inext
        t0, t1 = n + i, n + inext
        faces.append((b0, b1, t1))
        faces.append((b0, t1, t0))
    for a, b, c in roof_tris:
        faces.append((n + a, n + b, n + c))
        faces.append((a, c, b))
    return verts, np.asarray(faces, dtype=np.uint32)


def _extrude_textured_building_on_terrain(poly_xy: List[Tuple[float, float]], height_m: float, half_w: float, half_h: float, dem_grid: np.ndarray, facade_spec: Dict[str, Any], skirt_depth_m: float = 2.5) -> Optional[Tuple[Tuple[np.ndarray, np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray]]]:
    pts, roof_tris = triangulate_polygon_2d(poly_xy)
    n = len(pts)
    if n < 3 or not roof_tris:
        return None
    zs_ground = [sample_dem_bilinear(x, y, half_w, half_h, dem_grid) for x, y in pts]
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    z_center = sample_dem_bilinear(cx, cy, half_w, half_h, dem_grid)
    h_eff = max(2.8, float(height_m))
    z_roof = z_center + h_eff
    z_base = min(zs_ground) - abs(skirt_depth_m)
    bay_w_m = max(1.2, float(facade_spec.get('bay_w_m', 3.2)))
    floor_h_m = max(2.6, float(facade_spec.get('floor_h_m', 3.4)))
    bays_per_tile = max(1, int(facade_spec.get('bays_per_tile', 4)))
    floors_per_tile = max(1, int(facade_spec.get('floors_per_tile', 4)))
    floors = max(1, int(round(h_eff / floor_h_m)))
    v_roof = floors / float(floors_per_tile)
    v_per_m = v_roof / max(1.0, z_roof - z_center)
    v_base = (z_base - z_center) * v_per_m
    seg_dirs = []
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln > 1e-6:
            seg_dirs.append((dx / ln, dy / ln, ln))
        else:
            seg_dirs.append((1.0, 0.0, 0.0))
    sharp_corners = []
    for i in range(n):
        prev_i = (i - 1) % n
        d0x, d0y, l0 = seg_dirs[prev_i]
        d1x, d1y, l1 = seg_dirs[i]
        if l0 <= 1e-4 or l1 <= 1e-4 or d0x * d1x + d0y * d1y < 0.866:
            sharp_corners.append(i)
    if not sharp_corners:
        sharp_corners = [0]
    wall_verts_l = []
    wall_uvs_l = []
    wall_faces_l = []
    num_runs = len(sharp_corners)
    for r_idx in range(num_runs):
        s_i = sharp_corners[r_idx]
        e_i = sharp_corners[(r_idx + 1) % num_runs]
        run_edges = [s_i]
        cur_i = (s_i + 1) % n
        while cur_i != e_i:
            run_edges.append(cur_i)
            cur_i = (cur_i + 1) % n
            if len(run_edges) >= n:
                break
        run_len = sum(seg_dirs[ei][2] for ei in run_edges)
        if run_len <= 1e-4:
            continue
        run_bays = max(1, int(round(run_len / bay_w_m)))
        u_span_total = run_bays / float(bays_per_tile)
        acc_len = 0.0
        for ei in run_edges:
            seg_l = seg_dirs[ei][2]
            if seg_l <= 1e-4:
                continue
            x0, y0 = pts[ei]
            x1, y1 = pts[(ei + 1) % n]
            u0 = u_span_total * (acc_len / run_len)
            acc_len += seg_l
            u1 = u_span_total * (acc_len / run_len)
            base_v = len(wall_verts_l)
            wall_verts_l.extend([(x0,y0,z_base),(x1,y1,z_base),(x1,y1,z_roof),(x0,y0,z_roof)])
            wall_uvs_l.extend([(u0,v_base),(u1,v_base),(u1,v_roof),(u0,v_roof)])
            wall_faces_l.append((base_v,base_v + 1,base_v + 2))
            wall_faces_l.append((base_v,base_v + 2,base_v + 3))
    if not wall_faces_l:
        return None
    roof_verts = np.zeros((2 * n, 3), dtype=np.float32)
    for i,(x,y) in enumerate(pts):
        roof_verts[i] = (x,y,z_base)
        roof_verts[n + i] = (x,y,z_roof)
    roof_faces_l = []
    for a,b,c in roof_tris:
        roof_faces_l.append((n+a,n+b,n+c))
        roof_faces_l.append((a,c,b))
    return ((np.asarray(wall_verts_l,dtype=np.float32),np.asarray(wall_faces_l,dtype=np.uint32),np.asarray(wall_uvs_l,dtype=np.float32)),
            (roof_verts,np.asarray(roof_faces_l,dtype=np.uint32)))


def _clean_ccw_ring_2d(poly_xy: List[Tuple[float, float]], min_seg_m: float = 0.12) -> List[Tuple[float, float]]:
    pts = []
    for p in poly_xy:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > min_seg_m:
            pts.append((float(p[0]), float(p[1])))
    if len(pts) >= 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= min_seg_m:
        pts.pop()
    if len(pts) > 160:
        pts = _rdp_simplify_2d(pts, 0.65)
    if len(pts) < 3:
        return []
    if _signed_area_2d(pts) < 0.0:
        pts.reverse()
    filtered = []
    m = len(pts)
    for i in range(m):
        p_prev = pts[(i - 1) % m]
        p_cur = pts[i]
        p_next = pts[(i + 1) % m]
        dx1, dy1 = p_cur[0] - p_prev[0], p_cur[1] - p_prev[1]
        dx2, dy2 = p_next[0] - p_cur[0], p_next[1] - p_cur[1]
        l1 = math.hypot(dx1, dy1)
        l2 = math.hypot(dx2, dy2)
        if l1 <= 1e-4 or l2 <= 1e-4:
            continue
        dot_v = (dx1 * dx2 + dy1 * dy2) / (l1 * l2)
        cross_v = abs(dx1 * dy2 - dy1 * dx2) / (l1 * l2)
        if dot_v > 0.99985 and cross_v < 0.015 and len(pts) > 4:
            continue
        filtered.append(p_cur)
    return filtered if len(filtered) >= 3 else pts


def _segments_properly_intersect_2d(a0: Tuple[float, float], a1: Tuple[float, float], b0: Tuple[float, float], b1: Tuple[float, float]) -> bool:
    def _ccw_val(p: Tuple[float, float], q: Tuple[float, float], r: Tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if (max(a0[0], a1[0]) < min(b0[0], b1[0]) - 1e-6 or
        max(b0[0], b1[0]) < min(a0[0], a1[0]) - 1e-6 or
        max(a0[1], a1[1]) < min(b0[1], b1[1]) - 1e-6 or
        max(b0[1], b1[1]) < min(a0[1], a1[1]) - 1e-6):
        return False
    d1 = _ccw_val(a0, a1, b0)
    d2 = _ccw_val(a0, a1, b1)
    d3 = _ccw_val(b0, b1, a0)
    d4 = _ccw_val(b0, b1, a1)
    return d1 * d2 <= 1e-9 and d3 * d4 <= 1e-9


def _ear_clip_indexed_ccw(pts_ccw: List[Tuple[float, float]]) -> Optional[List[Tuple[int, int, int]]]:
    n = len(pts_ccw)
    if n < 3 or _signed_area_2d(pts_ccw) <= 1e-4:
        return None
    idxs = list(range(n))
    tris = []

    def _cross(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    def _in_tri(px: float, py: float, ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
        c1 = _cross(ax, ay, bx, by, px, py)
        c2 = _cross(bx, by, cx, cy, px, py)
        c3 = _cross(cx, cy, ax, ay, px, py)
        return c1 >= -1e-6 and c2 >= -1e-6 and c3 >= -1e-6

    guard = 0
    max_guard = n * n + 16
    while len(idxs) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        m = len(idxs)
        for k in range(m):
            ia = idxs[(k - 1) % m]
            ib = idxs[k]
            ic = idxs[(k + 1) % m]
            ax, ay = pts_ccw[ia]
            bx, by = pts_ccw[ib]
            cx, cy = pts_ccw[ic]
            if _cross(ax, ay, bx, by, cx, cy) <= 1e-6:
                continue
            blocked = False
            for j in idxs:
                if j in (ia, ib, ic):
                    continue
                if _in_tri(pts_ccw[j][0], pts_ccw[j][1], ax, ay, bx, by, cx, cy):
                    blocked = True
                    break
            if blocked:
                continue
            tris.append((ia, ib, ic))
            idxs.pop(k)
            ear_found = True
            break
        if not ear_found:
            return None
    if len(idxs) == 3:
        ia, ib, ic = idxs[0], idxs[1], idxs[2]
        if _cross(pts_ccw[ia][0], pts_ccw[ia][1], pts_ccw[ib][0], pts_ccw[ib][1], pts_ccw[ic][0], pts_ccw[ic][1]) > 1e-7:
            tris.append((ia, ib, ic))
    if len(tris) != n - 2:
        return None
    return tris


def _inset_polygon_2d_safe(pts_ccw: List[Tuple[float, float]], target_inset_m: float, min_area_ratio: float = 0.24) -> Optional[Tuple[List[Tuple[float, float]], List[Tuple[int, int, int]]]]:
    n = len(pts_ccw)
    if n < 3 or target_inset_m <= 0.04 or n > 96:
        return None
    area_outer = _signed_area_2d(pts_ccw)
    if area_outer <= 2.0:
        return None
    xs = [p[0] for p in pts_ccw]
    ys = [p[1] for p in pts_ccw]
    min_span = min(max(xs) - min(xs), max(ys) - min(ys))
    if min_span <= target_inset_m * 2.6:
        return None
    edge_vecs = []
    inward_normals = []
    for i in range(n):
        x0, y0 = pts_ccw[i]
        x1, y1 = pts_ccw[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln <= 1e-5:
            return None
        ux, uy = dx / ln, dy / ln
        edge_vecs.append((ux, uy, ln))
        inward_normals.append((-uy, ux))
    for scale_try in (1.0, 0.55):
        d_in = target_inset_m * scale_try
        if d_in < 0.08:
            break
        cand = []
        valid_step = True
        for i in range(n):
            n0x, n0y = inward_normals[(i - 1) % n]
            n1x, n1y = inward_normals[i]
            bx, by = n0x + n1x, n0y + n1y
            blen = math.hypot(bx, by)
            denom = 1.0 + (n0x * n1x + n0y * n1y)
            if blen <= 1e-5 or denom <= 0.16:
                sx, sy = n1x * d_in, n1y * d_in
            else:
                miter_len = min(d_in * 2.2, d_in * blen / denom)
                sx, sy = bx / blen * miter_len, by / blen * miter_len
            cand.append((pts_ccw[i][0] + sx, pts_ccw[i][1] + sy))
        for i in range(n):
            ix0, iy0 = cand[i]
            ix1, iy1 = cand[(i + 1) % n]
            idx, idy = ix1 - ix0, iy1 - iy0
            iln = math.hypot(idx, idy)
            ox, oy, _ = edge_vecs[i]
            if iln < 0.14 or idx * ox + idy * oy <= 0.05 * iln:
                valid_step = False
                break
        if not valid_step:
            continue
        area_in = _signed_area_2d(cand)
        if area_in < max(1.0, area_outer * min_area_ratio) or area_in >= area_outer:
            continue
        has_cross = False
        for i in range(n):
            a0, a1 = cand[i], cand[(i + 1) % n]
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                b0, b1 = cand[j], cand[(j + 1) % n]
                if _segments_properly_intersect_2d(a0, a1, b0, b1):
                    has_cross = True
                    break
            if has_cross:
                break
        if has_cross:
            continue
        inner_tris = _ear_clip_indexed_ccw(cand)
        if inner_tris is not None:
            return cand, inner_tris
    return None


def _longest_edge_axis_2d(pts: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    best_l = -1.0
    ux, uy = 1.0, 0.0
    x0, y0 = pts[0]
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy)
        if ln > best_l:
            best_l = ln
            if ln > 1e-6:
                ux, uy = dx / ln, dy / ln
                x0, y0 = ax, ay
    return ux, uy, x0, y0


def _point_in_polygon_2d(px: float, py: float, poly: List[Tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / max(1e-12, yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _min_dist_to_poly_edges_2d(px: float, py: float, poly: List[Tuple[float, float]]) -> float:
    best = 1e12
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        vx, vy = bx - ax, by - ay
        l2 = vx * vx + vy * vy
        if l2 <= 1e-10:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / l2))
            d = math.hypot(px - (ax + t * vx), py - (ay + t * vy))
        if d < best:
            best = d
    return best


def _extrude_wall_tier_uv(pts_ccw: List[Tuple[float, float]], z_bot: float, z_top: float, z_ref_ground: float, facade_spec: Dict[str, Any], b_id: int, tier_salt: int = 0) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    n = len(pts_ccw)
    h_span = z_top - z_bot
    if n < 3 or h_span <= 0.15:
        return None
    bay_w_m = max(1.2, float(facade_spec.get('bay_w_m', 3.2)))
    floor_h_m = max(2.6, float(facade_spec.get('floor_h_m', 3.5)))
    bays_per_tile = max(1, int(facade_spec.get('bays_per_tile', 12)))
    floors_per_tile = max(1, int(facade_spec.get('floors_per_tile', 12)))
    visible_h = max(floor_h_m, z_top - max(z_bot, z_ref_ground))
    vis_floors = max(1, int(round(visible_h / floor_h_m)))
    v_per_m = vis_floors / float(floors_per_tile) / visible_h
    h_mix = ((int(b_id) * 2654435761) ^ (int(tier_salt) * 2246822519)) & 4294967295
    k_floor_shift = (h_mix >> 7) % floors_per_tile if b_id != 0 else 0
    v_top_anchor = (k_floor_shift + vis_floors) / float(floors_per_tile)
    v_bot = v_top_anchor - (z_top - z_bot) * v_per_m
    v_top = v_top_anchor
    seg_dirs = []
    for i in range(n):
        x0, y0 = pts_ccw[i]
        x1, y1 = pts_ccw[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        seg_dirs.append((dx / ln, dy / ln, ln) if ln > 1e-6 else (1.0, 0.0, 0.0))
    sharp_corners = []
    for i in range(n):
        d0x, d0y, l0 = seg_dirs[(i - 1) % n]
        d1x, d1y, l1 = seg_dirs[i]
        if l0 <= 1e-4 or l1 <= 1e-4 or d0x * d1x + d0y * d1y < 0.866:
            sharp_corners.append(i)
    if not sharp_corners:
        sharp_corners = [0]
    wall_verts_l = []
    wall_uvs_l = []
    wall_faces_l = []
    num_runs = len(sharp_corners)
    for r_idx in range(num_runs):
        s_i = sharp_corners[r_idx]
        e_i = sharp_corners[(r_idx + 1) % num_runs]
        run_edges = [s_i]
        cur_i = (s_i + 1) % n
        while cur_i != e_i:
            run_edges.append(cur_i)
            cur_i = (cur_i + 1) % n
            if len(run_edges) >= n:
                break
        run_len = sum(seg_dirs[ei][2] for ei in run_edges)
        if run_len <= 1e-4:
            continue
        run_bays = max(1, int(round(run_len / bay_w_m)))
        u_span_total = run_bays / float(bays_per_tile)
        k_bay_shift = ((h_mix >> 3) + r_idx * 5 + tier_salt * 3) % bays_per_tile if b_id != 0 else 0
        u_phase = k_bay_shift / float(bays_per_tile)
        acc_len = 0.0
        for ei in run_edges:
            seg_l = seg_dirs[ei][2]
            if seg_l <= 1e-4:
                continue
            x0, y0 = pts_ccw[ei]
            x1, y1 = pts_ccw[(ei + 1) % n]
            u0 = u_phase + u_span_total * (acc_len / run_len)
            acc_len += seg_l
            u1 = u_phase + u_span_total * (acc_len / run_len)
            base_v = len(wall_verts_l)
            wall_verts_l.extend([(x0, y0, z_bot), (x1, y1, z_bot), (x1, y1, z_top), (x0, y0, z_top)])
            wall_uvs_l.extend([(u0, v_bot), (u1, v_bot), (u1, v_top), (u0, v_top)])
            wall_faces_l.append((base_v, base_v + 1, base_v + 2))
            wall_faces_l.append((base_v, base_v + 2, base_v + 3))
    if not wall_faces_l:
        return None
    return (np.asarray(wall_verts_l, dtype=np.float32), np.asarray(wall_faces_l, dtype=np.uint32), np.asarray(wall_uvs_l, dtype=np.float32))


def _build_parapet_or_flat_roof_uv(pts_ccw: List[Tuple[float, float]], z_top: float, roof_spec: Dict[str, Any], use_parapet: bool, inset_m: float, recess_depth_m: float, b_id: int) -> Optional[Tuple[Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]], Tuple[np.ndarray, np.ndarray, np.ndarray], Optional[Tuple[List[Tuple[float, float]], List[Tuple[int, int, int]], float]]]]:
    n = len(pts_ccw)
    if n < 3:
        return None
    ux, uy, ox, oy = _longest_edge_axis_2d(pts_ccw)
    vx, vy = -uy, ux
    tile_w = max(1.0, float(roof_spec.get('tile_w_m', 6.0)))
    tile_h = max(1.0, float(roof_spec.get('tile_h_m', 6.0)))
    phase_u = (int(b_id) * 17 % 100) / 100.0
    phase_v = (int(b_id) * 31 % 100) / 100.0

    def _roof_uv(px: float, py: float) -> Tuple[float, float]:
        rx, ry = px - ox, py - oy
        u_val = (rx * vx + ry * vy) / tile_w + phase_u
        v_val = (rx * ux + ry * uy) / tile_h + phase_v
        return u_val, v_val

    if use_parapet:
        inset_res = _inset_polygon_2d_safe(pts_ccw, inset_m, min_area_ratio=0.25)
        if inset_res is not None:
            inner_pts, inner_tris = inset_res
            z_deck = z_top - abs(recess_depth_m)
            p_verts = []
            p_uvs = []
            p_faces = []
            p_tile = float(PARAPET_TRIM_SPEC.get('tile_w_m', 4.0))
            acc_p = 0.0
            for i in range(n):
                inext = (i + 1) % n
                ox0, oy0 = pts_ccw[i]
                ox1, oy1 = pts_ccw[inext]
                ix0, iy0 = inner_pts[i]
                ix1, iy1 = inner_pts[inext]
                seg_l = math.hypot(ox1 - ox0, oy1 - oy0)
                u0 = acc_p / p_tile
                acc_p += seg_l
                u1 = acc_p / p_tile
                bv = len(p_verts)
                p_verts.extend([(ox0, oy0, z_top), (ox1, oy1, z_top), (ix1, iy1, z_top), (ix0, iy0, z_top)])
                p_uvs.extend([(u0, 0.0), (u1, 0.0), (u1, 0.25), (u0, 0.25)])
                p_faces.append((bv, bv + 1, bv + 2))
                p_faces.append((bv, bv + 2, bv + 3))
                bv2 = len(p_verts)
                p_verts.extend([(ix0, iy0, z_top), (ix1, iy1, z_top), (ix1, iy1, z_deck), (ix0, iy0, z_deck)])
                v_drop = abs(recess_depth_m) / p_tile
                p_uvs.extend([(u0, 0.25), (u1, 0.25), (u1, 0.25 + v_drop), (u0, 0.25 + v_drop)])
                p_faces.append((bv2, bv2 + 1, bv2 + 2))
                p_faces.append((bv2, bv2 + 2, bv2 + 3))
            parapet_part = (np.asarray(p_verts, dtype=np.float32), np.asarray(p_faces, dtype=np.uint32), np.asarray(p_uvs, dtype=np.float32))
            d_verts = np.asarray([(px, py, z_deck) for px, py in inner_pts], dtype=np.float32)
            d_uvs = np.asarray([_roof_uv(px, py) for px, py in inner_pts], dtype=np.float32)
            d_faces = np.asarray(inner_tris, dtype=np.uint32)
            deck_part = (d_verts, d_faces, d_uvs)
            return parapet_part, deck_part, (inner_pts, inner_tris, z_deck)
    _, flat_tris = triangulate_polygon_2d(pts_ccw)
    if not flat_tris:
        return None
    pts_tri, flat_tris = triangulate_polygon_2d(pts_ccw)
    f_verts = np.asarray([(px, py, z_top) for px, py in pts_tri], dtype=np.float32)
    f_uvs = np.asarray([_roof_uv(px, py) for px, py in pts_tri], dtype=np.float32)
    f_faces = np.asarray(flat_tris, dtype=np.uint32)
    return None, (f_verts, f_faces, f_uvs), None


def _build_step_terrace_ring_uv(outer_ccw: List[Tuple[float, float]], inner_ccw: List[Tuple[float, float]], z_step: float, use_parapet: bool, b_id: int) -> Tuple[Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]], Tuple[np.ndarray, np.ndarray, np.ndarray], float]:
    n = len(outer_ccw)
    ux, uy, ox, oy = _longest_edge_axis_2d(outer_ccw)
    vx, vy = -uy, ux
    tile_w = float(ROOF_SPECS[0]['tile_w_m'])

    def _t_uv(px: float, py: float) -> Tuple[float, float]:
        rx, ry = px - ox, py - oy
        return (rx * vx + ry * vy) / tile_w, (rx * ux + ry * uy) / tile_w

    if use_parapet:
        rim_res = _inset_polygon_2d_safe(outer_ccw, 0.36, min_area_ratio=0.35)
        if rim_res is not None and len(rim_res[0]) == n:
            rim_pts = rim_res[0]
            z_terrace = z_step - 0.42
            p_verts = []
            p_uvs = []
            p_faces = []
            acc_p = 0.0
            for i in range(n):
                inext = (i + 1) % n
                ox0, oy0 = outer_ccw[i]
                ox1, oy1 = outer_ccw[inext]
                rx0, ry0 = rim_pts[i]
                rx1, ry1 = rim_pts[inext]
                u0 = acc_p / 4.0
                acc_p += math.hypot(ox1 - ox0, oy1 - oy0)
                u1 = acc_p / 4.0
                bv = len(p_verts)
                p_verts.extend([(ox0, oy0, z_step), (ox1, oy1, z_step), (rx1, ry1, z_step), (rx0, ry0, z_step)])
                p_uvs.extend([(u0, 0.0), (u1, 0.0), (u1, 0.25), (u0, 0.25)])
                p_faces.extend([(bv, bv + 1, bv + 2), (bv, bv + 2, bv + 3)])
                bv2 = len(p_verts)
                p_verts.extend([(rx0, ry0, z_step), (rx1, ry1, z_step), (rx1, ry1, z_terrace), (rx0, ry0, z_terrace)])
                p_uvs.extend([(u0, 0.25), (u1, 0.25), (u1, 0.36), (u0, 0.36)])
                p_faces.extend([(bv2, bv2 + 1, bv2 + 2), (bv2, bv2 + 2, bv2 + 3)])
            d_verts = []
            d_uvs = []
            d_faces = []
            for i in range(n):
                inext = (i + 1) % n
                rx0, ry0 = rim_pts[i]
                rx1, ry1 = rim_pts[inext]
                ix0, iy0 = inner_ccw[i]
                ix1, iy1 = inner_ccw[inext]
                bd = len(d_verts)
                d_verts.extend([(rx0, ry0, z_terrace), (rx1, ry1, z_terrace), (ix1, iy1, z_terrace), (ix0, iy0, z_terrace)])
                d_uvs.extend([_t_uv(rx0, ry0), _t_uv(rx1, ry1), _t_uv(ix1, iy1), _t_uv(ix0, iy0)])
                d_faces.extend([(bd, bd + 1, bd + 2), (bd, bd + 2, bd + 3)])
            return ((np.asarray(p_verts, dtype=np.float32), np.asarray(p_faces, dtype=np.uint32), np.asarray(p_uvs, dtype=np.float32)),
                    (np.asarray(d_verts, dtype=np.float32), np.asarray(d_faces, dtype=np.uint32), np.asarray(d_uvs, dtype=np.float32)), z_terrace)
    d_verts_f = []
    d_uvs_f = []
    d_faces_f = []
    for i in range(n):
        inext = (i + 1) % n
        ox0, oy0 = outer_ccw[i]
        ox1, oy1 = outer_ccw[inext]
        ix0, iy0 = inner_ccw[i]
        ix1, iy1 = inner_ccw[inext]
        bd = len(d_verts_f)
        d_verts_f.extend([(ox0, oy0, z_step), (ox1, oy1, z_step), (ix1, iy1, z_step), (ix0, iy0, z_step)])
        d_uvs_f.extend([_t_uv(ox0, oy0), _t_uv(ox1, oy1), _t_uv(ix1, iy1), _t_uv(ix0, iy0)])
        d_faces_f.extend([(bd, bd + 1, bd + 2), (bd, bd + 2, bd + 3)])
    return None, (np.asarray(d_verts_f, dtype=np.float32), np.asarray(d_faces_f, dtype=np.uint32), np.asarray(d_uvs_f, dtype=np.float32)), z_step


def _find_safe_penthouse_core_rect(deck_pts_ccw: List[Tuple[float, float]], deck_tris: List[Tuple[int, int, int]]) -> Optional[List[Tuple[float, float]]]:
    ux, uy, ox, oy = _longest_edge_axis_2d(deck_pts_ccw)
    vx, vy = -uy, ux
    us = [(p[0] - ox) * ux + (p[1] - oy) * uy for p in deck_pts_ccw]
    vs = [(p[0] - ox) * vx + (p[1] - oy) * vy for p in deck_pts_ccw]
    span_u = max(us) - min(us)
    span_v = max(vs) - min(vs)
    if span_u < 11.0 or span_v < 9.5:
        return None
    core_hl = min(5.4, max(2.7, span_u * 0.16))
    core_hw = min(4.0, max(2.2, span_v * 0.16))
    cx_avg = sum(p[0] for p in deck_pts_ccw) / len(deck_pts_ccw)
    cy_avg = sum(p[1] for p in deck_pts_ccw) / len(deck_pts_ccw)
    candidates = [(cx_avg, cy_avg)]
    best_tri_area = -1.0
    best_tc = None
    for ia, ib, ic in deck_tris:
        ax, ay = deck_pts_ccw[ia]
        bx, by = deck_pts_ccw[ib]
        cx, cy = deck_pts_ccw[ic]
        ta = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) * 0.5
        if ta > best_tri_area:
            best_tri_area = ta
            best_tc = ((ax + bx + cx) / 3.0, (ay + by + cy) / 3.0)
    if best_tc is not None:
        candidates.append(best_tc)
    for ccx, ccy in candidates:
        corners = [
            (ccx - core_hl * ux - core_hw * vx, ccy - core_hl * uy - core_hw * vy),
            (ccx + core_hl * ux - core_hw * vx, ccy + core_hl * uy - core_hw * vy),
            (ccx + core_hl * ux + core_hw * vx, ccy + core_hl * uy + core_hw * vy),
            (ccx - core_hl * ux + core_hw * vx, ccy - core_hl * uy + core_hw * vy),
        ]
        mids = [((corners[k][0] + corners[(k + 1) % 4][0]) * 0.5,
                 (corners[k][1] + corners[(k + 1) % 4][1]) * 0.5) for k in range(4)]
        ok = True
        for tx, ty in corners + mids + [(ccx, ccy)]:
            if not _point_in_polygon_2d(tx, ty, deck_pts_ccw) or _min_dist_to_poly_edges_2d(tx, ty, deck_pts_ccw) < 1.05:
                ok = False
                break
        if ok:
            return corners
    return None


def _build_articulated_building_v24(poly_xy: List[Tuple[float, float]], height_m: float, area_m2: float, tags: Dict[str, Any], b_id: int, half_w: float, half_h: float, dem_grid: np.ndarray, main_fac_idx: int, roof_style: str = 'parapet_vietnam', skirt_depth_m: float = 2.5, min_z_base: Optional[float] = None) -> Optional[Dict[str, Any]]:
    pts_ccw = _clean_ccw_ring_2d(poly_xy)
    if len(pts_ccw) < 3:
        return None
    base_tris = _ear_clip_indexed_ccw(pts_ccw)
    if base_tris is None:
        pts_fb, tris_fb = triangulate_polygon_2d(poly_xy)
        if len(pts_fb) < 3 or not tris_fb:
            return None
        pts_ccw, base_tris = pts_fb, tris_fb
    n = len(pts_ccw)
    zs_ground = [sample_dem_bilinear(x, y, half_w, half_h, dem_grid) for x, y in pts_ccw]
    cx = sum(p[0] for p in pts_ccw) / n
    cy = sum(p[1] for p in pts_ccw) / n
    z_center = sample_dem_bilinear(cx, cy, half_w, half_h, dem_grid)
    h_eff = max(3.0, float(height_m))
    z_roof = z_center + h_eff
    z_base = min(zs_ground) - abs(skirt_depth_m)
    if min_z_base is not None:
        z_base = min(z_roof - 0.5, max(float(min_z_base), z_base))
    is_high = h_eff >= 21.0
    use_parapet_mode = roof_style in ('parapet_vietnam', 'parapet_concrete')
    walls_by_fac = {}
    parapet_parts = []
    roofs_by_idx = {}

    def _add_wall(f_idx: int, part: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]) -> None:
        if part is not None:
            walls_by_fac.setdefault(f_idx, []).append(part)

    def _add_roof(r_idx: int, part: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]) -> None:
        if part is not None:
            roofs_by_idx.setdefault(r_idx, []).append(part)

    if is_high:
        main_spec = FACADE_SPECS[main_fac_idx]
        fh_main = float(main_spec.get('floor_h_m', 3.5))
        cur_poly = pts_ccw
        z_cur = z_base
        z_ground_cur = z_center
        if h_eff >= 30.0 and area_m2 >= 140.0:
            podium_spec = FACADE_SPECS[PODIUM_FACADE_INDEX]
            podium_floors = 3 if h_eff >= 48.0 else 2
            h_podium = podium_floors * float(podium_spec.get('floor_h_m', 4.3))
            if h_eff - h_podium >= 14.0:
                z_podium_top = z_center + h_podium
                _add_wall(PODIUM_FACADE_INDEX, _extrude_wall_tier_uv(cur_poly, z_base, z_podium_top, z_center, podium_spec, b_id, tier_salt=1))
                step_pod = _inset_polygon_2d_safe(cur_poly, 1.15, min_area_ratio=0.48) if area_m2 >= 360.0 else None
                if step_pod is not None and len(step_pod[0]) == len(cur_poly):
                    p_rim, d_ring, z_next = _build_step_terrace_ring_uv(cur_poly, step_pod[0], z_podium_top, use_parapet_mode, b_id)
                    if p_rim is not None:
                        parapet_parts.append(p_rim)
                    _add_roof(0, d_ring)
                    cur_poly = step_pod[0]
                    z_cur = z_next
                    z_ground_cur = z_podium_top
                else:
                    z_cur = z_podium_top
                    z_ground_cur = z_podium_top
        rem_h = z_roof - z_ground_cur
        did_upper_setback = False
        if h_eff >= 38.0 and area_m2 >= 300.0 and rem_h >= 18.0:
            upper_setback_m = 1.65 if area_m2 >= 520.0 else 1.25
            step_up = _inset_polygon_2d_safe(cur_poly, upper_setback_m, min_area_ratio=0.42)
            if step_up is not None and len(step_up[0]) == len(cur_poly):
                lower_floors = max(3, int(round(rem_h * 0.68 / fh_main)))
                z_step_up = z_ground_cur + lower_floors * fh_main
                if z_roof - z_step_up >= 7.0:
                    _add_wall(main_fac_idx, _extrude_wall_tier_uv(cur_poly, z_cur, z_step_up, z_ground_cur, main_spec, b_id, tier_salt=2))
                    p_rim2, d_ring2, z_next2 = _build_step_terrace_ring_uv(cur_poly, step_up[0], z_step_up, use_parapet_mode, b_id + 13)
                    if p_rim2 is not None:
                        parapet_parts.append(p_rim2)
                    _add_roof(0, d_ring2)
                    _add_wall(main_fac_idx, _extrude_wall_tier_uv(step_up[0], z_next2, z_roof, z_step_up, main_spec, b_id, tier_salt=3))
                    cur_poly = step_up[0]
                    did_upper_setback = True
        if not did_upper_setback:
            _add_wall(main_fac_idx, _extrude_wall_tier_uv(cur_poly, z_cur, z_roof, z_ground_cur, main_spec, b_id, tier_salt=2))
        cap_high = _build_parapet_or_flat_roof_uv(cur_poly, z_roof, ROOF_SPECS[0], use_parapet=use_parapet_mode and area_m2 >= 28.0, inset_m=0.4, recess_depth_m=0.65, b_id=b_id)
        if cap_high is None:
            return None
        p_cap, d_cap, inner_info = cap_high
        if p_cap is not None:
            parapet_parts.append(p_cap)
        _add_roof(0, d_cap)
        if h_eff >= 38.0 and area_m2 >= 280.0 and inner_info is not None:
            in_pts_top, in_tris_top, z_deck_top = inner_info
            core_rect = _find_safe_penthouse_core_rect(in_pts_top, in_tris_top)
            if core_rect is not None:
                z_core_top = z_roof + 3.4
                core_spec = FACADE_SPECS[PENTHOUSE_FACADE_INDEX]
                _add_wall(PENTHOUSE_FACADE_INDEX, _extrude_wall_tier_uv(core_rect, z_deck_top, z_core_top, z_deck_top, core_spec, b_id, tier_salt=7))
                cap_core = _build_parapet_or_flat_roof_uv(core_rect, z_core_top, ROOF_SPECS[0], use_parapet=use_parapet_mode, inset_m=0.22, recess_depth_m=0.28, b_id=b_id + 97)
                if cap_core is not None:
                    if cap_core[0] is not None:
                        parapet_parts.append(cap_core[0])
                    _add_roof(0, cap_core[1])
    else:
        low_spec = FACADE_SPECS[main_fac_idx]
        _add_wall(main_fac_idx, _extrude_wall_tier_uv(pts_ccw, z_base, z_roof, z_center, low_spec, b_id, tier_salt=1))
        roof_idx = select_lowrise_roof_variant_index(tags, area_m2, b_id, roof_style=roof_style)
        btype_low = str(tags.get('building') or 'yes').lower()
        is_small_shed = area_m2 < 22.0 or btype_low in ('shed', 'hut', 'garage', 'carport', 'roof', 'kiosk')
        cap_low = _build_parapet_or_flat_roof_uv(pts_ccw, z_roof, ROOF_SPECS[roof_idx], use_parapet=use_parapet_mode and not is_small_shed, inset_m=0.24, recess_depth_m=0.36, b_id=b_id)
        if cap_low is None:
            return None
        if cap_low[0] is not None:
            parapet_parts.append(cap_low[0])
        _add_roof(roof_idx, cap_low[1])
    if not walls_by_fac:
        return None
    bot_verts = np.asarray([(px, py, z_base) for px, py in pts_ccw], dtype=np.float32)
    bot_faces = np.asarray([(a, c, b) for a, b, c in base_tris], dtype=np.uint32)
    return {'walls_by_fac': walls_by_fac, 'parapet_parts': parapet_parts, 'roofs_by_idx': roofs_by_idx, 'bottom_part': (bot_verts, bot_faces)}


def _sweep_road_ribbon_on_terrain(pts_xy: List[Tuple[float, float]], width_m: float, half_w: float, half_h: float, dem_grid: np.ndarray, z_offset_m: float = 0.14, curb_floor_z: Optional[float] = None, min_road_z: Optional[float] = None) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    clean = []
    for p in pts_xy:
        if not clean or math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.35:
            clean.append(p)
    if len(clean) < 2:
        return None
    hw = width_m * 0.5
    m = len(clean)
    has_curb = curb_floor_z is not None
    verts = np.zeros((m * 4 if has_curb else m * 2, 3), dtype=np.float32)
    for i, (x, y) in enumerate(clean):
        if i == 0:
            dx, dy = clean[1][0] - x, clean[1][1] - y
        elif i == m - 1:
            dx, dy = x - clean[i - 1][0], y - clean[i - 1][1]
        else:
            dx1, dy1 = x - clean[i - 1][0], y - clean[i - 1][1]
            l1 = max(1e-6, math.hypot(dx1, dy1))
            dx2, dy2 = clean[i + 1][0] - x, clean[i + 1][1] - y
            l2 = max(1e-6, math.hypot(dx2, dy2))
            dx, dy = dx1 / l1 + dx2 / l2, dy1 / l1 + dy2 / l2
        ln = max(1e-6, math.hypot(dx, dy))
        nx, ny = -dy / ln, dx / ln
        lx, ly = x + nx * hw, y + ny * hw
        rx, ry = x - nx * hw, y - ny * hw
        zl = sample_dem_bilinear(lx, ly, half_w, half_h, dem_grid) + z_offset_m
        zr = sample_dem_bilinear(rx, ry, half_w, half_h, dem_grid) + z_offset_m
        if min_road_z is not None:
            zl = max(float(min_road_z), zl)
            zr = max(float(min_road_z), zr)
        verts[2 * i] = (lx, ly, zl)
        verts[2 * i + 1] = (rx, ry, zr)
        if has_curb:
            zf = float(curb_floor_z)
            verts[2 * m + 2 * i] = (lx, ly, min(zl - 0.01, zf))
            verts[2 * m + 2 * i + 1] = (rx, ry, min(zr - 0.01, zf))
    faces = []
    for i in range(m - 1):
        l0, r0 = 2 * i, 2 * i + 1
        l1, r1 = 2 * (i + 1), 2 * (i + 1) + 1
        faces.append((l0, r0, r1))
        faces.append((l0, r1, l1))
        if has_curb:
            lb0, rb0 = 2 * m + 2 * i, 2 * m + 2 * i + 1
            lb1, rb1 = 2 * m + 2 * (i + 1), 2 * m + 2 * (i + 1) + 1
            faces.append((l0, l1, lb1))
            faces.append((l0, lb1, lb0))
            faces.append((r1, r0, rb0))
            faces.append((r1, rb0, rb1))
    if has_curb:
        l_s, r_s = 0, 1
        lb_s, rb_s = 2 * m, 2 * m + 1
        faces.append((r_s, l_s, lb_s))
        faces.append((r_s, lb_s, rb_s))
        l_e, r_e = 2 * (m - 1), 2 * (m - 1) + 1
        lb_e, rb_e = 2 * m + 2 * (m - 1), 2 * m + 2 * (m - 1) + 1
        faces.append((l_e, r_e, rb_e))
        faces.append((l_e, rb_e, lb_e))
    return verts, np.asarray(faces, dtype=np.uint32)


def _make_architectural_tree(x: float, y: float, z0: float, height_m: float = 6.5) -> Tuple[np.ndarray, np.ndarray]:
    r_canopy = height_m * 0.34
    z_mid = z0 + height_m * 0.58
    z_top = z0 + height_m
    z_bot_canopy = z0 + height_m * 0.28
    verts = [(x, y, z_top), (x + r_canopy, y, z_mid),
             (x, y + r_canopy, z_mid), (x - r_canopy, y, z_mid),
             (x, y - r_canopy, z_mid), (x, y, z_bot_canopy)]
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),
             (5, 2, 1), (5, 3, 2), (5, 4, 3), (5, 1, 4)]
    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.uint32)


def _merge_mesh_parts(parts: List[Tuple[np.ndarray, np.ndarray]]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if not parts:
        return None
    v_list = []
    f_list = []
    offset = 0
    for v, f in parts:
        v_list.append(v)
        f_list.append(f + offset)
        offset += len(v)
    return np.vstack(v_list), np.vstack(f_list)


def _merge_uv_mesh_parts(parts: List[Tuple[np.ndarray, np.ndarray, np.ndarray]]) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    if not parts:
        return None
    v_list = []
    f_list = []
    uv_list = []
    offset = 0
    for v, f, uv in parts:
        v_list.append(v)
        f_list.append(f + offset)
        uv_list.append(uv)
        offset += len(v)
    return np.vstack(v_list), np.vstack(f_list), np.vstack(uv_list)


def _clip_segment_liang_barsky(x0: float, y0: float, x1: float, y1: float, xmin: float, xmax: float, ymin: float, ymax: float) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    dx = x1 - x0
    dy = y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if abs(p) < 1e-12:
            if q < 0.0:
                return None
            continue
        r = q / p
        if p < 0.0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def _clip_polyline_to_rect(pts_xy: List[Tuple[float, float]], xmin: float, xmax: float, ymin: float, ymax: float) -> List[List[Tuple[float, float]]]:
    chains = []
    cur_chain = []
    for i in range(len(pts_xy) - 1):
        seg = _clip_segment_liang_barsky(pts_xy[i][0], pts_xy[i][1], pts_xy[i + 1][0], pts_xy[i + 1][1], xmin, xmax, ymin, ymax)
        if seg is None:
            if len(cur_chain) >= 2:
                chains.append(cur_chain)
            cur_chain = []
            continue
        p_start, p_end = seg
        if not cur_chain:
            cur_chain = [p_start, p_end]
        else:
            if math.hypot(cur_chain[-1][0] - p_start[0], cur_chain[-1][1] - p_start[1]) > 0.05:
                if len(cur_chain) >= 2:
                    chains.append(cur_chain)
                cur_chain = [p_start, p_end]
            else:
                cur_chain.append(p_end)
    if len(cur_chain) >= 2:
        chains.append(cur_chain)
    return chains


def build_mode1_context_scene(params: Dict[str, Any], cache_dir: Path,
                              progress_cb: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
    def report(msg: str, pct: int):
        if progress_cb:
            progress_cb(msg, pct)

    if 'south' in params and 'north' in params and 'west' in params and 'east' in params:
        south = float(params['south'])
        west = float(params['west'])
        north = float(params['north'])
        east = float(params['east'])
        lat0, lon0, width_m, height_m = bbox_dimensions_meters(south, west, north, east)
    else:
        lat0 = float(params.get('lat', 21.028511))
        lon0 = float(params.get('lon', 105.854444))
        width_m = float(params.get('width_m', 320.0))
        height_m = float(params.get('height_m', 320.0))
        south, west, north, east = bbox_from_center_meters(lat0, lon0, width_m, height_m)
    width_m = max(30.0, min(width_m, 4000.0))
    height_m = max(30.0, min(height_m, 4000.0))
    half_w, half_h = width_m * 0.5, height_m * 0.5
    grid_res = int(params.get('dem_grid', 64))
    grid_res = max(16, min(160, grid_res))
    z_exag = float(params.get('z_exaggeration', 1.0))
    default_floors = float(params.get('default_floors', 3.5))
    sat_provider = str(params.get('sat_provider', 'esri_sat'))
    sat_px = int(params.get('sat_px', 4096))
    include_buildings = bool(params.get('include_buildings', True))
    include_buildings_high = bool(params.get('include_buildings_high', include_buildings))
    include_buildings_low = bool(params.get('include_buildings_low', include_buildings))
    include_buildings = include_buildings and (include_buildings_high or include_buildings_low)
    bstyle_raw = str(params.get('building_style') or 'textured').strip().lower()
    building_style = 'white_box' if bstyle_raw in ('white_box', 'white', 'box', 'clay') else 'textured'
    rstyle_raw = str(params.get('roof_style') or 'parapet_vietnam').strip().lower()
    roof_style = rstyle_raw if rstyle_raw in ('parapet_vietnam', 'parapet_concrete', 'flat_simple') else 'parapet_vietnam'
    include_roads = bool(params.get('include_roads', True))
    include_roads_main = bool(params.get('include_roads_main', include_roads))
    include_roads_alley = bool(params.get('include_roads_alley', include_roads))
    any_roads_enabled = include_roads_main or include_roads_alley
    include_water = bool(params.get('include_water', True))
    include_trees = bool(params.get('include_trees', True))
    offline_synthetic = bool(params.get('offline_synthetic', False))
    tmode_raw = str(params.get('terrain_mode') or 'terrain_3d').strip().lower()
    terrain_mode = 'flat' if tmode_raw in ('flat', 'flat_z0', 'plane', '2d') else 'terrain_3d'
    raw_anchor = params.get('anchor') if isinstance(params.get('anchor'), dict) else None
    has_prior_anchor = bool(raw_anchor and 'lat' in raw_anchor and 'lon' in raw_anchor)
    anchor_lat = float(raw_anchor['lat']) if has_prior_anchor else lat0
    anchor_lon = float(raw_anchor['lon']) if has_prior_anchor else lon0
    anchor_terrain_mode = (str(raw_anchor.get('terrain_mode') or 'terrain_3d').strip().lower()
                           if has_prior_anchor and raw_anchor else terrain_mode)
    is_hill_patch = bool(terrain_mode == 'terrain_3d' and
                         (bool(params.get('hill_patch', False)) or
                          (has_prior_anchor and anchor_terrain_mode == 'flat')))
    if has_prior_anchor and raw_anchor and raw_anchor.get('z_exaggeration') is not None and not is_hill_patch:
        z_exag = float(raw_anchor['z_exaggeration'])
    if terrain_mode == 'flat':
        report('Chế độ Map Phẳng Z=0: Bỏ tải DEM, đang ghép ảnh vệ tinh độ nét cao...', 22)
    elif is_hill_patch:
        report('Chế độ Trám Đồi 3D: Đang tải DEM quả đồi & đo cốt chân đồi...', 18)
    else:
        report('Đang tải cao độ địa hình DEM & ghép ảnh vệ tinh độ nét cao...', 18)
    lats_1d = np.linspace(south, north, grid_res)
    lons_1d = np.linspace(west, east, grid_res)
    lons_2d, lats_2d = np.meshgrid(lons_1d, lats_1d)
    if offline_synthetic:
        if terrain_mode == 'flat':
            center_elev = 0.0
            dem_grid = np.zeros((grid_res, grid_res), dtype=np.float32)
        else:
            custom_dem = params.get('custom_dem_asl')
            if isinstance(custom_dem, np.ndarray) and custom_dem.shape == (grid_res, grid_res):
                abs_elev = custom_dem.astype(np.float64)
            else:
                abs_elev = (12.5 + 3.8 * np.sin((lats_2d - 21.0285) * 900.0)
                            * np.cos((lons_2d - 105.8544) * 900.0)
                            + 140.0 * (lons_2d - 105.8544))
            mid = grid_res // 2
            center_elev = round(float(abs_elev[mid, mid]), 3)
            dem_grid = ((abs_elev - center_elev) * z_exag).astype(np.float32)
        im = Image.new('RGB', (1024, 1024), (74, 108, 72))
        px = np.asarray(im).copy()
        px[::64, :, :] = (165, 172, 160)
        px[:, ::64, :] = (165, 172, 160)
        buf = io.BytesIO()
        Image.fromarray(px).save(buf, format='JPEG', quality=90)
        sat_bytes = buf.getvalue()
        osm_data = params['mock_osm_data'] if isinstance(params.get('mock_osm_data'), dict) else {
            'elements': [
                {'type':'node','id':1,'lat':lat0-0.0003,'lon':lon0-0.0004},
                {'type':'node','id':2,'lat':lat0-0.0003,'lon':lon0-0.0001},
                {'type':'node','id':3,'lat':lat0+0.0001,'lon':lon0-0.0001},
                {'type':'node','id':4,'lat':lat0+0.0001,'lon':lon0-0.0004},
                {'type':'way','id':101,'nodes':[1,2,3,4,1],'tags':{'building':'apartments','building:levels':'8'}},
                {'type':'node','id':11,'lat':lat0+0.00018,'lon':lon0-0.00036},
                {'type':'node','id':12,'lat':lat0+0.00018,'lon':lon0-0.00016},
                {'type':'node','id':13,'lat':lat0+0.00036,'lon':lon0-0.00016},
                {'type':'node','id':14,'lat':lat0+0.00036,'lon':lon0-0.00036},
                {'type':'way','id':104,'nodes':[11,12,13,14,11],'tags':{'building':'residential','building:levels':'4'}},
                {'type':'node','id':5,'lat':anchor_lat,'lon':west-0.003},
                {'type':'node','id':6,'lat':anchor_lat,'lon':east+0.003},
                {'type':'way','id':102,'nodes':[5,6],'tags':{'highway':'primary'}},
                {'type':'node','id':8,'lat':south+(north-south)*0.2,'lon':lon0+0.0002},
                {'type':'node','id':9,'lat':south+(north-south)*0.8,'lon':lon0+0.0002},
                {'type':'way','id':103,'nodes':[8,9],'tags':{'highway':'residential'}},
                {'type':'node','id':7,'lat':lat0+0.0003,'lon':lon0+0.0003,'tags':{'natural':'tree'}},
            ]}
    else:
        if terrain_mode == 'flat':
            dem_grid = np.zeros((grid_res, grid_res), dtype=np.float32)
            center_elev = 0.0
        else:
            try:
                dem_grid, center_elev = download_terrarium_dem_grid(
                    south, west, north, east, grid_res=grid_res,
                    cache_dir=cache_dir, z_exaggeration=z_exag)
            except Exception:
                dem_grid = np.zeros((grid_res,grid_res),dtype=np.float32)
                center_elev = 0.0
        report('Đang ghép & lọc nét ảnh vệ tinh 4K/8K...', 42)
        try:
            sat_bytes = download_stitched_satellite(
                south, west, north, east, cache_dir=cache_dir,
                provider=sat_provider, target_px=sat_px, sharpen=True)
        except Exception:
            im_fb = Image.new('RGB',(1024,1024),(82,104,78))
            buf_fb = io.BytesIO()
            im_fb.save(buf_fb,format='JPEG',quality=88)
            sat_bytes = buf_fb.getvalue()
        if any((include_buildings, any_roads_enabled, include_water, include_trees)):
            report('Đang ưu tiên lấy 100% Đường giao thông 2 cấp, Mặt nước & Khối công trình...', 62)
            try:
                osm_data = fetch_osm_overpass(south, west, north, east, cache_dir=cache_dir,
                                             include_roads=any_roads_enabled,
                                             include_buildings=include_buildings,
                                             include_water=include_water)
            except Exception:
                osm_data = {'elements':[],'all_subtiles_ok':False,
                            'peak_hour_window':is_vietnam_peak_map_hour(),
                            'peak_hour_degraded':True,'overpass_overloaded':True}
        else:
            osm_data = {'elements': [], 'all_subtiles_ok': True}
    verified_proj = params.get('__verified_projection__') if isinstance(params.get('__verified_projection__'), dict) else None
    requires_grant = bool(_ARMOR_MOD is not None and hasattr(_ARMOR_MOD, 'get_locked_policy')
                          and str(_ARMOR_MOD.get_locked_policy().get('distribution_mode') or '') == 'saas')
    if requires_grant and not verified_proj:
        raise PermissionError('MISSING_AUTHORITATIVE_PROJECTION_GRANT: Bắt buộc có giấy phép chiếu tọa độ Ed25519 từ máy chủ MapSKP SaaS.')
    if verified_proj and isinstance(verified_proj.get('rot'), list) and len(verified_proj['rot']) == 9:
        rot_mat = np.asarray(verified_proj['rot'], dtype=np.float64).reshape((3,3))
        orig_ecef_arr = np.asarray(verified_proj['origin_ecef'], dtype=np.float64).reshape((3,))
        off_xy = verified_proj.get('center_offset_xy') or [0.0, 0.0]
        cx_anchor, cy_anchor = (float(off_xy[0]), float(off_xy[1])) if has_prior_anchor else (0.0, 0.0)
        lat_r = np.radians(lats_2d.ravel())
        lon_r = np.radians(lons_2d.ravel())
        s_lat = np.sin(lat_r)
        c_lat = np.cos(lat_r)
        n_ellip = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s_lat * s_lat)
        pts_ecef = np.stack([n_ellip*c_lat*np.cos(lon_r), n_ellip*c_lat*np.sin(lon_r),
                             n_ellip*(1.0-WGS84_E2)*s_lat], axis=-1)
        enu_grid = (pts_ecef - orig_ecef_arr) @ rot_mat.T
        gx_flat, gy_flat = enu_grid[:,0], enu_grid[:,1]
    else:
        rot_mat = None
        orig_ecef_arr = None
        cx_anchor, cy_anchor = (latlon_to_local_xy(lat0, lon0, anchor_lat, anchor_lon)
                                if has_prior_anchor else (0.0,0.0))
        gx_flat, gy_flat = latlon_array_to_local_xy(lats_2d.ravel(), lons_2d.ravel(), anchor_lat, anchor_lon)
    xx_local = (gx_flat.reshape((grid_res,grid_res)) - cx_anchor).astype(np.float32)
    yy_local = (gy_flat.reshape((grid_res,grid_res)) - cy_anchor).astype(np.float32)
    xmin_local = float(xx_local[:,0].mean())
    xmax_local = float(xx_local[:,-1].mean())
    ymin_local = float(yy_local[0,:].mean())
    ymax_local = float(yy_local[-1,:].mean())
    hill_foot_asl_m = 0.0
    hill_peak_rel_m = 0.0
    if terrain_mode == 'flat':
        report('Đang dựng mặt phẳng chuẩn Z = 0.000m & đường giao thông nổi phẳng...', 82)
        center_elev = 0.0
        anchor_elev_m = (float(raw_anchor['elevation_m'])
                         if has_prior_anchor and raw_anchor and raw_anchor.get('elevation_m') is not None and anchor_terrain_mode != 'flat'
                         else 0.0)
        dz_anchor = 0.0
        flat_top_mesh = build_flat_sheet_mesh(xx_local, yy_local, z_flat=0.0)
        terrain_layer_entry = {'name':'MapSKP_Terrain_Flat_Z0','tag':'MapSKP_01_Terrain',
                               'tag_color':[92,168,96],'soften_cos':0.995,
                               'meshes':[{'mat_idx':0, **flat_top_mesh}]}
    elif is_hill_patch:
        report('Đang cắt ôm sát chân đồi, hạ cốt Z=0 & vát êm tiếp giáp nền phẳng...', 82)
        hill_mesh, hill_dem, hill_foot_asl_m, hill_peak_rel_m = build_trimmed_hill_patch_mesh(
            dem_grid, center_elev, z_exag, xx_local, yy_local,
            min_relief_cutoff_m=0.35, toe_contact_z_m=0.015)
        dem_grid = hill_dem
        anchor_elev_m = 0.0
        dz_anchor = 0.0
        terrain_layer_entry = {'name':'MapSKP_Terrain_HillPatch_3D','tag':'MapSKP_01B_Terrain_HillPatch',
                               'tag_color':[16,185,129],'soften_cos':0.78,
                               'meshes':[{'mat_idx':0, **hill_mesh}]}
    else:
        report('Đang dựng hình học 3D tách lớp & bám cao độ địa hình...', 82)
        anchor_elev_m = (float(raw_anchor['elevation_m'])
                         if has_prior_anchor and raw_anchor and raw_anchor.get('elevation_m') is not None else center_elev)
        dz_anchor = (center_elev - anchor_elev_m) * z_exag if has_prior_anchor else 0.0
        top_mesh, plinth_mesh = build_terrain_mesh_with_plinth(width_m,height_m,dem_grid,
                                                             plinth_depth_m=4.0,grid_xy=(xx_local,yy_local))
        terrain_layer_entry = {'name':'MapSKP_Terrain_DEM','tag':'MapSKP_01_Terrain',
                               'tag_color':[92,168,96],'soften_cos':0.78,
                               'meshes':[{'mat_idx':0,**top_mesh},{'mat_idx':1,**plinth_mesh}]}
    materials = [
        {'name':'MapSKP_Satellite_Terrain','color':[255,255,255,255],'texture_bytes':sat_bytes,'ext':'jpg'},
        {'name':'MapSKP_Maquette_Plinth','color':[56,62,74,255],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Building_WarmWhite','color':[238,235,228,255],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Building_Highrise','color':[205,216,228,255],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Road_Main_Asphalt','color':[58,64,74,255],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Water_Surface','color':[46,134,193,220],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Foliage_Green','color':[72,142,78,255],'texture_bytes':None,'ext':'jpg'},
        {'name':'MapSKP_Road_Alley_Concrete','color':[118,126,138,255],'texture_bytes':None,'ext':'jpg'},
    ]
    layers = [terrain_layer_entry]

    def _project_latlon_to_tile_xy(pt_lat: float, pt_lon: float) -> Tuple[float, float]:
        if rot_mat is not None and orig_ecef_arr is not None:
            ex_pt, ey_pt, ez_pt = latlon_to_ecef(pt_lat, pt_lon, 0.0)
            vec_enu = rot_mat @ (np.array([ex_pt,ey_pt,ez_pt],dtype=np.float64) - orig_ecef_arr)
            ax, ay = float(vec_enu[0]), float(vec_enu[1])
        else:
            ax, ay = latlon_to_local_xy(pt_lat,pt_lon,anchor_lat,anchor_lon)
        return ax-cx_anchor, ay-cy_anchor

    def _project_geom_list(geom_list: List[Dict[str,Any]]) -> List[Tuple[float,float]]:
        if not geom_list:
            return []
        glats = np.asarray([float(g['lat']) for g in geom_list if 'lat' in g and 'lon' in g],dtype=np.float64)
        glons = np.asarray([float(g['lon']) for g in geom_list if 'lat' in g and 'lon' in g],dtype=np.float64)
        if len(glats) == 0:
            return []
        if rot_mat is not None and orig_ecef_arr is not None:
            lat_r = np.radians(glats)
            lon_r = np.radians(glons)
            s_l = np.sin(lat_r)
            c_l = np.cos(lat_r)
            n_el = WGS84_A / np.sqrt(1.0-WGS84_E2*s_l*s_l)
            ecef_arr = np.stack([n_el*c_l*np.cos(lon_r),n_el*c_l*np.sin(lon_r),n_el*(1.0-WGS84_E2)*s_l],axis=-1)
            enu_arr = (ecef_arr-orig_ecef_arr) @ rot_mat.T
            xs_arr = enu_arr[:,0]-cx_anchor
            ys_arr = enu_arr[:,1]-cy_anchor
        else:
            ax_arr,ay_arr = latlon_array_to_local_xy(glats,glons,anchor_lat,anchor_lon)
            xs_arr = ax_arr-cx_anchor
            ys_arr = ay_arr-cy_anchor
        return list(zip(xs_arr.tolist(),ys_arr.tolist()))

    nodes_xy = {}
    tree_points = []
    elements = osm_data.get('elements') or []
    for el in elements:
        if el.get('type') == 'node' and 'lat' in el and 'lon' in el:
            nid = int(el['id'])
            ex,ny = _project_latlon_to_tile_xy(float(el['lat']),float(el['lon']))
            nodes_xy[nid] = (ex,ny)
            ntags = el.get('tags') or {}
            if include_trees and ntags.get('natural') == 'tree':
                if xmin_local <= ex <= xmax_local and ymin_local <= ny <= ymax_local:
                    tree_points.append((ex,ny))
    bldg_low_parts = []
    bldg_high_parts = []
    road_main_parts = []
    road_alley_parts = []
    water_parts = []
    osm_road_chains_xy = []
    osm_bldg_centers_xy = []
    bldg_candidates = []
    bldg_count = 0
    road_main_count = 0
    road_alley_count = 0
    MAX_BUILDINGS_PER_TILE = 4500
    pad_x = max(25.0,width_m*0.05)
    pad_y = max(25.0,height_m*0.05)
    SLOPE_MIN_Z = 0.5
    road_curb_z = 0.008 if terrain_mode == 'flat' else None
    road_min_z_main = 0.16 if is_hill_patch else None
    road_min_z_alley = 0.12 if is_hill_patch else None
    road_soften_cos = 0.94 if terrain_mode == 'flat' else 0.85
    water_z_off = 0.04 if terrain_mode == 'flat' else 0.08
    bldg_skirt_m = 0.0 if terrain_mode == 'flat' else 1.5 if is_hill_patch else 2.5
    bldg_min_z_base = 0.0 if terrain_mode == 'flat' else 0.02 if is_hill_patch else None

    def _extract_slope_road_subchains(ch_in: List[Tuple[float,float]]) -> List[List[Tuple[float,float]]]:
        if not is_hill_patch:
            return [ch_in]
        zs_ch = [sample_dem_bilinear(px,py,half_w,half_h,dem_grid) for px,py in ch_in]
        if not zs_ch or max(zs_ch) <= SLOPE_MIN_Z:
            return []
        sub_out = []
        cur_seg = []
        for idx_p,(pt_c,z_c) in enumerate(zip(ch_in,zs_ch)):
            if z_c >= 0.3:
                if not cur_seg and idx_p > 0:
                    cur_seg.append(ch_in[idx_p-1])
                cur_seg.append(pt_c)
            elif cur_seg:
                cur_seg.append(pt_c)
                if len(cur_seg) >= 2:
                    sub_out.append(cur_seg)
                cur_seg = []
        if len(cur_seg) >= 2:
            sub_out.append(cur_seg)
        return sub_out

    def _queue_building_footprint(pts_b: List[Tuple[float,float]], tags_b: Dict[str,Any], b_id: int):
        if len(pts_b) < 3:
            return
        xs_b = [p[0] for p in pts_b]
        ys_b = [p[1] for p in pts_b]
        cx_b = sum(xs_b)/len(xs_b)
        cy_b = sum(ys_b)/len(ys_b)
        if not (xmin_local <= cx_b <= xmax_local and ymin_local <= cy_b <= ymax_local):
            return
        area = abs(_signed_area_2d(pts_b))
        if area < 6.0:
            return
        osm_bldg_centers_xy.append((cx_b,cy_b))
        if is_hill_patch and sample_dem_bilinear(cx_b,cy_b,half_w,half_h,dem_grid) <= SLOPE_MIN_Z:
            return
        bldg_candidates.append((area,pts_b,tags_b,b_id))

    for el in elements:
        try:
            el_type = el.get('type')
            tags = el.get('tags') or {}
            if el_type == 'relation' and include_buildings and 'building' in tags:
                rel_id = int(el.get('id') or 1)
                for mem in el.get('members') or []:
                    if mem.get('type') == 'way' and str(mem.get('role') or 'outer') in ('outer',''):
                        m_pts = _project_geom_list(mem.get('geometry') or [])
                        if len(m_pts) >= 3:
                            _queue_building_footprint(m_pts,tags,rel_id)
                continue
            if el_type != 'way':
                continue
            geom_raw = el.get('geometry')
            if isinstance(geom_raw,list) and geom_raw:
                pts_xy = _project_geom_list(geom_raw)
            else:
                nids = el.get('nodes') or []
                pts_xy = [nodes_xy[n] for n in nids if n in nodes_xy]
            if len(pts_xy) < 2:
                continue
            xs_w = [p[0] for p in pts_xy]
            ys_w = [p[1] for p in pts_xy]
            if (max(xs_w) < xmin_local-pad_x or min(xs_w) > xmax_local+pad_x
                or max(ys_w) < ymin_local-pad_y or min(ys_w) > ymax_local+pad_y):
                continue
            if any_roads_enabled and 'highway' in tags:
                road_cls = classify_vietnam_road_tier(tags)
                if road_cls:
                    tier_name,w_road = road_cls
                    clipped_chains = _clip_polyline_to_rect(pts_xy,xmin_local,xmax_local,ymin_local,ymax_local)
                    for chain in clipped_chains:
                        osm_road_chains_xy.append(chain)
                        for s_chain in _extract_slope_road_subchains(chain):
                            if tier_name == 'main' and include_roads_main:
                                rib = _sweep_road_ribbon_on_terrain(s_chain,w_road,half_w,half_h,dem_grid,
                                                                   z_offset_m=0.16,curb_floor_z=road_curb_z,min_road_z=road_min_z_main)
                                if rib:
                                    road_main_parts.append(rib)
                                    road_main_count += 1
                            elif tier_name == 'alley' and include_roads_alley:
                                rib = _sweep_road_ribbon_on_terrain(s_chain,w_road,half_w,half_h,dem_grid,
                                                                   z_offset_m=0.12,curb_floor_z=road_curb_z,min_road_z=road_min_z_alley)
                                if rib:
                                    road_alley_parts.append(rib)
                                    road_alley_count += 1
                continue
            if include_water and (tags.get('natural') == 'water' or tags.get('waterway') == 'riverbank') and len(pts_xy) >= 3:
                pts_clean,w_tris = triangulate_polygon_2d(pts_xy)
                if len(pts_clean) >= 3 and w_tris:
                    pts_clean,w_tris = _clip_triangles_to_rect_2d(pts_clean,w_tris,xmin_local,xmax_local,ymin_local,ymax_local)
                if len(pts_clean) >= 3 and w_tris:
                    raw_w_zs = [sample_dem_bilinear(wx,wy,half_w,half_h,dem_grid) for wx,wy in pts_clean]
                    if not is_hill_patch or max(raw_w_zs) > SLOPE_MIN_Z:
                        wv = np.zeros((len(pts_clean),3),dtype=np.float32)
                        for i,((wx,wy),base_wz) in enumerate(zip(pts_clean,raw_w_zs)):
                            wv[i] = (wx,wy,base_wz+water_z_off)
                        water_parts.append((wv,np.asarray(w_tris,dtype=np.uint32)))
                continue
            if include_buildings and 'building' in tags and len(pts_xy) >= 3:
                _queue_building_footprint(pts_xy,tags,int(el.get('id',1)))
                continue
            if include_trees and tags.get('leisure') == 'park' and len(pts_xy) >= 3:
                for px,py in pts_xy[::2]:
                    if xmin_local*0.96 <= px <= xmax_local*0.96 and ymin_local*0.96 <= py <= ymax_local*0.96:
                        tree_points.append((px,py))
        except Exception:
            continue
    gf_road_count = 0
    gf_bldg_count = 0
    gf_bldgs = []
    custom_rm = params.get('custom_roadmap_rgb')
    should_run_gapfill = (not offline_synthetic or custom_rm is not None) and (any_roads_enabled or include_buildings)
    need_bldg_gf = include_buildings and (len(osm_bldg_centers_xy) < max(6,int(width_m*height_m/220000.0))
                                        or not bool(osm_data.get('all_subtiles_ok',True)))
    if should_run_gapfill:
        report('Đang đối chiếu & khóa đủ 100% Đường chính + Đường ngõ theo Google Street Map...',76)
        try:
            gf_main,gf_alley,gf_bldgs = extract_google_street_vectors(
                south=south,west=west,north=north,east=east,cache_dir=cache_dir,
                xmin_local=xmin_local,xmax_local=xmax_local,ymin_local=ymin_local,ymax_local=ymax_local,
                existing_osm_roads_xy=osm_road_chains_xy,existing_osm_bldgs_xy=osm_bldg_centers_xy,
                need_roads=any_roads_enabled,need_buildings=need_bldg_gf,
                custom_roadmap_rgb=custom_rm if isinstance(custom_rm,np.ndarray) else None)
        except Exception:
            gf_main,gf_alley,gf_bldgs = [],[],[]
        if include_roads_main:
            for ch_m in gf_main:
                for clipped_m in _clip_polyline_to_rect(ch_m,xmin_local,xmax_local,ymin_local,ymax_local):
                    for s_m in _extract_slope_road_subchains(clipped_m):
                        rib_m = _sweep_road_ribbon_on_terrain(s_m,9.5,half_w,half_h,dem_grid,
                                                             z_offset_m=0.16,curb_floor_z=road_curb_z,min_road_z=road_min_z_main)
                        if rib_m:
                            road_main_parts.append(rib_m)
                            road_main_count += 1
                            gf_road_count += 1
        if include_roads_alley:
            for ch_a in gf_alley:
                for clipped_a in _clip_polyline_to_rect(ch_a,xmin_local,xmax_local,ymin_local,ymax_local):
                    for s_a in _extract_slope_road_subchains(clipped_a):
                        rib_a = _sweep_road_ribbon_on_terrain(s_a,4.5,half_w,half_h,dem_grid,
                                                             z_offset_m=0.12,curb_floor_z=road_curb_z,min_road_z=road_min_z_alley)
                        if rib_a:
                            road_alley_parts.append(rib_a)
                            road_alley_count += 1
                            gf_road_count += 1
    HIGHRISE_THRESHOLD_M = 21.0
    bldg_deferred_count = 0
    bldg_high_count = 0
    bldg_low_count = 0
    tex_wall_high = {i:[] for i in range(len(FACADE_SPECS))}
    tex_wall_low = {i:[] for i in range(len(FACADE_SPECS))}
    tex_parapet_high = []
    tex_parapet_low = []
    tex_roof_high = {i:[] for i in range(len(ROOF_SPECS))}
    tex_roof_low = {i:[] for i in range(len(ROOF_SPECS))}
    tex_bot_high = []
    tex_bot_low = []

    def _collect_articulated_bldg(art_res: Dict[str,Any], high_flag: bool):
        w_target = tex_wall_high if high_flag else tex_wall_low
        p_target = tex_parapet_high if high_flag else tex_parapet_low
        r_target = tex_roof_high if high_flag else tex_roof_low
        b_target = tex_bot_high if high_flag else tex_bot_low
        for f_k,w_list in art_res['walls_by_fac'].items():
            w_target[f_k].extend(w_list)
        p_target.extend(art_res['parapet_parts'])
        for r_k,r_list in art_res['roofs_by_idx'].items():
            r_target[r_k].extend(r_list)
        b_target.append(art_res['bottom_part'])

    if include_buildings and bldg_candidates:
        if len(bldg_candidates) > MAX_BUILDINGS_PER_TILE:
            bldg_deferred_count = len(bldg_candidates)-MAX_BUILDINGS_PER_TILE
            bldg_candidates.sort(key=lambda t:t[0],reverse=True)
            selected_bldgs = bldg_candidates[:MAX_BUILDINGS_PER_TILE]
        else:
            selected_bldgs = bldg_candidates
        for area_b,pts_b,tags_b,b_id in selected_bldgs:
            try:
                h_m = infer_vietnam_building_height(tags_b,area_b,b_id,default_floors=default_floors)
                is_high = h_m >= HIGHRISE_THRESHOLD_M
                if is_high and not include_buildings_high:
                    continue
                if not is_high and not include_buildings_low:
                    continue
                if building_style == 'textured':
                    fac_idx = select_facade_variant_index(tags_b,h_m,area_b,b_id)
                    art_ext = _build_articulated_building_v24(
                        pts_b,h_m,area_b,tags_b,b_id,half_w,half_h,dem_grid,fac_idx,
                        roof_style=roof_style,skirt_depth_m=bldg_skirt_m,min_z_base=bldg_min_z_base)
                    if art_ext:
                        _collect_articulated_bldg(art_ext,is_high)
                        if is_high:
                            bldg_high_count += 1
                        else:
                            bldg_low_count += 1
                        bldg_count += 1
                else:
                    ext = _extrude_polygon_on_terrain(pts_b,h_m,half_w,half_h,dem_grid,
                                                      skirt_depth_m=bldg_skirt_m,min_z_base=bldg_min_z_base)
                    if ext:
                        if is_high:
                            bldg_high_parts.append(ext)
                            bldg_high_count += 1
                        else:
                            bldg_low_parts.append(ext)
                            bldg_low_count += 1
                        bldg_count += 1
            except Exception:
                continue
    if need_bldg_gf and gf_bldgs and bldg_count < MAX_BUILDINGS_PER_TILE:
        rem_budget = MAX_BUILDINGS_PER_TILE-bldg_count
        gf_h_m = max(3.6,default_floors*3.3)
        gf_is_high = gf_h_m >= HIGHRISE_THRESHOLD_M
        if (gf_is_high and include_buildings_high) or (not gf_is_high and include_buildings_low):
            for gf_i,b_poly in enumerate(gf_bldgs[:rem_budget]):
                try:
                    if is_hill_patch:
                        gx_c = sum(p[0] for p in b_poly)/max(1,len(b_poly))
                        gy_c = sum(p[1] for p in b_poly)/max(1,len(b_poly))
                        if sample_dem_bilinear(gx_c,gy_c,half_w,half_h,dem_grid) <= SLOPE_MIN_Z:
                            continue
                    gf_area = max(24.0,abs(_signed_area_2d(b_poly)))
                    gf_tags = {'building':'yes'}
                    gf_bid = 900000+gf_i
                    if building_style == 'textured':
                        fac_idx_gf = select_facade_variant_index(gf_tags,gf_h_m,gf_area,gf_bid)
                        art_gf = _build_articulated_building_v24(
                            b_poly,gf_h_m,gf_area,gf_tags,gf_bid,half_w,half_h,dem_grid,fac_idx_gf,
                            roof_style=roof_style,skirt_depth_m=bldg_skirt_m,min_z_base=bldg_min_z_base)
                        if art_gf:
                            _collect_articulated_bldg(art_gf,gf_is_high)
                            if gf_is_high:
                                bldg_high_count += 1
                            else:
                                bldg_low_count += 1
                            bldg_count += 1
                            gf_bldg_count += 1
                    else:
                        ext_gf = _extrude_polygon_on_terrain(b_poly,gf_h_m,half_w,half_h,dem_grid,
                                                             skirt_depth_m=bldg_skirt_m,min_z_base=bldg_min_z_base)
                        if ext_gf:
                            if gf_is_high:
                                bldg_high_parts.append(ext_gf)
                                bldg_high_count += 1
                            else:
                                bldg_low_parts.append(ext_gf)
                                bldg_low_count += 1
                            bldg_count += 1
                            gf_bldg_count += 1
                except Exception:
                    continue
    road_count = road_main_count+road_alley_count
    peak_hour_window = bool(osm_data.get('peak_hour_window',False))
    peak_hour_degraded = bool(osm_data.get('peak_hour_degraded',False) or osm_data.get('overpass_overloaded',False))
    peak_hour_notice = ''
    if peak_hour_degraded:
        peak_hour_notice = 'Khung giờ cao điểm quốc tế (17:30–23:30): Máy chủ dữ liệu công trình thế giới đang nghẽn tải. MapSKP đã ưu tiên dựng đầy đủ Đường chính & Đường ngõ trước — bạn có thể cập nhật thêm khối công trình ngoài giờ cao điểm.'
    elif peak_hour_window and max(width_m,height_m) >= 1800.0:
        peak_hour_notice = 'Đang trong khung giờ cao điểm quốc tế (17:30–23:30): MapSKP đã kích hoạt chế độ Ưu tiên 100% Đường giao thông trước để bảo đảm ô lớn không bao giờ lỗi. Các cụm công trình nhỏ có thể cập nhật bổ sung ngoài giờ cao điểm.'
    high_meshes = []
    low_meshes = []
    if building_style == 'textured' and bldg_count > 0:
        materials.append({'name':str(PARAPET_TRIM_SPEC['name']), 'color':list(PARAPET_TRIM_COLOR),
                          'texture_bytes':get_parapet_trim_jpeg_bytes(),'ext':'jpg'})
        mat_parapet_idx = len(materials)-1
        roof_jpegs = get_roof_jpeg_bytes_list()
        roof_mat_map = {}
        for r_i,(r_spec,r_jpg) in enumerate(zip(ROOF_SPECS,roof_jpegs)):
            if r_i > 0 and not tex_roof_high[r_i] and not tex_roof_low[r_i]:
                continue
            materials.append({'name':str(r_spec['name']), 'color':list(r_spec['fallback_color']),
                              'texture_bytes':r_jpg,'ext':'jpg'})
            roof_mat_map[r_i] = len(materials)-1
        mat_concrete_deck_idx = roof_mat_map[0]
        facade_jpegs = get_facade_jpeg_bytes_list()
        facade_mat_map = {}
        for f_i,(spec,jpg_bytes) in enumerate(zip(FACADE_SPECS,facade_jpegs)):
            if f_i > 0 and not tex_wall_high[f_i] and not tex_wall_low[f_i]:
                continue
            materials.append({'name':str(spec['name']), 'color':list(spec['fallback_color']),
                              'texture_bytes':jpg_bytes,'ext':'jpg'})
            facade_mat_map[f_i] = len(materials)-1
        for f_i in range(len(FACADE_SPECS)):
            mw_h = _merge_uv_mesh_parts(tex_wall_high[f_i])
            if mw_h and f_i in facade_mat_map:
                high_meshes.append({'mat_idx':facade_mat_map[f_i],'verts':mw_h[0],'faces':mw_h[1],'uvs':mw_h[2]})
            mw_l = _merge_uv_mesh_parts(tex_wall_low[f_i])
            if mw_l and f_i in facade_mat_map:
                low_meshes.append({'mat_idx':facade_mat_map[f_i],'verts':mw_l[0],'faces':mw_l[1],'uvs':mw_l[2]})
        mp_h = _merge_uv_mesh_parts(tex_parapet_high)
        if mp_h:
            high_meshes.append({'mat_idx':mat_parapet_idx,'verts':mp_h[0],'faces':mp_h[1],'uvs':mp_h[2]})
        mp_l = _merge_uv_mesh_parts(tex_parapet_low)
        if mp_l:
            low_meshes.append({'mat_idx':mat_parapet_idx,'verts':mp_l[0],'faces':mp_l[1],'uvs':mp_l[2]})
        for r_i in range(len(ROOF_SPECS)):
            mr_h = _merge_uv_mesh_parts(tex_roof_high[r_i])
            if mr_h and r_i in roof_mat_map:
                high_meshes.append({'mat_idx':roof_mat_map[r_i],'verts':mr_h[0],'faces':mr_h[1],'uvs':mr_h[2]})
            mr_l = _merge_uv_mesh_parts(tex_roof_low[r_i])
            if mr_l and r_i in roof_mat_map:
                low_meshes.append({'mat_idx':roof_mat_map[r_i],'verts':mr_l[0],'faces':mr_l[1],'uvs':mr_l[2]})
        mb_h = _merge_mesh_parts(tex_bot_high)
        if mb_h:
            high_meshes.append({'mat_idx':mat_concrete_deck_idx,'verts':mb_h[0],'faces':mb_h[1],'uvs':None})
        mb_l = _merge_mesh_parts(tex_bot_low)
        if mb_l:
            low_meshes.append({'mat_idx':mat_concrete_deck_idx,'verts':mb_l[0],'faces':mb_l[1],'uvs':None})
    else:
        m_high = _merge_mesh_parts(bldg_high_parts)
        if m_high:
            high_meshes.append({'mat_idx':3,'verts':m_high[0],'faces':m_high[1],'uvs':None})
        m_low = _merge_mesh_parts(bldg_low_parts)
        if m_low:
            low_meshes.append({'mat_idx':2,'verts':m_low[0],'faces':m_low[1],'uvs':None})
    if high_meshes:
        layers.append({'name':f'MapSKP_Buildings_Highrise ({bldg_high_count})',
                       'tag':'MapSKP_02A_Buildings_Highrise','tag_color':[59,130,246],
                       'soften_cos':0.995,'meshes':high_meshes})
    if low_meshes:
        layers.append({'name':f'MapSKP_Buildings_Lowrise ({bldg_low_count})',
                       'tag':'MapSKP_02B_Buildings_Lowrise','tag_color':[233,69,96],
                       'soften_cos':0.995,'meshes':low_meshes})
    m_road_main = _merge_mesh_parts(road_main_parts)
    if m_road_main:
        layers.append({'name':f'MapSKP_Roads_Main ({road_main_count})',
                       'tag':'MapSKP_03A_Roads_Main','tag_color':[243,156,18],
                       'soften_cos':road_soften_cos,
                       'meshes':[{'mat_idx':4,'verts':m_road_main[0],'faces':m_road_main[1],'uvs':None}]})
    m_road_alley = _merge_mesh_parts(road_alley_parts)
    if m_road_alley:
        layers.append({'name':f'MapSKP_Roads_Alley ({road_alley_count})',
                       'tag':'MapSKP_03B_Roads_Alley','tag_color':[149,165,166],
                       'soften_cos':road_soften_cos,
                       'meshes':[{'mat_idx':7,'verts':m_road_alley[0],'faces':m_road_alley[1],'uvs':None}]})
    m_water = _merge_mesh_parts(water_parts)
    if m_water:
        layers.append({'name':'MapSKP_Water','tag':'MapSKP_04_Water','tag_color':[52,152,219],
                       'soften_cos':0.85,
                       'meshes':[{'mat_idx':5,'verts':m_water[0],'faces':m_water[1],'uvs':None}]})
    if include_trees and tree_points:
        tree_parts = []
        kept_tree_cnt = 0
        for idx,(tx,ty) in enumerate(tree_points):
            if kept_tree_cnt >= 350:
                break
            tz = sample_dem_bilinear(tx,ty,half_w,half_h,dem_grid)
            if is_hill_patch and tz <= SLOPE_MIN_Z:
                continue
            th = 5.5+(kept_tree_cnt%4)*1.1
            tree_parts.append(_make_architectural_tree(tx,ty,tz,height_m=th))
            kept_tree_cnt += 1
        m_tree = _merge_mesh_parts(tree_parts)
        if m_tree:
            layers.append({'name':f'MapSKP_Trees ({kept_tree_cnt})','tag':'MapSKP_05_Trees',
                           'tag_color':[46,204,113],'soften_cos':0.98,
                           'meshes':[{'mat_idx':6,'verts':m_tree[0],'faces':m_tree[1],'uvs':None}]})
    report('Đã hoàn tất dựng mô hình bối cảnh 3D!',95)
    return {
        'name':str(params.get('project_name') or f'MapSKP_{lat0:.4f}_{lon0:.4f}'),
        'origin':{
            'lat':round(lat0,7),'lon':round(lon0,7),'elevation_m':round(center_elev,3),
            'south':round(south,7),'west':round(west,7),'north':round(north,7),'east':round(east,7),
            'terrain_mode':terrain_mode,'hill_patch':is_hill_patch,
            'hill_foot_asl_m':round(hill_foot_asl_m,3),'hill_peak_rel_m':round(hill_peak_rel_m,3),
            'z_exaggeration':round(z_exag,3),'tz_offset':estimate_tz_offset(lon0),
            'width_m':round(width_m,2),'height_m':round(height_m,2),
            'anchor_lat':round(anchor_lat,7),'anchor_lon':round(anchor_lon,7),
            'anchor_elev_m':round(anchor_elev_m,3),'anchor_terrain_mode':anchor_terrain_mode,
            'has_prior_anchor':has_prior_anchor,
            'offset_from_anchor_m':[round(cx_anchor,4),round(cy_anchor,4),round(dz_anchor,4)],
            'buildings_count':bldg_count,'buildings_highrise_count':bldg_high_count,'buildings_lowrise_count':bldg_low_count,
            'building_style':building_style,'roof_style':roof_style,'buildings_deferred_count':bldg_deferred_count,
            'roads_count':road_count,'roads_main_count':road_main_count,'roads_alley_count':road_alley_count,
            'google_gapfill_roads':gf_road_count,'google_gapfill_buildings':gf_bldg_count,
            'mvt_used':bool(osm_data.get('mvt_used',False)),'peak_hour_window':peak_hour_window,
            'peak_hour_degraded':peak_hour_degraded,'peak_hour_notice':peak_hour_notice,
        },
        'materials':materials,'layers':layers,
    }
