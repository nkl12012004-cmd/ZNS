"""Simple SiteCraft trees: a short capped trunk and a round, closed crown.

Coordinates are scene-local metres with Z up. This module adds new geometry;
no recovered MapSKP implementation is modified. Color is chosen by the caller.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
import numbers

import numpy as np


TRUNK_SEGMENTS = 8
CROWN_SEGMENTS = 12
CROWN_LATITUDE_STEPS = 8


def _mesh(vertices, triangles):
    vertices = np.asarray(vertices, dtype=np.float32)
    triangles = np.asarray(triangles, dtype=np.uint32)
    if not np.isfinite(vertices).all():
        raise ValueError("Tree coordinates exceed float32 precision")
    points = vertices[triangles].astype(np.float64)
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    if not np.all(np.einsum("ij,ij->i", normals, normals) > 0):
        raise ValueError("Tree dimensions are too small at these coordinates")
    return {"verts": vertices, "faces": triangles, "uvs": None}


def make_round_tree(x, y, z, height_m=5.5, radius_m=1.7):
    """Return ``{'trunk': mesh, 'crown': mesh}``, totaling 200 triangles.

    Each mesh has ``verts`` (float32 Nx3), ``faces`` (uint32 Mx3), and
    ``uvs=None``. Both parts are closed solids with outward face winding.
    ``height_m`` is the tree's full height; the spherical crown has the given
    radius and bottom at ``z + height_m - 2 * radius_m``. The trunk starts at
    ``z`` and extends a little inside that crown. Height must exceed diameter.
    """
    values = (x, y, z, height_m, radius_m)
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real)
           or not math.isfinite(value) for value in values):
        raise ValueError("Tree coordinates and dimensions must be finite real numbers")
    x, y, z, height, radius = map(float, values)
    if radius <= 0 or height <= 2 * radius:
        raise ValueError("Tree height must exceed twice its positive crown radius")

    crown_bottom = z + height - 2 * radius
    crown_center = z + height - radius
    overlap = min(radius * 0.2, (height - 2 * radius) * 0.5)
    trunk_top = crown_bottom + overlap
    trunk_radius = min(radius * 0.12, (height - 2 * radius) * 0.15)

    trunk_vertices = []
    for level in (z, trunk_top):
        for segment in range(TRUNK_SEGMENTS):
            angle = segment * 2 * math.pi / TRUNK_SEGMENTS
            trunk_vertices.append((x + trunk_radius * math.cos(angle),
                                   y + trunk_radius * math.sin(angle), level))
    bottom_center = len(trunk_vertices)
    trunk_vertices.append((x, y, z))
    top_center = len(trunk_vertices)
    trunk_vertices.append((x, y, trunk_top))
    trunk_faces = []
    for segment in range(TRUNK_SEGMENTS):
        following = (segment + 1) % TRUNK_SEGMENTS
        top = segment + TRUNK_SEGMENTS
        next_top = following + TRUNK_SEGMENTS
        trunk_faces.extend(((segment, following, next_top),
                            (segment, next_top, top),
                            (bottom_center, following, segment),
                            (top_center, top, next_top)))

    crown_vertices = [(x, y, z + height)]
    # Single vertices at both poles avoid zero-area pole triangles and cracks.
    for latitude in range(1, CROWN_LATITUDE_STEPS):
        polar = latitude * math.pi / CROWN_LATITUDE_STEPS
        ring_radius = radius * math.sin(polar)
        level = crown_center + radius * math.cos(polar)
        for segment in range(CROWN_SEGMENTS):
            angle = segment * 2 * math.pi / CROWN_SEGMENTS
            crown_vertices.append((x + ring_radius * math.cos(angle),
                                   y + ring_radius * math.sin(angle), level))
    bottom_pole = len(crown_vertices)
    crown_vertices.append((x, y, crown_bottom))
    crown_faces = []
    for segment in range(CROWN_SEGMENTS):
        following = (segment + 1) % CROWN_SEGMENTS
        crown_faces.append((0, 1 + segment, 1 + following))
    for latitude in range(CROWN_LATITUDE_STEPS - 2):
        upper = 1 + latitude * CROWN_SEGMENTS
        lower = upper + CROWN_SEGMENTS
        for segment in range(CROWN_SEGMENTS):
            following = (segment + 1) % CROWN_SEGMENTS
            crown_faces.extend(((upper + segment, lower + segment, lower + following),
                                (upper + segment, lower + following, upper + following)))
    last_ring = 1 + (CROWN_LATITUDE_STEPS - 2) * CROWN_SEGMENTS
    for segment in range(CROWN_SEGMENTS):
        following = (segment + 1) % CROWN_SEGMENTS
        crown_faces.append((last_ring + segment, bottom_pole, last_ring + following))

    return {"trunk": _mesh(trunk_vertices, trunk_faces),
            "crown": _mesh(crown_vertices, crown_faces)}
