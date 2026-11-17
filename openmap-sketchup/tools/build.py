#!/usr/bin/env python3
"""Build a local SiteCraft mixed-rights candidate; this script never publishes."""
from hashlib import sha256
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.2"
DIST = ROOT / "dist"
ORIGINAL_MODULES = {
    "geo_math", "facade_texture_gen", "mode1_osm_dem_builder",
    "skp_capi_writer", "ocr_google_earth",
}
FORBIDDEN_KERNEL_SUFFIXES = {
    ".marshal", ".pyc", ".pyo", ".vlt", ".vault", ".pak",
    ".dll", ".pyd", ".exe", ".so", ".dylib", ".o", ".obj",
    ".a", ".lib", ".pdb", ".bin",
}
GENERATED_DIRECTORIES = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist",
    "test-artifacts", "test-results", "playwright-report", ".cache",
    ".pytest_cache", ".mypy_cache", "htmlcov", "coverage", "install",
}
GENERATED_SUFFIXES = {
    ".pyc", ".pyo", ".marshal", ".log", ".tmp", ".bak",
    ".swp", ".swo", ".orig", ".rej",
}
PACKAGE_NOTICE = """# SiteCraft 0.4.2 — editable source and runtime

The five recovered MapSKP engine modules are editable Python source, not
bytecode loading wrappers. Their original rights are retained. No open-source
license for the recovered code was found in the supplied archive, so this
package must not be described as entirely MIT or entirely open source.

The new SiteCraft integration code keeps its MIT license. Runtime libraries,
fonts, and external map data retain their separate upstream terms. See NOTICE.md
and server/original_kernel/RECOVERY_NOTICE.md for provenance and limitations;
recovery-manifest.json records each recovered source file's size and SHA-256.

The user explicitly approved publication of the recovered source files in
nkl12012004-cmd/ZNS on 2026-11-17. Original rights remain unchanged. This
script creates local files only. It does not upload, commit, or publish anything.
Original account/payment modules, armor/vault payloads, signing keys, and native
binaries are not included in server/original_kernel. Optional native-policy
checks in the recovered source retain their normal behavior.
"""


def verify_original_modules():
    """Verify the five final text modules before reading any build output."""
    folder = ROOT / "server/original_kernel"
    manifest = json.loads((folder / "recovery-manifest.json").read_text(encoding="utf8"))
    modules = manifest.get("modules", {})
    if not isinstance(modules, dict) or set(modules) != ORIGINAL_MODULES:
        raise ValueError("Recovered-source manifest must list exactly the five approved engine modules")
    expected_names = {name + ".py" for name in ORIGINAL_MODULES}
    actual_names = set()
    native_magic = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
    for path in folder.rglob("*"):
        rel = path.relative_to(folder)
        if path.is_symlink():
            raise ValueError("Symlinks do not belong in the recovered-source folder: " + rel.as_posix())
        if any("armor" in part.lower() or "vault" in part.lower() for part in rel.parts):
            raise ValueError("Armor/vault payload does not belong in the recovered-source folder: " + rel.as_posix())
        if path.name == "__pycache__" or path.suffix.lower() in FORBIDDEN_KERNEL_SUFFIXES:
            raise ValueError("Bytecode/native payload does not belong in the recovered-source folder: " + rel.as_posix())
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            prefix = stream.read(4)
        if prefix.startswith(native_magic):
            raise ValueError("Native binary does not belong in the recovered-source folder: " + rel.as_posix())
        if path.suffix.lower() == ".py":
            actual_names.add(rel.as_posix())
    if actual_names != expected_names:
        raise ValueError("Unexpected or missing recovered Python source file")
    for name, expected in modules.items():
        if not isinstance(expected, dict) or expected.get("path") != name + ".py" or expected.get("format") != "Python source":
            raise ValueError("Recovered module must identify its exact Python source path and format: " + name)
        size, digest = expected.get("bytes"), expected.get("sha256")
        if type(size) is not int or size < 1 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid recovered-source size/checksum: " + name)
        data = (folder / expected["path"]).read_bytes()
        if len(data) != size or sha256(data).hexdigest() != digest:
            raise ValueError("Recovered source checksum mismatch: " + name)
        try:
            text = data.decode("utf8")
        except UnicodeDecodeError as error:
            raise ValueError("Recovered module is not UTF-8 Python source: " + name) from error
        if "\x00" in text:
            raise ValueError("Recovered module contains binary NUL bytes: " + name)
    return manifest


def excluded(relative, *, source=False, server=False):
    """Retain test source and upstream notices; omit generated files and secrets."""
    if GENERATED_DIRECTORIES.intersection(relative.parts):
        return True
    if server and "tests" in relative.parts:
        return True
    if relative.name == ".env" or relative.name.startswith(".env.") and relative.name not in {".env.example", ".env.sample"}:
        return True
    if relative.name == ".coverage" or relative.suffix.lower() in GENERATED_SUFFIXES:
        return True
    if source and relative.suffix.lower() in {".pak", ".rbz", ".zip"}:
        return True
    return False


def add(archive, name, data):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def create():
    verify_original_modules()
    runtime = ROOT / "extension/openmap_sketchup/runtime/windows-x64.pak"
    if not runtime.is_file():
        raise SystemExit("Run python tools/prepare_runtime.py before building the Full installer.")
    DIST.mkdir(exist_ok=True)
    rbz = DIST / ("SiteCraft_Full_%s_Windows_x64.rbz" % VERSION)
    with zipfile.ZipFile(rbz, "w") as archive:
        for path in sorted((ROOT / "extension").rglob("*")):
            rel = path.relative_to(ROOT / "extension")
            if path.is_file() and not excluded(rel):
                add(archive, rel.as_posix(), path.read_bytes())
        add(archive, "openmap_sketchup/LICENSE", (ROOT / "LICENSE").read_bytes())
        add(archive, "openmap_sketchup/NOTICE.md", (ROOT / "NOTICE.md").read_bytes())
        add(archive, "openmap_sketchup/PACKAGE_CONTENTS_NOTICE.md", PACKAGE_NOTICE.encode())
        for path in sorted((ROOT / "server").rglob("*")):
            rel = path.relative_to(ROOT / "server")
            if path.is_file() and not excluded(rel, server=True):
                add(archive, "openmap_sketchup/server/" + rel.as_posix(), path.read_bytes())
    source = DIST / ("SiteCraft_Source_%s.zip" % VERSION)
    with zipfile.ZipFile(source, "w") as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if path.is_file() and not excluded(relative, source=True):
                add(archive, "SiteCraft/" + relative.as_posix(), path.read_bytes())
        add(archive, "SiteCraft/install/" + rbz.name, rbz.read_bytes())
        add(archive, "SiteCraft/PACKAGE_CONTENTS_NOTICE.md", PACKAGE_NOTICE.encode())
    for path in (rbz, source):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive CRC verification failed: " + path.name)
    checksums = "".join(sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in (rbz, source))
    (DIST / "SHA256SUMS.txt").write_text(checksums, encoding="utf8")
    print(checksums, end="")
    return rbz, source


if __name__ == "__main__":
    create()
