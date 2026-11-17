Windows x64 Full — original-style map workflow, place search and OSM recovery.

- One sidebar contains controls, progress, export and tile linking; the map has room beside it. No account/Supabase setup is required.
- Restores the old “Vệ tinh sạch” name and Esri source, original layer order, Hanoi/380m/4K/grid64 defaults, and visible main-road/alley toggles.
- Visible satellite selection now controls exported imagery too. OSM remains preview-only, with the output imagery choice stated separately.
- Place autocomplete, Arrow/Enter/Escape selection and immediate jump on submit; ArcGIS/Photon/Nominatim submit fallback and cached Photon/ArcGIS suggestions.
- Esri no-data placeholder detection and bounded lower-zoom handling; report the actual source zoom and avoid claiming extra detail from a 4K file.
- Coordinates/Google Maps links, search-bar preset/OCR shortcuts and bounded allowlisted shortlink redirects.
- Small regions use fast OSM XML first, then alternate hosts and bounded Overpass fallbacks. If all OSM providers fail, preserve imagery/terrain with explicit missing-layer flags; do not auto-import incomplete results.
- Neighbor controls use the most recent imported base tile, with inline anchor controls. Hill patches do not replace that reference.

Install the RBZ in Extension Manager, quit all SketchUp windows completely, then reopen OpenMap. No separate Python/pip/server setup is required.

Validated with 62 Python unit/integration tests, Playwright UI fixtures and native Windows packaged-runtime checks. Live Hanoi and HCMC imagery/DEM/OSM builds and Vietnamese geocoding were also exercised; exact measurements are in docs/VALIDATION.md. SketchUp Desktop itself remains unavailable in CI, so actual model import/Undo/placement must still be confirmed there.

The original readable UI/network behavior was used for the transfer. The old geocoder/OSM/geometry core is encrypted and unavailable as source; these backend paths are independent implementations, not recovered proprietary source. The Google Photorealistic 3D mesh remains unavailable.
