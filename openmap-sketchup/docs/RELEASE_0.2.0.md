Windows x64 Full bundle, with the runtime included.

- CPython 3.14.10, Pillow 12.3.0, Tesseract 5.5.1, Leptonica 1.85.0 and English OCR model.
- The worker installs to the user's LocalAppData cache and starts automatically from SketchUp.
- One private loopback worker/port per SketchUp instance; stops on close or parent-process exit.
- Configure Supabase Project URL/public key inside the plugin. No Python/pip/terminal setup is required for the bundled Windows mode.
- Email/Google login, 2D/3D maps, DEM and hill patches, OSM roads/buildings/water/trees, OBJ/GLB/SKP and metadata linking.
- No coins, credits, subscriptions or per-export accounting.

Install the **Full Windows x64 RBZ**, restart SketchUp, open OpenMap and enter your own Supabase public configuration.
Google login also requires the Google provider and the loopback redirect allowlist in that Supabase project.

This release is published only after the GitHub Windows job passes packaged-runtime,
OCR, HTTP authentication/configuration, Ruby startup/restart and parent-exit checks.
SketchUp Desktop itself is not installed on the CI runner: actual model import,
textures, Undo and placement callbacks still require a smoke test in SketchUp.

The runtime is an independent open-source implementation. Recovered original MapSKP
reference files keep their original rights; the encrypted proprietary core was not recovered.
