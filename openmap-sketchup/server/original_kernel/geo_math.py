"""Readable reconstruction of geo_math from the user-provided MapSKP runtime.

The formulas, signatures and numerical operation order were recovered from the
original Python 3.14 code objects. This is not a new MIT implementation and does
not change the original rights. It contains no loader, licensing or account code.
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
INCH_PER_METER = 39.37007874015748


def latlon_to_ecef(lat_deg: float, lon_deg: float, h_m: float = 0.0) -> Tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + h_m) * cos_lat * cos_lon
    y = (n + h_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + h_m) * sin_lat
    return x, y, z


def ecef_to_enu_matrix(lat0_deg: float, lon0_deg: float, h0_m: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    x0, y0, z0 = latlon_to_ecef(lat0_deg, lon0_deg, h0_m)
    lat0 = math.radians(lat0_deg)
    lon0 = math.radians(lon0_deg)
    slat, clat = math.sin(lat0), math.cos(lat0)
    slon, clon = math.sin(lon0), math.cos(lon0)
    rot = np.array([
        [-slon, clon, 0.0],
        [-slat * clon, -slat * slon, clat],
        [clat * clon, clat * slon, slat],
    ], dtype=np.float64)
    origin = np.array([x0, y0, z0], dtype=np.float64)
    return rot, origin


def ecef_points_to_enu(pts_ecef: np.ndarray, lat0_deg: float, lon0_deg: float, h0_m: float = 0.0) -> np.ndarray:
    rot, origin = ecef_to_enu_matrix(lat0_deg, lon0_deg, h0_m)
    delta = np.asarray(pts_ecef, dtype=np.float64) - origin
    return delta @ rot.T


def latlon_to_local_xy(lat_deg: float, lon_deg: float, lat0_deg: float, lon0_deg: float) -> Tuple[float, float]:
    x, y, z = latlon_to_ecef(lat_deg, lon_deg, 0.0)
    rot, origin = ecef_to_enu_matrix(lat0_deg, lon0_deg, 0.0)
    vec = rot @ (np.array([x, y, z], dtype=np.float64) - origin)
    return float(vec[0]), float(vec[1])


def latlon_array_to_local_xy(lats: np.ndarray, lons: np.ndarray, lat0_deg: float, lon0_deg: float) -> Tuple[np.ndarray, np.ndarray]:
    lat_r = np.radians(lats)
    lon_r = np.radians(lons)
    sin_lat = np.sin(lat_r)
    cos_lat = np.cos(lat_r)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    xs = n * cos_lat * np.cos(lon_r)
    ys = n * cos_lat * np.sin(lon_r)
    zs = n * (1.0 - WGS84_E2) * sin_lat
    pts = np.stack([xs, ys, zs], axis=-1)
    enu = ecef_points_to_enu(pts, lat0_deg, lon0_deg, 0.0)
    return enu[:, 0], enu[:, 1]


def bbox_from_center_meters(lat0_deg: float, lon0_deg: float, width_east_m: float, height_north_m: float) -> Tuple[float, float, float, float]:
    lat_r = math.radians(lat0_deg)
    sin_lat = math.sin(lat_r)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_r) + 1.175 * math.cos(4 * lat_r)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    m_per_deg_lon = max(1.0, (math.pi / 180.0) * n * math.cos(lat_r))
    d_lat = (height_north_m * 0.5) / m_per_deg_lat
    d_lon = (width_east_m * 0.5) / m_per_deg_lon
    return (
        max(-85.05, lat0_deg - d_lat),
        max(-180.0, lon0_deg - d_lon),
        min(85.05, lat0_deg + d_lat),
        min(180.0, lon0_deg + d_lon),
    )


def bbox_dimensions_meters(south: float, west: float, north: float, east: float) -> Tuple[float, float, float, float]:
    lat0 = 0.5 * (south + north)
    lon0 = 0.5 * (west + east)
    e_east, _ = latlon_to_local_xy(lat0, east, lat0, lon0)
    e_west, _ = latlon_to_local_xy(lat0, west, lat0, lon0)
    _, n_north = latlon_to_local_xy(north, lon0, lat0, lon0)
    _, n_south = latlon_to_local_xy(south, lon0, lat0, lon0)
    return lat0, lon0, abs(e_east - e_west), abs(n_north - n_south)


def latlon_to_tile_float(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[float, float]:
    lat_clamped = max(-85.05112878, min(85.05112878, lat_deg))
    lat_rad = math.radians(lat_clamped)
    n = 2.0 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) * 0.5 * n
    return xtile, ytile


def tile_xy_to_latlon(xtile: float, ytile: float, zoom: int) -> Tuple[float, float]:
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
    return math.degrees(lat_rad), lon_deg


def optimal_satellite_zoom(width_m: float, height_m: float, lat_deg: float, target_px: int = 4096) -> int:
    span = max(width_m, height_m, 20.0)
    target_mpp = span / max(512, min(target_px, 8192))
    cos_lat = max(0.1, math.cos(math.radians(lat_deg)))
    for z in range(19, 12, -1):
        mpp = 156543.03392 * cos_lat / (2 ** z)
        tiles_needed = math.ceil(width_m / (mpp * 256.0) + 1) * math.ceil(height_m / (mpp * 256.0) + 1)
        if mpp >= target_mpp * 0.65 and tiles_needed <= 81:
            return z
        if tiles_needed <= 64 and z <= 18:
            return z
    return 15


def estimate_tz_offset(lon_deg: float) -> float:
    if 102.0 <= lon_deg <= 110.5:
        return 7.0
    return float(round(lon_deg / 15.0))
