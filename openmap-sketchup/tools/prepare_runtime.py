#!/usr/bin/env python3
"""Build the Windows runtime from pinned public release archives, with no pip."""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import struct
import urllib.request
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"OPENMAPR1"


def safe_path(name):
    p = PurePosixPath(name)
    return bool(name and not p.is_absolute() and not any(part in ("", ".", "..") for part in name.split("/")) and "\\" not in name and ":" not in name)


def prepare(cache, output):
    lock = json.loads((ROOT / "tools/runtime.lock.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    for name, metadata in lock["downloads"].items():
        target = cache / name
        if not target.is_file() or sha256(target.read_bytes()).hexdigest() != metadata["sha256"]:
            temporary = target.with_suffix(target.suffix + ".download")
            request = urllib.request.Request(metadata["url"], headers={"User-Agent": "OpenMap-runtime-build/0.2"})
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as destination:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > metadata["size"]:
                        raise ValueError("Download exceeds pinned size: " + name)
                    destination.write(chunk)
            if sha256(temporary.read_bytes()).hexdigest() != metadata["sha256"]:
                raise ValueError("Dependency checksum mismatch: " + name)
            temporary.replace(target)
        print("Verified", name, flush=True)
    entries = {}

    def put(name, data):
        if not safe_path(name) or name.casefold() in {key.casefold() for key in entries}:
            raise ValueError("Unsafe or duplicate runtime path: " + name)
        entries[name] = data

    for archive_name, prefix in (("python.zip", ""), ("pillow.whl", "Lib/site-packages/")):
        with zipfile.ZipFile(cache / archive_name) as archive:
            assert archive.testzip() is None
            for item in archive.infolist():
                if item.is_dir():
                    continue
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Symlink in dependency archive")
                put(prefix + item.filename, archive.read(item))
    pth = "python" + "".join(lock["python_version"].split(".")[:2]) + "._pth"
    entries[pth] = (pth.replace("._pth", ".zip") + "\n.\nLib/site-packages\n").encode()
    with zipfile.ZipFile(cache / "tesseract-modern.nupkg") as archive:
        for name in ("leptonica-1.85.0.dll", "tesseract55.dll", "tesseract.exe"):
            put("ocr/" + name, archive.read("x64/" + name))
        put("licenses/TesseractOCR.nuspec", archive.read("TesseractOCR.nuspec"))
    put("ocr/tessdata/eng.traineddata", (cache / "eng.traineddata").read_bytes())
    with zipfile.ZipFile(cache / 'vclibs.appx') as archive:
        for name in archive.namelist():
            if name.startswith('msvcp140') and name.endswith('.dll') or name == 'concrt140.dll':
                put(name, archive.read(name))
        put('licenses/Microsoft.VCLibs.AppxManifest.xml', archive.read('AppxManifest.xml'))
    put('licenses/MICROSOFT_VCLIBS_NOTICE.txt', b'Microsoft Visual C++ Runtime support files are supplied unmodified from the official Microsoft.VCLibs x64 Desktop package. Copyright Microsoft Corporation. These platform redistributables are not covered by the OpenMap MIT license. See https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution and the upstream Microsoft software license terms. The official package URL and SHA-256 are in SOURCE_LINKS.json.\n')
    for name in ("TESSERACT_LICENSE.txt", "LEPTONICA_LICENSE.txt", "TESSDATA_LICENSE.txt"):
        put("licenses/" + name, (cache / name).read_bytes())
    put("licenses/SOURCE_LINKS.json", json.dumps(lock, indent=2).encode())
    output.mkdir(parents=True, exist_ok=True)
    catalog = {}
    package = output / "windows-x64.pak"
    with package.open("wb") as stream:
        stream.write(MAGIC + struct.pack("<I", len(entries)))
        for name, data in sorted(entries.items()):
            path = name.encode("utf8")
            compressed = zlib.compress(data, 9)
            digest = sha256(data).digest()
            if len(path) > 240 or len(data) > 80 * 1024 * 1024:
                raise ValueError("Runtime entry too large")
            stream.write(struct.pack("<H", len(path)) + path + struct.pack("<II", len(data), len(compressed)) + digest + compressed)
            catalog[name] = {"size": len(data), "sha256": digest.hex()}
    manifest = {"schema": "openmap.runtime.v1", "platform": "windows-x64", "format": "OPENMAPR1+zlib", "package_sha256": sha256(package.read_bytes()).hexdigest(),
                "package_size": package.stat().st_size, "file_count": len(entries), "unpacked_bytes": sum(map(len, entries.values())),
                "python_version": lock["python_version"], "pillow_version": lock["pillow_version"], "tesseract_version": lock["tesseract_version"],
                "dependencies": lock["downloads"], "files": catalog}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Built", package.name, manifest["package_size"], "bytes;", len(entries), "files", flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/runtime")
    parser.add_argument("--output", type=Path, default=ROOT / "extension/openmap_sketchup/runtime")
    args = parser.parse_args()
    prepare(args.cache, args.output)
