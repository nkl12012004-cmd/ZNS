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


def refine_large_canopies(image, crowns, width_m, height_m, *, level='medium', cancel=None):
    """Represent broad verified crowns with a few distinct image-supported peaks.

    A smooth single dome is retained as one candidate (rendered smaller by the
    caller). Only separated peaks with a visible valley can create children;
    no circle offsets, grid points, area fill or random placement are used.
    """
    _check(cancel)
    if not crowns or image is None:
        return [dict(c) for c in (crowns or [])[:2500]]
    image = image.convert('RGB')
    width, height = image.size
    metres = max(width_m/width, height_m/height)
    if metres <= 0:
        return [dict(c) for c in crowns[:2500]]
    large = [c for c in crowns if c['radius_m'] > 3.0]
    if not large:
        return [dict(c) for c in crowns[:2500]]
    gray_image = image.convert('L')
    gray = np.asarray(gray_image, dtype=np.float32)
    rgb = np.asarray(image, dtype=np.float32)
    r,g,b = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    green = (g > r*1.055) & (g > b*1.10) & (gray > 20) & (gray < 185)
    smooth = np.asarray(gray_image.filter(ImageFilter.GaussianBlur(max(.7,.55/metres))),dtype=np.float32)
    background = np.asarray(gray_image.filter(ImageFilter.GaussianBlur(max(1.5,1.6/metres))),dtype=np.float32)
    response = smooth-background
    encoded = np.clip(response*5+128,0,255).astype(np.uint8)
    maxima = np.asarray(Image.fromarray(encoded).filter(ImageFilter.MaxFilter(5)))
    minimum_response = {'sparse':8.0,'medium':7.0,'dense':6.0}.get(level,7.0)
    available = (encoded == maxima) & (response >= minimum_response) & green
    result = []

    def supported(x,y,radius_m):
        radius = max(2.0,radius_m/metres)
        reach = int(math.ceil(radius))
        left,right=max(0,x-reach),min(width,x+reach+1)
        top,bottom=max(0,y-reach),min(height,y+reach+1)
        yy,xx=np.ogrid[top:bottom,left:right]
        disk=(xx-x)**2+(yy-y)**2 <= radius**2
        selected = green[top:bottom,left:right][disk]
        if len(selected)<10 or selected.mean()<.65:
            return False
        values=gray[top:bottom,left:right][disk & green[top:bottom,left:right]]
        return len(values)>=10 and values.std()>=5.0

    def separate_valley(first,second):
        # A gentle dome slope or noisy leaf fragment does not separate crowns.
        samples=np.linspace(.2,.8,9)
        xx=np.rint(first[0]+samples*(second[0]-first[0])).astype(int)
        yy=np.rint(first[1]+samples*(second[1]-first[1])).astype(int)
        valley=float(smooth[yy,xx].min())
        lower_peak=min(float(smooth[first[1],first[0]]),float(smooth[second[1],second[0]]))
        return lower_peak-valley>=5.0

    for parent_index,parent in enumerate(crowns):
        _check(cancel)
        source_radius=float(parent['radius_m'])
        if source_radius<=3.0:
            result.append(dict(parent));continue
        cx=parent['u']*(width-1);cy=(1-parent['v'])*(height-1)
        radius=source_radius/metres
        reach=int(math.ceil(radius))
        left,right=max(0,int(cx)-reach),min(width,int(cx)+reach+1)
        top,bottom=max(0,int(cy)-reach),min(height,int(cy)+reach+1)
        yy,xx=np.where(available[top:bottom,left:right])
        xx,yy=xx+left,yy+top
        inside=(xx-cx)**2+(yy-cy)**2 <= (radius*.94)**2
        xx,yy=xx[inside],yy[inside]
        ranking=sorted(zip(xx.tolist(),yy.tolist()),key=lambda p:(-float(response[p[1],p[0]]),p[1],p[0]))[:1200]
        child_radius=min(2.0,max(1.3,source_radius*.42))
        minimum_distance=max(3.2,child_radius*1.8)/metres
        maximum_children=min(6,max(2,int(math.ceil((source_radius/2.0)**2*.5))))
        peaks=[]
        for x,y in ranking:
            if not supported(x,y,min(child_radius,1.5)):
                continue
            if any((x-old[0])**2+(y-old[1])**2 < minimum_distance**2 for old in peaks):
                continue
            if any(not separate_valley((x,y),old) for old in peaks):
                continue
            peaks.append((x,y))
            if len(peaks)>=maximum_children:
                break
        if len(peaks)<2:
            result.append(dict(parent));continue
        for x,y in peaks:
            result.append({**parent,'u':x/max(1,width-1),'v':1-y/max(1,height-1),
                           'radius_m':round(child_radius,3),'method':'crown_cluster_peak',
                           'parent_u':parent['u'],'parent_v':parent['v'],
                           'parent_radius_m':source_radius,'parent_canopy_id':parent_index})
    # Neighboring parent regions can share peaks. Keep one small tree per peak.
    selected=[]
    for crown in result:
        if any(((crown['u']-old['u'])*(width-1)*metres)**2+((crown['v']-old['v'])*(height-1)*metres)**2
               < (.8*(min(2.0,crown['radius_m'])+min(2.0,old['radius_m'])))**2 for old in selected):
            continue
        selected.append(crown)
        if len(selected)>=2500:
            break
    return selected
