import base64
import binascii
from io import BytesIO
import os
import shutil
import subprocess

from PIL import Image

from .net import PublicError
from . import native_ocr


def binary(configured=None):
    return configured or os.environ.get("TESSERACT_BIN") or shutil.which("tesseract")


def available(configured=None):
    return bool(binary(configured) or native_ocr.available())


def recognize(body, configured=None):
    program = binary(configured)
    if native_ocr.available() and not configured and not os.environ.get("TESSERACT_BIN"):
        program = None
    if not program and not native_ocr.available():
        raise PublicError("OCR cần Tesseract trên máy chủ. Bạn vẫn có thể dán tọa độ hoặc link Google Maps.", 503)
    encoded = body.get("image")
    if not isinstance(encoded, str) or len(encoded) > 8_000_000:
        raise PublicError("Ảnh OCR phải nhỏ hơn 6 MB.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as image:
            if max(image.size) > 8192:
                raise PublicError("Ảnh OCR quá lớn; cắt vùng chứa tọa độ trước.")
            image.thumbnail((3000, 3000))
            if not program:
                return {"text": native_ocr.recognize(image)}
            stream = BytesIO(); image.convert("RGB").save(stream, "PNG")
        result = subprocess.run([program, "stdin", "stdout", "-l", "eng", "--psm", "6"], input=stream.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, check=False)
        if result.returncode:
            raise PublicError("Tesseract không đọc được ảnh. Kiểm tra gói ngôn ngữ eng.", 502)
        return {"text": result.stdout.decode("utf-8", errors="replace")[:20_000]}
    except (ValueError, binascii.Error, OSError, Image.DecompressionBombError):
        raise PublicError("Ảnh OCR hoặc đường dẫn Tesseract không hợp lệ.") from None
    except subprocess.TimeoutExpired:
        raise PublicError("OCR quá thời gian; hãy cắt nhỏ ảnh và thử lại.", 504) from None
