"""Private integration of the unchanged, locally recovered MapSKP libraries.

This adapter is new code. It does not claim the recovered implementations are
editable source or MIT licensed, and does not modify their policy/projection
branches. Raw scenes go directly to the original writers.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import uuid
import zipfile

from .net import PublicError
from .original_scene import adapt_scene, _json_ready
from .glb_compat import repair_untextured_primitives


_ENGINE_LOCK = threading.Lock()
_KERNEL_NAMES = ("geo_math", "facade_texture_gen", "mode1_osm_dem_builder", "skp_capi_writer")
_FIXTURE_KEYS = ("custom_dem_asl", "mock_osm_data", "custom_roadmap_rgb")


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise PublicError("Giá trị %s phải nằm trong [%s, %s]." % (label, low, high))
    return float(value)


def _basename(value):
    value = re.sub(r"[^\w \-]", "", str(value or "MapSKP_Context")).strip()[:80] or "MapSKP_Context"
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", value, re.I):
        value = "MapSKP_" + value
    return value


class OriginalEngine:
    def __init__(self, config):
        self.config = config
        self.kernel_dir = Path(config.get("OPENMAP_ORIGINAL_KERNEL_DIR") or Path(__file__).resolve().parents[1] / "original_kernel").resolve()
        configured = config.get("OPENMAP_WORK_DIR")
        self.work_root = Path(configured).expanduser().resolve() if configured else Path(tempfile.mkdtemp(prefix="openmap_original_"))
        self.cache_dir = self.work_root / "cache"
        self._modules = None

    def availability(self):
        if sys.version_info[:2] != (3, 14):
            return {"available": False, "engine": "original", "reason": "Lõi MapSKP gốc cần CPython 3.14.", "python": sys.version.split()[0]}
        missing = [name for name in ("numpy", "requests", "PIL") if importlib.util.find_spec(name) is None]
        missing.extend(name for name in _KERNEL_NAMES if not (self.kernel_dir / (name + ".py")).is_file())
        if missing:
            return {"available": False, "engine": "original", "reason": "Thiếu thành phần của lõi gốc: " + ", ".join(missing), "missing": missing}
        return {"available": True, "engine": "original", "python": sys.version.split()[0], "recovered_implementation": True, "fully_editable_source": True}

    @property
    def available(self):
        return self.availability()["available"]

    def _load(self):
        status = self.availability()
        if not status["available"]:
            raise PublicError(status["reason"], 503)
        if self._modules is None:
            location = str(self.kernel_dir)
            if location not in sys.path:
                sys.path.insert(0, location)
            modules = tuple(importlib.import_module(name) for name in _KERNEL_NAMES)
            for module in modules:
                if Path(module.__file__).resolve().parent != self.kernel_dir:
                    raise PublicError("Đã nạp nhầm vị trí thư viện MapSKP gốc. Khởi động lại bộ xử lý.", 503)
            self._modules = modules
        return self._modules

    def original_parameters(self, params):
        """Translate the new controls to the old UI's public payload only."""
        geo, _textures, _builder, _writer = self._load()
        lat = _number(params.get("lat"), "vĩ độ", -79.9, 79.9)
        lon = _number(params.get("lon"), "kinh độ", -179.9, 179.9)
        width = _number(params.get("width", params.get("width_m", 380)), "chiều rộng (m)", 30, 4000)
        height = _number(params.get("height", params.get("height_m", 380)), "chiều dài (m)", 30, 4000)
        south, west, north, east = geo.bbox_from_center_meters(lat, lon, width, height)
        imagery = params.get("imagery", "satellite")
        fixture = self.config.get("OPENMAP_ORIGINAL_FIXTURE")
        if imagery == "none" and fixture is None:
            raise PublicError("Lõi MapSKP gốc cần một nguồn ảnh. Chọn Vệ tinh sạch hoặc Google trong phần ảnh xuất.")
        providers = {"satellite": "esri_sat", "esri_sat": "esri_sat", "google_sat": "google_sat", "google_hybrid": "google_hybrid", "google_street": "google_street"}
        if imagery not in providers and not (imagery == "none" and fixture is not None):
            raise PublicError("Nguồn ảnh không được lõi gốc hỗ trợ.")
        terrain = params.get("terrain", params.get("terrain_mode", "terrain_3d") != "flat")
        terrain_mode = "terrain_3d" if terrain else "flat"
        z_exag = _number(params.get("exaggeration", params.get("z_exaggeration", 1)), "hệ số cao độ", .1, 10)
        anchor = params.get("anchor")
        if anchor is not None:
            if not isinstance(anchor, dict):
                raise PublicError("Mốc chung không hợp lệ.")
            anchor = {"lat": _number(anchor.get("lat"), "mốc vĩ độ", -80, 80),
                      "lon": _number(anchor.get("lon"), "mốc kinh độ", -180, 180),
                      "elevation_m": _number(anchor.get("elevation_m", anchor.get("elevation", 0)), "cao độ mốc", -12000, 20000),
                      "z_exaggeration": _number(anchor.get("z_exaggeration", z_exag), "hệ số cao độ mốc", .1, 10),
                      "terrain_mode": anchor.get("terrain_mode", terrain_mode)}
            if anchor["terrain_mode"] not in ("flat", "terrain_3d"):
                raise PublicError("Chế độ nền của mốc không hợp lệ.")
        roads = bool(params.get("roads", True))
        main = roads and bool(params.get("roads_main", True))
        alley = roads and bool(params.get("roads_local", True))
        buildings = bool(params.get("buildings", True))
        result = {"project_name": _basename(params.get("project_name")), "lat": lat, "lon": lon,
                  "width_m": width, "height_m": height, "south": south, "west": west, "north": north, "east": east,
                  "anchor": anchor, "terrain_mode": terrain_mode,
                  "hill_patch": bool(terrain and anchor and anchor["terrain_mode"] == "flat"),
                  "sat_provider": providers.get(imagery, "esri_sat"), "sat_px": int(params.get("image_size", 4096)),
                  "dem_grid": int(params.get("grid", 64)), "default_floors": params.get("default_floors", 3.5), "z_exaggeration": z_exag,
                  "include_buildings": buildings,
                  "include_buildings_high": buildings and bool(params.get("buildings_high", True)),
                  "include_buildings_low": buildings and bool(params.get("buildings_low", True)),
                  "include_roads": main or alley, "include_roads_main": main, "include_roads_alley": alley,
                  "include_water": bool(params.get("water", False)), "include_trees": bool(params.get("trees", False)),
                  "building_style": "white_box" if params.get("building_style") in ("white", "white_box", "box", "clay") else "textured",
                  "roof_style": params.get("roof_style", "parapet_vietnam")}
        if fixture is not None:
            if not isinstance(fixture, dict):
                raise PublicError("Cấu hình fixture của lõi gốc phải là dictionary nội bộ.", 500)
            # Only trusted process configuration can select the original test
            # branch. No such switch is copied from HTTP/user parameters.
            result["offline_synthetic"] = True
            result.update({key: fixture[key] for key in _FIXTURE_KEYS if key in fixture})
        return result

    def build(self, params, progress=lambda *_: None, cancel=None, job_id=None):
        cancel = cancel or threading.Event()
        job_id = job_id or uuid.uuid4().hex
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise PublicError("Mã tác vụ không hợp lệ.")

        def check():
            if cancel.is_set():
                raise PublicError("Đã hủy tác vụ.")

        def report(message, percent):
            check()
            progress(float(percent), str(message))

        check()
        while not _ENGINE_LOCK.acquire(timeout=.1):
            check()
        try:
            check()
            original_params = self.original_parameters(params)
            _geo, _textures, builder, writer = self._load()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            directory = self.work_root / "jobs" / job_id
            directory.mkdir(parents=True, exist_ok=False)
            name = original_params["project_name"]
            scene = builder.build_mode1_context_scene(original_params, self.cache_dir, report)
            check()
            origin = _json_ready(scene.get("origin", {}))
            normalized_anchor = {"lat": origin.get("anchor_lat", origin.get("lat")),
                                 "lon": origin.get("anchor_lon", origin.get("lon")),
                                 "elevation": origin.get("anchor_elev_m", origin.get("elevation_m", 0)),
                                 "terrain_mode": origin.get("anchor_terrain_mode", origin.get("terrain_mode", "terrain_3d")),
                                 "z_exaggeration": origin.get("z_exaggeration", 1)}
            mesh = adapt_scene(scene, anchor=normalized_anchor,
                               center={"lat": origin.get("lat", original_params["lat"]), "lon": origin.get("lon", original_params["lon"])},
                               bbox={key: original_params[key] for key in ("south", "west", "north", "east")},
                               parameters=params,
                               attribution=["Original MapSKP data pipeline: imagery/data © their respective providers; OpenStreetMap contributors where used."])
            source_degraded = bool(origin.get("peak_hour_degraded") or origin.get("overpass_overloaded") or origin.get("all_subtiles_ok") is False)
            warnings = []
            if origin.get("peak_hour_notice"):
                warnings.append(str(origin["peak_hour_notice"]))
            elif source_degraded:
                warnings.append("Lõi gốc báo nguồn dữ liệu đang giảm khả dụng; giữ nguyên đường/công trình đã dựng được, không coi toàn bộ lớp OSM là mất.")
            mesh.update(engine="original", source_degraded=source_degraded, warnings=warnings,
                        original_fixture=bool(self.config.get("OPENMAP_ORIGINAL_FIXTURE") is not None))
            report("Đang xuất OBJ bằng bộ ghi gốc", 96)
            obj_result = writer.write_obj_bundle(scene, directory / (name + ".obj"))
            check()
            glb_result = writer.write_glb_binary(scene, directory / (name + ".glb"))
            glb_path = directory / (name + ".glb")
            original_glb = glb_path.read_bytes()
            glb_bytes, glb_compat = repair_untextured_primitives(
                original_glb, [material.get("color", [210, 210, 210, 255]) for material in scene.get("materials", [])])
            original_glb_path = glb_path
            if glb_compat["changed"]:
                original_glb_path = directory / (name + "_original.glb")
                original_glb_path.write_bytes(original_glb)
                glb_path.write_bytes(glb_bytes)
                glb_result = {**glb_result, "size_kb": round(len(glb_bytes) / 1024, 1),
                              "original_writer_path": str(original_glb_path), "compatibility_applied": True}
            check()
            fallback = writer.write_ruby_fallback_json(scene, directory / (name + "_fallback.json"), directory / (name + "_ruby_textures"))
            check()
            packed = writer.pack_scene_to_mapskp1(scene)
            pack_path = directory / (name + ".mapskp1")
            pack_path.write_bytes(packed)
            sdk_result = {"ok": False, "code": "SDK_NOT_REQUESTED", "error": "Chưa đặt thư mục SketchUp SDK; có JSON fallback gốc."}
            su_dir = self.config.get("OPENMAP_SKETCHUP_DIR") or params.get("su_exe_dir")
            skp = directory / (name + ".skp")
            if os.name == "nt":
                report("Đang ghi SKP bằng SketchUp SDK", 98)
                try:
                    sdk_result = writer.write_skp_subprocess(packed, skp,
                        preferred_year=str(self.config.get("OPENMAP_SKETCHUP_VERSION") or params.get("su_version") or "") or None,
                        su_exe_dir=str(su_dir) if su_dir else None)
                except Exception as error:
                    sdk_result = {"ok": False, "code": "SDK_ERROR", "error": str(error)}
            elif su_dir:
                sdk_result = {"ok": False, "code": "SDK_PLATFORM_UNAVAILABLE", "error": "SketchUp SDK cần Windows; giữ JSON fallback gốc."}
            native_ready = bool(sdk_result.get("ok") and skp.is_file() and skp.stat().st_size > 0)
            if sdk_result.get("ok") and not native_ready:
                sdk_result = {**sdk_result, "ok": False, "error": "Bộ ghi SDK không tạo tệp SKP hợp lệ."}
            check()
            manifest = {"engine": "original", "job_id": job_id, "name": name,
                        "origin": origin, "original_parameters": _json_ready(original_params),
                        "geometry_preserved": True, "texture_bytes_preserved": True,
                        "editable_adapter_only": False, "fully_editable_original_source": True,
                        "source_degraded": source_degraded, "warnings": warnings,
                        "fixture": mesh["original_fixture"],
                        "obj": _json_ready(obj_result), "glb": _json_ready(glb_result),
                        "glb_compatibility": glb_compat, "original_glb_path": str(original_glb_path),
                        "fallback_path": str(fallback), "mapskp1_path": str(pack_path),
                        "mapskp1_sha256": sha256(packed).hexdigest(),
                        "native_skp_ready": native_ready, "sdk_result": _json_ready(sdk_result)}
            manifest_path = directory / (name + "_original_manifest.json")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf8")
            zipped = BytesIO()
            with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in [directory / (name + ".obj"), directory / (name + ".mtl"), manifest_path]:
                    archive.write(path, path.relative_to(directory).as_posix())
                maps = directory / (name + "_maps")
                if maps.is_dir():
                    for path in sorted(maps.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(directory).as_posix())
            report("Đã dựng và xuất bằng lõi MapSKP gốc", 100)
            return {"mesh": mesh, "raw_scene": scene, "obj_zip": zipped.getvalue(),
                    "glb": glb_bytes, "original_glb_path": str(original_glb_path),
                    "skp_path": str(skp) if native_ready else None,
                    "native_skp_ready": native_ready, "original_manifest": manifest,
                    "original_manifest_path": str(manifest_path), "fallbackpath": str(fallback),
                    "exportdir": str(directory), "original_parameters": original_params,
                    "source_degraded": source_degraded, "warnings": warnings}
        finally:
            _ENGINE_LOCK.release()
