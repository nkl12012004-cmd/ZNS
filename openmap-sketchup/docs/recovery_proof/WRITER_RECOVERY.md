# Editable original writer recovery (local only)

`skp_capi_writer.py` reconstructs all 14 original writer functions from the user-provided CPython 3.14 code object. This is editable Python, not a wrapper around `.marshal` or `.pyc`. Original rights apply; this recovery does not itself grant an MIT license.

Run oracle tests with:

```
/workspace/work/python314_linux/venv/bin/python /workspace/work/runtime_recovery/readable/test_skp_capi_writer_oracle.py
```

Results: `skp_capi_writer_oracle_report.json` (16 groups passed).

- OBJ, MTL, textures, GLB, Ruby fallback JSON and MAPSKP1 exports have identical bytes for the complete original Quynh Luu scene and small/empty fixtures (17 + 5 + 5 files).
- MAPSKP1 unpack/repack preserves the original package bytes.
- Soft edges match across 54 original-mesh/threshold cases; year parsing, sRGB conversion, five SDK ABI structures, SDK discovery and worker result/control-flow branches match.
- Native geometry/material SDK call sequences match through the save boundary: 129,707 calls on the actual scene; 208,048 on the 16,001-triangle chunk fixture; smaller fixtures also cover origin metadata, invalid faces, duplicate names, transparency and UVs.
- SDK call tests use a recording fixture that deliberately raises before the save function. No fake SKP file is generated. Actual native SKP creation still requires Windows and the real installed SketchUpAPI.dll.

The original module's `__main__` dispatcher is restored exactly: at least six argv entries and `--worker-skp` dispatch `argv[2:6]` to `run_skp_worker_cli`, then exit with its result. The original `_resolve_skp_worker_script` can therefore execute this readable source directly when the native bridge path is unavailable. Both original dispatch conditions and worker result/exit behavior are covered by local oracle tests. No adapter metadata workaround is required.

The automatic local PyLingual 3.14 decompilation is available only as an unverified aid in `../pylingual_output/decompiled_skp_capi_writer.py`. Most of its functions failed compilation/control-flow checks; the verified source above was reconstructed manually and tested against the original. No original code was submitted to an online decompiler or other remote service.
