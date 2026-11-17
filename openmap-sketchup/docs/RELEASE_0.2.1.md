Windows x64 Full — open the map directly, no account or Supabase setup.

- Bundled mode no longer requires Email/Google login or Supabase URL/public key.
- The local API uses the per-instance private transport token, without a fabricated login session. Remote server mode retains Supabase authentication.
- Replaces Sketchup::Http calls to the local worker with background, direct loopback HTTP and explicit proxy bypass. UI callbacks run on SketchUp's main thread.
- Startup failures open recovery settings with restart/log controls instead of leaving disabled login buttons.
- Includes CPython 3.14.10, Pillow 12.3.0, Tesseract 5.5.0/English OCR and Leptonica 1.85.0.

Install the new RBZ using Extension Manager, **quit all SketchUp windows completely**, reopen SketchUp and open OpenMap. Do not enter Supabase settings.
Existing Supabase configuration does not block the new bundled mode.

Release is gated by 28 server tests and native Windows checks using the actual Ruby Core HTTP bridge, direct map/mesh/GLB access without Supabase, proxy bypass, Unicode paths, OCR, restart and parent-exit shutdown. The UI flow is checked with Playwright fixtures.

SketchUp Desktop itself is not installed on the CI runner; the specific failure on the user's machine cannot be declared verified until they open the update. Actual model import/Undo/placement still requires a SketchUp smoke test.
This is an independent implementation; the encrypted original MapSKP core and Google Photorealistic 3D were not recovered.
