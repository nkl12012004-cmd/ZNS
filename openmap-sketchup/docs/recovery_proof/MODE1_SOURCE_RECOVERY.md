# Readable recovery of the original MapSKP model builder

This is local recovery from the user-provided MapSKP 2.8.1 runtime. Original
attribution and rights are retained. The reconstructed original code is **not**
relicensed under the independent OpenMap implementation's MIT license.

## Result

`mode1_osm_dem_builder.py` is the complete assembled, editable Python builder:

- All **51 original top-level functions**, in their original module order.
- Every nested function/closure belonging to `build_mode1_context_scene`.
- Original imported dependencies, constants and initial cache state.
- The original `try: import mapskp_armor ... except Exception: ... = None` import
  behavior and the builder's native `get_locked_policy` / missing projection
  grant checks. No native policy is unconditionally disabled.
- A single module globals dictionary for all builder helper calls.
- No marshal/pyc loading, dynamic source execution, bytecode fallback or imports
  from source-recovery fragments in the production builder.

It imports the separately recovered readable `geo_math.py` and
`facade_texture_gen.py`, plus NumPy, Pillow and Requests. Keep these readable
files together on the normal import path when loading the assembled builder.
The local recovery tests use a separate module namespace so the readable files
cannot accidentally resolve to their original bytecode counterparts.

## Assembly provenance

The source functions were collected by AST from the independently verified
fragments:

- `model_data.py`: data/provider/OSM/MVT/morphology routines.
- `model_geometry.py`: terrain/plinth, roads, buildings, roof/parapet/penthouse.
- `model_polygon_helpers.py`: polygon, merge and clipping helpers.
- `model_scene.py`: original scene orchestration, materials/layers and metadata.

`_rdp_simplify_2d` was present in two fragments. Both variants passed their own
oracle checks; the assembled module retains the `model_data.py` version once.
The original code object was used only by the local assembly/check tool to
verify function names/order/signatures/constants; the generated builder is
ordinary source and does not need that code object.

`mode1_source_assembly_manifest.json` records the function names, source-fragment
provenance and module constants. `assemble_mode1_source.py` is a local recovery
tool, not a production dependency.

## Exact comparisons

`test_mode1_assembled_oracle.py` completed **61/61 cases** using the full assembled
readable builder and the readable geographic/facade implementations. It does
not inject original geometry/data helper implementations into the readable
builder. Normal-mode data IO fixtures are controlled on both sides of tests;
full synthetic/geometry calculations use each implementation's own helpers.

Comparison includes:

- All 51 signatures, parameter names/kinds/defaults and initial module constants.
- Exact NumPy dtype, array shape, vertex/triangle/UV values and ordering.
- Exact texture bytes, material/layer order, geospatial origin and statistics.
- Exact progress messages and event ordering.
- Flat aliases, DEM terrain, hill patches, custom DEMs and prior anchors.
- Building/roof styles, high/low/road switches and relation/water/tree/park data.
- Data-provider and Google gapfill fallback behavior and element error handling.
- Largest-first 4,500-building cap, 350-tree cap and large-area peak notices.
- Native SaaS policy denial when a required grant is missing, native policy
  exceptions, malformed input and progress-callback cancellation.

47 cases return complete scenes. 14 deliberately return the same exception
class/message or cancellation on both sides. The report distinguishes these.

Report: `mode1_assembled_oracle_report.json`.

## Actual-region cache-only proof

`test_mode1_cached_quynh_luu.py` used the existing public imagery/DEM/MVT cache for
Quỳnh Lưu (19.14507, 105.63640; requested 1558 × 1701 m), without sending any
network traffic. It compares:

1. The unchanged original builder with the cached data.
2. The complete assembled readable builder with the same cached data.
3. The original `.mapskp1` scene saved by the earlier successful live-data run.

All three scenes match exactly. The two fresh progress sequences also match.

- 13 materials, 4 layers, 7,316 vertices, 10,500 triangles.
- Geometry/UV/material-index fingerprint:
  `b013b958853c85ec824510e554703a624256b5905b62a6b71ae52a0386d7a980`.
- All 53 cache files remained byte-for-byte unchanged.
- Readable run: approximately 2.84 seconds; original run: 3.39 seconds.
- Six cache-miss request attempts were stopped before Requests could send:
  OpenFreeMap metadata and unavailable Overpass endpoints. Original fallback
  handling then used cached metadata/MVT. No vendor request was attempted.

Report: `mode1_cached_quynh_luu_report.json`.

This sample correctly retains the original result's degraded building metadata:
2 low-rise buildings and 300 road chains, including 109 road gapfills and one
building gapfill. Source equivalence does not manufacture missing provider data
or promise all external services will always respond.

## Reproduce locally

Use the task's CPython 3.14 environment with NumPy, Pillow and Requests:

```sh
/workspace/work/python314_linux/venv/bin/python test_mode1_assembled_oracle.py
/workspace/work/python314_linux/venv/bin/python test_mode1_cached_quynh_luu.py
```

The oracle tests need the unchanged local recovered original modules in
`../recovered/`. That requirement belongs to tests only. The production readable
builder uses no oracle module.

## Limits

- The signed authoritative-projection **success** branch was transcribed and
  preserved, but was not exercised because no real signed grant was supplied.
  Tests do not forge one or alter native policy checks.
- The exact comparisons run on Linux CPython 3.14.10 with the task dependencies;
  native SketchUp/C SDK calls and the user's Windows installation are separate
  verification tasks.
- This builder and its geometry/data/texture dependencies are recovered. The
  commercial account, billing, update and authorization service implementations
  are outside this source recovery; their behavior has not been reconstructed.
- This work remains local. It does not assert a new right to publicly relicense
  or redistribute the original author's implementation.
