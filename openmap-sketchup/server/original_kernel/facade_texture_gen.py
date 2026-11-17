"""Readable reconstruction of facade_texture_gen from user-provided MapSKP code.

Original rights are retained; this reconstruction is not relicensed under MIT.
All numerical/image routines are checked against the unmodified original code.
"""
from __future__ import annotations
import io
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from PIL import Image

ROOF_CONCRETE_COLOR = [132, 138, 146, 255]

PARAPET_TRIM_COLOR = [214, 218, 224, 255]

PODIUM_FACADE_INDEX = 5

PENTHOUSE_FACADE_INDEX = 4

FACADE_SPECS = [{'key': 'blue_glass',
  'name': 'MapSKP_Facade_01_BlueGlass',
  'fallback_color': [104, 156, 206, 255],
  'bays_per_tile': 16,
  'floors_per_tile': 12,
  'bay_w_m': 2.1,
  'floor_h_m': 3.6,
  'tier': 'high'},
 {'key': 'teal_mirror',
  'name': 'MapSKP_Facade_02_TealMirrorGlass',
  'fallback_color': [92, 142, 154, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 12,
  'bay_w_m': 2.6,
  'floor_h_m': 3.6,
  'tier': 'high'},
 {'key': 'white_grid',
  'name': 'MapSKP_Facade_03_WhiteGrid',
  'fallback_color': [228, 232, 238, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 12,
  'bay_w_m': 3.2,
  'floor_h_m': 3.5,
  'tier': 'high'},
 {'key': 'warm_highrise',
  'name': 'MapSKP_Facade_04_WarmHighrise',
  'fallback_color': [224, 215, 200, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 12,
  'bay_w_m': 3.4,
  'floor_h_m': 3.3,
  'tier': 'high'},
 {'key': 'charcoal_tower',
  'name': 'MapSKP_Facade_05_CharcoalTower',
  'fallback_color': [74, 82, 92, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 12,
  'bay_w_m': 2.8,
  'floor_h_m': 3.6,
  'tier': 'high'},
 {'key': 'podium_commercial',
  'name': 'MapSKP_Facade_06_PodiumCommercial',
  'fallback_color': [154, 152, 148, 255],
  'bays_per_tile': 8,
  'floors_per_tile': 4,
  'bay_w_m': 4.8,
  'floor_h_m': 4.3,
  'tier': 'podium'},
 {'key': 'cream_shophouse',
  'name': 'MapSKP_Facade_07_CreamShophouse',
  'fallback_color': [232, 226, 214, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 8,
  'bay_w_m': 3.8,
  'floor_h_m': 3.35,
  'tier': 'low'},
 {'key': 'terracotta_urban',
  'name': 'MapSKP_Facade_08_TerracottaUrban',
  'fallback_color': [174, 118, 96, 255],
  'bays_per_tile': 12,
  'floors_per_tile': 8,
  'bay_w_m': 3.6,
  'floor_h_m': 3.35,
  'tier': 'low'}]

PARAPET_TRIM_SPEC = {'key': 'parapet_trim',
 'name': 'MapSKP_Roof_Parapet_Trim',
 'fallback_color': [214, 218, 224, 255],
 'tile_w_m': 4.0,
 'tile_h_m': 4.0}

ROOF_SPECS = [{'key': 'concrete_deck',
  'name': 'MapSKP_Roof_Concrete_Grey',
  'fallback_color': [132, 138, 146, 255],
  'tile_w_m': 8.0,
  'tile_h_m': 8.0},
 {'key': 'metal_muted_red',
  'name': 'MapSKP_Roof_Metal_MutedRed',
  'fallback_color': [134, 76, 70, 255],
  'tile_w_m': 6.0,
  'tile_h_m': 6.0},
 {'key': 'metal_muted_blue',
  'name': 'MapSKP_Roof_Metal_MutedBlue',
  'fallback_color': [68, 90, 110, 255],
  'tile_w_m': 6.0,
  'tile_h_m': 6.0},
 {'key': 'metal_muted_green',
  'name': 'MapSKP_Roof_Metal_MutedGreen',
  'fallback_color': [72, 94, 82, 255],
  'tile_w_m': 6.0,
  'tile_h_m': 6.0}]

_FACADE_JPEG_CACHE = None

_ROOF_JPEG_CACHE = None

_PARAPET_JPEG_CACHE = None

def _cell_hash(bx: int, fy: int, salt: int) -> float:
    x = ((bx * 73856093) ^ (fy * 19349663) ^ (salt * 83492791)) & 4294967295
    x = ((x ^ (x >> 16)) * 73244475) & 4294967295
    x = (x ^ (x >> 16)) & 65535
    return x / 65535.0


def _periodic_value_noise_2d(sz: int, period: int, seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    grid = rng.uniform(0.0, 1.0, size=(period, period)).astype(np.float32)
    coords = np.linspace(0.0, float(period), sz, endpoint=False, dtype=np.float32)
    i0 = np.floor(coords).astype(np.int32) % period
    i1 = (i0 + 1) % period
    f = coords - np.floor(coords)
    u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0)
    c00 = grid[i0[:, None], i0[None, :]]
    c10 = grid[i1[:, None], i0[None, :]]
    c01 = grid[i0[:, None], i1[None, :]]
    c11 = grid[i1[:, None], i1[None, :]]
    wy = u[:, None]
    wx = u[None, :]
    nx0 = c00 * (1.0 - wx) + c01 * wx
    nx1 = c10 * (1.0 - wx) + c11 * wx
    return nx0 * (1.0 - wy) + nx1 * wy


def _seamless_cloud_fbm(sz: int, seed: int = 1337) -> np.ndarray:
    acc = np.zeros((sz, sz), dtype=np.float32)
    amp = 0.52
    norm = 0.0
    for oct_i, period in enumerate((2, 4, 8, 16, 32)):
        acc += amp * _periodic_value_noise_2d(sz, period, seed + oct_i * 97)
        norm += amp
        amp *= 0.52
    fbm = acc / max(1e-6, norm)
    fbm = np.clip((fbm - 0.36) / 0.46, 0.0, 1.0)
    return fbm * fbm * (3.0 - 2.0 * fbm)


def _sample_sky_environment_field(sz: int, zenith_rgb: Tuple[float, float, float], horizon_rgb: Tuple[float, float, float], cloud_rgb: Tuple[float, float, float], cloud_strength: float, seed: int) -> np.ndarray:
    clouds = _seamless_cloud_fbm(sz, seed=seed)
    haze = _periodic_value_noise_2d(sz, period=3, seed=seed + 501)
    yy = np.linspace(0.0, 1.0, sz, endpoint=False, dtype=np.float32)[:, None]
    sky_t = 0.5 - 0.5 * np.cos(2.0 * np.pi * yy)
    sky_t = 0.65 * sky_t + 0.35 * haze
    z_arr = np.array(zenith_rgb, dtype=np.float32)[None, None, :]
    h_arr = np.array(horizon_rgb, dtype=np.float32)[None, None, :]
    c_arr = np.array(cloud_rgb, dtype=np.float32)[None, None, :]
    sky = z_arr * (1.0 - sky_t[:, :, None]) + h_arr * sky_t[:, :, None]
    c_mask = (clouds * cloud_strength)[:, :, None]
    return sky * (1.0 - c_mask) + c_arr * c_mask


def _avalanche_u16(b_id: int, salt: int = 0) -> int:
    x_mix = ((int(b_id) & 4294967295) ^ ((int(b_id) >> 16) & 65535) ^ (int(salt) & 4294967295)) * 73244475
    x_mix = ((x_mix & 4294967295) ^ ((x_mix >> 16) & 65535)) * 73244475
    return ((x_mix & 4294967295) ^ ((x_mix >> 16) & 65535)) & 65535


def select_facade_variant_index(tags: Dict[str, Any], height_m: float, area_m2: float, b_id: int) -> int:
    btype = str(tags.get('building') or 'yes').lower()
    h_bucket = _avalanche_u16(b_id, int(round(area_m2)))
    if height_m >= 21.0:
        if btype in ('office', 'commercial', 'civic', 'public') or height_m >= 42.0:
            r = h_bucket % 12
            if r < 4:
                return 0
            if r < 7:
                return 1
            if r < 10:
                return 2
            if r == 10:
                return 4
            return 3
        if btype in ('apartments', 'residential', 'dormitory', 'hotel'):
            r = h_bucket % 12
            if r < 5:
                return 3
            if r < 8:
                return 2
            if r < 10:
                return 1
            if r == 10:
                return 0
            return 4
        r = h_bucket % 15
        if r < 4:
            return 0
        if r < 7:
            return 1
        if r < 10:
            return 2
        if r < 13:
            return 3
        return 4
    if btype in ('commercial', 'office', 'retail', 'hotel') and height_m >= 13.5 and area_m2 >= 180.0:
        return 4 if h_bucket % 3 == 0 else 2
    return 7 if h_bucket % 10 < 3 else 6


def select_lowrise_roof_variant_index(tags: Dict[str, Any], area_m2: float, b_id: int, roof_style: str = 'parapet_vietnam') -> int:
    if roof_style == 'parapet_concrete':
        return 0
    rmat = str(tags.get('roof:material') or '').lower()
    if rmat in ('concrete', 'stone', 'tar_paper'):
        return 0
    h = _avalanche_u16(b_id, int(round(area_m2 * 3.0)) + 7919) % 20
    if h < 7:
        return 1
    if h < 13:
        return 2
    if h < 16:
        return 3
    return 0


def _encode_rgb_jpeg(arr: np.ndarray, quality: int = 89) -> bytes:
    clipped = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(clipped, mode='RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    return buf.getvalue()


def _gen_blue_curtain_wall(sz: int = 1024) -> np.ndarray:
    sky_env = _sample_sky_environment_field(
        sz,
        zenith_rgb=(54.0, 114.0, 182.0),
        horizon_rgb=(112.0, 168.0, 218.0),
        cloud_rgb=(234.0, 243.0, 252.0),
        cloud_strength=0.68,
        seed=1401,
    )
    img = sky_env.copy()
    bays, floors = 16, 12
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        cell_h = y1 - y0
        sp_h = max(14, cell_h // 5)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            cell_w = x1 - x0
            r_sx = _cell_hash(bx, fy, 11)
            r_sy = _cell_hash(bx, fy, 23)
            dx = int((r_sx - 0.5) * 44.0)
            dy = int((r_sy - 0.5) * 36.0)
            ys = (np.arange(y0, y1) + dy) % sz
            xs = (np.arange(x0, x1) + dx) % sz
            pane_sky = sky_env[ys[:, None], xs[None, :]].copy()
            rnd = _cell_hash(bx, fy, 101)
            rnd2 = _cell_hash(bx, fy, 109)
            if rnd > 0.78:
                blind_end = sp_h + int((cell_h - sp_h) * (0.36 + 0.45 * rnd2))
                pane_sky[sp_h + 2:blind_end, 3:cell_w - 2] = (
                    pane_sky[sp_h + 2:blind_end, 3:cell_w - 2] * 0.52
                    + np.array([204.0, 214.0, 226.0], dtype=np.float32) * 0.48
                )
            elif rnd < 0.22:
                pane_sky[sp_h + 2:, :] *= 0.76
            elif 0.46 <= rnd <= 0.54:
                pane_sky[sp_h + 4:cell_h - 6, 4:cell_w - 4] = (
                    pane_sky[sp_h + 4:cell_h - 6, 4:cell_w - 4] * 0.74
                    + np.array([186.0, 174.0, 146.0], dtype=np.float32) * 0.26
                )
            pane_sky[:sp_h, :] = pane_sky[:sp_h, :] * 0.54 + np.array([22.0, 44.0, 74.0], dtype=np.float32) * 0.46
            pane_sky[sp_h:sp_h + 3, :] *= 0.72
            img[y0:y1, x0:x1] = pane_sky
            img[y0:y1, x0:x0 + 2] = (212.0, 224.0, 236.0)
            img[y0:y1, x0 + 2:x0 + 4] *= 0.72
            img[y0:y1, x1 - 1:x1] = (182.0, 198.0, 214.0)
        img[y0:y0 + 2, :] = (218.0, 228.0, 240.0)
        img[y0 + sp_h - 1:y0 + sp_h + 1, :] = (176.0, 194.0, 212.0)
    return img


def _gen_teal_mirror_tower(sz: int = 1024) -> np.ndarray:
    sky_env = _sample_sky_environment_field(
        sz, zenith_rgb=(44.0, 96.0, 114.0), horizon_rgb=(104.0, 156.0, 168.0),
        cloud_rgb=(224.0, 238.0, 240.0), cloud_strength=0.62, seed=2402,
    )
    img = sky_env.copy()
    bays, floors = 12, 12
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        cell_h = y1 - y0
        sp_h = max(14, cell_h // 5)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            cell_w = x1 - x0
            dx = int((_cell_hash(bx, fy, 31) - 0.5) * 40.0)
            dy = int((_cell_hash(bx, fy, 37) - 0.5) * 32.0)
            ys = (np.arange(y0, y1) + dy) % sz
            xs = (np.arange(x0, x1) + dx) % sz
            pane = sky_env[ys[:, None], xs[None, :]].copy()
            rnd = _cell_hash(bx, fy, 205)
            if rnd > 0.76:
                bh = sp_h + int((cell_h - sp_h) * (0.4 + 0.4 * _cell_hash(bx, fy, 211)))
                pane[sp_h + 2:bh, 4:cell_w - 3] = (
                    pane[sp_h + 2:bh, 4:cell_w - 3] * 0.55
                    + np.array([196.0, 210.0, 212.0], dtype=np.float32) * 0.45
                )
            elif rnd < 0.25:
                pane[sp_h + 2:, :] *= 0.74
            pane[:sp_h, :] = pane[:sp_h, :] * 0.48 + np.array([26.0, 52.0, 62.0], dtype=np.float32) * 0.52
            pane[sp_h:sp_h + 3, :] *= 0.7
            mid_x = cell_w // 2
            pane[:, mid_x - 1:mid_x + 1] = pane[:, mid_x - 1:mid_x + 1] * 0.4 + np.array([148.0, 168.0, 174.0]) * 0.6
            img[y0:y1, x0:x1] = pane
            img[y0:y1, x0:x0 + 3] = (202.0, 214.0, 218.0)
            img[y0:y1, x0 + 3:x0 + 6] *= 0.68
        img[y0:y0 + 2, :] = (196.0, 210.0, 214.0)
    return img


def _gen_white_grid_tower(sz: int = 1024) -> np.ndarray:
    stone_noise = _periodic_value_noise_2d(sz, period=16, seed=3101)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = 232.0 + 10.0 * stone_noise
    img[:, :, 1] = 235.0 + 10.0 * stone_noise
    img[:, :, 2] = 240.0 + 9.0 * stone_noise
    sky_glass = _sample_sky_environment_field(
        sz, zenith_rgb=(36.0, 56.0, 82.0), horizon_rgb=(74.0, 102.0, 134.0),
        cloud_rgb=(176.0, 196.0, 216.0), cloud_strength=0.52, seed=3303,
    )
    bays, floors = 12, 12
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        img[y0:y0 + 3, :] = (248.0, 250.0, 252.0)
        img[y0 + 3:y0 + 7, :] = (198.0, 205.0, 214.0)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            pad_l = 14 if bx % 4 == 0 else 10
            pad_r = 14 if bx % 4 == 3 else 10
            wx0, wx1 = x0 + pad_l, x1 - pad_r
            wy0, wy1 = y0 + 13, y1 - 10
            img[wy0 - 3:wy1, wx0 - 3:wx1] = (164.0, 172.0, 184.0)
            img[wy1:wy1 + 2, wx0 - 2:wx1 + 2] = (249.0, 251.0, 253.0)
            dx = int((_cell_hash(bx, fy, 41) - 0.5) * 32.0)
            dy = int((_cell_hash(bx, fy, 43) - 0.5) * 28.0)
            ys = (np.arange(wy0, wy1) + dy) % sz
            xs = (np.arange(wx0, wx1) + dx) % sz
            pane = sky_glass[ys[:, None], xs[None, :]].copy()
            rnd = _cell_hash(bx, fy, 309)
            if 0.42 <= rnd <= 0.63:
                bh = int((wy1 - wy0) * (0.35 + 0.45 * _cell_hash(bx, fy, 317)))
                pane[:bh, 2:-2] = pane[:bh, 2:-2] * 0.35 + np.array([204.0, 210.0, 218.0], dtype=np.float32) * 0.65
            elif rnd > 0.84:
                pane *= 1.18
            elif rnd < 0.18:
                pane *= 0.78
            img[wy0:wy1, wx0:wx1] = pane
            mx = (wx0 + wx1) // 2
            img[wy0:wy1, mx - 1:mx + 1] = (218.0, 224.0, 232.0)
            img[y0:y1, x0:x0 + 2] = (214.0, 220.0, 228.0)
    return img


def _gen_warm_highrise_apt(sz: int = 1024) -> np.ndarray:
    wall_noise = _periodic_value_noise_2d(sz, period=12, seed=4101)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = 228.0 + 10.0 * wall_noise
    img[:, :, 1] = 219.0 + 9.0 * wall_noise
    img[:, :, 2] = 204.0 + 8.0 * wall_noise
    sky_glass = _sample_sky_environment_field(
        sz, zenith_rgb=(42.0, 66.0, 92.0), horizon_rgb=(86.0, 114.0, 138.0),
        cloud_rgb=(188.0, 202.0, 214.0), cloud_strength=0.45, seed=4202,
    )
    bays, floors = 12, 12
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        img[y0:y0 + 6, :] = (240.0, 234.0, 222.0)
        img[y0 + 6:y0 + 10, :] = (188.0, 178.0, 162.0)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            rnd = _cell_hash(bx, fy, 409)
            if bx % 3 == 1:
                lx0, lx1 = x0 + 8, x1 - 8
                ly0, ly1 = y0 + 11, y1 - 5
                img[ly0:ly1, lx0:lx1] = (66.0, 64.0, 62.0) if rnd < 0.65 else (88.0, 82.0, 74.0)
                gx0, gx1 = lx0 + 6, lx1 - 6
                gy0, gy1 = ly0 + 5, ly1 - 20
                img[gy0:gy1, gx0:gx1] = sky_glass[gy0:gy1, gx0:gx1] * (0.82 if rnd < 0.78 else 1.05)
                rail_y = ly1 - 22
                img[rail_y:rail_y + 2, lx0:lx1] = (218.0, 222.0, 226.0)
                img[rail_y + 2:ly1, lx0:lx1] = (
                    img[rail_y + 2:ly1, lx0:lx1] * 0.42
                    + np.array([116.0, 142.0, 158.0], dtype=np.float32) * 0.58
                )
            else:
                has_louver = bx % 3 == 2
                wx0 = x0 + 12
                wx1 = x1 - (24 if has_louver else 12)
                wy0, wy1 = y0 + 16, y1 - 18
                img[wy0 - 2:wy1 + 2, wx0 - 2:wx1 + 2] = (176.0, 166.0, 150.0)
                pane = sky_glass[wy0:wy1, wx0:wx1].copy()
                if rnd > 0.74:
                    pane = pane * 0.45 + np.array([186.0, 176.0, 156.0], dtype=np.float32) * 0.55
                img[wy0:wy1, wx0:wx1] = pane
                mx = (wx0 + wx1) // 2
                img[wy0:wy1, mx - 1:mx + 1] = (228.0, 222.0, 212.0)
                if has_louver:
                    lx0_l, lx1_l = x1 - 19, x1 - 7
                    for sl_y in range(y0 + 15, y1 - 12, 5):
                        img[sl_y:sl_y + 2, lx0_l:lx1_l] = (132.0, 124.0, 112.0)
            if bx % 3 == 0:
                img[y0:y1, x0:x0 + 3] = (206.0, 196.0, 180.0)
    return img


def _gen_cream_shophouse(sz: int = 1024) -> np.ndarray:
    plaster = _periodic_value_noise_2d(sz, period=16, seed=7101)
    img = np.full((sz, sz, 3), (234.0, 228.0, 216.0), dtype=np.float32)
    sky_win = _sample_sky_environment_field(
        sz, zenith_rgb=(40.0, 56.0, 74.0), horizon_rgb=(76.0, 96.0, 116.0),
        cloud_rgb=(168.0, 182.0, 196.0), cloud_strength=0.4, seed=7202,
    )
    bays, floors = 12, 8
    bw = sz // bays
    fh = sz // floors
    palettes = (
        (238.0, 233.0, 222.0),
        (224.0, 226.0, 229.0),
        (236.0, 226.0, 206.0),
        (230.0, 225.0, 218.0),
    )
    for bx in range(bays):
        x0 = bx * bw
        x1 = sz if bx == bays - 1 else (bx + 1) * bw
        base_c = palettes[(bx // 2 + bx % 3) % len(palettes)]
        for ch in range(3):
            img[:, x0:x1, ch] = base_c[ch] + (plaster[:, x0:x1] - 0.5) * 10.0
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        img[y0:y0 + 6, :] = np.clip(img[y0:y0 + 6, :] + 12.0, 0.0, 252.0)
        img[y0 + 6:y0 + 10, :] *= 0.84
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            img[y0:y1, x0:x0 + 2] *= 0.86
            wx0, wx1 = x0 + 16, x1 - 16
            wy0, wy1 = y0 + 18, y1 - 14
            rnd = _cell_hash(bx, fy, 709)
            img[wy0 - 3:wy1 + 3, wx0 - 3:wx1 + 3] = (248.0, 246.0, 242.0)
            pane = sky_win[wy0:wy1, wx0:wx1].copy()
            if rnd > 0.72:
                pane = pane * 0.45 + np.array([172.0, 162.0, 144.0], dtype=np.float32) * 0.55
            img[wy0:wy1, wx0:wx1] = pane
            mx = (wx0 + wx1) // 2
            img[wy0:wy1, mx - 1:mx + 2] = (240.0, 238.0, 232.0)
            rail_y = y1 - 22
            img[rail_y:rail_y + 2, x0 + 10:x1 - 10] = (92.0, 96.0, 102.0)
            for rx in range(x0 + 12, x1 - 10, 7):
                img[rail_y + 2:y1 - 6, rx:rx + 1] = (108.0, 112.0, 118.0)
    return img


def _gen_terracotta_urban(sz: int = 1024) -> np.ndarray:
    tex_n = _periodic_value_noise_2d(sz, period=16, seed=8101)
    yy = np.arange(sz, dtype=np.int32)[:, None]
    brick_course = (yy % 8 == 0).astype(np.float32)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = 172.0 + 14.0 * (tex_n - 0.5) - 7.0 * brick_course
    img[:, :, 1] = 118.0 + 11.0 * (tex_n - 0.5) - 5.0 * brick_course
    img[:, :, 2] = 98.0 + 9.0 * (tex_n - 0.5) - 4.0 * brick_course
    sky_win = _sample_sky_environment_field(
        sz, zenith_rgb=(38.0, 52.0, 68.0), horizon_rgb=(74.0, 92.0, 110.0),
        cloud_rgb=(162.0, 176.0, 190.0), cloud_strength=0.38, seed=8202,
    )
    bays, floors = 12, 8
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        img[y0:y0 + 6, :] = (218.0, 198.0, 182.0)
        img[y0 + 6:y0 + 9, :] = (128.0, 84.0, 68.0)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            if bx % 3 == 0:
                img[y0:y1, x0:x0 + 2] = (142.0, 96.0, 78.0)
            wx0, wx1 = x0 + 18, x1 - 18
            wy0, wy1 = y0 + 20, y1 - 18
            rnd = _cell_hash(bx, fy, 809)
            img[wy0 - 4:wy1 + 4, wx0 - 4:wx1 + 4] = (238.0, 232.0, 222.0)
            pane = sky_win[wy0:wy1, wx0:wx1].copy()
            if rnd > 0.74:
                pane = pane * 0.48 + np.array([156.0, 142.0, 122.0], dtype=np.float32) * 0.52
            img[wy0:wy1, wx0:wx1] = pane
            mx = (wx0 + wx1) // 2
            my = wy0 + (wy1 - wy0) // 2
            img[wy0:wy1, mx - 1:mx + 1] = (232.0, 226.0, 216.0)
            img[my - 1:my + 1, wx0:wx1] = (232.0, 226.0, 216.0)
    return img


def _gen_parapet_trim_stone(sz: int = 256) -> np.ndarray:
    n1 = _periodic_value_noise_2d(sz, period=8, seed=9001)
    n2 = _periodic_value_noise_2d(sz, period=32, seed=9002)
    base = 212.0 + 8.0 * (n1 - 0.5) + 5.0 * (n2 - 0.5)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = base
    img[:, :, 1] = base + 3.0
    img[:, :, 2] = base + 8.0
    for k in (0, sz // 2):
        img[:, k:k + 2] *= 0.91
    return img


def _gen_concrete_roof_deck(sz: int = 512) -> np.ndarray:
    n_macro = _periodic_value_noise_2d(sz, period=4, seed=9101)
    n_fine = _periodic_value_noise_2d(sz, period=32, seed=9102)
    val = 132.0 + 14.0 * (n_macro - 0.5) + 8.0 * (n_fine - 0.5)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = val - 2.0
    img[:, :, 1] = val + 3.0
    img[:, :, 2] = val + 10.0
    step = sz // 2
    for pos in range(0, sz, step):
        img[pos:pos + 2, :] *= 0.84
        img[pos + 2:pos + 3, :] = np.clip(img[pos + 2:pos + 3, :] * 1.07, 0.0, 255.0)
        img[:, pos:pos + 2] *= 0.84
        img[:, pos + 2:pos + 3] = np.clip(img[:, pos + 2:pos + 3] * 1.07, 0.0, 255.0)
    return img


def _gen_corrugated_metal_roof(base_rgb: Tuple[float, float, float], seed: int, sz: int = 512) -> np.ndarray:
    weather = _periodic_value_noise_2d(sz, period=4, seed=seed)
    grain = _periodic_value_noise_2d(sz, period=16, seed=seed + 17)
    xx = np.linspace(0.0, 1.0, sz, endpoint=False, dtype=np.float32)[None, :]
    ribs = 32.0
    wave = np.sin(2.0 * np.pi * ribs * xx)
    ridge = 0.65 * wave + 0.35 * np.tanh(2.2 * wave)
    shade = 1.0 + 0.11 * ridge + 0.08 * (weather - 0.5) + 0.04 * (grain - 0.5)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = base_rgb[0] * shade
    img[:, :, 1] = base_rgb[1] * shade
    img[:, :, 2] = base_rgb[2] * shade
    for lap_y in (0, sz // 2):
        img[lap_y:lap_y + 2, :] *= 0.82
        img[lap_y + 2:lap_y + 4, :] = np.clip(img[lap_y + 2:lap_y + 4, :] * 1.08, 0.0, 255.0)
    return img


def _gen_charcoal_commercial_tower(sz: int = 1024) -> np.ndarray:
    img = np.full((sz, sz, 3), (62.0, 68.0, 78.0), dtype=np.float32)
    sky_glass = _sample_sky_environment_field(
        sz,
        zenith_rgb=(38.0, 54.0, 76.0),
        horizon_rgb=(82.0, 106.0, 132.0),
        cloud_rgb=(174.0, 188.0, 204.0),
        cloud_strength=0.48,
        seed=5105,
    )
    bays, floors = 12, 12
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        img[y0:y0 + 11, :] = (48.0, 54.0, 64.0)
        img[y0:y0 + 2, :] = (138.0, 144.0, 154.0)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            wx0, wx1 = x0 + 7, x1 - 6
            wy0, wy1 = y0 + 13, y1 - 6
            dx = int((_cell_hash(bx, fy, 53) - 0.5) * 30.0)
            dy = int((_cell_hash(bx, fy, 59) - 0.5) * 26.0)
            ys = (np.arange(wy0, wy1) + dy) % sz
            xs = (np.arange(wx0, wx1) + dx) % sz
            pane = sky_glass[ys[:, None], xs[None, :]].copy()
            rnd = _cell_hash(bx, fy, 509)
            if rnd > 0.8:
                pane = pane * 0.48 + np.array([164.0, 146.0, 114.0], dtype=np.float32) * 0.52
            elif rnd < 0.28:
                pane *= 0.72
            img[wy0:wy1, wx0:wx1] = pane
            fin_col = (166.0, 164.0, 158.0) if bx % 2 == 0 else (138.0, 144.0, 152.0)
            img[y0:y1, x0:x0 + 3] = fin_col
            img[y0:y1, x0 + 3:x0 + 6] = (34.0, 38.0, 46.0)
    return img


def _gen_podium_commercial(sz: int = 1024) -> np.ndarray:
    granite = _periodic_value_noise_2d(sz, period=16, seed=6101)
    img = np.zeros((sz, sz, 3), dtype=np.float32)
    img[:, :, 0] = 166.0 + 16.0 * granite
    img[:, :, 1] = 162.0 + 15.0 * granite
    img[:, :, 2] = 156.0 + 14.0 * granite
    sky_street = _sample_sky_environment_field(
        sz,
        zenith_rgb=(52.0, 82.0, 112.0),
        horizon_rgb=(116.0, 138.0, 156.0),
        cloud_rgb=(206.0, 214.0, 222.0),
        cloud_strength=0.42,
        seed=6202,
    )
    bays, floors = 8, 4
    bw = sz // bays
    fh = sz // floors
    for fy in range(floors):
        y0 = fy * fh
        y1 = sz if fy == floors - 1 else (fy + 1) * fh
        band_h = 22 if fy == 0 else 14
        img[y0:y0 + 4, :] = (206.0, 202.0, 194.0)
        img[y0 + 4:y0 + band_h, :] = (142.0, 138.0, 132.0)
        img[y0 + band_h:y0 + band_h + 4, :] = (92.0, 90.0, 88.0)
        for bx in range(bays):
            x0 = bx * bw
            x1 = sz if bx == bays - 1 else (bx + 1) * bw
            pil_w = 18
            wx0, wx1 = x0 + pil_w, x1 - pil_w
            wy0, wy1 = y0 + band_h + 4, y1 - 10
            pane = sky_street[wy0:wy1, wx0:wx1].copy()
            rnd = _cell_hash(bx, fy, 607)
            warm_tint = np.array([182.0, 164.0, 132.0], dtype=np.float32)
            mix_w = 0.34 if fy >= floors - 2 else (0.24 if rnd > 0.55 else 0.08)
            pane = pane * (1.0 - mix_w) + warm_tint[None, None, :] * mix_w
            img[wy0:wy1, wx0:wx1] = pane
            w_span = wx1 - wx0
            for k_sub in (1, 2):
                sx = wx0 + (w_span * k_sub) // 3
                img[wy0:wy1, sx - 1:sx + 1] = (96.0, 102.0, 110.0)
            mid_y = wy0 + (wy1 - wy0) // 3
            img[mid_y - 1:mid_y + 1, wx0:wx1] = (104.0, 110.0, 118.0)
            img[y0:y1, x0:x0 + 2] = (122.0, 118.0, 112.0)
            img[y0:y1, x0 + 2:x0 + 4] = (192.0, 188.0, 182.0)
    return img

__annotations__ = {'ROOF_CONCRETE_COLOR': 'List[int]',
 'PARAPET_TRIM_COLOR': 'List[int]',
 'PODIUM_FACADE_INDEX': 'int',
 'PENTHOUSE_FACADE_INDEX': 'int',
 'FACADE_SPECS': 'List[Dict[str, Any]]',
 'PARAPET_TRIM_SPEC': 'Dict[str, Any]',
 'ROOF_SPECS': 'List[Dict[str, Any]]',
 '_FACADE_JPEG_CACHE': 'Optional[List[bytes]]',
 '_ROOF_JPEG_CACHE': 'Optional[List[bytes]]',
 '_PARAPET_JPEG_CACHE': 'Optional[bytes]'}


def get_facade_jpeg_bytes_list() -> List[bytes]:
    global _FACADE_JPEG_CACHE
    if _FACADE_JPEG_CACHE is not None:
        return _FACADE_JPEG_CACHE
    generators = (
        _gen_blue_curtain_wall,
        _gen_teal_mirror_tower,
        _gen_white_grid_tower,
        _gen_warm_highrise_apt,
        _gen_charcoal_commercial_tower,
        _gen_podium_commercial,
        _gen_cream_shophouse,
        _gen_terracotta_urban,
    )
    _FACADE_JPEG_CACHE = [_encode_rgb_jpeg(gen(1024), quality=89) for gen in generators]
    return _FACADE_JPEG_CACHE


def get_parapet_trim_jpeg_bytes() -> bytes:
    global _PARAPET_JPEG_CACHE
    if _PARAPET_JPEG_CACHE is None:
        _PARAPET_JPEG_CACHE = _encode_rgb_jpeg(_gen_parapet_trim_stone(256), quality=88)
    return _PARAPET_JPEG_CACHE


def get_roof_jpeg_bytes_list() -> List[bytes]:
    global _ROOF_JPEG_CACHE
    if _ROOF_JPEG_CACHE is not None:
        return _ROOF_JPEG_CACHE
    roof_arrays = (
        _gen_concrete_roof_deck(512),
        _gen_corrugated_metal_roof((134.0, 76.0, 70.0), seed=9201, sz=512),
        _gen_corrugated_metal_roof((68.0, 90.0, 110.0), seed=9301, sz=512),
        _gen_corrugated_metal_roof((72.0, 94.0, 82.0), seed=9401, sz=512),
    )
    _ROOF_JPEG_CACHE = [_encode_rgb_jpeg(arr, quality=88) for arr in roof_arrays]
    return _ROOF_JPEG_CACHE
