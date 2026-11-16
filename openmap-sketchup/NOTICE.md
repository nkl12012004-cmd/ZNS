# Source and data provenance

OpenMap SketchUp 0.1.0 is an independent implementation written for this task.
Its Ruby, Python, JavaScript, CSS, HTML, scripts, and icon are provided under MIT.
The installed extension does not load MapSKP's protected vault, native modules,
signatures, embedded runtime, original branding, or account backend.
It is not an official MapSKP release.

The source archive additionally carries recovered readable original files under
`reference/mapskp_original_readable/`, unchanged, for comparison and further
porting as requested by the user. Their original authorship/copyright is retained.
No open-source license for those original files was found in the supplied ZIP.
They are excluded from this project's MIT license and from the RBZ runtime.

Runtime dependency Pillow is installed separately and retains its own HPND license.
Optional development tools Playwright and Ruby Prism retain their own licenses;
their code is not bundled in the distribution.

Map data is external and is not covered by the software's MIT license:

- OpenStreetMap data: © OpenStreetMap contributors, ODbL; https://www.openstreetmap.org/copyright
- Esri World Imagery: Esri and location-dependent providers; https://www.esri.com/en-us/legal/terms/data-attributions
- Elevation: Mapzen/Tilezen terrain tiles and their underlying open data sources; https://github.com/tilezen/joerd/blob/master/docs/attribution.md
- Authentication: the operator's Supabase project, using its configured Email and Google providers.

Each generated model and export includes data attribution. No external map data
is included in the source package or RBZ.
