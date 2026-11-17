"""Map enhancement contracts, with fake local results and no cloud requests."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image, ImageDraw

from openmap_server.ai_texture import annotate_glb_texture, enhance_map_textures, validate_map_result
from openmap_server.builder import parameters
from openmap_server.net import PublicError


def image_bytes(image, format="PNG"):
    stream = BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


def map_image(size=(512, 512)):
    image = Image.new("RGB", size, "#998c67")
    draw = ImageDraw.Draw(image)
    w, h = size
    for x in range(13, w, 47):
        draw.line((x, 0, min(w - 1, x + 100), h), fill="#d6c1a2", width=5)
    for y in range(8, h, 71):
        draw.line((0, y, w, max(0, y - 40)), fill="#797269", width=8)
    draw.ellipse((w // 5, h // 3, w * .6, h * .8), fill="#246d77")
    draw.rectangle((w // 2, 40, w * .8, h // 5), fill="#334824")
    return image


class FakeService:
    def __init__(self, result, connected=True):
        self.result = result
        self.connected = connected
        self.calls = []

    def status(self):
        return {"bridge": {"paired": self.connected, "connected": self.connected}}

    def route(self, method, path, body):
        self.calls.append((method, path, body))
        if path.endswith("assets"):
            self.original = base64.b64decode(body["data_url"].split(",", 1)[1])
            return {"id": "a" * 32}
        return {"ok": True}

    def create_job(self, body):
        self.calls.append(("job", body))
        return {"id": "b" * 32}

    def wait_for_job(self, job_id, cancel, timeout):
        return {"id": job_id, "state": "complete", "result_ids": ["c" * 32]}

    def asset_bytes(self, asset_id):
        return self.result, {}


class MapTextureTests(unittest.TestCase):
    def test_glb_provenance_keeps_every_binary_chunk_byte(self):
        metadata = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 16}]}).encode()
        metadata += b" " * (-len(metadata) % 4)
        tail = struct.pack("<II", 16, 0x004E4942) + b"0123456789abcdef"
        glb = struct.pack("<4sIIII", b"glTF", 2, 20 + len(metadata) + len(tail), len(metadata), 0x4E4F534A) + metadata + tail
        info = {"enabled": True, "applied": True, "source_sha256": "f" * 64}
        result = annotate_glb_texture(glb, info)
        length = struct.unpack_from("<I", result, 12)[0]
        self.assertEqual(result[20 + length:], tail)
        self.assertEqual(json.loads(result[20:20 + length])["extras"]["sitecraft_ai_texture"], info)
        self.assertEqual(struct.unpack_from("<I", result, 8)[0], len(result))
        self.assertIs(annotate_glb_texture(glb, {"applied": False}), glb)

    def test_optional_flag_is_boolean_and_disabled_by_default(self):
        self.assertFalse(parameters({"lat": 21, "lon": 105})["ai_texture"])
        with self.assertRaises(PublicError):
            parameters({"lat": 21, "lon": 105, "ai_texture": "true"})

    def test_larger_aligned_texture_does_not_rewrite_geometry_uv(self):
        image = map_image()
        original = image_bytes(image)
        candidate = image_bytes(image.resize((1024, 1024), Image.Resampling.LANCZOS))
        geometry = {"verts": np.array([[0., 0., 8.], [1., 0., 3.], [0., 1., 5.]]),
                    "faces": np.array([[0, 1, 2]]), "uvs": np.array([[0., 0.], [1., 0.], [0., 1.]])}
        scene = {"materials": [{"name": "MapSKP_Satellite_Terrain", "texture_bytes": original, "ext": "png"},
                               {"name": "Facade", "texture_bytes": b"unchanged"}], "layers": [{"meshes": [geometry]}]}
        snapshot = deepcopy(scene)
        service = FakeService(candidate)
        info = enhance_map_textures(scene, {"ai_texture": True}, service)
        self.assertTrue(info["applied"])
        self.assertEqual(scene["materials"][0]["texture_bytes"], candidate)
        self.assertEqual(scene["materials"][1], snapshot["materials"][1])
        for field in ("verts", "faces", "uvs"):
            np.testing.assert_array_equal(geometry[field], snapshot["layers"][0]["meshes"][0][field])
        self.assertEqual(service.original, original)
        self.assertEqual(info["source_size"], [512, 512])
        self.assertEqual(info["result_size"], [1024, 1024])

    def test_four_k_never_submits_a_two_k_job(self):
        original = image_bytes(map_image((4096, 2048)))
        scene = {"materials": [{"name": "MapSKP_Satellite_Terrain", "texture_bytes": original, "ext": "png"}]}
        service = FakeService(b"unused")
        info = enhance_map_textures(scene, {"ai_texture": True}, service)
        self.assertFalse(info["applied"])
        self.assertIn("2K", info["warnings"][0])
        self.assertEqual(service.calls, [])
        self.assertEqual(scene["materials"][0]["texture_bytes"], original)

    def test_downsizing_aspect_change_and_shift_are_rejected(self):
        image = map_image()
        before = image_bytes(image)
        for size in ((256, 256), (1024, 800)):
            with self.subTest(size=size), self.assertRaises(PublicError):
                validate_map_result(before, image_bytes(image.resize(size)))
        shifted = Image.new("RGB", (1024, 1024), "#998c67")
        shifted.paste(image.resize((1024, 1024)), (16, 0))
        with self.assertRaises(PublicError):
            validate_map_result(before, image_bytes(shifted))

    def test_repainted_image_is_not_accepted_as_geospatial_texture(self):
        original = image_bytes(map_image())
        with self.assertRaises(PublicError):
            validate_map_result(original, image_bytes(Image.new("RGB", (1024, 1024), "green")))

    def test_transparent_or_exif_rotated_map_cannot_create_export_gaps(self):
        image = map_image()
        original = image_bytes(image)
        transparent = image.resize((1024, 1024)).convert("RGBA")
        transparent.putalpha(0)
        with self.assertRaises(PublicError):
            validate_map_result(original, image_bytes(transparent))
        output = BytesIO()
        orientation = Image.Exif(); orientation[274] = 6
        image.resize((1024, 1024)).save(output, "JPEG", exif=orientation)
        with self.assertRaises(PublicError):
            validate_map_result(original, output.getvalue())

    def test_unpaired_and_disabled_paths_do_not_send_images(self):
        original = image_bytes(map_image())
        for enabled, connected in ((False, True), (True, False)):
            with self.subTest(enabled=enabled, connected=connected):
                service = FakeService(b"unused", connected=connected)
                scene = {"materials": [{"name": "MapSKP_Satellite_Terrain", "texture_bytes": original, "ext": "png"}]}
                info = enhance_map_textures(scene, {"ai_texture": enabled}, service)
                self.assertFalse(info["applied"])
                self.assertEqual(scene["materials"][0]["texture_bytes"], original)
                self.assertEqual(service.calls, [])

    def test_invalid_result_keeps_original_and_warns(self):
        original = image_bytes(map_image())
        scene = {"materials": [{"name": "MapSKP_Satellite_Terrain", "texture_bytes": original, "ext": "png"}]}
        info = enhance_map_textures(scene, {"ai_texture": True}, FakeService(b"not-an-image"))
        self.assertFalse(info["applied"])
        self.assertTrue(info["warnings"])
        self.assertEqual(scene["materials"][0]["texture_bytes"], original)

    def test_cancelled_map_never_changes_texture(self):
        cancel = threading.Event()
        cancel.set()
        service = FakeService(b"unused")
        with self.assertRaises(PublicError):
            enhance_map_textures({}, {"ai_texture": True}, service, cancel=cancel)
        self.assertEqual(service.calls, [])


@unittest.skipUnless(sys.version_info[:2] == (3, 14), "Recovered scene writer requires Python 3.14")
class OriginalPipelineAITests(unittest.TestCase):
    def test_original_analysis_precedes_ai_and_all_exports_share_the_final_texture(self):
        from openmap_server.original_engine import OriginalEngine
        source = image_bytes(map_image())
        enhanced = image_bytes(map_image().resize((1024, 1024), Image.Resampling.LANCZOS))
        service = FakeService(enhanced)
        events = []
        with tempfile.TemporaryDirectory() as directory:
            engine = OriginalEngine({"OPENMAP_WORK_DIR": directory, "OPENMAP_ORIGINAL_FIXTURE": {}})
            builder = engine._load()[2]
            original_builder = builder.build_mode1_context_scene

            def fixture_builder(*args, **kwargs):
                scene = original_builder(*args, **kwargs)
                scene["materials"][0].update(texture_bytes=source, ext="png")
                return scene

            def analyze(scene, *args, **kwargs):
                events.append("analyze-original")
                self.assertEqual(scene["materials"][0]["texture_bytes"], source)
                return {"osm": 0, "inferred": 0}

            def transform(scene, params, cancel, progress):
                events.append("enhance")
                return enhance_map_textures(scene, params, service, cancel=cancel, progress=progress)

            engine.texture_transform = transform
            params = {"lat": 21.028511, "lon": 105.854444, "width": 100, "height": 100,
                      "grid": 8, "image_size": 1024, "imagery": "satellite", "terrain": True,
                      "roads": False, "buildings": False, "water": False, "trees": True,
                      "ai_texture": True, "project_name": "AI_Test"}
            with patch.object(builder, "build_mode1_context_scene", side_effect=fixture_builder), \
                 patch("openmap_server.original_engine.add_simple_trees", side_effect=analyze), \
                 patch("socket.socket.connect", side_effect=AssertionError("No cloud requests")):
                bundle = engine.build(params, job_id="d" * 32)
            self.assertEqual(events, ["analyze-original", "enhance"])
            self.assertTrue(bundle["original_manifest"]["ai_texture"]["applied"])
            self.assertFalse(bundle["original_manifest"]["texture_bytes_preserved"])
            self.assertEqual(base64.b64decode(bundle["mesh"]["materials"][0]["texture_png"]), enhanced)
            with zipfile.ZipFile(BytesIO(bundle["obj_zip"])) as archive:
                textures = [archive.read(name) for name in archive.namelist() if name.endswith(".png")]
                self.assertIn(enhanced, textures)
            fallback = json.loads(Path(bundle["fallbackpath"]).read_bytes())
            self.assertEqual(Path(fallback["materials"][0]["tex_path"]).read_bytes(), enhanced)
            self.assertTrue(fallback["origin"]["sitecraft_ai_texture"]["applied"])
            writer = engine._load()[3]
            pack = Path(bundle["original_manifest"]["mapskp1_path"]).read_bytes()
            unpacked = writer.unpack_mapskp1_to_scene(pack)
            self.assertEqual(unpacked["materials"][0]["texture_bytes"], enhanced)
            self.assertTrue(unpacked["origin"]["sitecraft_ai_texture"]["applied"])
            self.assertIn(enhanced, bundle["glb"])
            length = struct.unpack_from("<I", bundle["glb"], 12)[0]
            self.assertTrue(json.loads(bundle["glb"][20:20 + length])["extras"]["sitecraft_ai_texture"]["applied"])


if __name__ == "__main__":
    unittest.main()
