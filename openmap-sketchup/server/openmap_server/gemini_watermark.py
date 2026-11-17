"""Conservative removal of supported visible Gemini sparkle overlays only.

MIT port of the white-overlay inverse and mask geometry from AllenK/Kwyshell,
GeminiWatermarkTool commit 7c6a99f2c3df97eb3c430ef87a0c962aea5cb80e.
Copyright (c) 2024 AllenK (Kwyshell); legacy shared-mask notice (c) 2025 Jad.
Residual/silhouette checks informed by long66666's MIT detector (c) 2026,
commit d2c585f3935904ebb019f42184c3184d51a657a4. Full notices, mask hashes and
provenance accompany watermark_assets/. This is a bounded Pillow/NumPy port;
its additional acceptance gates are intentionally stricter than upstream.

A confidence value is a heuristic score, never a calibrated probability or a
promise of perfect restoration. No invisible provenance is targeted. Unknown
positions, opacity, resizing, clipping and difficult backgrounds are refused.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path
import warnings

import numpy as np
from PIL import Image, ImageOps, PngImagePlugin

from .net import PublicError

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 64 * 1024 * 1024
ASSETS = Path(__file__).with_name("watermark_assets")
MASKS = {
    "v1_small": ("bg_48_png.png", "4afc99afe0ef108d67acc45bf4dc5da867ddb793bebc89c9243bb121ce7f0f57"),
    "v1_large": ("bg_96_png.png", "3e26f2233a12a5829acac174d8df1f3db40e07fef04ecdd0e035732154077911"),
    "v2_small": ("bg_b_36_png.png", "a3e7d5ca932e6acf9ff826a4db47d597458480e72089da81a40bd4b52668cd31"),
    "v2_large": ("bg_b_96_png.png", "3911f3b68b3083096326cee24f09868ec87f8d39d248e97057cd14ee838c5552"),
}


@lru_cache(maxsize=4)
def _alpha(variant):
    name, digest = MASKS[variant]
    raw = (ASSETS / name).read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise PublicError("Mẫu logo Gemini không khớp bản đã kiểm tra.", 500)
    with Image.open(BytesIO(raw)) as image:
        values = np.asarray(image.convert("RGB"), dtype=np.float64)
    # Upstream calculate_alpha_map: maximum captured RGB channel / 255.
    result = np.max(values, axis=2) / 255.0
    if not 0 < float(result.max()) < .6:
        raise PublicError("Độ trong suốt mẫu logo không hợp lệ.", 500)
    result.flags.writeable = False
    return result


def _geometry(width, height, version):
    large = width > 1024 and height > 1024
    if version == "v1":
        size, margin = (96, 64) if large else (48, 32)
        return "v1_large" if large else "v1_small", size, margin
    if large:
        return "v2_large", 96, 192
    long_side, short_side = max(width, height), min(width, height)
    if long_side > 1100:
        canonical = min((2752, 2816, 2848), key=lambda value: abs(2 * long_side - value))
    else:
        canonical = 2752 if short_side >= 566 else 2816 if short_side >= 550 else 2848
    scale = long_side / canonical
    margin = int(math.floor(192 * scale + .5))
    ideal = int(math.floor(96 * scale + .5))
    return "v2_small", 36 if ideal <= 40 else ideal, margin


def _template(variant, size):
    alpha = _alpha(variant)
    if alpha.shape == (size, size):
        return alpha
    # Only the known 1376/1408/1424-class half-size V2 geometry is interpolated.
    # BOX is the Pillow area average for the calibrated 96 -> 48 reduction.
    if variant != "v2_small" or size != 48:
        return None
    source = Image.fromarray(_alpha("v2_large").astype(np.float32), mode="F")
    return np.asarray(source.resize((size, size), Image.Resampling.BOX), dtype=np.float64)


def _ncc(left, right):
    a = np.asarray(left, dtype=np.float64).ravel(); a = a - a.mean()
    b = np.asarray(right, dtype=np.float64).ravel(); b = b - b.mean()
    divisor = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / divisor) if divisor > 1e-8 else 0.0


def _gradient(values):
    return np.stack(np.gradient(values, axis=(0, 1)), axis=-1)


def _energy(rgb, weights):
    gradients = _gradient(rgb)
    return float(np.sum(np.sum(gradients * gradients, axis=(2, 3)) * weights) / max(float(weights.sum()), 1e-9))


def _evaluate(image, alpha, x, y):
    size = len(alpha)
    if x < 3 or y < 3 or x + size + 3 > image.width or y + size + 3 > image.height:
        return None
    crop = image.crop((x, y, x + size, y + size))
    if (crop.mode == "RGBA" or "transparency" in crop.info) and crop.convert("RGBA").getextrema()[3] != (255, 255):
        return None
    rgb = np.asarray(crop.convert("RGB"), dtype=np.float64)
    yy, xx = np.mgrid[:size, :size]
    plane = np.stack((np.ones_like(xx), 2 * xx / (size - 1) - 1,
                      2 * yy / (size - 1) - 1), axis=-1)
    # Captured masks contain tiny nonzero background alpha, so fit the scene
    # from an untouched external ring rather than assuming the mask is black.
    padding = 3
    padded = np.asarray(image.crop((x - padding, y - padding, x + size + padding,
                                    y + size + padding)).convert("RGB"), dtype=np.float64)
    py, px = np.mgrid[-padding:size + padding, -padding:size + padding]
    ring_plane = np.stack((np.ones_like(px), 2 * px / (size - 1) - 1,
                           2 * py / (size - 1) - 1), axis=-1)
    ring = (px < 0) | (py < 0) | (px >= size) | (py >= size)
    support = alpha >= .002
    coefficients = np.linalg.lstsq(ring_plane[ring], padded[ring], rcond=None)[0]
    background = plane @ coefficients
    expected = alpha[..., None] * (255.0 - background)
    delta = rgb - background
    denominator = float(np.sum(expected * expected))
    if denominator < 1e-6:
        return None
    opacity = float(np.sum(expected * delta) / denominator)
    brightness = float(np.mean(background[support]))
    amplitude = float(np.sqrt(np.mean(expected[support] ** 2)))
    spatial = _ncc(delta, expected)
    gradient = _ncc(_gradient(delta), _gradient(expected))
    # Known-mask/opacity/signature gates: do not fit an arbitrary strength logo.
    if not (.88 <= opacity <= 1.12 and amplitude >= 5 and brightness < 235 and spatial >= .72 and gradient >= .55):
        return None
    corrected = rgb.copy()
    corrected[support] = (rgb[support] - alpha[support, None] * 255.0) / (1.0 - alpha[support, None])
    negative = float(np.mean((corrected[support] < -2.0) | (corrected[support] > 257.0)))
    residual = abs(_ncc(corrected - background, expected))
    residual_rms = float(np.sqrt(np.mean((corrected - background) ** 2)))
    residual_signature = abs(float(np.sum((corrected - background) * expected) / denominator))
    weights = np.linalg.norm(_gradient(alpha), axis=-1)
    weights[weights < .01] = 0
    before = _energy(rgb, weights)
    after = _energy(corrected, weights)
    survival = after / max(before, 1e-6)
    controls = []
    for ox, oy in ((-size - 8, 0), (0, -size - 8), (-size - 8, -size - 8)):
        cx, cy = x + ox, y + oy
        if cx >= 0 and cy >= 0:
            sample = np.asarray(image.crop((cx, cy, cx + size, cy + size)).convert("RGB"), dtype=np.float64)
            controls.append(_energy(sample, weights))
    control = float(np.median(controls)) if controls else 0.0
    control_ratio = after / max(control, 3.0)
    # Inversion must erase, not manufacture, the calibrated silhouette. Reject
    # negative ghosts, clipping, and residual structure unlike nearby content.
    if (negative > .002 or residual_signature > .12 or (residual > .22 and residual_rms > 2.0)
            or survival > .65 or control_ratio > 2.8):
        return None
    score = max(0.0, min(1.0, .5 * spatial + .3 * gradient + .2 * (1 - survival)))
    return {"confidence": score, "opacity_signature": opacity, "spatial_ncc": spatial,
            "gradient_ncc": gradient, "residual_ncc": residual, "residual_rms": residual_rms,
            "residual_signature": residual_signature, "edge_survival": survival,
            "control_edge_ratio": control_ratio, "negative_fraction": negative,
            "corrected": np.clip(np.rint(corrected), 0, 255).astype(np.uint8), "support": support}


def remove_gemini(raw, mode="auto"):
    """Return ``(bytes, info)``; uncertain/absent marks return the original bytes.

    Supported modes are auto, legacy/v1 and current/v2. Manual modes restrict
    the profile only; they never override the conservative signature gates.
    Only accepted mask pixels are changed. Applied output is a separate PNG.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise PublicError("Ảnh phải là bytes hợp lệ và không quá 32 MiB.")
    modes = {"auto": ("v1", "v2"), "legacy": ("v1",), "v1": ("v1",), "current": ("v2",), "v2": ("v2",)}
    if not isinstance(mode, str) or mode not in modes:
        raise PublicError("Chọn chế độ logo auto, legacy hoặc current.")
    info = {"applied": False, "variant": None, "confidence": 0.0, "confidence_kind": "heuristic_not_probability",
            "reason": "no_supported_signature", "source_sha256": sha256(raw).hexdigest(),
            "algorithm": "known-mask-reverse-alpha", "source_commit": "7c6a99f2c3df97eb3c430ef87a0c962aea5cb80e"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP") or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Unsupported image format")
                if max(source.size) > 16384 or source.width * source.height > MAX_PIXELS:
                    raise ValueError("Image dimensions exceed bound")
                source.verify()
            with Image.open(BytesIO(raw)) as source:
                orientation = source.getexif().get(274, 1)
                image = ImageOps.exif_transpose(source)
                image.load()
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PublicError("Ảnh không hợp lệ hoặc vượt giới hạn 64 triệu điểm ảnh.") from None
    if image.mode not in ("RGB", "RGBA", "L", "P"):
        return raw, {**info, "reason": "unsupported_color_mode"}
    accepted = []
    for version in modes[mode]:
        variant, size, margin = _geometry(image.width, image.height, version)
        alpha = _template(variant, size)
        if alpha is None:
            continue
        expected_x, expected_y = image.width - margin - size, image.height - margin - size
        radius = 3 if variant == "v2_small" else 0
        # Test the exact geometry first; only a narrow small-V2 rounding search
        # is permitted. There is no broad scene/logo search.
        offsets = [(0, 0)] + [(dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1) if dx or dy]
        found = []
        for dx, dy in offsets:
            x, y = expected_x + dx, expected_y + dy
            result = _evaluate(image, alpha, x, y)
            if result:
                found.append((result["confidence"], variant, x, y, result))
                if dx == 0 and dy == 0:
                    break
        if found:
            accepted.append(max(found, key=lambda item: item[0]))
    if len(accepted) != 1:
        return raw, {**info, "reason": "ambiguous_profiles" if accepted else "no_supported_signature"}
    confidence, variant, x, y, result = accepted[0]
    size = result["corrected"].shape[0]
    output = image.copy() if image.mode in ("RGB", "RGBA") else image.convert("RGBA" if "transparency" in image.info else "RGB")
    original_patch = np.asarray(output.crop((x, y, x + size, y + size))).copy()
    original_patch[..., :3][result["support"]] = result["corrected"][result["support"]]
    output.paste(Image.fromarray(original_patch), (x, y))
    stream = BytesIO()
    pnginfo = PngImagePlugin.PngInfo()
    for key, value in image.info.items():
        if isinstance(key, str) and isinstance(value, str):
            pnginfo.add_text(key, value)
    save_options = {"format": "PNG", "pnginfo": pnginfo}
    if image.getexif():
        save_options["exif"] = image.getexif().tobytes()
    if image.info.get("icc_profile"):
        save_options["icc_profile"] = image.info["icc_profile"]
    output.save(stream, **save_options)
    encoded = stream.getvalue()
    if len(encoded) > MAX_BYTES:
        return raw, {**info, "reason": "output_exceeds_bound"}
    metrics = {key: round(float(value), 6) for key, value in result.items() if key not in ("corrected", "support")}
    return encoded, {**info, **metrics, "applied": True, "variant": variant, "reason": "supported_signature",
                     "region": {"x": x, "y": y, "width": size, "height": size},
                     "orientation_applied": orientation in (2, 3, 4, 5, 6, 7, 8),
                     "mime": "image/png", "width": output.width, "height": output.height,
                     "result_sha256": sha256(encoded).hexdigest()}
