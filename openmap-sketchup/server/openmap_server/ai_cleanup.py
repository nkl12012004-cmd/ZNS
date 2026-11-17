"""Explicit local image cleanup: manual fill or supported Gemini mark removal.

A boundary-fitted plane initializes a bounded harmonic/diffusion fill. This
estimates nearby color; it cannot recover hidden detail and blurs complex
textures. Only user-selected pixels are replaced, and the source is immutable.
"""
# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
from io import BytesIO
import math
import re
import warnings

import numpy as np
from PIL import Image, ImageOps

from .net import PublicError

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216
MAX_MASK_PIXELS = 262_144
MAX_ROI_PIXELS = 1_048_576
MAX_TOTAL_ROI_PIXELS = 2_097_152
ITERATIONS = 240


def _regions(value, width, height):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise PublicError('Chọn từ 1 đến 8 vùng chữ nhật để làm sạch.')
    rectangles = []
    normalized = []
    for region in value:
        if not isinstance(region, dict) or set(region) != {'x', 'y', 'width', 'height'}:
            raise PublicError('Vùng làm sạch không hợp lệ.')
        numbers = [region[key] for key in ('x', 'y', 'width', 'height')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 or not math.isfinite(v) for v in numbers):
            raise PublicError('Tọa độ vùng phải là số hữu hạn trong khoảng 0–1.')
        x, y, w, h = numbers
        if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x+w <= 1.000000001 and y+h <= 1.000000001):
            raise PublicError('Vùng chọn phải nằm hoàn toàn trong ảnh.')
        box = (int(math.floor(x*width)), int(math.floor(y*height)),
               min(width, int(math.ceil((x+w)*width))), min(height, int(math.ceil((y+h)*height))))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise PublicError('Vùng chọn quá nhỏ.')
        rectangles.append(box)
        normalized.append(dict(zip(('x', 'y', 'width', 'height'), map(float, numbers))))
    mask = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in rectangles:
        mask[y0:y1, x0:x1] = True
    count = int(mask.sum())
    if count > MAX_MASK_PIXELS or count > width*height*.1:
        raise PublicError('Tổng vùng chọn chỉ được tối đa 10% ảnh và 262.144 điểm ảnh. Chọn vùng nhỏ hơn.')
    return rectangles, normalized, mask, count


def _boxes(rectangles, width, height):
    boxes = [(max(0,a-16), max(0,b-16), min(width,c+16), min(height,d+16)) for a,b,c,d in rectangles]
    changed = True
    while changed:
        changed = False
        merged = []
        while boxes:
            a = boxes.pop(0)
            for index,b in enumerate(boxes):
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[index] = (min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))
                    changed = True
                    break
            else:
                merged.append(a)
        boxes = merged
    if any((c-a)*(d-b) > MAX_ROI_PIXELS for a,b,c,d in boxes) or sum((c-a)*(d-b) for a,b,c,d in boxes) > MAX_TOTAL_ROI_PIXELS:
        raise PublicError('Vùng xử lý quá lớn hoặc quá trải rộng. Chọn từng vùng nhỏ rồi thử lại.')
    return boxes


