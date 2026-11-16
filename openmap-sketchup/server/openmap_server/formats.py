import base64
from io import BytesIO
import json
import math
import struct

from PIL import Image


def export_glb(model):
    """glTF 2.0 binary, embedded images, metres; convert Z-up to Y-up."""
    binary = bytearray()
    document = {"asset": {"version": "2.0", "generator": "OpenMap SketchUp"}, "scene": 0, "scenes": [{"nodes": []}],
                "nodes": [], "meshes": [], "materials": [], "accessors": [], "bufferViews": [], "buffers": [],
                "extras": {"anchor": model["anchor"], "attribution": model["attribution"]}}

    def view(data, target=None):
        while len(binary) % 4: binary.append(0)
        item = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
        if target: item["target"] = target
        binary.extend(data); document["bufferViews"].append(item)
        return len(document["bufferViews"]) - 1

    def accessor(values, components, indices=False, extrema=False):
        flat = values if indices else [number for value in values for number in value]
        data = struct.pack('<%d%s' % (len(flat), 'I' if indices else 'f'), *flat)
        item = {"bufferView": view(data, 34963 if indices else 34962), "componentType": 5125 if indices else 5126,
                "count": len(values), "type": "SCALAR" if indices else {2: "VEC2", 3: "VEC3"}[components]}
        if extrema:
            item["min"] = [min(value[i] for value in values) for i in range(components)]
            item["max"] = [max(value[i] for value in values) for i in range(components)]
        document["accessors"].append(item)
        return len(document["accessors"]) - 1

    for source in model["materials"]:
        material = {"name": source["name"], "pbrMetallicRoughness": {"baseColorFactor": [c / 255 for c in source["color"]] + [source.get("alpha", 1)], "metallicFactor": 0, "roughnessFactor": .85}, "doubleSided": True}
        encoded = source.get("texture_png") or source.get("texture_jpeg")
        if encoded:
            document.setdefault("images", []).append({"bufferView": view(base64.b64decode(encoded)), "mimeType": "image/jpeg" if source.get("texture_jpeg") else "image/png"})
            image_id = len(document["images"]) - 1
            samplers = document.setdefault("samplers", [])
            samplers.append({"magFilter": 9729, "minFilter": 9729, "wrapS": 33071 if source["name"] == "Ground" else 10497, "wrapT": 33071 if source["name"] == "Ground" else 10497})
            document.setdefault("textures", []).append({"source": image_id, "sampler": len(samplers) - 1})
            material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(document["textures"]) - 1}
        if source.get("alpha", 1) < 1: material["alphaMode"] = "BLEND"
        document["materials"].append(material)
    for source in model["meshes"]:
        points = [[v[0], v[2], -v[1]] for v in source["vertices"]]
        faces, uv = source["triangles"], source["uv"]
        if not source["smooth"]:
            order = [i for face in faces for i in face]
            points = [points[i] for i in order]
            uv = [uv[i] for i in order] if uv else []
            faces = [list(range(i, i + 3)) for i in range(0, len(points), 3)]
        normals = [[0.0, 0.0, 0.0] for _ in points]
        for triangle in faces:
            a, b, c = [points[i] for i in triangle]
            u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            for index in triangle:
                for axis in range(3): normals[index][axis] += normal[axis]
        for normal in normals:
            length = math.sqrt(sum(v * v for v in normal)) or 1
            for axis in range(3): normal[axis] /= length
        attributes = {"POSITION": accessor(points, 3, extrema=True), "NORMAL": accessor(normals, 3)}
        if uv: attributes["TEXCOORD_0"] = accessor([[v[0], 1 - v[1]] for v in uv], 2)
        primitive = {"attributes": attributes, "indices": accessor([i for face in faces for i in face], 1, True), "material": source["material"]}
        document["meshes"].append({"name": source["name"], "primitives": [primitive]})
        index = len(document["nodes"])
        document["nodes"].append({"name": source["name"], "mesh": len(document["meshes"]) - 1})
        document["scenes"][0]["nodes"].append(index)
    document["buffers"] = [{"byteLength": len(binary)}]
    while len(binary) % 4: binary.append(0)
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    size = 12 + 8 + len(text) + 8 + len(binary)
    return struct.pack('<4sII', b'glTF', 2, size) + struct.pack('<I4s', len(text), b'JSON') + text + struct.pack('<I4s', len(binary), b'BIN\0') + binary


def preview_mesh(model):
    result = {**model, "materials": []}
    for source in model["materials"]:
        material = {key: value for key, value in source.items() if key not in ("texture_png", "texture_jpeg")}
        encoded = source.get("texture_png") or source.get("texture_jpeg")
        if encoded:
            with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                image.thumbnail((1024, 1024))
                stream = BytesIO(); image.convert("RGB").save(stream, "JPEG", quality=85)
                material["texture_jpeg"] = base64.b64encode(stream.getvalue()).decode()
        result["materials"].append(material)
    return result
