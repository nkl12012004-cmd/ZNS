from io import BytesIO
import json
import unittest
import zipfile

from openmap_server.builder import export_obj


def example():
    return {
        "schema": "openmap.mesh.v1", "anchor": {"lat": 21, "lon": 105, "elevation": 16},
        "center": {"lat": 21, "lon": 105}, "bbox": {"west": 104.99, "east": 105.01, "south": 20.99, "north": 21.01},
        "attribution": ["Fixture"], "warnings": [], "parameters": {"terrain": True},
        "materials": [{"name": "Ground", "color": [255, 255, 255]}],
        "meshes": [{"name": "Ground", "material": 0, "smooth": True,
                    "vertices": [[0, 0, 5], [2, 0, 5], [0, 3, 5]],
                    "triangles": [[0, 1, 2]], "uv": [[0, 0], [1, 0], [0, 1]]}],
    }


class ObjExportContractTests(unittest.TestCase):
    def unpack(self, model):
        with zipfile.ZipFile(BytesIO(export_obj(model))) as archive:
            self.assertIsNone(archive.testzip())
            return archive.read("model.obj").decode(), json.loads(archive.read("metadata.json"))

    def test_matches_old_metres_y_up_contract_and_keeps_winding(self):
        model = example()
        text, metadata = self.unpack(model)
        self.assertIn("1 unit = 1 meter; Y-Up", text.splitlines()[0])
        points = [list(map(float, line.split()[1:])) for line in text.splitlines() if line.startswith("v ")]
        self.assertEqual(points, [[0, 5, 0], [2, 5, 0], [0, 5, -3]])
        a, b, c = points
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        self.assertGreater(u[2] * v[0] - u[0] * v[2], 0, "An upward source face must remain upward in Y-up OBJ")
        self.assertEqual([line for line in text.splitlines() if line.startswith("f ")], ["f 1/1 2/2 3/3"])
        self.assertEqual(metadata["up_axis"], "Y")
        self.assertEqual(metadata["units"], "metres")
        self.assertEqual(metadata["axes"], {"X": "east", "Y": "up", "Z": "south"})
        self.assertEqual(metadata["anchor"], model["anchor"])

    def test_preserves_uv_orientation_and_offsets_across_untextured_group(self):
        model = example()
        model["meshes"].extend([
            {"name": "Road", "material": 0, "smooth": False, "vertices": [[0, 0, 1], [1, 0, 1], [0, 1, 1]], "triangles": [[0, 1, 2]], "uv": []},
            {"name": "Roof", "material": 0, "smooth": False, "vertices": [[0, 0, 9], [1, 0, 9], [0, 1, 9]], "triangles": [[0, 1, 2]], "uv": [[.25, .5], [.75, .5], [.25, 1]]},
        ])
        text, _ = self.unpack(model)
        self.assertEqual([line for line in text.splitlines() if line.startswith("f ")], ["f 1/1 2/2 3/3", "f 4 5 6", "f 7/4 8/5 9/6"])
        uvs = [list(map(float, line.split()[1:])) for line in text.splitlines() if line.startswith("vt ")]
        self.assertEqual(uvs, [[0, 0], [1, 0], [0, 1], [.25, .5], [.75, .5], [.25, 1]])
        self.assertIn("o Road\nusemtl material_0", text)
        self.assertIn("o Roof\nusemtl material_0", text)

    def test_rotation_preserves_metres_and_does_not_mutate_source_mesh(self):
        model = example()
        model["meshes"][0]["vertices"] = [[-2, 3, 5], [7, -4, 8], [9, 11, -6]]
        before = json.dumps(model, sort_keys=True)
        text, _ = self.unpack(model)
        points = [list(map(float, line.split()[1:])) for line in text.splitlines() if line.startswith("v ")]
        self.assertEqual(points, [[-2, 5, -3], [7, 8, 4], [9, -6, -11]])
        source = model["meshes"][0]["vertices"]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            self.assertAlmostEqual(sum((source[a][i] - source[b][i]) ** 2 for i in range(3)), sum((points[a][i] - points[b][i]) ** 2 for i in range(3)))
        self.assertEqual(json.dumps(model, sort_keys=True), before)
