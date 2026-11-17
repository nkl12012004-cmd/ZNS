"""Conservative crown candidates from visible satellite-image evidence.

This uses color, connected outlines, texture and multi-scale crown contrast.
It does not scatter points in green land-use polygons or on a placement grid.
Ambiguous/low-resolution vegetation is intentionally omitted. It is not a
trained species/tree inventory model and cannot guarantee perfect recognition.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections import defaultdict
import math
import numpy as np
from PIL import Image, ImageFilter
from .net import PublicError


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise PublicError('Đã hủy tác vụ.')


def _components(mask, cancel):
    """Run-length 8-connected components; avoids a Python loop over all pixels."""
    parent = []
    runs = []
    previous = []
    def find(label):
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label
    for y, row in enumerate(mask):
        if y % 32 == 0:
            _check(cancel)
        edges = np.diff(np.pad(row.astype(np.int8), (1, 1)))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)-1
        current, cursor = [], 0
        for left, right in zip(starts.tolist(), ends.tolist()):
            label = len(parent); parent.append(label)
            while cursor < len(previous) and previous[cursor][1] < left-1:
                cursor += 1
            index = cursor
            while index < len(previous) and previous[index][0] <= right+1:
                other = find(previous[index][2]); root = find(label)
                if root != other:
                    parent[root] = other
                index += 1
            current.append((left, right, label)); runs.append((label, y, left, right))
        previous = current
    grouped = defaultdict(list)
    for label, y, left, right in runs:
        grouped[find(label)].append((y, left, right))
    return list(grouped.values())


def detect_canopies(image, width_m, height_m, *, level='medium', blocked=None, cancel=None):
    """Return measured crown centers/radii in image UV space, with confidence.

    ``v`` increases upward. ``blocked`` is an optional same-sized occupied mask.
    All candidates must have crown evidence; OSM labels never create candidates.
    """
    _check(cancel)
    if image is None or width_m <= 0 or height_m <= 0:
        return []
    image = image.convert('RGB')
    width, height = image.size
    metres = max(width_m/width, height_m/height)
    # There must be several source pixels across a crown to infer its outline.
    min_radius = max({'sparse': 1.8, 'medium': 1.5, 'dense': 1.1}.get(level, 1.5), metres*2.5)
    if min_radius > 6.5:
        return []
    rgb = np.asarray(image, dtype=np.float32)
    red, green, blue = (rgb[:, :, index] for index in range(3))
    maximum, minimum = rgb.max(axis=2), rgb.min(axis=2)
    saturation = (maximum-minimum)/np.maximum(maximum, 1)
    gray_image = image.convert('L')
    gray = np.asarray(gray_image, dtype=np.float32)
    vegetation = ((green > red*1.055) & (green > blue*1.10) & (saturation > .16)
                  & (gray > 20) & (gray < 185))
    vegetation = np.asarray(Image.fromarray(vegetation.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))) > 0
    if blocked is not None:
        vegetation &= ~np.asarray(blocked, dtype=bool)
    if not vegetation.any():
        return []
    _check(cancel)
    components = _components(vegetation, cancel)
    complex_mask = np.zeros_like(vegetation)
    candidates = []
    texture_minimum = {'sparse': 7.0, 'medium': 5.5, 'dense': 4.5}.get(level, 5.5)

    def evidence(px, py, radius):
        radius_px = max(2.0, radius/metres)
        reach = int(math.ceil(radius_px*1.65))
        left, right = max(0, int(px)-reach), min(width, int(px)+reach+1)
        top, bottom = max(0, int(py)-reach), min(height, int(py)+reach+1)
        yy, xx = np.ogrid[top:bottom, left:right]
        distance = ((xx-px)**2+(yy-py)**2)/radius_px**2
        disk = distance <= 1.0
        ring = (distance > 1.0) & (distance <= 2.5)
        if disk.sum() < 12 or ring.sum() < 12:
            return None
        pixels = gray[top:bottom, left:right]
        local_green = vegetation[top:bottom, left:right]
        fraction = float(local_green[disk].mean())
        if fraction < .52:
            return None
        crown_pixels = pixels[disk & local_green]
        texture = float(crown_pixels.std())
        if texture < texture_minimum:
            return None
        # Parallel roof ribs/crop rows have one dominant texture direction;
        # foliage normally has less directional texture within the crown.
        gy, gx = np.gradient(pixels)
        interior = disk & local_green
        xx_energy = float(np.square(gx[interior]).sum())
        yy_energy = float(np.square(gy[interior]).sum())
        xy_energy = float((gx[interior]*gy[interior]).sum())
        coherence = math.sqrt((xx_energy-yy_energy)**2+4*xy_energy**2)/max(1e-6,xx_energy+yy_energy)
        if coherence > {'sparse': .62, 'medium': .72, 'dense': .82}.get(level, .72):
            return None
        crown_mean = float(crown_pixels.mean())
        # A canopy has structured light/shadow. A uniform lawn alone has none.
        shadow = float((pixels[ring] < max(12, crown_mean*.77)).mean())
        green_drop = fraction-float(local_green[ring].mean())
        dome = float(pixels[distance <= .36].mean())-float(pixels[ring].mean())
        return fraction, texture, shadow, green_drop, dome

    for component in components:
        _check(cancel)
        area = sum(right-left+1 for _, left, right in component)
        if area*metres**2 < math.pi*min_radius**2*.55:
            continue
        xmin = min(left for _, left, _ in component); xmax = max(right for _, _, right in component)
        ymin, ymax = component[0][0], component[-1][0]
        span_x, span_y = xmax-xmin+1, ymax-ymin+1
        aspect = max(span_x, span_y)/max(1, min(span_x, span_y))
        fill = area/(span_x*span_y)
        radius = math.sqrt(area/math.pi)*metres
        if fill > .94:
            # A solid rectangular lawn/field/roof is not a crown outline.
            continue
        if radius > 10.0 or aspect > 1.9 or max(span_x, span_y)*metres > 25:
            for y, left, right in component:
                complex_mask[y, left:right+1] = True
            continue
        # Full rectangular green roofs/lawns have no irregular crown outline.
        if not min_radius <= radius <= 10.0 or not .38 <= fill <= .92:
            continue
        px = sum((left+right)*(right-left+1)*.5 for _, left, right in component)/area
        py = sum(y*(right-left+1) for y, left, right in component)/area
        check = evidence(px, py, radius)
        if check is None:
            continue
        fraction, texture, shadow, green_drop, dome = check
        if green_drop < .15 or shadow < .06:
            continue
        confidence = min(.98, .55+.12*min(1, texture/18)+.15*min(1, green_drop/.5)+.10*(2-aspect))
        candidates.append((px, py, radius, confidence, 'outlined_crown'))

    # Touching crowns need actual image peaks/valleys, never polygon/grid fill.
    if complex_mask.any():
        for radius in (1.5, 2.2, 3.2, 4.5, 6.0):
            _check(cancel)
            if radius < min_radius:
                continue
            pixels = radius/metres
            inner = np.asarray(gray_image.filter(ImageFilter.GaussianBlur(max(.6, pixels*.38))), dtype=np.float32)
            outer = np.asarray(gray_image.filter(ImageFilter.GaussianBlur(max(1.2, pixels*.95))), dtype=np.float32)
            response = inner-outer
            threshold = {'sparse': 7.0, 'medium': 5.5, 'dense': 4.5}.get(level, 5.5)
            encoded = np.clip(response*4+128, 0, 255).astype(np.uint8)
            local_max = np.asarray(Image.fromarray(encoded).filter(ImageFilter.MaxFilter(5)))
            peaks = (encoded == local_max) & (response >= threshold) & complex_mask & vegetation
            yy, xx = np.where(peaks)
            if len(xx) > 5000:
                ranking = np.argsort(response[yy, xx])[-5000:]
                yy, xx = yy[ranking], xx[ranking]
            for py, px in zip(yy.tolist(), xx.tolist()):
                check = evidence(px, py, radius)
                if check is None:
                    continue
                fraction, texture, shadow, green_drop, dome = check
                if shadow < .075 or (green_drop < .10 and dome < threshold+1.5):
                    continue
                confidence = min(.94, .54+.12*min(1, response[py, px]/12)+.10*min(1, texture/18)+.12*min(1, shadow/.25))
                candidates.append((float(px), float(py), radius, confidence, 'textured_crown_peak'))
    selected = []
    for px, py, radius, confidence, method in sorted(candidates, key=lambda item:(-item[3]*min(1.5,math.sqrt(item[2]/min_radius)),-item[2],item[1],item[0])):
        _check(cancel)
        # Suppress duplicate scale responses to the same visible crown.
        if any(((px-old[0])*metres)**2+((py-old[1])*metres)**2 < max(.82*(radius+old[2]),1.12*max(radius,old[2]))**2 for old in selected):
            continue
        selected.append((px, py, radius, confidence, method))
        if len(selected) >= 2500:
            break
    return [{'u':px/max(1,width-1), 'v':1-py/max(1,height-1), 'radius_m':round(radius,3),
             'confidence':round(float(confidence),3), 'method':method}
            for px,py,radius,confidence,method in selected]
