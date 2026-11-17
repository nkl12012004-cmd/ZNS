# SiteCraft 0.4.0 — source, font and data provenance

SiteCraft is the product name of this SketchUp integration. It is not an official
MapSKP release. Internal `openmap_sketchup` paths and `OPENMAP_*` names remain
for compatibility; they do not change the rights of any component.

## Newly written integration

The newly written Ruby, Python, JavaScript, CSS, HTML and build tools retain the
project's MIT license, except where a file or directory identifies recovered
original content or an upstream component with separate terms.

## Recovered MapSKP source

The five modules under `server/original_kernel/` were reconstructed locally from
the user-supplied `MapSKP_3D_for_SketchUp.zip`:

- `mode1_osm_dem_builder.py`: scene/data/geometry pipeline, 51 functions.
- `geo_math.py`: coordinates and tile mathematics, 11 functions.
- `facade_texture_gen.py`: procedural facade/roof textures, 22 functions.
- `skp_capi_writer.py`: portable export and optional SDK writer, 14 functions.
- `ocr_google_earth.py`: coordinate parsing/OCR, 6 functions.

These are editable Python text, not opaque code-object loading wrappers. Original
authorship, attribution and rights are retained. No open-source license for these
original modules was found in the supplied archive. They are **excluded from
SiteCraft's MIT license**; source recovery does not grant redistribution rights
or make the entire package open source. See `RECOVERY_NOTICE.md` and the source
file sizes/SHA-256 values in `recovery-manifest.json` in the same directory.

Original readable files under `reference/mapskp_original_readable/` also retain
their original rights. They are included for comparison and are not loaded by
the extension. Original account/payment modules, armor/vault payloads and signing
keys are not bundled. Optional native-policy checks in recovered Python retain
their normal behavior; no substitute signed grants are supplied.

The user explicitly approved publication of these recovered source files in
nkl12012004-cmd/ZNS on 2026-11-17. Their original rights remain unchanged. An
earlier automatic-review rejection concerned a protected original payload, which
is not bundled. The build script only creates local archives.

## SVN-Avo fonts

The four SVN-Avo TTF files were supplied by the user and copied unchanged.
They retain their original rights and are excluded from the MIT license.
The supplied font metadata is not a grant of unrestricted redistribution.
See `extension/openmap_sketchup/ui/fonts/NOTICE.md` and `font-manifest.json` for
the retained metadata, hashes and style mapping. Those notices accompany both
the source package and installer. The interface loads these files locally.

## Runtime and development libraries

The Windows runtime includes CPython (PSF), NumPy (BSD and bundled-library
licenses), Requests and its dependencies (their upstream licenses), Pillow and
its codecs (MIT-CMU and the included upstream licenses), Tesseract (Apache-2.0),
Leptonica (BSD-style), and the English tessdata_fast model (Apache-2.0).
Their license/provenance texts accompany the runtime. `tools/runtime.lock.json`
pins public dependency downloads by version, size and SHA-256.

Microsoft C/C++ runtime components supplied by the official CPython distribution
and Microsoft VCLibs Desktop package retain their upstream terms and notices.
Windows, SketchUp and SketchUp SDK components retain their own platform/SDK
licenses. A real native SKP writer requires Windows and a compatible, separately
available `SketchUpAPI.dll`; portable fallback/export does not prove native SDK
availability. Playwright and Ruby Prism retain their own licenses and are not
bundled as application runtime code.

## External map data

Map data is not covered by SiteCraft's software license:

- OpenStreetMap contributors: ODbL, <https://www.openstreetmap.org/copyright>.
  OpenFreeMap MVT and Overpass are data delivery sources for this OSM pipeline.
- Esri World Imagery and location-dependent providers retain their own terms:
  <https://www.esri.com/en-us/legal/terms/data-attributions>.
- Google imagery/roadmap data retain Google's applicable terms and attribution.
- Terrain tiles: Mapzen/Tilezen and underlying elevation providers;
  <https://github.com/tilezen/joerd/blob/master/docs/attribution.md>.

Exports retain the attribution supplied by the data/geometry pipeline. No fetched
map imagery, OSM dataset or generated geographic model is part of the source
package or installer. Optional remote authentication uses the operator's own
Supabase project; Windows Full opens its local workspace without Supabase.
