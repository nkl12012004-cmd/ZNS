import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import math
import re
import struct
import threading
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw

from . import geo
from .net import PublicError, fetch, fetch_json

SATELLITE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ELEVATION = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
IMAGERY = {
    "satellite": (SATELLITE, "satellite"), "esri_sat": (SATELLITE, "satellite"),
    "google_sat": ("https://mt0.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", "google"),
    "google_hybrid": ("https://mt0.google.com/vt/lyrs=y&hl=vi&x={x}&y={y}&z={z}", "google"),
    "google_street": ("https://mt0.google.com/vt/lyrs=m&hl=vi&x={x}&y={y}&z={z}", "google"),
}
ATTRIBUTIONS = {
    "google": "Map imagery/data © Google and its data providers. https://www.google.com/permissions/geoguidelines/",
    "osm": "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright",
    "satellite": "Tiles © Esri; imagery sources vary by location. https://www.esri.com/en-us/legal/terms/data-attributions",
    "elevation": "Elevation: Mapzen / Tilezen Terrain Tiles; underlying SRTM and other open elevation data.",
}


def parameters(body):
    lat = geo.number(body.get("lat"), "vĩ độ", -79.9, 79.9)
    lon = geo.number(body.get("lon"), "kinh độ", -179.9, 179.9)
    width = geo.number(body.get("width", 500), "chiều rộng (m)", 10, 10_000)
    height = geo.number(body.get("height", 500), "chiều dài (m)", 10, 10_000)
    grid = geo.number(body.get("grid", 48), "số ô lưới", 4, 128)
    if not grid.is_integer():
        raise PublicError("Số ô lưới phải là số nguyên.")
    image_size = body.get("image_size", 2048)
    if isinstance(image_size, bool) or image_size not in (1024, 2048, 4096, 8192):
        raise PublicError("Độ phân giải ảnh phải là 1024, 2048, 4096 hoặc 8192.")
    imagery = body.get("imagery", "satellite")
    if imagery != "none" and imagery not in IMAGERY:
        raise PublicError("Nguồn ảnh không hợp lệ.")
    for key in ("terrain", "roads", "roads_main", "roads_local", "buildings", "water", "trees"):
        if key in body and not isinstance(body[key], bool):
            raise PublicError("Tùy chọn %s phải là boolean." % key)
    anchor = body.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, dict):
            raise PublicError("Mốc tọa độ không hợp lệ.")
        anchor = {"lat": geo.number(anchor.get("lat"), "mốc vĩ độ", -80, 80), "lon": geo.number(anchor.get("lon"), "mốc kinh độ", -180, 180), "elevation": geo.number(anchor.get("elevation"), "cao độ mốc", -12_000, 20_000), "terrain_mode": anchor.get("terrain_mode", "terrain_3d")}
        if anchor["terrain_mode"] not in ("flat", "terrain_3d"):
            raise PublicError("Chế độ nền của mốc không hợp lệ.")
        if math.hypot(*geo.xy(lat, lon, anchor)) > 250_000:
            raise PublicError("Vùng chọn cách mốc mô hình hơn 250 km. Tạo mô hình mới cho khu vực này.")
    style, roof = body.get("building_style", "white"), body.get("roof_style", "flat_simple")
    if style not in ("white", "textured") or roof not in ("flat_simple", "parapet_vietnam", "parapet_concrete"):
        raise PublicError("Kiểu nhà hoặc mái không hợp lệ.")
    project_name = str(body.get("project_name", "OpenMap_Context")).strip()[:80]
    project_name = re.sub(r"[^\w \-]", "", project_name) or "OpenMap_Context"
    return dict(lat=lat, lon=lon, width=width, height=height, grid=int(grid), image_size=int(image_size), imagery=imagery,
                terrain=body.get("terrain", False), roads=body.get("roads", True), buildings=body.get("buildings", True),
                roads_main=body.get("roads_main", True), roads_local=body.get("roads_local", True), water=body.get("water", False), trees=body.get("trees", False),
                building_style=style, roof_style=roof, default_floors=geo.number(body.get("default_floors", 3.5), "số tầng mặc định", 1, 100), project_name=project_name,
                exaggeration=geo.number(body.get("exaggeration", 1), "hệ số cao độ", 0.1, 10), anchor=anchor, bbox=geo.bounds(lat, lon, width, height))


