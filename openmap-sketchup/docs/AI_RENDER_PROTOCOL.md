# SiteCraft Render AI — implementation contract (0.5.0 beta)

This is new MIT integration code. The supplied encrypted Ruby, vendor JavaScript,
account service, keys and branding are reference material, not executable
product dependencies. Readable prompt TEXT is reused at the user's explicit
request, with original rights/source locations in `reference/nano_render_prompts.json`.
Public MIT watermark code/assets keep their upstream notices. The backend is the user's
Google Flow web session, controlled by a separately paired Chrome MV3 extension.
No bundled model, unlimited Google quota, guaranteed fidelity or render speed is
claimed. Never bypass login, CAPTCHA, quota or payment requirements.

## SketchUp panel

New `ai_render.rb` owns a separate HtmlDialog loading `ui/ai.html`. JavaScript
calls `sketchup.sitecraft_ai(JSON.stringify({id, action, args}))` and receives
`window.SiteCraftAI.receive(id, {ok, data, error, status})`.

Actions: `config` (version, managed, model_context), `api` (method/path/body;
only `/api/ai/`), `capture` ({width: 1280|1600|2048|2560|3200,
size_mode?:'width'|'long_edge',hide_helpers?:bool}; returns asset
metadata plus `data_url` using the active view and normal authenticated worker),
`save_image` ({asset_id}, native save panel), `open_flow` (only fixed Flow URL),
`open_folder`, `open_bridge_folder`, `open_image` ({asset_id}), `open_cleanup`
({asset_id?}), `frame_overlay` ({enabled,aspect,crop?}), `camera_watch` ({enabled};
debounce then `SiteCraftAI.cameraChanged()`), `watch_downloads` ({job_id}),
`stop_downloads`, `downloads_status`, `close`. Download candidates are emitted
as `SiteCraftAI.downloadCandidate(metadata,job_id)` and require UI confirmation.
Camera stamps prevent feedback loops/stale annotations. Frame overlays require
SketchUp 2023+ and never replace the active tool. Show/reply never replaces the map
dialog or expose the map worker transport token to Chrome/HTML. All SketchUp API
calls on the main thread. Capture/export cannot change active model/camera.

UI: one working screen, source/results, prompt, refs (max 4), annotated-image
source/region edit, keep design/camera, presets, aspect crop, before/after slider,
queue/cancel, persistent history drawer, bridge pairing/settings drawer, native
save. Existing SVN-Avo fonts and SiteCraft green branding. No fake success in a
standalone browser, no timers claiming imaginary AI progress.

## Private worker API

Uses existing `X-OpenMap-Local`; local managed mode only in the first version.
Paths are `/api/ai/...`; request JSON can contain image data (bounded 64 MiB).
IDs are 32 lowercase hex; all media validated using Pillow. Responses never
include bridge tokens. Store jobs/assets atomically under a dedicated AI state
folder, with bounded metadata/history; no arbitrary local filesystem paths.

- GET `status`: `{protocol:1, bridge:{port,paired,connected}, jobs:[summary]}`.
- POST `pair` `{}`: `{code,port,expires_in}`; explicit short-lived local pairing.
- POST `unpair` `{}` invalidates bridge credentials and active leases.
- POST `assets` `{data_url,name?,role?}` -> `{id,width,height,mime,sha256}`.
- GET `assets/{id}` -> metadata plus `data_url`.
- GET `assets/{id}/thumbnail` -> <=512px preview, same ID, preview dimensions/
  hash plus original_* metadata; keep thumbnail/full-image caches separate.
- POST `jobs` `{client_request_id,operation,source_id,reference_ids:[],prompt,
  comparison_source_id?,options:{keep_design,keep_camera,aspect?,preset?,
  prompt_is_complete?,manual_handoff?},annotation_notes?}`.
  `operation` is `render`, `edit`, or `upscale`; `upscale` means Flow's visible
  **2K download** action, not promised 2x/4x neural SR. Returns job summary.
  Identical client request IDs are idempotent; different data with the same ID
  is an error. Render/edit require a prompt; upscale can use an empty prompt.
  `comparison_source_id` is the clean cropped image, protected from garbage
  collection independently of the marked Flow upload. Complete prompts pass
  verbatim without bridge additions; manual handoff starts at `waiting_user`.