def _fill(crop, mask):
    pixels = np.asarray(crop, dtype=np.uint8)
    values = pixels.astype(np.float32)
    ys, xs = np.indices(mask.shape, dtype=np.float32)
    known = ~mask
    if int(known.sum()) < 8:
        raise PublicError('Vùng chọn thiếu màu nền xung quanh để ước lượng.')
    # Bounded sampling keeps the least-squares initialization independent of
    # the full image size, including a selection at an image corner.
    known_y, known_x = np.nonzero(known)
    step = max(1, len(known_x)//20_000)
    known_y, known_x = known_y[::step], known_x[::step]
    scale = max(mask.shape)
    design = np.column_stack((known_x/scale, known_y/scale, np.ones(len(known_x))))
    coefficients = np.linalg.lstsq(design, pixels[known_y,known_x].astype(np.float64), rcond=None)[0]
    initial = (xs[...,None]/scale*coefficients[0] + ys[...,None]/scale*coefficients[1] + coefficients[2])
    values[mask] = np.clip(initial[mask], 0, 255)
    for iteration in range(ITERATIONS):
        padded = np.pad(values, ((1,1),(1,1),(0,0)), mode='edge')
        average = (padded[:-2,1:-1] + padded[2:,1:-1] + padded[1:-1,:-2] + padded[1:-1,2:])*.25
        delta = float(np.max(np.abs(values[mask] - average[mask])))
        values[mask] = average[mask]
        if iteration >= 24 and delta < .025:
            break
    result = pixels.copy()
    result[mask] = np.clip(np.rint(values[mask]),0,255).astype(np.uint8)
    return Image.fromarray(result), iteration+1


def cleanup(service, body):
    """Return a new result only when processing applies; never modify source.

    ``mode=gemini`` is an explicit user action independent of cloud generation.
    A refused/absent supported mark returns source metadata with applied=False,
    not a newly uploaded, falsely advertised cleaned image.
    """
    if not isinstance(body, dict) or set(body) - {'asset_id','regions','mode'}:
        raise PublicError('Yêu cầu làm sạch không hợp lệ.')
    mode = body.get('mode','manual')
    if not isinstance(mode,str) or mode not in ('manual','gemini') or mode == 'gemini' and 'regions' in body:
        raise PublicError('Chọn dọn vùng thủ công hoặc nhận diện dấu Gemini; không trộn hai chế độ.')
    identifier = body.get('asset_id')
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
        raise PublicError('Mã ảnh không hợp lệ.')
    raw, source = service.asset_bytes(identifier)
    if not isinstance(raw,bytes) or not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise PublicError('Ảnh phải nhỏ hơn 32 MiB.')
    if mode == 'gemini':
        from .gemini_watermark import remove_gemini
        encoded, info = remove_gemini(raw,mode='auto')
        detail = {**info,'method':'gemini-known-mask-reverse-alpha','original_preserved':True,
                  'warning':'Nhận diện theo mẫu là ước lượng, có thể nhầm hoặc bỏ sót. Kiểm tra trước / sau trước khi lưu.'}
        if not info['applied']:
            return {**source,'id':identifier,'source_id':identifier,'cleanup':detail}
        label = str(source.get('name') or 'Ảnh')[:90] + ' — Gemini cleaned'
        asset = service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(encoded).decode('ascii'),
                                                   'name':label,'role':'result'})
        return {**asset,'source_id':identifier,'cleanup':detail}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG','WEBP') or getattr(image,'n_frames',1) != 1 or image.width*image.height > MAX_IMAGE_PIXELS:
                    raise ValueError('Unsupported image')
                image.load()
                orientation = image.getexif().get(274, 1)
                output = ImageOps.exif_transpose(image).convert('RGBA')
                output.info.clear()
    except (ValueError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise PublicError('Ảnh không hợp lệ hoặc lớn hơn 16.777.216 điểm ảnh.') from None
    width,height = output.size
    rectangles, normalized, mask, count = _regions(body.get('regions'),width,height)
    boxes = _boxes(rectangles,width,height)
    iterations = 0
    for box in boxes:
        left,top,right,bottom = box
        patch, used = _fill(output.crop(box),mask[top:bottom,left:right])
        output.paste(patch,(left,top))
        iterations = max(iterations,used)
    stream = BytesIO(); output.save(stream,format='PNG',compress_level=6)
    encoded = stream.getvalue()
    if len(encoded) > MAX_IMAGE_BYTES:
        raise PublicError('Ảnh PNG sau xử lý vượt 32 MiB. Giảm kích thước ảnh trước khi thử lại; ảnh gốc được giữ nguyên.')
    label = str(source.get('name') or 'Ảnh')[:90] + ' — cleaned'
    asset = service.route('POST','/api/ai/assets',{'data_url':'data:image/png;base64,'+base64.b64encode(encoded).decode('ascii'),
                                              'name':label,'role':'result'})
    return {**asset,'source_id':identifier,'cleanup':{'method':'local-harmonic-diffusion-v1','applied':True,'regions':normalized,
            'source_size':[width,height],'orientation_applied':orientation in (2,3,4,5,6,7,8),
            'masked_pixels':count,'masked_fraction':round(count/(width*height),6),'iterations':iterations,
            'original_preserved':True,'warning':'Vùng đã chọn được ước lượng từ màu lân cận; chi tiết bị che không được khôi phục. Nền phức tạp có thể bị nhòe.'}}
