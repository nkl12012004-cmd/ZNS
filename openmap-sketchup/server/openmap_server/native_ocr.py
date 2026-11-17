"""Tesseract C API for the bundled Windows DLLs, without a CLI install."""
import ctypes
import os
from pathlib import Path
import threading

from .net import PublicError

_lock = threading.Lock()
_loaded = None
_dll_directories = []


def directory():
    value = os.environ.get("OPENMAP_OCR_DIR", "")
    return Path(value) if value else None


def available():
    root = directory()
    return bool(os.name == "nt" and root and (root / "tesseract55.dll").is_file() and (root / "tessdata/eng.traineddata").is_file())


def library():
    global _loaded
    with _lock:
        if _loaded:
            return _loaded
        root = directory()
        if not available():
            raise PublicError("Bộ OCR cục bộ chưa sẵn sàng.", 503)
        try:
            if hasattr(os, "add_dll_directory"):
                _dll_directories.append(os.add_dll_directory(str(root)))
            # Load the dependency first. Keep its handle alive with the OCR DLL.
            dependency = ctypes.CDLL(str(root / "leptonica-1.85.0.dll"))
            dll = ctypes.CDLL(str(root / "tesseract55.dll"))
            signatures = {
                "TessVersion": ([], ctypes.c_char_p),
                "TessBaseAPICreate": ([], ctypes.c_void_p),
                "TessBaseAPIInit5": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int], ctypes.c_int),
                "TessBaseAPISetPageSegMode": ([ctypes.c_void_p, ctypes.c_int], None),
                "TessBaseAPISetVariable": ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
                "TessBaseAPISetImage": ([ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], None),
                "TessBaseAPIRecognize": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
                "TessBaseAPIGetUTF8Text": ([ctypes.c_void_p], ctypes.c_void_p),
                "TessDeleteText": ([ctypes.c_void_p], None),
                "TessBaseAPIEnd": ([ctypes.c_void_p], None),
                "TessBaseAPIDelete": ([ctypes.c_void_p], None),
            }
            for name, (args, result) in signatures.items():
                function = getattr(dll, name)
                function.argtypes, function.restype = args, result
            _loaded = dll, dependency
            return _loaded
        except (OSError, AttributeError):
            raise PublicError("Không nạp được thư viện OCR Windows. Kiểm tra Visual C++ Runtime đi kèm SketchUp.", 503) from None


def recognize(image):
    dll, _dependency = library()
    handle = dll.TessBaseAPICreate()
    if not handle:
        raise PublicError("Không khởi tạo được OCR.", 502)
    text_pointer = None
    try:
        root = directory()
        # Read with Python's Unicode-safe file API; Tesseract receives model bytes.
        model = (root / "tessdata/eng.traineddata").read_bytes()
        model_buffer = ctypes.create_string_buffer(model)
        if dll.TessBaseAPIInit5(handle, model_buffer, len(model), b"eng", 3, None, 0, None, None, 0, 0):
            raise PublicError("Không nạp được dữ liệu OCR tiếng Anh.", 502)
        dll.TessBaseAPISetPageSegMode(handle, 6)
        dll.TessBaseAPISetVariable(handle, b"user_defined_dpi", b"300")
        gray = image.convert("L")
        raw = gray.tobytes()
        pixels = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        dll.TessBaseAPISetImage(handle, pixels, gray.width, gray.height, 1, gray.width)
        if dll.TessBaseAPIRecognize(handle, None):
            raise PublicError("OCR không nhận dạng được ảnh.", 502)
        text_pointer = dll.TessBaseAPIGetUTF8Text(handle)
        return ctypes.string_at(text_pointer).decode("utf8", errors="replace")[:20_000] if text_pointer else ""
    finally:
        if text_pointer:
            dll.TessDeleteText(text_pointer)
        dll.TessBaseAPIEnd(handle)
        dll.TessBaseAPIDelete(handle)
