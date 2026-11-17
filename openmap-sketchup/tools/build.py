#!/usr/bin/env python3
"""Reproducible source/RBZ packaging; never include credentials or caches."""
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.1"
DIST = ROOT / "dist"


def add(archive, name, data):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 16, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def create():
    DIST.mkdir(exist_ok=True)
    runtime = ROOT / 'extension/openmap_sketchup/runtime/windows-x64.pak'
    if not runtime.is_file():
        raise SystemExit('Run python tools/prepare_runtime.py before building the Full installer.')
    rbz = DIST / ("OpenMap_SketchUp_Full_%s_Windows_x64.rbz" % VERSION)
    with zipfile.ZipFile(rbz, "w") as archive:
        for path in sorted((ROOT / "extension").rglob("*")):
            if path.is_file():
                add(archive, path.relative_to(ROOT / "extension").as_posix(), path.read_bytes())
        add(archive, "openmap_sketchup/LICENSE", (ROOT / "LICENSE").read_bytes())
        add(archive, "openmap_sketchup/NOTICE.md", (ROOT / "NOTICE.md").read_bytes())
        for path in sorted((ROOT / 'server').rglob('*')):
            rel = path.relative_to(ROOT / 'server')
            if path.is_file() and not {'tests','.venv','__pycache__'}.intersection(rel.parts) and path.name != '.env' and path.suffix != '.pyc':
                add(archive, 'openmap_sketchup/server/' + rel.as_posix(), path.read_bytes())
    source = DIST / ("OpenMap_SketchUp_Open_Source_%s.zip" % VERSION)
    excluded = {".git", ".venv", "__pycache__", "node_modules", "dist", "test-artifacts", ".cache"}
    with zipfile.ZipFile(source, "w") as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if not path.is_file() or excluded.intersection(relative.parts) or path.name == ".env" or path.suffix in (".pyc", ".pak"):
                continue
            add(archive, "OpenMap_SketchUp/" + relative.as_posix(), path.read_bytes())
        add(archive, "OpenMap_SketchUp/install/" + rbz.name, rbz.read_bytes())
    for path in (rbz, source):
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
    checksums = "".join(sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in (rbz, source))
    (DIST / "SHA256SUMS.txt").write_text(checksums)
    print(checksums, end="")
    return rbz, source


if __name__ == "__main__":
    create()
