"""Targeted GLB compatibility repairs around the unchanged original exporter.

The original writer can assign a roof texture to faces without UV coordinates.
This adapter changes only the affected material references and JSON metadata.
Every geometry/image BIN byte and every unknown GLB chunk remains untouched.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import struct

_JSON = 0x4E4F534A
_BIN = 0x004E4942
_TEXTURE_PATHS = (
    ("pbrMetallicRoughness", "baseColorTexture"),
    ("pbrMetallicRoughness", "metallicRoughnessTexture"),
    ("normalTexture",),
    ("occlusionTexture",),
    ("emissiveTexture",),
)


def _chunks(raw):
    if not isinstance(raw, bytes):
        raise TypeError("GLB input must be bytes")
    if len(raw) < 20:
        raise ValueError("Truncated GLB header or JSON chunk")
    magic, version, total = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2:
        raise ValueError("Expected a GLB version 2 file")
    if total != len(raw):
        raise ValueError("GLB declared length differs from input length")
    chunks = []
    offset = 12
    while offset < total:
        if offset + 8 > total:
            raise ValueError("Truncated GLB chunk header")
        length, kind = struct.unpack_from("<II", raw, offset)
        end = offset + 8 + length
        if length % 4 or end > total:
            raise ValueError("Invalid GLB chunk length or padding")
        chunks.append((kind, raw[offset + 8:end]))
        offset = end
    if not chunks or chunks[0][0] != _JSON:
        raise ValueError("The first GLB chunk must contain JSON")
    if sum(kind == _JSON for kind, _ in chunks) != 1:
        raise ValueError("GLB must have exactly one JSON chunk")
    if sum(kind == _BIN for kind, _ in chunks) > 1:
        raise ValueError("GLB has multiple BIN chunks")
    return chunks


def _bindings(material):
    for path in _TEXTURE_PATHS:
        parent = material
        for key in path[:-1]:
            parent = parent.get(key, {})
            if not isinstance(parent, dict):
                raise ValueError("Invalid GLB material texture container")
        binding = parent.get(path[-1])
        if binding is not None:
            if not isinstance(binding, dict):
                raise ValueError("Invalid GLB material texture binding")
            yield path, binding


def _texcoord(binding):
    coordinate = binding.get("texCoord", 0)
    extensions = binding.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("Invalid GLB texture extensions")
    transform = extensions.get("KHR_texture_transform", {})
    if not isinstance(transform, dict):
        raise ValueError("Invalid GLB texture transform")
    coordinate = transform.get("texCoord", coordinate)
    if isinstance(coordinate, bool) or not isinstance(coordinate, int) or coordinate < 0:
        raise ValueError("Invalid GLB texture coordinate index")
    return coordinate


def _color(material_index, material, colors):
    rgba = colors[material_index] if colors is not None and material_index < len(colors) else None
    if rgba is None:
        factor = material.get("pbrMetallicRoughness", {}).get("baseColorFactor", [1, 1, 1, 1])
        return list(factor), None, "existing_base_color_factor"
    if not isinstance(rgba, (list, tuple)) or len(rgba) not in (3, 4):
        raise ValueError("Scene material color must contain RGB or RGBA values")
    rgba = [float(channel) for channel in rgba]
    if not all(math.isfinite(channel) and 0 <= channel <= 255 for channel in rgba):
        raise ValueError("Scene material color values must be finite and in [0,255]")
    # Identical conversion and rounding to the original writer's solid material.
    def linear(channel):
        value = max(0.0, min(1.0, channel / 255.0))
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    factor = [round(linear(channel), 5) for channel in rgba[:3]]
    factor.append(round(rgba[3] / 255.0, 4) if len(rgba) == 4 else 1.0)
    return factor, rgba, "scene_rgba"


def repair_untextured_primitives(glb_bytes, material_colors=None):
    """Return ``(GLB bytes, report)`` with missing-UV material bindings repaired.

    ``material_colors`` is the original scene's RGB/RGBA list in material-index
    order. If omitted, existing GLB base colors are retained. A material clone is
    shared by all affected primitives that originally referenced that material.
    Missing nonzero UV sets and unknown material texture extensions are rejected
    rather than silently assigning a different mapping. Already compatible files
    return the exact input bytes without reserialization.
    """
    chunks = _chunks(glb_bytes)
    try:
        document = json.loads(chunks[0][1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid GLB JSON chunk") from exc
    if not isinstance(document, dict):
        raise ValueError("GLB JSON must be an object")
    if material_colors is not None and not isinstance(material_colors, (list, tuple)):
        raise TypeError("material_colors must be a sequence of scene colors")
    materials = document.get("materials", [])
    meshes = document.get("meshes", [])
    if not isinstance(materials, list) or not isinstance(meshes, list):
        raise ValueError("GLB materials and meshes must be arrays")
    binary = next((payload for kind, payload in chunks if kind == _BIN), None)
    raw_hash = sha256(glb_bytes).hexdigest()
    report = {"changed": False, "corrected_primitives": 0, "new_materials": 0,
              "raw_sha256": raw_hash, "output_sha256": raw_hash,
              "bin_sha256": sha256(binary).hexdigest() if binary is not None else None,
              "primitive_fixes": []}
    clones = {}
    original_material_count = len(materials)
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives", []), list):
            raise ValueError("Invalid GLB mesh primitives")
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            if not isinstance(primitive, dict):
                raise ValueError("Invalid GLB primitive")
            material_index = primitive.get("material")
            if material_index is None:
                continue
            if isinstance(material_index, bool) or not isinstance(material_index, int) or not 0 <= material_index < original_material_count:
                raise ValueError("GLB primitive references an invalid material")
            material = materials[material_index]
            attributes = primitive.get("attributes", {})
            if not isinstance(material, dict) or not isinstance(attributes, dict):
                raise ValueError("Invalid GLB primitive attributes or material")
            missing = []
            for path, binding in _bindings(material):
                coordinate = _texcoord(binding)
                if "TEXCOORD_" + str(coordinate) in attributes:
                    continue
                if coordinate != 0:
                    raise ValueError("Cannot repair missing TEXCOORD_%d on mesh %d primitive %d" %
                                     (coordinate, mesh_index, primitive_index))
                missing.append(path)
            if not missing:
                continue
            if material.get("extensions"):
                raise ValueError("Cannot repair a missing-UV material with texture extensions")
            if material_index not in clones:
                clone = deepcopy(material)
                for path in missing:
                    parent = clone
                    for key in path[:-1]:
                        parent = parent[key]
                    del parent[path[-1]]
                factor, rgba, color_source = _color(material_index, material, material_colors)
                clone.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = factor
                clone["name"] = str(material.get("name") or "Material_%d" % material_index) + " (without UV)"
                clone_index = len(materials)
                materials.append(clone)
                clones[material_index] = (clone_index, factor, rgba, color_source)
            clone_index, factor, rgba, color_source = clones[material_index]
            primitive["material"] = clone_index
            fix = {"mesh": mesh_index, "primitive": primitive_index, "original_material": material_index,
                   "replacement_material": clone_index, "missing_attribute": "TEXCOORD_0",
                   "removed_texture_bindings": [".".join(path) for path in missing],
                   "base_color_factor": factor, "original_rgba": rgba, "color_source": color_source}
            report["primitive_fixes"].append(fix)
            extras = primitive.get("extras")
            if extras is None:
                primitive["extras"] = {}
            if extras is None or isinstance(extras, dict):
                primitive["extras"]["openmap_no_uv_compat"] = deepcopy(fix)
    if not clones:
        return glb_bytes, report
    report.update(changed=True, corrected_primitives=len(report["primitive_fixes"]), new_materials=len(clones))
    # Store the complete repair inventory even when an existing primitive uses
    # a scalar/array extras value that cannot safely receive a metadata member.
    asset = document.setdefault("asset", {})
    if not isinstance(asset, dict):
        raise ValueError("Invalid GLB asset metadata")
    asset_extras = asset.get("extras")
    if asset_extras is None:
        asset_extras = {}
    elif not isinstance(asset_extras, dict):
        asset_extras = {"original_extras": asset_extras}
    asset["extras"] = asset_extras
    asset_extras["openmap_glb_compat"] = {"raw_sha256": raw_hash,
        "corrected_primitives": report["corrected_primitives"], "new_materials": len(clones),
        "primitive_fixes": report["primitive_fixes"]}
    json_chunk = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    repaired_chunks = [(chunks[0][0], json_chunk), *chunks[1:]]
    total = 12 + sum(8 + len(payload) for _, payload in repaired_chunks)
    result = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    for kind, payload in repaired_chunks:
        result.extend(struct.pack("<II", len(payload), kind))
        result.extend(payload)
    result = bytes(result)
    report["output_sha256"] = sha256(result).hexdigest()
    return result, report
