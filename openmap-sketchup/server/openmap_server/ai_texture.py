"""Opt-in Flow texture enhancement after original-image geometry analysis.

This adapter changes only the terrain material. Geometry, UVs and source imagery
used for tree recognition stay untouched. Alignment checks are conservative image
heuristics, not a claim that a generative service preserves survey accuracy.
"""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
import struct

import numpy as np
from PIL import Image

from .net import PublicError


MAX_EDGE = 8192
MAX_BYTES = 32 * 1024 * 1024


def annotate_glb_texture(data, info):
    """Attach AI provenance without rewriting GLB geometry or image buffers."""
    if not info.get("applied"):
        return data
    if len(data) < 20 or struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("Invalid GLB header")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A or length % 4 or 20 + length > len(data):
        raise ValueError("Invalid GLB JSON")
    document = json.loads(data[20:20 + length])
    document.setdefault("extras", {})["sitecraft_ai_texture"] = info
    metadata = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf8")
    metadata += b" " * (-len(metadata) % 4)
    tail = data[20 + length:]
    total = 20 + len(metadata) + len(tail)
    return struct.pack("<4sIIII", b"glTF", 2, total, len(metadata), 0x4E4F534A) + metadata + tail


def _image(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise PublicError("Ảnh AI quá lớn hoặc không hợp lệ.")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Unsupported image")
            if min(source.size) < 16 or max(source.size) > MAX_EDGE:
                raise ValueError("Unsupported dimensions")
            source.load()
            if source.getexif().get(274, 1) != 1:
                raise PublicError("Ảnh AI có hướng xoay EXIF khác ảnh bản đồ; giữ texture gốc.")
            if "A" in source.getbands() or "transparency" in source.info:
                if source.convert("RGBA").getchannel("A").getextrema() != (255, 255):
                    raise PublicError("Ảnh AI có vùng trong suốt; giữ texture bản đồ gốc.")
            return source.convert("RGB")
    except (ValueError, OSError, Image.DecompressionBombError):
        raise PublicError("Ảnh AI không hợp lệ hoặc vượt giới hạn texture 8192 px.") from None


def _correlation(left, right):
    a = left.astype(np.float64).ravel()
    b = right.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator > 1e-8 else None


def validate_map_result(original, candidate):
    """Reject downsizing, crops, shifted layouts and conspicuous repainting.

    Return normalized PNG/JPEG bytes plus auditable check metrics. Never resize
    or crop a result to make it pass. The original is kept for manual comparison.
    """
    before, after = _image(original), _image(candidate)
    width, height = before.size
    new_width, new_height = after.size
    if new_width <= width or new_height <= height:
        raise PublicError("Flow trả ảnh không lớn hơn ảnh gốc; giữ nguyên texture, không hạ ảnh 4K/8K xuống 2K.")
    if abs(new_width * height - new_height * width) > max(width, height):
        raise PublicError("Ảnh AI đổi tỷ lệ hoặc khung cắt; giữ ảnh gốc để tránh lệch bản đồ.")
    target = (192, max(16, round(192 * height / width))) if width >= height else (max(16, round(192 * width / height)), 192)
    left = np.asarray(before.resize(target, Image.Resampling.LANCZOS).convert("L"), dtype=np.float64)
    right = np.asarray(after.resize(target, Image.Resampling.LANCZOS).convert("L"), dtype=np.float64)
    similarity = _correlation(left, right)
    # Uniform images do not contain enough evidence for geographic alignment.
    if similarity is None or float(left.std()) < 3 or float(right.std()) < 3:
        raise PublicError("Ảnh không có đủ chi tiết để kiểm tra độ khớp; giữ texture gốc.")
    lg = np.stack((np.diff(left, axis=1)[:-1], np.diff(left, axis=0)[:, :-1]), axis=-1)
    rg = np.stack((np.diff(right, axis=1)[:-1], np.diff(right, axis=0)[:, :-1]), axis=-1)
    denominator = float(np.linalg.norm(lg) * np.linalg.norm(rg))
    edge_similarity = float(np.sum(lg * rg) / denominator) if denominator > 1e-8 else 0.0
    if similarity < .94 or edge_similarity < .82:
        raise PublicError("Ảnh AI thay đổi bố cục/chi tiết quá nhiều; giữ texture gốc. Có thể dùng ảnh này riêng trong Render AI.")
    # Detect an offset even where a high global correlation hides a small shift.
    best_shift, best = (0, 0), similarity
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            h, w = left.shape
            a = left[max(0, dy):min(h, h + dy), max(0, dx):min(w, w + dx)]
            b = right[max(0, -dy):min(h, h - dy), max(0, -dx):min(w, w - dx)]
            score = _correlation(a, b)
            if score is not None and score > best:
                best, best_shift = score, (dx, dy)
    if best_shift != (0, 0) and best - similarity > .003:
        raise PublicError("Ảnh AI bị dịch vị trí so với ảnh gốc; không gán vào UV bản đồ.")
    encoded = candidate
    extension = "png" if candidate.startswith(b"\x89PNG\r\n\x1a\n") else "jpg"
    if not candidate.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8")):
        output = BytesIO()
        after.save(output, format="PNG")
        encoded, extension = output.getvalue(), "png"
    if len(encoded) > MAX_BYTES:
        raise PublicError("Texture AI sau giải mã quá lớn; giữ ảnh gốc.")
    return encoded, {"source_size": [width, height], "result_size": [new_width, new_height],
                     "luminance_correlation": round(similarity, 6), "edge_similarity": round(edge_similarity, 6),
                     "alignment_check": "conservative-image-heuristic", "ext": extension}


def enhance_map_textures(scene, params, service, *, cancel=None, progress=lambda *_: None):
    """Run only explicitly selected, eligible map images through Flow's 2K UI."""
    info = {"enabled": bool(params.get("ai_texture", False)), "applied": False, "provider": "Google Flow web", "warnings": []}
    if not info["enabled"]:
        return info
    if cancel and cancel.is_set():
        raise PublicError("Đã hủy tác vụ.")

    def keep(message):
        info["warnings"].append(message)
        scene.setdefault("sitecraft", {})["ai_texture"] = info
        return info

    material = next((item for item in scene.get("materials", []) if item.get("name") == "MapSKP_Satellite_Terrain"), None)
    if not material or not material.get("texture_bytes"):
        return keep("Không có ảnh nền để xử lý AI; giữ nguyên mô hình.")
    original = bytes(material["texture_bytes"])
    info["source_sha256"] = sha256(original).hexdigest()
    try:
        # Most maps are already 4K/8K. Inspect the header before decoding a
        # potentially 64-megapixel image for a Flow action that cannot improve it.
        with Image.open(BytesIO(original)) as header:
            info["source_size"] = list(header.size)
            if max(header.size) >= 2048:
                return keep("Ảnh nền đã từ 2K trở lên. Luồng Flow hiện có chỉ chọn tải 2K; giữ ảnh gốc, không hạ độ phân giải.")
        source = _image(original)
    except (PublicError, ValueError, OSError, Image.DecompressionBombError) as error:
        return keep(str(error) if isinstance(error, PublicError) else "Không kiểm tra được ảnh nền; giữ texture gốc.")
    try:
        bridge = service.status().get("bridge", {})
    except Exception:
        return keep("Không mở được kết nối Flow; giữ texture gốc. Mở Render AI để kiểm tra.")
    if not bridge.get("paired") or not bridge.get("connected"):
        return keep("Chưa kết nối SiteCraft Flow Bridge. Mở Render AI để ghép nối; lần xuất này giữ texture gốc.")
    progress(95, "Đang chờ Flow xử lý ảnh nền; có thể mở Render AI để theo dõi hoặc hủy tác vụ.")
    job_id = None
    try:
        mime = "image/png" if original.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        asset = service.route("POST", "/api/ai/assets", {"data_url": "data:" + mime + ";base64," + base64.b64encode(original).decode("ascii"),
                                                        "name": "Map original", "role": "source"})
        info["source_asset_id"] = asset["id"]
        # Rebuilding identical imagery reuses the existing request rather than
        # silently charging another generation/download action.
        request_id = sha256(b"SiteCraft-map-flow-2k-v1\x00" + original).hexdigest()[:32]
        job = service.create_job({"client_request_id": request_id, "operation": "upscale", "source_id": asset["id"],
                                  "reference_ids": [], "prompt": "", "options": {"keep_design": True, "keep_camera": True, "aspect": "original", "preset": "map"}})
        job_id = job["id"]
        info["job_id"] = job_id
        job = service.wait_for_job(job_id, cancel, timeout=600)
        result_ids = job.get("result_ids", [])
        if job.get("state") != "complete" or not result_ids:
            return keep("Flow chưa trả ảnh hoàn tất; giữ texture gốc. Xem Render AI để kiểm tra.")
        result_id = result_ids[0]
        candidate, _metadata = service.asset_bytes(result_id)
        final, metrics = validate_map_result(original, candidate)
        material["texture_bytes"] = final
        material["ext"] = metrics.pop("ext")
        info.update(applied=True, result_asset_id=result_id, result_sha256=sha256(final).hexdigest(), **metrics)
        scene.setdefault("sitecraft", {})["ai_texture"] = info
        scene.setdefault("origin", {})["sitecraft_ai_texture"] = info
        return info
    except Exception as error:
        if cancel and cancel.is_set():
            if job_id:
                service.route("DELETE", "/api/ai/jobs/" + job_id, {})
            raise PublicError("Đã hủy tác vụ.") from None
        reason = str(error) if isinstance(error, PublicError) else "Không xử lý được ảnh Flow; giữ texture gốc. Xem Render AI để kiểm tra."
        return keep(reason)
