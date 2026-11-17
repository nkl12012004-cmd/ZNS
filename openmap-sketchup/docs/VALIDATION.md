# Validation — Windows Full 0.2.2

- 28 server tests passed locally. New cases build and retrieve geometry in local
  mode without a Supabase project, verify the private IPC token is still required,
  and verify standalone servers do not accidentally enable local access.
- Playwright passed: direct workspace with no auth/config API calls, map/build,
  manual/automatic import, OBJ/GLB, WebGL, restart, and startup failure/retry.
  Remote Email/Google flows remain fixture tested.
- All changed Ruby files passed Prism syntax validation.
- Native Windows release gate now loads the actual Core.http method rather than
  testing a separate Net::HTTP client. The host stub rejects Sketchup::Http in
  managed mode and checks that callbacks/timers stay on the main thread.
- That gate checks health, /me, job creation, mesh and binary GLB without login,
  with a broken proxy environment, then restart and parent-exit cleanup.
- SketchUp Desktop is not installed locally or on CI. We cannot yet confirm
  the fix on the user's machine or actual geometry API import/Undo/placement.

Historical checks below refer to versions 0.2.0 and 0.1.0. Their mandatory
Supabase/login instructions do not apply to Windows Full 0.2.2.

# Validation — Windows Full 0.2.0

[Native Windows run 43996909891 passed](https://github.com/nkl12012004-cmd/ZNS/actions/runs/43996909891).
Packaged CPython 3.14.10 and Pillow 12.3.0 passed all 25 server tests.
The native OCR engine reports 5.5.0 (NuGet package TesseractOCR 5.5.2) and
recognized `10.776889, 106.700806` from a generated image. HTTPS/OpenSSL,
Ruby start/restart, Unicode install/cache paths and parent-exit cleanup passed.
The release assets were downloaded again and matched SHA-256 and ZIP CRC.

- 25 server tests pass locally, including local transport, Supabase config,
  persistence, token separation and rejection of secret/service_role keys.
- First-run progress, Supabase setup and restart are checked in Playwright
  in addition to the existing map/auth/3D/import/export flows with fixtures.
- All Ruby files are syntax checked. The runtime archive is independently
  unpacked and checked entry-by-entry against its SHA-256 catalog.
- Native Windows release is gated by tools/windows-smoke.py in GitHub Actions:
  packaged CPython/Pillow, full server tests, OCR recognition, HTTPS/OpenSSL,
  Ruby first-start/restart, Unicode paths and parent-exit shutdown.
- GitHub Release is published only after that native Windows job succeeds.

SketchUp Desktop is not installed here or on the runner. Actual model import,
textures, Undo and SKP placement still need a SketchUp smoke test. Real Supabase
credentials are intentionally not provided; the user chose to enter them later.
The implementation retains the feature limits in FEATURE_PORT.md; the encrypted
MapSKP proprietary core was not recovered.

The earlier section below describes version 0.1.0; its packaging and OCR limitations
are superseded by the Full Windows checks above.

Previous live-data / geometry validation (0.1.0):

# Validation — 2026-11-16

Passed checks:

- 18 Python unittest cases: actual HTTP requests against a local Supabase protocol
  fixture; invalid credentials, fabricated tokens, refresh, Google PKCE, polling
  secret, one-time delivery, ownership checks for mesh/OBJ/GLB/preview, missing
  configuration and browser-origin rejection.
- WGS84 in metres, concave/closed building geometry, clipping, terrain/UV,
  shared patch seams with a constant DEM fixture, flat-base hill patches with
  zero boundary height, building/roof/water/tree options, OBJ and GLB structure,
  glTF UV orientation, preview resizing, XML fallback and DTD/entity rejection.
- OCR dependency error and fixed-argv Tesseract calls tested with fixtures.
- JavaScript syntax checked with Node.js; all four Ruby files with Prism 2.1.0.
- Importer preflight run in a real Ruby 3.3 WebAssembly VM on a live generated
  mesh: valid data accepted, bad indices/NaN/materials rejected, JPEG dimensions,
  SKP ENU offsets and legacy metadata conversion checked.
- Playwright/Chromium: Email/Google login, invalid login, decimal/DMS input,
  manual/automatic import, OBJ/GLB, theme, WebGL preview/wireframe, responsive
  layout and logout. Native SketchUp bridge/auth responses are fixtures.
- Live public-data build at 10.776889, 106.700806, area 100 x 100 m:
  Esri imagery, Terrarium DEM, OSM fallback; 1,376 triangles (Ground 128,
  Roads_main 10, Roads_local 30, Buildings_lowrise 412, Building_roofs 88,
  Roof_parapets 708). No OSM water/tree objects occurred in this region;
  those layers were checked with fixtures.
- Live-generated GLB passed Khronos glTF Validator: 0 errors, 0 warnings.
- Original reference files preserved byte-for-byte with SHA-256 inventory.
- ZIP/RBZ CRC checked. No .env, caches, node_modules, encrypted vault or native
  runtime binary is bundled in the RBZ.

Requires the operator's environment:

- The user chose to fill Supabase configuration later. Live Email/Google login
  is not tested against their project; .env.example contains no live keys.
- SketchUp Desktop is unavailable. Actual import/textures, placement observers,
  Undo, toolbar and SKP saving need a smoke test in SketchUp 2021 or newer.
  Ruby VM validation does not emulate SketchUp geometry APIs.
- Tesseract was not installed here; OCR subprocess behavior uses fixtures.
- The 8K option, Google tile endpoints and all combinations of roof/terrain
  settings have not received exhaustive live tests. RAM/provider availability
  affect large jobs.
- Overpass was unavailable during the live check; OSM map API fallback worked.
- New runtime is independent. Recovered original reference files retain their
  original rights; encrypted/native MapSKP source and signing keys were not recovered.
