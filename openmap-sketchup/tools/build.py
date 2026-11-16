#!/usr/bin/env python3
"""Reproducible source/RBZ packaging; never include credentials or caches."""
from hashlib import sha256
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
DIST = ROOT / "dist"


def add(archive, name, data):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 16, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def create():
    DIST.mkdir(exist_ok=True)
    rbz = DIST / ("OpenMap_SketchUp_%s.rbz" % VERSION)
    with zipfile.ZipFile(rbz, "w") as archive:
        for path in sorted((ROOT / "extension").rglob("*")):
            if path.is_file():
                add(archive, path.relative_to(ROOT / "extension").as_posix(), path.read_bytes())
        add(archive, "openmap_sketchup/LICENSE", (ROOT / "LICENSE").read_bytes())
        add(archive, "openmap_sketchup/NOTICE.md", (ROOT / "NOTICE.md").read_bytes())
    source = DIST / ("OpenMap_SketchUp_Open_Source_%s.zip" % VERSION)
    excluded = {".git", ".venv", "__pycache__", "node_modules", "dist", "test-artifacts"}
    with zipfile.ZipFile(source, "w") as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if not path.is_file() or excluded.intersection(relative.parts) or path.name == ".env" or path.suffix == ".pyc":
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
