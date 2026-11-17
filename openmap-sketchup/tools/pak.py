"""Independent bounded reader for the open runtime archive."""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import struct
import zlib


def unpack(package, destination):
    destination = Path(destination)
    manifest = json.loads(Path(package).with_name('manifest.json').read_text())
    data = Path(package).read_bytes()
    if sha256(data).hexdigest() != manifest['package_sha256'] or data[:9] != b'OPENMAPR1':
        raise ValueError('Runtime package checksum or magic failed')
    count, = struct.unpack_from('<I', data, 9)
    if count != manifest['file_count'] or not 1 <= count <= 5000:
        raise ValueError('Runtime entry count failed')
    offset, seen = 13, set()
    for _ in range(count):
        length, = struct.unpack_from('<H', data, offset); offset += 2
        if not 1 <= length <= 240: raise ValueError('Invalid path length')
        name = data[offset:offset+length].decode('utf8'); offset += length
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or name.casefold() in seen:
            raise ValueError('Unsafe runtime path')
        seen.add(name.casefold())
        size, compressed_size = struct.unpack_from('<II', data, offset); offset += 8
        digest = data[offset:offset+32]; offset += 32
        if size > 80 * 1024 * 1024 or compressed_size > 80 * 1024 * 1024:
            raise ValueError('Runtime file exceeds bounds')
        decoder = zlib.decompressobj()
        raw = decoder.decompress(data[offset:offset+compressed_size], size+1); offset += compressed_size
        if not decoder.eof or decoder.unconsumed_tail or len(raw) != size or sha256(raw).digest() != digest:
            raise ValueError('Runtime entry checksum failed: '+name)
        expected = manifest['files'][name]
        if digest.hex() != expected['sha256'] or size != expected['size']:
            raise ValueError('Runtime catalog mismatch')
        target = destination.joinpath(*path.parts); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    if offset != len(data): raise ValueError('Trailing runtime bytes')
    return manifest
