import math

from .net import PublicError

A = 6378137.0
E2 = 6.6943799901413165e-3


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise PublicError("Giá trị %s phải nằm trong [%s, %s]." % (name, low, high))
    return float(value)


def ecef(lat, lon):
    lat, lon = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    return n * math.cos(lat) * math.cos(lon), n * math.cos(lat) * math.sin(lon), n * (1 - E2) * math.sin(lat)


def xy(lat, lon, anchor):
    p, q = ecef(lat, lon), ecef(anchor["lat"], anchor["lon"])
    x, y, z = (p[i] - q[i] for i in range(3))
    a, b = math.radians(anchor["lat"]), math.radians(anchor["lon"])
    return -math.sin(b) * x + math.cos(b) * y, -math.sin(a) * math.cos(b) * x - math.sin(a) * math.sin(b) * y + math.cos(a) * z


def tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    a = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(a)) / math.pi) / 2 * n


def bounds(lat, lon, width, height):
    rad = math.radians(lat)
    lat_scale = math.pi / 180 * A * (1 - E2) / (1 - E2 * math.sin(rad) ** 2) ** 1.5
    lon_scale = math.pi / 180 * A * math.cos(rad) / math.sqrt(1 - E2 * math.sin(rad) ** 2)
    bbox = {"south": lat - height / (2 * lat_scale), "north": lat + height / (2 * lat_scale), "west": lon - width / (2 * lon_scale), "east": lon + width / (2 * lon_scale)}
    if bbox["south"] < -80 or bbox["north"] > 80 or bbox["west"] < -180 or bbox["east"] > 180:
        raise PublicError("Vùng chọn vượt biên bản đồ; chọn lại tâm và kích thước.")
    return bbox


def clip_polygon(points, bbox):
    """Sutherland-Hodgman clipping of lon/lat rings to the requested rectangle."""
    result = list(points)
    for axis, edge, sign in ((0, bbox["west"], 1), (0, bbox["east"], -1), (1, bbox["south"], 1), (1, bbox["north"], -1)):
        incoming, result = result, []
        if not incoming:
            break
        previous = incoming[-1]
        for current in incoming:
            a, b = (previous[axis] - edge) * sign >= 0, (current[axis] - edge) * sign >= 0
            if a != b:
                t = (edge - previous[axis]) / (current[axis] - previous[axis])
                hit = tuple(previous[i] + t * (current[i] - previous[i]) for i in range(2))
                result.append(hit)
            if b:
                result.append(current)
            previous = current
    clean = []
    for point in result:
        if not clean or abs(point[0] - clean[-1][0]) + abs(point[1] - clean[-1][1]) > 1e-12:
            clean.append(point)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean.pop()
    return clean


def clip_segment(p, q, bbox):
    dx, dy = q[0] - p[0], q[1] - p[1]
    start, end = 0.0, 1.0
    for a, b in ((-dx, p[0] - bbox["west"]), (dx, bbox["east"] - p[0]), (-dy, p[1] - bbox["south"]), (dy, bbox["north"] - p[1])):
        if abs(a) < 1e-20:
            if b < 0:
                return None
        else:
            t = b / a
            if a < 0:
                start = max(start, t)
            else:
                end = min(end, t)
    if start >= end:
        return None
    return ((p[0] + start * dx, p[1] + start * dy), (p[0] + end * dx, p[1] + end * dy))


def triangulate(points):
    """Ear clipping for simple concave footprints. Return CCW triangles."""
    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    indices = list(range(len(points)))
    if area < 0:
        indices.reverse()
    result = []
    while len(indices) > 3:
        found = False
        for i, b in enumerate(indices):
            a, c = indices[i - 1], indices[(i + 1) % len(indices)]
            if cross(points[a], points[b], points[c]) <= 1e-8:
                continue
            if any(j not in (a, b, c) and min(cross(points[a], points[b], points[j]), cross(points[b], points[c], points[j]), cross(points[c], points[a], points[j])) >= -1e-8 for j in indices):
                continue
            result.append([a, b, c])
            indices.pop(i)
            found = True
            break
        if not found:
            # Remove a redundant collinear vertex; reject invalid self intersections.
            for i, b in enumerate(indices):
                if abs(cross(points[indices[i - 1]], points[b], points[indices[(i + 1) % len(indices)]])) < 1e-7:
                    indices.pop(i)
                    found = True
                    break
            if not found:
                return []
    if len(indices) == 3 and abs(cross(*(points[i] for i in indices))) > 1e-8:
        result.append(indices[:])
    return result