- GET `jobs` -> `{jobs:[summary]}` (newest first, includes persistent history).
- GET `jobs/{id}` -> job incl `source_id`, `reference_ids`, `prompt`, `options`,
  `result_ids`, `flow` (only validated Flow page URLs/media ID), `message`.
- DELETE `jobs/{id}` cancels; late completion cannot revive a cancelled job.
- POST `jobs/{id}/import` `{asset_id}`: explicit manual result fallback only;
  attaches a validated imported image to a waiting/error job (never cancelled).
- DELETE `history/{id}` removes only AI history/owned media, never user files.
- POST `cleanup` `{asset_id,regions:[normalized rectangles]}` performs bounded
  local diffusion fill; optional `{asset_id,mode:'gemini'}` uses a licensed
  known-marker detector/reverse-alpha helper. Uncertain matches retain original
  bytes; processed assets never overwrite source files. CPU work runs outside
  the queue lock. Cleanup uses its own native dialog/callback.

Summaries have `id,operation,state,created,updated,message,progress,result_ids,
source_id`; states `queued,claimed,running,waiting_user,complete,error,cancelled`.
Only real progress events change progress; UI renders indeterminate if unknown.
No automatic retry of a possibly submitted Google generation.

Python `AIRenderService(config)` exposes `route(method,path,body)`, `close()`,
`status()`; lazy bridge start via status/pair, no external calls on construction.
It also exposes `wait_for_job(job_id,cancel,timeout=600)` for map pipeline use.
Successful wait returns full job incl `result_ids`; `asset_bytes(id)` returns
`(bytes, metadata)`; `create_job(body)` returns the same summary as POST jobs.

## Chrome/Flow bridge

Separate loopback HTTP server on first free port 17865..17872, not the map API.
Bind IPv4 loopback only. Exact extension origin paired, random bearer token,
bounded JSON/body sizes, CORS only that extension; no wildcard website origins.

- GET `/health`: `{name:'SiteCraft AI Bridge',protocol:1,paired}` (no secrets).
- POST `/pair` `{code,client_id}` from `chrome-extension://[a-p]{32}` ->
  `{token,port,protocol:1}`. Code expires and rate limits attempts.
- POST `/jobs/claim` `{client_id}` with bearer -> `{job:null|{id,lease,
  operation,prompt,options,source:{...metadata,data_url},references:[...],flow?}}`.
- POST `/jobs/{id}/progress` `{lease,state,message,progress?}`.
- POST `/jobs/{id}/complete` `{lease,images:[data_url],flow?}`.
- POST `/jobs/{id}/fail` `{lease,message,code?}`.
- POST `/heartbeat` `{client_id}` -> connection status.

Single active job initially; claim/lease is atomic, completion is idempotent.
Reconnect/restart must not duplicate a generation. A stale/ambiguous running
job becomes `waiting_user`, requiring explicit resolution. Browser result URLs
are not trusted for arbitrary network fetch on Python. Only validated image
bytes cross the bridge; no cookies or Google credentials are read/transferred.

Chrome code is new readable JS, no eval/obfuscation/third-party keys or bundles.
User chooses a Flow tab/project and explicitly connects. Background operation
uses that pinned tab and the same page UI; optional `debugger` permission is
requested only for a user-enabled trusted-click mode. CDP targets are confined
to the paired tab/job/lease/semantic and validated viewport coordinates; no
cookie/network-reading command is provided. Auto-reopening a closed tab is
explicit opt-in and never resubmits an ambiguous pending job. Operate the UI:
upload source/refs, fill ProseMirror prompt, click visible generation button,
track new result media/history relative to a baseline, send exact new image
bytes back. 2K action opens selected media then visible Download/2K menu.
Respect sign-in, CAPTCHA/quota errors; report `waiting_user`. Never guess a
result from an unrelated tab or old image. Flow DOM selectors are isolated,
feature-detected, bounded waits and clear manual import fallback if UI changes.

## Map textures

Optional, off by default. Preserve original imagery for tree/geometry analysis.
Flow generation is not geospatial reconstruction. A map texture replacement
must preserve aspect/crop and UVs, pass dimensions/alignment checks, and actually
increase resolution; never silently downsize a 4K/8K map to Flow's 2K output.
Keep original on failure and report the reason. All export formats must consume
the same final validated texture, with provenance recorded.
