# Original model geometry: readable recovery

The user-provided `mode1_osm_dem_builder` CPython 3.14 code objects were the source of this reconstruction. The geometry routines are readable Python implementations, with no calls to recovered bytecode or a vendor server. Original rights remain; recovery does not establish an open-source license or transfer copyright.

`model_geometry.py` contains 18 recovered functions. `model_polygon_helpers.py` contains another 10 and is explicitly imported/reexported by `model_geometry.py`.

- Terrain: original bilinear DEM sampler, gridded terrain with perimeter plinth, flat sheet, trimmed and feathered hill patch.
- Buildings: original triangulation, ring cleanup, iterative RDP simplification, polygon extrusion, legacy textured extrusion, facade wall tier UV mapping, polygon inset, parapet/recessed or flat roof, stepped terraces, safe penthouse placement, and the complete articulated v24 building routine including podium and upper setback decisions.
- Roads and trees: terrain-following road ribbons with the original curb/clamping behavior, and the original six-vertex architectural tree.
- Helpers: original signed area, longest-edge axis, point inclusion, edge distance, segment intersection, ear clipping, merge with and without UVs, segment/polyline clipping, and triangle clipping to a rectangle.

All original triangle winding, vertex order, float32 and uint32 array conversion, UV phase rules, material-index decisions, thresholds and existing quirks are retained. No corrective geometry changes have been mixed into the recovery.

## Verification

Run locally with the matching original interpreter:

```sh
/workspace/work/python314_linux/venv/bin/python /workspace/work/runtime_recovery/readable/test_model_geometry_oracle.py
/workspace/work/python314_linux/venv/bin/python /workspace/work/runtime_recovery/readable/test_model_polygon_helpers_oracle.py
```

`model_geometry_oracle_report.json`: PASS, 12,032 comparisons over 18 functions. This includes 778 articulated building cases spanning low-rise, podium, upper setback, roof and penthouse decisions, 1,184 triangle clipping cases, 216 trimmed hills, 900 road ribbons and 3,000 DEM samples.

`model_polygon_helpers_oracle_report.json`: PASS, 11,123 comparisons over 10 functions. Combined: 23,155 comparisons.

Comparisons check returned Python types and structure, scalar float64 bits, NumPy array dtype/shape/bytes, and exceptions. The oracle uses unchanged supplied code objects. The geometry suite loads the reconstructed facade module independently and asserts it is distinct from the facade functions already imported by the oracle. Both original and reconstructed code run under the same Python/NumPy environment. The corpus is broad but is not a mathematical proof for all possible inputs; cross-version floating-point behavior is not claimed.

## Integration contract

The geometry module requires NumPy plus the adjacent readable `facade_texture_gen.py` for original facade/roof specifications and low-rise roof selection, and the adjacent `model_polygon_helpers.py`. Its public/private names retain the original callable names, so the separately recovered scene builder can import them explicitly. It does not implement data download, OSM/MVT parsing, raster street extraction, authentication, desktop UI, scene orchestration or export writers; those are separate components owned by other recovery modules. No unavailable original function is silently emulated or loaded from bytecode here.
