Windows x64 Full — fix startup using an obsolete remote server setting.

- A Full upgrade now starts the bundled worker even if earlier versions saved a remote mode or server URL.
- Legacy URLs remain stored, but remote mode requires an explicit new choice in Settings; that choice persists across restarts.
- A remote connection failure automatically opens Settings with a one-click switch to the bundled worker.
- No login, account or Supabase is needed in bundled mode. Python/Pillow/OCR remain included.

Install the new RBZ using Extension Manager, **quit every SketchUp window completely**, then reopen SketchUp and OpenMap. You do not need to delete AppData/configuration.

Native Windows checks cover preferences from an old install and actual Core.start_runtime + Core.http calls with an unreachable legacy server URL, alongside the existing 28 Python tests, OCR, mesh/GLB, restart and parent-exit tests. Playwright checks remote failure and one-click local recovery.

SketchUp Desktop itself is not available in CI; the fix still needs confirmation on the user's SketchUp installation. The proprietary encrypted MapSKP core/Google Photorealistic 3D remains unrecovered.