class Raster:
    def __init__(self, bbox, zoom, template, getter=fetch, cancel=None, max_tiles=81):
        self.bbox, self.zoom = bbox, zoom
        self.left, self.top = geo.tile_xy(bbox["north"], bbox["west"], zoom)
        self.right, self.bottom = geo.tile_xy(bbox["south"], bbox["east"], zoom)
        xmin, ymin = math.floor(self.left), math.floor(self.top)
        # Include boundary pixels from the adjacent tile for bilinear DEM sampling.
        xmax, ymax = math.floor(self.right), math.floor(self.bottom)
        if (xmax - xmin + 1) * (ymax - ymin + 1) > min(1225, max_tiles):
            raise PublicError("Vùng ảnh cần quá nhiều tile. Giảm kích thước vùng hoặc độ phân giải.")
        self.origin = xmin, ymin
        self.image = Image.new("RGB", ((xmax - xmin + 1) * 256, (ymax - ymin + 1) * 256))

        def download(pair):
            x, y = pair
            if cancel and cancel.is_set():
                raise PublicError("Đã hủy tác vụ.")
            data = getter(template.format(z=zoom, x=x % (2 ** zoom), y=y), limit=3_000_000, timeout=25)
            try:
                with Image.open(BytesIO(data)) as image:
                    if image.size != (256, 256) or image.format not in ("PNG", "JPEG"):
                        raise ValueError("Invalid tile dimensions")
                    image.load()
                    return x, y, image.convert("RGB")
            except (OSError, ValueError, Image.DecompressionBombError):
                raise PublicError("Ảnh tile không hợp lệ hoặc dữ liệu địa hình bị thiếu.", 502) from None

        pairs = [(x, y) for y in range(ymin, ymax + 1) for x in range(xmin, xmax + 1)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for x, y, image in pool.map(download, pairs):
                self.image.paste(image, ((x - xmin) * 256, (y - ymin) * 256))

    def sample(self, lat, lon):
        x, y = geo.tile_xy(lat, lon, self.zoom)
        x = max(0, min(self.image.width - 1.000001, (x - self.origin[0]) * 256))
        y = max(0, min(self.image.height - 1.000001, (y - self.origin[1]) * 256))
        ix, iy, fx, fy = int(x), int(y), x % 1, y % 1
        def value(px, py):
            r, g, b = self.image.getpixel((px, py))
            return r * 256 + g + b / 256 - 32768
        a = value(ix, iy) * (1 - fx) + value(ix + 1, iy) * fx
        b = value(ix, iy + 1) * (1 - fx) + value(ix + 1, iy + 1) * fx
        return a * (1 - fy) + b * fy

    def crop_png(self, maximum, jpeg=False):
        box = ((self.left - self.origin[0]) * 256, (self.top - self.origin[1]) * 256,
               (self.right - self.origin[0]) * 256, (self.bottom - self.origin[1]) * 256)
        width, height = box[2] - box[0], box[3] - box[1]
        scale = maximum / max(width, height)
        size = max(1, round(width * scale)), max(1, round(height * scale))
        image = self.image.transform(size, Image.Transform.EXTENT, box, Image.Resampling.BICUBIC)
        result = BytesIO()
        image.save(result, "JPEG" if jpeg else "PNG", **({"quality": 92} if jpeg else {}))
        return result.getvalue()


def osm_data(bbox, roads, buildings, endpoint, water=False, trees=False):
    filters = []
    box = "{south},{west},{north},{east}".format(**bbox)
    if roads:
        filters.append('way["highway"](%s);' % box)
    if buildings:
        filters.append('way["building"](%s);' % box)
    if water:
        filters.extend(['way["natural"="water"](%s);' % box, 'way["waterway"](%s);' % box])
    if trees:
        filters.append('node["natural"="tree"](%s);' % box)
    if not filters:
        return []
    query = '[out:json][timeout:20];(%s);out geom;' % "".join(filters)
    try:
        result = fetch_json(endpoint, method="POST", data=urllib.parse.urlencode({"data": query}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=25, limit=20_000_000)
        if not isinstance(result, dict) or result.get("remark"):
            raise PublicError("Overpass chưa trả đủ dữ liệu.", 502)
        elements = result.get("elements", [])
    except PublicError:
        # A bounded, user-selected map request; no background bulk downloads.
        try:
            url = "https://api.openstreetmap.org/api/0.6/map?" + urllib.parse.urlencode({"bbox": "{west},{south},{east},{north}".format(**bbox)})
            elements = parse_osm_xml(fetch(url, timeout=25, limit=20_000_000), roads, buildings, water, trees)
        except PublicError:
            raise PublicError("Chưa tải được đường/nhà OSM. Thử lại, chọn vùng nhỏ hơn, hoặc bỏ chọn hai lớp OSM để dựng nền và địa hình.", 502) from None
    if not isinstance(elements, list) or len(elements) > 25_000:
        raise PublicError("Vùng có quá nhiều đối tượng OSM. Chia thành các mảnh nhỏ hơn.")
    return elements


def parse_osm_xml(raw, roads, buildings, water=False, trees=False):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise PublicError("Dữ liệu OSM XML không hợp lệ.", 502)
    try:
        root = ET.fromstring(raw)
        if root.tag != "osm":
            raise ValueError("Not OSM data")
        nodes = {node.attrib["id"]: {"lat": float(node.attrib["lat"]), "lon": float(node.attrib["lon"])} for node in root.findall("node")}
        result = []
        if trees:
            for node in root.findall("node"):
                tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
                if tags.get("natural") == "tree":
                    result.append({"type": "node", **nodes[node.attrib["id"]], "tags": tags})
        for way in root.findall("way"):
            tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
            if not ((roads and tags.get("highway")) or (buildings and tags.get("building")) or (water and (tags.get("natural") == "water" or tags.get("waterway")))):
                continue
            refs = [node.attrib["ref"] for node in way.findall("nd")]
            if all(ref in nodes for ref in refs):
                result.append({"tags": tags, "geometry": [nodes[ref] for ref in refs]})
        return result
    except (ET.ParseError, ValueError, KeyError):
        raise PublicError("Không đọc được dữ liệu OSM XML.", 502) from None


def mesh(name, material, smooth=False):
    return {"name": name, "material": material, "smooth": smooth, "vertices": [], "triangles": [], "uv": []}


def append_quad(target, points):
    offset = len(target["vertices"])
    target["vertices"].extend(points)
    target["triangles"].extend([[offset, offset + 1, offset + 2], [offset, offset + 2, offset + 3]])


def tag_number(text, default):
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", str(text or ""))
    return float(match[1]) if match else default


def facade_texture(highrise):
    """Original procedural facade art, generated locally; no licensed assets."""
    image = Image.new("RGB", (512, 512), (155, 176, 188) if highrise else (216, 209, 192))
    draw = ImageDraw.Draw(image)
    for y in range(8, 512, 32):
        for x in range(8, 512, 32):
            shade = 90 + (x // 32 * 11 + y // 32 * 7) % 50
            draw.rectangle((x, y, x + 20, y + 23), fill=(shade, min(220, shade + 28), min(240, shade + 43)))
            draw.line((x + 2, y + 2, x + 17, y + 18), fill=(170, 195, 205), width=1)
    stream = BytesIO(); image.save(stream, "PNG")
    return base64.b64encode(stream.getvalue()).decode()


def add_tree(trunks, crowns, location, height):
    x, y, z = location
    radius, split = max(.15, height * .035), height * .38
    sides = 6
    for i in range(sides):
        a, b = i * 2 * math.pi / sides, (i + 1) * 2 * math.pi / sides
        append_quad(trunks, [[x + radius * math.cos(a), y + radius * math.sin(a), z], [x + radius * math.cos(b), y + radius * math.sin(b), z], [x + radius * math.cos(b), y + radius * math.sin(b), z + split], [x + radius * math.cos(a), y + radius * math.sin(a), z + split]])
        r = height * .28
        offset = len(crowns["vertices"])
        crowns["vertices"].extend([[x + r * math.cos(a), y + r * math.sin(a), z + split], [x + r * math.cos(b), y + r * math.sin(b), z + split], [x, y, z + height]])
        crowns["triangles"].append([offset, offset + 1, offset + 2])


def add_roof(roof_mesh, trim, feet, roof_tris, top, style):
    n, offset = len(feet), len(roof_mesh["vertices"])
    roof_mesh["vertices"].extend([[v[0], v[1], top + .02] for v in feet])
    roof_mesh["triangles"].extend([[offset + i for i in triangle] for triangle in roof_tris])
    if style == "flat_simple":
        return
    cx, cy = sum(v[0] for v in feet) / n, sum(v[1] for v in feet) / n
    inner = []
    for v in feet:
        length = max(.01, math.hypot(cx - v[0], cy - v[1]))
        factor = min(.2, .16 / length)
        inner.append([v[0] + (cx - v[0]) * factor, v[1] + (cy - v[1]) * factor])
    for i in range(n):
        j = (i + 1) % n
        outer_i, outer_j = feet[i][:2], feet[j][:2]
        append_quad(trim, [[*outer_i, top], [*outer_j, top], [*outer_j, top + .35], [*outer_i, top + .35]])
        append_quad(trim, [[*inner[j], top], [*inner[i], top], [*inner[i], top + .35], [*inner[j], top + .35]])
        append_quad(trim, [[*outer_i, top + .35], [*outer_j, top + .35], [*inner[j], top + .35], [*inner[i], top + .35]])


def build(params, *, progress=lambda *_: None, cancel=None, getter=fetch, osm_getter=None, overpass="https://overpass-api.de/api/interpreter"):
    p, b = params, params["bbox"]
    cancel = cancel or threading.Event()
    def update(percent, label):
        if cancel.is_set():
            raise PublicError("Đã hủy tác vụ.")
        progress(percent, label)
    update(5, "Chuẩn bị vùng bản đồ")
    dem = None
    if p["terrain"]:
        update(10, "Tải lưới cao độ DEM")
        dem = Raster(b, 12, ELEVATION, getter, cancel)
    anchor = p["anchor"] or {"lat": p["lat"], "lon": p["lon"], "elevation": dem.sample(p["lat"], p["lon"]) if dem else 0.0, "terrain_mode": "terrain_3d" if dem else "flat"}
    hill_patch = bool(dem and anchor.get("terrain_mode") == "flat")
    hill_base = 0
    if hill_patch:
        edge = []
        for i in range(17):
            u = i / 16
            lat, lon = b["south"] + (b["north"] - b["south"]) * u, b["west"] + (b["east"] - b["west"]) * u
            edge.extend([dem.sample(lat, b["west"]), dem.sample(lat, b["east"]), dem.sample(b["south"], lon), dem.sample(b["north"], lon)])
        hill_base = min(edge)
    def point(lat, lon, lift=0):
        x, y = geo.xy(lat, lon, anchor)
        z = (dem.sample(lat, lon) - anchor["elevation"]) * p["exaggeration"] if dem else 0.0
        if hill_patch:
            u, v = (lon - b["west"]) / (b["east"] - b["west"]), (lat - b["south"]) / (b["north"] - b["south"])
            t = max(0, min(1, min(u, v, 1 - u, 1 - v) / .12))
            z = max(0, dem.sample(lat, lon) - hill_base) * p["exaggeration"] * t * t * (3 - 2 * t)
        return [round(x, 6), round(y, 6), round(z + lift, 6)]
    material = {"name": "Ground", "color": [177, 195, 164]}
    attribution = []
    if dem:
        attribution.append(ATTRIBUTIONS["elevation"])
    if p["imagery"] != "none":
        update(25, "Ghép ảnh vệ tinh")
        x0, y0 = geo.tile_xy(b["north"], b["west"], 0)
        x1, y1 = geo.tile_xy(b["south"], b["east"], 0)
        span = max(x1 - x0, y1 - y0)
        zoom = max(0, min(20, int(math.floor(math.log2(p["image_size"] / (256 * span))))))
        tile_budget = (math.ceil(p["image_size"] / 256) + 2) ** 2
        while zoom > 0:
            x0, y0 = geo.tile_xy(b["north"], b["west"], zoom)
            x1, y1 = geo.tile_xy(b["south"], b["east"], zoom)
            if (math.floor(x1) - math.floor(x0) + 1) * (math.floor(y1) - math.floor(y0) + 1) <= tile_budget:
                break
            zoom -= 1
        template, credit = IMAGERY[p["imagery"]]
        raster = Raster(b, zoom, template, getter, cancel, tile_budget)
        jpeg = p["image_size"] == 8192
        material["texture_jpeg" if jpeg else "texture_png"] = base64.b64encode(raster.crop_png(p["image_size"], jpeg)).decode()
        material["color"] = [255, 255, 255]
        attribution.append(ATTRIBUTIONS[credit])
    update(50, "Dựng mặt nền")
    ground = mesh("Terrain_hill_patch" if hill_patch else "Ground", 0, True)
    cells = p["grid"] if p["terrain"] else 4
    _, top = geo.tile_xy(b["north"], b["west"], 0)
    _, bottom = geo.tile_xy(b["south"], b["east"], 0)
    for row in range(cells + 1):
        lat = b["south"] + (b["north"] - b["south"]) * row / cells
        _, merc_y = geo.tile_xy(lat, b["west"], 0)
        for col in range(cells + 1):
            lon = b["west"] + (b["east"] - b["west"]) * col / cells
            ground["vertices"].append(point(lat, lon))
            ground["uv"].append([col / cells, 1 - (merc_y - top) / (bottom - top)])
    for row in range(cells):
        for col in range(cells):
            a = row * (cells + 1) + col
            ground["triangles"].extend([[a, a + 1, a + cells + 2], [a, a + cells + 2, a + cells + 1]])
    major, minor = mesh("Roads_main", 1), mesh("Roads_local", 2)
    low, high = mesh("Buildings_lowrise", 3), mesh("Buildings_highrise", 4)
    roofs, trim = mesh("Building_roofs", 5), mesh("Roof_parapets", 6)
    water, trunks, crowns = mesh("Water", 7), mesh("Tree_trunks", 8), mesh("Tree_crowns", 9)
    update(65, "Đọc đường và khối nhà OpenStreetMap")
    include_osm = p["roads"] or p["buildings"] or p["water"] or p["trees"]
    elements = (osm_getter(b, p["roads"], p["buildings"]) if osm_getter else osm_data(b, p["roads"], p["buildings"], overpass, p["water"], p["trees"])) if include_osm else []
    skipped = 0
    for index, element in enumerate(elements):
        if index % 100 == 0:
            update(70 + 20 * index / max(1, len(elements)), "Dựng đường và khối nhà")
        tags = element.get("tags", {})
        if p["trees"] and tags.get("natural") == "tree" and element.get("type") == "node":
            lat, lon = element.get("lat"), element.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and b["south"] <= lat <= b["north"] and b["west"] <= lon <= b["east"]:
                add_tree(trunks, crowns, point(lat, lon), min(40, max(2, tag_number(tags.get("height"), 8))))
        coords = [(v["lon"], v["lat"]) for v in element.get("geometry", []) if isinstance(v, dict) and isinstance(v.get("lon"), (int, float)) and isinstance(v.get("lat"), (int, float)) and math.isfinite(v["lon"]) and math.isfinite(v["lat"])]
        if p["buildings"] and tags.get("building") not in (None, "no") and len(coords) >= 4 and coords[0] == coords[-1]:
            ring = geo.clip_polygon(coords[:-1], b)
            if not 3 <= len(ring) <= 500:
                skipped += 1
                continue
            feet = [point(lat, lon) for lon, lat in ring]
            signed_area = sum(a[0] * z[1] - z[0] * a[1] for a, z in zip(feet, feet[1:] + feet[:1]))
            if signed_area < 0:
                feet.reverse()
            roof = geo.triangulate([(v[0], v[1]) for v in feet])
            if not roof:
                skipped += 1
                continue
            height = min(300, max(1, tag_number(tags.get("height"), tag_number(tags.get("building:levels"), p["default_floors"]) * 3)))
            buildings = high if height >= 21 else low
            offset, n = len(buildings["vertices"]), len(feet)
            top_z = max(v[2] for v in feet) + height
            buildings["vertices"].extend(feet + [[v[0], v[1], top_z] for v in feet])
            lengths = [0.0]
            for a, v in zip(feet, feet[1:]): lengths.append(lengths[-1] + math.hypot(v[0] - a[0], v[1] - a[1]))
            buildings["uv"].extend([[value / 20, 0] for value in lengths] + [[value / 20, height / 30] for value in lengths])
            for tri in roof:
                buildings["triangles"].extend([[offset + n + i for i in tri], [offset + i for i in reversed(tri)]])
            for i in range(n):
                j = (i + 1) % n
                buildings["triangles"].extend([[offset + i, offset + j, offset + n + j], [offset + i, offset + n + j, offset + n + i]])
            add_roof(roofs, trim, feet, roof, top_z, p["roof_style"])
        if p["water"] and (tags.get("natural") == "water" or tags.get("waterway") == "riverbank") and len(coords) >= 4 and coords[0] == coords[-1]:
            ring = geo.clip_polygon(coords[:-1], b)
            if 3 <= len(ring) <= 1000:
                vertices = [point(lat, lon, .08) for lon, lat in ring]
                triangles = geo.triangulate([(v[0], v[1]) for v in vertices])
                z = sum(v[2] for v in vertices) / len(vertices)
                offset = len(water["vertices"])
                water["vertices"].extend([[v[0], v[1], z] for v in vertices])
                water["triangles"].extend([[offset + i for i in tri] for tri in triangles])
        if p["roads"] and tags.get("highway") and tags.get("tunnel") not in ("yes", "building_passage"):
            is_major = tags["highway"] in ("motorway", "trunk", "primary", "secondary", "tertiary")
            if (is_major and not p["roads_main"]) or (not is_major and not p["roads_local"]):
                continue
            target = major if is_major else minor
            half = min(40, max(0.5, tag_number(tags.get("width"), 10 if is_major else 4))) / 2
            for a, z in zip(coords, coords[1:]):
                clipped = geo.clip_segment(a, z, b)
                if not clipped:
                    continue
                a, z = clipped
                p1, p2 = point(a[1], a[0], .15), point(z[1], z[0], .15)
                length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                if length < .05:
                    continue
                dx, dy = -(p2[1] - p1[1]) / length * half, (p2[0] - p1[0]) / length * half
                append_quad(target, [[p1[0] - dx, p1[1] - dy, p1[2]], [p2[0] - dx, p2[1] - dy, p2[2]], [p2[0] + dx, p2[1] + dy, p2[2]], [p1[0] + dx, p1[1] + dy, p1[2]]])
        if sum(len(value["vertices"]) for value in (low, high, major, minor, water, trunks, crowns, roofs, trim)) > 300_000:
            raise PublicError("Mô hình quá dày để nạp ổn định. Chia vùng thành các mảnh nhỏ hơn.")
    if include_osm:
        attribution.append(ATTRIBUTIONS["osm"])
    meshes = [value for value in (ground, major, minor, low, high, roofs, trim, water, trunks, crowns) if value["triangles"]]
    building_materials = [{"name": "Lowrise", "color": [245, 245, 243]}, {"name": "Highrise", "color": [245, 245, 243]}]
    if p["building_style"] == "textured":
        for i, value in enumerate(building_materials):
            value.update(color=[255, 255, 255], texture_png=facade_texture(bool(i)))
    result = {"schema": "openmap.mesh.v1", "name": p["project_name"], "hill_patch": hill_patch, "anchor": anchor, "center": {"lat": p["lat"], "lon": p["lon"]}, "bbox": b,
              "materials": [material, {"name": "Main_roads", "color": [110, 116, 126]}, {"name": "Local_roads", "color": [156, 162, 171]}, *building_materials,
                            {"name": "Roof", "color": [116, 103, 94] if p["roof_style"] == "parapet_vietnam" else [175, 178, 176]}, {"name": "Parapet", "color": [221, 219, 210]},
                            {"name": "Water", "color": [64, 143, 180], "alpha": .8}, {"name": "Trunks", "color": [116, 90, 65]}, {"name": "Leaves", "color": [65, 133, 74]}],
              "meshes": meshes, "attribution": attribution, "warnings": (["%d khối nhà không có footprint hợp lệ đã được bỏ qua." % skipped] if skipped else []),
              "triangles": sum(len(value["triangles"]) for value in meshes), "parameters": p}
    update(100, "Đã dựng xong mô hình")
    return result


def export_obj(result):
    """Write portable OBJ/MTL/PNG plus geographic metadata; metres, Z up."""
    obj = ["# OpenMap SketchUp; metres, Z up", "mtllib model.mtl"]
    mtl = []
    offset = 1
    uv_offset = 1
    for i, material in enumerate(result["materials"]):
        mtl.extend(["newmtl material_%d" % i, "Kd " + " ".join("%.6f" % (c / 255) for c in material["color"])])
        if material.get("texture_png") or material.get("texture_jpeg"):
            mtl.append("map_Kd texture_%d.%s" % (i, "jpg" if material.get("texture_jpeg") else "png"))
        if "alpha" in material: mtl.append("d %.4f" % material["alpha"])
    for value in result["meshes"]:
        obj.extend(["o " + value["name"], "usemtl material_%d" % value["material"]])
        obj.extend("v %.6f %.6f %.6f" % tuple(v) for v in value["vertices"])
        has_uv = len(value["uv"]) == len(value["vertices"])
        if has_uv:
            obj.extend("vt %.9f %.9f" % tuple(uv) for uv in value["uv"])
        for tri in value["triangles"]:
            obj.append("f " + " ".join(("%d/%d" % (offset + index, uv_offset + index)) if has_uv else str(offset + index) for index in tri))
        offset += len(value["vertices"])
        if has_uv:
            uv_offset += len(value["uv"])
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("model.obj", "\n".join(obj) + "\n")
        archive.writestr("model.mtl", "\n".join(mtl) + "\n")
        archive.writestr("metadata.json", json.dumps({key: result[key] for key in ("schema", "anchor", "center", "bbox", "attribution", "warnings", "parameters")}, ensure_ascii=False, indent=2))
        for i, material in enumerate(result["materials"]):
            if material.get("texture_png") or material.get("texture_jpeg"):
                archive.writestr("texture_%d.%s" % (i, "jpg" if material.get("texture_jpeg") else "png"), base64.b64decode(material.get("texture_jpeg") or material["texture_png"]))
    return stream.getvalue()
