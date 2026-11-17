"""Persistent local AI queue and explicitly paired Chrome/Flow transport.

This service never contacts Google or reads browser credentials. Images cross
its loopback bridge as validated bytes; generation is the paired user's visible
Flow session. Ambiguous submissions are never automatically retried.
"""
from __future__ import annotations

import base64
from collections import OrderedDict, deque
from copy import deepcopy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import urllib.parse
import warnings

from PIL import Image, ImageOps

from .net import PublicError

MAX_BODY = 64 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
MAX_PIXELS = 64 * 1024 * 1024
MAX_ASSETS = 256
MAX_STORAGE = 512 * 1024 * 1024
MAX_HISTORY = 100
MAX_REQUESTS = 4096
MAX_CLAIM_BYTES = 64 * 1024 * 1024
THUMBNAIL_EDGE = 512
THUMBNAIL_CACHE_BYTES = 8 * 1024 * 1024
PORTS = range(17865, 17873)
ID = re.compile(r"[a-f0-9]{32}\Z")
EXTENSION = re.compile(r"chrome-extension://[a-p]{32}\Z")
CLIENT = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
ACTIVE = {"claimed", "running", "waiting_user"}
TERMINAL = {"complete", "error", "cancelled"}
SUMMARY = ("id", "operation", "state", "created", "updated", "message", "progress", "result_ids", "source_id", "comparison_source_id")
FORMATS = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}


def _id(value, label="ID"):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise PublicError(label + " không hợp lệ.")
    return value


def _text(value, maximum, label, empty=True):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise PublicError(label + " không hợp lệ.")
    value = value.strip()
    if not empty and not value:
        raise PublicError("Nhập " + label.lower() + ".")
    return value


def _json(raw):
    def invalid(_):
        raise ValueError("Non-finite JSON number")
    result = json.loads(raw, parse_constant=invalid)
    if not isinstance(result, dict):
        raise PublicError("Yêu cầu phải là JSON object.")
    return result


def _flow(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"page_url", "url", "media_id", "project_id"}:
        raise PublicError("Thông tin trang Flow không hợp lệ.")
    result = {}
    page = value.get("page_url", value.get("url"))
    if page is not None:
        page = _text(page, 2048, "URL Flow", False)
        parsed = urllib.parse.urlsplit(page)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None:
            raise PublicError("Chỉ dùng URL trang Google Flow.")
        path = parsed.path or "/"
        segments = path.split("/")
        if any(part in (".", "..") for part in segments) or "%" in path:
            raise PublicError("Đường dẫn trang Flow không hợp lệ.")
        allowed = (parsed.hostname == "labs.google" and re.fullmatch(r"/fx/(?:[a-z]{2}(?:-[A-Za-z]{2})?/)?tools/flow(?:/[A-Za-z0-9_.~-]+)*/?", path))
        allowed = allowed or (parsed.hostname == "flow.google.com" and re.fullmatch(r"/(?:project/[A-Za-z0-9_-]+(?:/edit/[A-Za-z0-9_-]+)?/?)?", path))
        if not allowed:
            raise PublicError("Chỉ dùng URL trang Google Flow.")
        # Never retain URL query/fragment parameters that might carry credentials.
        result["page_url"] = urllib.parse.urlunsplit(("https", parsed.hostname, path, "", ""))
    for key in ("media_id", "project_id"):
        if key in value:
            item = value[key]
            if not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", item):
                raise PublicError("Mã nội dung Flow không hợp lệ.")
            result[key] = item
    return result


class AIRenderService:
    def __init__(self, config):
        self.config = config
        configured = config.get("OPENMAP_AI_DIR")
        if configured:
            self.root = Path(configured).expanduser().resolve()
        elif config.get("OPENMAP_CONFIG_FILE"):
            self.root = Path(config["OPENMAP_CONFIG_FILE"]).expanduser().resolve().parent / "ai"
        elif config.get("OPENMAP_WORK_DIR"):
            self.root = Path(config["OPENMAP_WORK_DIR"]).expanduser().resolve() / "ai"
        else:
            self.root = Path.home() / ".sitecraft" / "ai"
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self._state = None
        self._file_lock = None
        self._server = None
        self._server_thread = None
        self._maintenance_thread = None
        self._stop = threading.Event()
        self._closed = False
        self._pending = None
        self._pair_attempts = deque()
        self._last_seen = 0
        self._thumbnails = OrderedDict()
        self._thumbnail_bytes = 0
        self._sensitive = {str(config.get("OPENMAP_LOCAL_TOKEN") or "")}
        self._stale_seconds = max(1, float(config.get("OPENMAP_AI_STALE_SECONDS", 90)))

    def _enabled(self):
        if not self.config.get("OPENMAP_LOCAL_TOKEN") or self.config.get("OPENMAP_AUTH_MODE", "local") != "local":
            raise PublicError("Render AI chỉ dùng trong bộ xử lý cục bộ được quản lý.", 403)
        if self._closed:
            raise PublicError("Bộ xử lý Render AI đã đóng.", 503)

    def _ensure(self):
        self._enabled()
        with self.lock:
            if self._state is not None:
                return
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.root / "assets").mkdir(exist_ok=True, mode=0o700)
            handle = open(self.root / "state.lock", "a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    if not handle.read(1):
                        handle.write(b"0"); handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise PublicError("Lịch sử Render AI đang được một bộ xử lý khác sử dụng.", 409) from None
            self._file_lock = handle
            state_file = self.root / "state.json"
            try:
                if state_file.exists():
                    if state_file.is_symlink() or state_file.stat().st_size > 16 * 1024 * 1024:
                        raise ValueError("Invalid AI state file")
                    state = _json(state_file.read_bytes())
                    if state.get("schema") != 1 or any(not isinstance(state.get(key), dict) for key in ("assets", "jobs", "requests", "pairing")):
                        raise ValueError("Invalid AI state schema")
                    if len(state["assets"]) > MAX_ASSETS or len(state["jobs"]) > MAX_HISTORY or len(state["requests"]) > MAX_REQUESTS:
                        raise ValueError("AI state exceeds configured bounds")
                    for key in (*state["assets"], *state["jobs"], *state["requests"]):
                        _id(key)
                else:
                    state = {"schema": 1, "assets": {}, "jobs": {}, "requests": {}, "pairing": {}}
                self._state = state
                for job in state["jobs"].values():
                    if job.get("state") in ("claimed", "running"):
                        self._waiting(job, "Phiên trước đã dừng sau khi nhận tác vụ. Kiểm tra Flow rồi nhập ảnh kết quả hoặc hủy; không tự tạo lại.")
                self._persist()
            except Exception as exc:
                self._state = None
                handle.close(); self._file_lock = None
                raise PublicError("Không đọc được lịch sử Render AI. Giữ nguyên dữ liệu để kiểm tra.", 500) from exc
            self._maintenance_thread = threading.Thread(target=self._maintenance, daemon=True, name="sitecraft-ai-state")
            self._maintenance_thread.start()

    def _persist(self):
        raw = json.dumps(self._state, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if len(raw) > 16 * 1024 * 1024:
            raise PublicError("Lịch sử Render AI đã đạt giới hạn lưu trữ.", 507)
        self._atomic(self.root / "state.json", raw)
        self.condition.notify_all()

    @staticmethod
    def _atomic(target, raw):
        temporary = target.with_name(target.name + "." + secrets.token_hex(8) + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _message(self, value, maximum=2000, preserve_whitespace=False):
        original = value
        value = _text(value, maximum, "Thông báo")
        if preserve_whitespace:
            value = original
        for token in self._sensitive:
            if token:
                value = value.replace(token, "[private]")
        return value

    def _summary(self, job):
        return deepcopy({key: job.get(key) for key in SUMMARY})

    def _job_public(self, job):
        return deepcopy({key: value for key, value in job.items() if not key.startswith("_") and key != "client_request_id"})

    def _job(self, job_id):
        _id(job_id, "Mã tác vụ")
        job = self._state["jobs"].get(job_id)
        if job is None:
            raise PublicError("Không tìm thấy tác vụ AI.", 404)
        return job

    def _waiting(self, job, message):
        job.update(state="waiting_user", message=message, updated=time.time())
        for key in ("_lease", "_client", "_touched"):
            job.pop(key, None)

    def _stale(self):
        now = time.time()
        changed = False
        for job in self._state["jobs"].values():
            if job["state"] in ("claimed", "running") and now - job.get("_touched", 0) > self._stale_seconds:
                self._waiting(job, "Mất kết nối với Flow. Kiểm tra tác vụ đã gửi rồi nhập kết quả hoặc hủy; không tự thử lại.")
                changed = True
        if changed:
            self._persist()

    def _maintenance(self):
        while not self._stop.wait(1):
            with self.lock:
                if self._closed or self._state is None:
                    return
                try:
                    self._stale()
                except OSError:
                    # A failed disk write must never requeue a submitted task.
                    pass

    def _asset(self, asset_id):
        _id(asset_id, "Mã ảnh")
        asset = self._state["assets"].get(asset_id)
        if asset is None:
            raise PublicError("Không tìm thấy ảnh AI.", 404)
        return asset

    def _asset_path(self, asset):
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(asset.get("mime"))
        if not suffix:
            raise PublicError("Định dạng ảnh đã lưu không hợp lệ.", 500)
        return self.root / "assets" / (_id(asset["id"]) + "." + suffix)

    def _asset_meta(self, asset):
        return deepcopy({key: value for key, value in asset.items() if not key.startswith("_")})

    def asset_bytes(self, asset_id):
        self._ensure()
        with self.lock:
            self._enabled()
            asset = self._asset(asset_id)
            path = self._asset_path(asset)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE:
                raise PublicError("Không đọc được ảnh AI đã lưu.", 404)
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != asset["sha256"]:
                raise PublicError("Ảnh AI đã lưu không còn khớp dữ liệu gốc.", 500)
            return raw, self._asset_meta(asset)

    def _asset_data(self, asset_id):
        raw, meta = self.asset_bytes(asset_id)
        return {**meta, "data_url": "data:" + meta["mime"] + ";base64," + base64.b64encode(raw).decode("ascii")}

    def _drop_thumbnail(self, asset_id):
        entry = self._thumbnails.pop(asset_id, None)
        if entry:
            self._thumbnail_bytes -= entry["weight"]

    def _asset_thumbnail(self, asset_id):
        """Small gallery preview; the persistent source asset is never changed."""
        asset = self._asset(asset_id)
        meta = self._asset_meta(asset)
        path = self._asset_path(asset)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE:
            raise PublicError("Không đọc được ảnh AI đã lưu.", 404)
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        entry = self._thumbnails.get(asset_id)
        if entry and (entry["source_sha256"] != meta["sha256"] or entry["signature"] != signature):
            self._drop_thumbnail(asset_id)
            entry = None
        if entry:
            self._thumbnails.move_to_end(asset_id)
        else:
            raw, meta = self.asset_bytes(asset_id)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(raw)) as image:
                        if (image.format not in FORMATS or getattr(image, "n_frames", 1) != 1
                                or image.size != (meta["width"], meta["height"])
                                or max(image.size) > 16384 or image.width * image.height > MAX_PIXELS):
                            raise ValueError("Invalid thumbnail source")
                        # Apply display orientation without retaining any EXIF
                        # metadata in the small image sent to the gallery.
                        preview = ImageOps.exif_transpose(image)
                        transparent = preview.mode in ("RGBA", "LA") or "transparency" in preview.info
                        preview = preview.convert("RGBA" if transparent else "RGB")
                        preview.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
                        output = BytesIO()
                        if transparent:
                            preview.save(output, format="PNG", optimize=True)
                            mime = "image/png"
                        else:
                            preview.save(output, format="JPEG", quality=82, optimize=True)
                            mime = "image/jpeg"
                        thumbnail = output.getvalue()
                        details = {"width": preview.width, "height": preview.height, "mime": mime,
                                   "sha256": sha256(thumbnail).hexdigest()}
            except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise PublicError("Không tạo được ảnh thu nhỏ từ dữ liệu đã lưu.", 500) from None
            weight = len(thumbnail) + len(json.dumps(details).encode()) + len(asset_id) + len(meta["sha256"])
            entry = {"bytes": thumbnail, "details": details, "signature": signature,
                     "source_sha256": meta["sha256"], "weight": weight}
            while self._thumbnails and self._thumbnail_bytes + weight > THUMBNAIL_CACHE_BYTES:
                self._drop_thumbnail(next(iter(self._thumbnails)))
            if weight <= THUMBNAIL_CACHE_BYTES:
                self._thumbnails[asset_id] = entry
                self._thumbnail_bytes += weight
        details = entry["details"]
        return {**meta, "original_width": meta["width"], "original_height": meta["height"],
                "original_mime": meta["mime"], "original_sha256": meta["sha256"], "thumbnail": True,
                **details, "data_url": "data:" + details["mime"] + ";base64," + base64.b64encode(entry["bytes"]).decode("ascii")}

    def _used_assets(self):
        return {asset_id for job in self._state["jobs"].values() for asset_id in
                [job["source_id"], job.get("comparison_source_id", job["source_id"]),
                 *job.get("reference_ids", []), *job.get("result_ids", [])]}

    def _delete_asset(self, asset_id):
        asset = self._state["assets"].pop(asset_id, None)
        self._drop_thumbnail(asset_id)
        if asset:
            self._asset_path(asset).unlink(missing_ok=True)

    def _media_room(self, size, protected=()):
        used = self._used_assets() | set(protected)
        candidates = sorted((asset for asset in self._state["assets"].values() if asset["id"] not in used), key=lambda a: a["created"])
        def total():
            return sum(a["_bytes"] for a in self._state["assets"].values())
        while candidates and (len(self._state["assets"]) >= MAX_ASSETS or total() + size > MAX_STORAGE):
            self._delete_asset(candidates.pop(0)["id"])
        if len(self._state["assets"]) >= MAX_ASSETS or total() + size > MAX_STORAGE:
            raise PublicError("Kho ảnh Render AI đã đầy. Xóa bớt lịch sử không còn dùng.", 413)

    @staticmethod
    def _validate_image(data_url):
        if not isinstance(data_url, str) or len(data_url) > MAX_BODY or not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+", data_url):
            raise PublicError("Chỉ nhận ảnh PNG, JPEG hoặc WebP dưới dạng data URL.")
        encoded = data_url.split(",", 1)[1]
        if len(encoded) > (MAX_IMAGE + 2) // 3 * 4 + 2:
            raise PublicError("Ảnh AI quá lớn.", 413)
        try:
            raw = base64.b64decode(encoded.replace("\r", "").replace("\n", ""), validate=True)
            if len(raw) > MAX_IMAGE:
                raise PublicError("Ảnh AI quá lớn.", 413)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    fmt, width, height = image.format, image.width, image.height
                    if fmt not in FORMATS or getattr(image, "n_frames", 1) != 1 or width < 1 or height < 1 or width > 16384 or height > 16384 or width * height > MAX_PIXELS:
                        raise ValueError("Unsupported image dimensions or format")
                    image.verify()
                with Image.open(BytesIO(raw)) as image:
                    image.load()
            mime, _ = FORMATS[fmt]
            if not data_url.startswith("data:" + mime + ";base64,"):
                raise ValueError("Image MIME mismatch")
        except PublicError:
            raise
        except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise PublicError("Ảnh không hợp lệ hoặc vượt giới hạn kích thước.") from None
        return raw, mime, width, height

    def _upload(self, body, role=None, protected=(), validated=None):
        raw, mime, width, height = validated or self._validate_image(body.get("data_url"))
        role = role or body.get("role", "source")
        if role not in ("source", "reference", "annotation", "manual_result", "result"):
            raise PublicError("Vai trò ảnh không hợp lệ.")
        name = self._message(body.get("name", "Ảnh"), 120)
        digest = sha256(raw).hexdigest()
        for asset in self._state["assets"].values():
            if asset["sha256"] == digest and asset["role"] == role:
                return self._asset_meta(asset)
        self._media_room(len(raw), protected)
        asset_id = secrets.token_hex(16)
        asset = {"id": asset_id, "width": width, "height": height, "mime": mime, "sha256": digest,
                 "name": name, "role": role, "created": time.time(), "_bytes": len(raw)}
        self._atomic(self._asset_path(asset), raw)
        self._state["assets"][asset_id] = asset
        self._persist()
        return self._asset_meta(asset)

    def _forget(self, job_id, protected=()):
        job = self._state["jobs"].pop(job_id)
        possible = {job["source_id"], job.get("comparison_source_id", job["source_id"]),
                    *job.get("reference_ids", []), *job.get("result_ids", [])}
        used = self._used_assets() | set(protected)
        for asset_id in possible - used:
            self._delete_asset(asset_id)

    def create_job(self, body):
        self._ensure()
        if not isinstance(body, dict):
            raise PublicError("Yêu cầu phải là JSON object.")
        request_id = _id(body.get("client_request_id"), "Mã yêu cầu")
        operation = body.get("operation")
        if operation not in ("render", "edit", "upscale"):
            raise PublicError("Chọn thao tác render, edit hoặc upscale.")
        source = _id(body.get("source_id"), "Mã ảnh nguồn")
        comparison = _id(body.get("comparison_source_id", source), "Mã ảnh so sánh")
        refs = body.get("reference_ids", [])
        if not isinstance(refs, list) or len(refs) > 4:
            raise PublicError("Chỉ dùng tối đa 4 ảnh tham chiếu.")
        refs = [_id(value, "Mã ảnh tham chiếu") for value in refs]
        prompt = self._message(body.get("prompt", ""), 8000)
        if operation != "upscale" and not prompt:
            raise PublicError("Nhập mô tả để tạo hoặc sửa ảnh.")
        options = body.get("options", {})
        if not isinstance(options, dict) or set(options) - {"keep_design", "keep_camera", "aspect", "preset", "prompt_is_complete", "manual_handoff"}:
            raise PublicError("Tùy chọn Render AI không hợp lệ.")
        options = deepcopy(options)
        for key in ("keep_design", "keep_camera", "prompt_is_complete", "manual_handoff"):
            if key in options and not isinstance(options[key], bool):
                raise PublicError("Tùy chọn giữ thiết kế/góc máy phải là boolean.")
        if options.get("prompt_is_complete", False):
            # New clients preview the final complete prompt. Preserve it as
            # supplied; the browser must not append hidden guards/notes again.
            prompt = self._message(body.get("prompt", ""), 8000, preserve_whitespace=True)
        if "aspect" in options and options["aspect"] != "original":
            aspect = options["aspect"]
            if not isinstance(aspect, str) or not re.fullmatch(r"[1-9][0-9]{0,3}:[1-9][0-9]{0,3}", aspect):
                raise PublicError("Tỷ lệ ảnh không hợp lệ.")
            width, height = (int(value) for value in aspect.split(":"))
            if not .05 <= width / height <= 20:
                raise PublicError("Tỷ lệ ảnh phải nằm trong khoảng 1:20 đến 20:1.")
        if "preset" in options:
            options["preset"] = self._message(options["preset"], 120)
        notes = self._message(body.get("annotation_notes", ""), 4000)
        normalized = {"operation": operation, "source_id": source, "comparison_source_id": comparison, "reference_ids": refs,
                      "prompt": prompt, "options": options, "annotation_notes": notes}
        fingerprint = sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        with self.lock:
            self._enabled()
            old = self._state["requests"].get(request_id)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise PublicError("Mã yêu cầu đã dùng với nội dung khác.", 409)
                if old["job_id"] not in self._state["jobs"]:
                    raise PublicError("Yêu cầu này đã có lịch sử bị xóa; dùng mã mới để tạo tác vụ mới.", 409)
                return self._summary(self._state["jobs"][old["job_id"]])
            self._asset(source)
            self._asset(comparison)
            for asset_id in refs:
                self._asset(asset_id)
            # Five individually valid images can exceed the browser's bounded
            # response reader. Reject before persisting/claiming such a job.
            projected = {"job": {"id": "0" * 32, "lease": "0" * 43,
                **normalized, "source": self._asset_meta(self._asset(source)),
                "references": [self._asset_meta(self._asset(value)) for value in refs], "flow": {}}}
            encoded_images = 0
            for item in [projected["job"]["source"], *projected["job"]["references"]]:
                asset = self._asset(item["id"])
                item["data_url"] = "data:" + item["mime"] + ";base64,"
                encoded_images += 4 * ((asset["_bytes"] + 2) // 3)
            if len(json.dumps(projected, ensure_ascii=False).encode()) + encoded_images + 1024 > MAX_CLAIM_BYTES:
                raise PublicError("Tổng ảnh nguồn và tham chiếu quá lớn cho cầu nối. Giảm kích thước hoặc số ảnh.", 413)
            self._stale()
            if sum(job["state"] not in TERMINAL for job in self._state["jobs"].values()) >= 8:
                raise PublicError("Hàng đợi AI đã có 8 tác vụ. Hoàn tất hoặc hủy tác vụ cũ.", 429)
            if len(self._state["requests"]) >= MAX_REQUESTS:
                raise PublicError("Chỉ mục yêu cầu AI đã đầy; không tự xóa mã để tránh tạo trùng.", 507)
            while len(self._state["jobs"]) >= MAX_HISTORY:
                completed = [job for job in self._state["jobs"].values() if job["state"] in TERMINAL]
                if not completed:
                    raise PublicError("Lịch sử AI đã đầy.", 507)
                self._forget(min(completed, key=lambda j: j["created"])["id"], protected=[source, comparison, *refs])
            now = time.time(); job_id = secrets.token_hex(16)
            job = {"id": job_id, **normalized, "state": "queued", "created": now, "updated": now,
                   "message": "Đang đợi Chrome/Flow đã ghép nối.", "progress": None, "result_ids": [], "flow": {},
                   "client_request_id": request_id}
            if options.get("manual_handoff", False):
                job.update(state="waiting_user", message="Đang chờ bạn tạo ảnh trên Flow và nhập kết quả.")
            if operation == "upscale":
                provenance = self._state["assets"][source].get("flow", {})
                if provenance:
                    job["flow"] = deepcopy(provenance)
            self._state["jobs"][job_id] = job
            self._state["requests"][request_id] = {"job_id": job_id, "fingerprint": fingerprint}
            self._persist()
            return self._summary(job)

    def status(self):
        self._ensure()
        with self.lock:
            self._enabled()
            self._start_bridge()
            self._stale()
            paired = bool(self._state["pairing"].get("token_hash"))
            return {"protocol": 1, "bridge": {"port": self._server.server_port, "paired": paired,
                    "connected": paired and time.time() - self._last_seen < self._stale_seconds},
                    "jobs": [self._summary(job) for job in sorted(self._state["jobs"].values(), key=lambda j: j["created"], reverse=True)]}

    def route(self, method, path, body):
        self._ensure()
        if not isinstance(body, dict):
            raise PublicError("Yêu cầu phải là JSON object.")
        if method == "GET" and path == "/api/ai/status":
            return self.status()
        if method == "POST" and path == "/api/ai/cleanup":
            # Image processing can take seconds. Its asset reads/writes acquire
            # their own locks; do not block Flow lease checks and queue status.
            with self.lock:
                self._enabled()
                self._stale()
            from .ai_cleanup import cleanup
            return cleanup(self, body)
        with self.lock:
            self._enabled()
            self._stale()
            if method == "POST" and path == "/api/ai/pair":
                self._start_bridge()
                self._pending = {"code": "%06d" % secrets.randbelow(1_000_000), "expires": time.monotonic() + 120, "attempts": 0}
                return {"code": self._pending["code"], "port": self._server.server_port, "expires_in": 120}
            if method == "POST" and path == "/api/ai/unpair":
                self._state["pairing"] = {}; self._pending = None; self._last_seen = 0
                for job in self._state["jobs"].values():
                    if job["state"] in ("claimed", "running"):
                        self._waiting(job, "Đã ngắt ghép nối. Kiểm tra Flow rồi nhập kết quả hoặc hủy tác vụ.")
                self._persist()
                return {"ok": True}
            if method == "POST" and path == "/api/ai/assets":
                return self._upload(body)
            match = re.fullmatch(r"/api/ai/assets/([a-f0-9]{32})(/thumbnail)?", path)
            if match and method == "GET":
                return self._asset_thumbnail(match[1]) if match[2] else self._asset_data(match[1])
            if path == "/api/ai/jobs":
                if method == "POST":
                    return self.create_job(body)
                if method == "GET":
                    return {"jobs": [self._summary(job) for job in sorted(self._state["jobs"].values(), key=lambda j: j["created"], reverse=True)]}
            match = re.fullmatch(r"/api/ai/jobs/([a-f0-9]{32})(/import)?", path)
            if match:
                job = self._job(match[1])
                if method == "GET" and not match[2]:
                    return self._job_public(job)
                if method == "DELETE" and not match[2]:
                    if job["state"] != "complete":
                        job.update(state="cancelled", message="Đã hủy tác vụ AI.", updated=time.time())
                        for key in ("_lease", "_client", "_touched"):
                            job.pop(key, None)
                        self._persist()
                    return {"ok": True, "job": self._summary(job)}
                if method == "POST" and match[2] == "/import":
                    if job["state"] not in ("waiting_user", "error"):
                        raise PublicError("Chỉ nhập kết quả thủ công cho tác vụ đang chờ hoặc bị lỗi.", 409)
                    asset = self._asset(body.get("asset_id"))
                    job.update(state="complete", result_ids=[asset["id"]], message="Đã nhập ảnh kết quả do bạn chọn.",
                               progress=100, updated=time.time(), manual_import=True)
                    self._persist()
                    return self._summary(job)
            match = re.fullmatch(r"/api/ai/history/([a-f0-9]{32})", path)
            if match and method == "DELETE":
                job = self._job(match[1])
                if job["state"] not in TERMINAL:
                    raise PublicError("Hủy tác vụ trước khi xóa lịch sử.", 409)
                self._forget(job["id"]); self._persist()
                return {"ok": True}
        raise PublicError("Không có API Render AI này.", 404)

    def wait_for_job(self, job_id, cancel, timeout=600):
        self._ensure()
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Invalid AI wait timeout")
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if self._closed:
                    raise PublicError("Bộ xử lý Render AI đã đóng.", 503)
                job = self._job(job_id)
                if cancel is not None and cancel.is_set():
                    if job["state"] != "complete":
                        job.update(state="cancelled", message="Đã hủy tác vụ AI.", updated=time.time())
                        for key in ("_lease", "_client", "_touched"):
                            job.pop(key, None)
                        self._persist()
                    raise PublicError("Đã hủy tác vụ AI.", 409)
                self._stale()
                if job["state"] == "complete":
                    return self._job_public(job)
                if job["state"] in ("error", "cancelled", "waiting_user"):
                    raise PublicError(job["message"], 409)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._waiting(job, "Hết thời gian đợi Flow. Kiểm tra trang Flow rồi nhập ảnh kết quả hoặc hủy; không tự tạo lại.")
                    self._persist()
                    raise PublicError(job["message"], 408)
                self.condition.wait(min(remaining, .25))

    def _start_bridge(self):
        if self._server is not None:
            return
        handler = _bridge_handler(self)
        for port in PORTS:
            try:
                server = _BridgeServer(("127.0.0.1", port), handler)
                break
            except OSError:
                continue
        else:
            raise PublicError("Không mở được cổng cầu nối Chrome 17865–17872.", 503)
        self._server = server
        self._server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="sitecraft-ai-bridge")
        self._server_thread.start()

    def _origin_allowed(self, origin, path):
        if not isinstance(origin, str) or not EXTENSION.fullmatch(origin):
            return False
        pairing = self._state["pairing"]
        if path == "/pair":
            return self._pending is not None or origin == pairing.get("origin")
        if path == "/health" and not pairing:
            return True
        return origin == pairing.get("origin")

    def _authorize(self, origin, authorization):
        pairing = self._state["pairing"]
        if origin != pairing.get("origin") or not EXTENSION.fullmatch(origin or ""):
            raise PublicError("Extension chưa được ghép nối.", 403)
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise PublicError("Thiếu mã xác thực cầu nối.", 401)
        token = authorization[7:]
        if len(token) > 256 or not secrets.compare_digest(sha256(token.encode()).hexdigest(), pairing.get("token_hash", "")):
            raise PublicError("Mã xác thực cầu nối không hợp lệ.", 401)
        self._sensitive.add(token)
        return pairing

    def _lease(self, job, body):
        lease = body.get("lease")
        if not isinstance(lease, str) or not job.get("_lease") or not secrets.compare_digest(lease, job["_lease"]):
            raise PublicError("Quyền xử lý tác vụ đã hết hoặc không đúng.", 409)
        if job["state"] not in ("claimed", "running"):
            raise PublicError("Tác vụ không còn nhận tiến trình hoặc kết quả.", 409)
        job["_touched"] = time.time()
        return lease

    def _bridge_route(self, path, body, origin, authorization):
        with self.lock:
            self._enabled(); self._stale()
            if path == "/pair":
                now = time.monotonic()
                while self._pair_attempts and now - self._pair_attempts[0] > 60:
                    self._pair_attempts.popleft()
                if len(self._pair_attempts) >= 10:
                    raise PublicError("Thử ghép nối quá nhiều lần. Đợi một phút.", 429)
                self._pair_attempts.append(now)
                pending = self._pending
                code = body.get("code")
                client = body.get("client_id")
                if not pending or now > pending["expires"] or pending["attempts"] >= 5:
                    raise PublicError("Mã ghép nối đã hết hạn. Tạo mã mới trong SketchUp.", 403)
                pending["attempts"] += 1
                if not isinstance(code, str) or not secrets.compare_digest(code, pending["code"]) or not isinstance(client, str) or not CLIENT.fullmatch(client):
                    raise PublicError("Mã ghép nối không đúng.", 403)
                token = secrets.token_urlsafe(32)
                self._state["pairing"] = {"origin": origin, "client_id": client, "token_hash": sha256(token.encode()).hexdigest()}
                for job in self._state["jobs"].values():
                    if job["state"] in ("claimed", "running"):
                        self._waiting(job, "Đã thay đổi ghép nối. Kiểm tra Flow trước khi nhập kết quả hoặc hủy.")
                self._pending = None; self._last_seen = time.time(); self._sensitive.add(token)
                self._persist()
                return {"token": token, "port": self._server.server_port, "protocol": 1}
            pairing = self._authorize(origin, authorization)
            self._last_seen = time.time()
            if path in ("/heartbeat", "/jobs/claim"):
                if body.get("client_id") != pairing["client_id"]:
                    raise PublicError("Client cầu nối không đúng.", 403)
                if path == "/heartbeat":
                    return {"ok": True, "connected": True, "protocol": 1}
                if any(job["state"] in ACTIVE for job in self._state["jobs"].values()):
                    return {"job": None}
                queued = sorted((job for job in self._state["jobs"].values() if job["state"] == "queued"), key=lambda j: j["created"])
                if not queued:
                    return {"job": None}
                job = queued[0]; lease = secrets.token_urlsafe(32)
                job.update(state="claimed", message="Chrome đã nhận tác vụ; chưa xác nhận gửi tạo ảnh.", updated=time.time(),
                           _lease=lease, _client=pairing["client_id"], _touched=time.time())
                self._persist()  # Claim is durable before the extension can submit.
                return {"job": {"id": job["id"], "lease": lease, "operation": job["operation"], "prompt": job["prompt"],
                    "options": deepcopy(job["options"]), "annotation_notes": job["annotation_notes"],
                    "source": self._asset_data(job["source_id"]), "references": [self._asset_data(value) for value in job["reference_ids"]],
                    "flow": deepcopy(job.get("flow", {}))}}
            match = re.fullmatch(r"/jobs/([a-f0-9]{32})/(progress|complete|fail)", path)
            if not match:
                raise PublicError("Không có API cầu nối này.", 404)
            job = self._job(match[1]); action = match[2]
            if action == "complete":
                images = body.get("images")
                if not isinstance(images, list) or not 1 <= len(images) <= 4:
                    raise PublicError("Kết quả cần từ 1 đến 4 ảnh hợp lệ.")
                flow = _flow(body.get("flow"))
                validated = [self._validate_image(value) for value in images]
                completion = sha256(json.dumps({"images": [sha256(value[0]).hexdigest() for value in validated],
                    "flow": flow}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                lease = body.get("lease")
                if job["state"] == "complete":
                    if isinstance(lease, str) and secrets.compare_digest(sha256(lease.encode()).hexdigest(), job.get("_completed_lease", "")) and secrets.compare_digest(completion, job.get("_completion", "")):
                        return {"ok": True, "job": self._summary(job)}
                    raise PublicError("Tác vụ đã hoàn tất với nội dung khác.", 409)
                lease = self._lease(job, body)
                assets = []
                for value, verified in zip(images, validated):
                    assets.append(self._upload({"data_url": value, "name": "Kết quả Flow"}, role="result",
                                               protected=[asset["id"] for asset in assets], validated=verified))
                if len(assets) == 1 and flow:
                    self._state["assets"][assets[0]["id"]]["flow"] = flow
                job.update(state="complete", result_ids=[asset["id"] for asset in assets], flow=flow, progress=100,
                           message="Đã nhận đúng ảnh kết quả từ Flow.", updated=time.time(),
                           _completed_lease=sha256(lease.encode()).hexdigest(), _completion=completion)
                for key in ("_lease", "_client", "_touched"):
                    job.pop(key, None)
                self._persist()
                return {"ok": True, "job": self._summary(job)}
            self._lease(job, body)
            message = self._message(body.get("message", ""))
            if action == "fail":
                code = self._message(body.get("code", "flow_error"), 100)
                job.update(state="error", message=message or "Flow không hoàn tất tác vụ.", error_code=code, updated=time.time())
                for key in ("_lease", "_client", "_touched"):
                    job.pop(key, None)
            else:
                state = body.get("state")
                if state not in ("claimed", "running", "waiting_user") or (job["state"] == "running" and state == "claimed"):
                    raise PublicError("Trạng thái tiến trình không hợp lệ.")
                if "progress" in body:
                    progress = body["progress"]
                    if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress) or not 0 <= progress <= 100:
                        raise PublicError("Tiến trình phải nằm trong [0,100].")
                    job["progress"] = progress
                if state == "waiting_user":
                    self._waiting(job, message or "Flow cần thao tác của bạn. Kiểm tra trang Flow hoặc nhập ảnh kết quả.")
                else:
                    job.update(state=state, message=message, updated=time.time())
            self._persist()
            return {"ok": True, "job": self._summary(job)}

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True; self._stop.set()
            self._thumbnails.clear(); self._thumbnail_bytes = 0
            if self._state is not None:
                for job in self._state["jobs"].values():
                    if job["state"] in ("claimed", "running"):
                        self._waiting(job, "Bộ xử lý đã đóng sau khi nhận tác vụ. Kiểm tra Flow rồi nhập kết quả hoặc hủy.")
                try:
                    self._persist()
                except (OSError, PublicError):
                    # On a full/unavailable disk, a persisted claimed/running
                    # job is still converted to waiting_user on the next boot.
                    # Port/thread/file-lock cleanup must always finish.
                    pass
            self.condition.notify_all()
            server, thread = self._server, self._server_thread
        if server:
            server.shutdown(); server.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        if self._maintenance_thread and self._maintenance_thread is not threading.current_thread():
            self._maintenance_thread.join(timeout=3)
        with self.lock:
            if self._file_lock:
                self._file_lock.close(); self._file_lock = None


class _BridgeServer(ThreadingHTTPServer):
    address_family = socket.AF_INET
    daemon_threads = True
    # HTTP/1.0 closes accepted sockets before the listener; Unix TIME_WAIT must
    # not exhaust all eight bridge ports during a normal quick worker restart.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


def _bridge_handler(service):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "SiteCraft-AI-Bridge/1"

        def log_message(self, *_):
            pass

        def send(self, status, body):
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Vary", "Origin")
            origin = getattr(self, "cors_origin", None)
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                if self.command == "OPTIONS":
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                    self.send_header("Access-Control-Max-Age", "60")
                    if self.headers.get("Access-Control-Request-Private-Network") == "true":
                        self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            self.cors_origin = None
            try:
                target = urllib.parse.urlsplit(self.path)
                if target.query or target.fragment or target.netloc:
                    raise PublicError("Đường dẫn cầu nối không hợp lệ.")
                if self.headers.get("Host") != "127.0.0.1:%d" % self.server.server_port:
                    raise PublicError("Host cầu nối không hợp lệ.", 403)
                origins = self.headers.get_all("Origin", [])
                if len(origins) > 1:
                    raise PublicError("Origin cầu nối không hợp lệ.", 403)
                origin = origins[0] if origins else None
                with service.lock:
                    service._enabled()
                    allowed = service._origin_allowed(origin, target.path)
                    if allowed:
                        self.cors_origin = origin
                    if self.command == "GET" and target.path == "/health":
                        if origin is not None and not allowed:
                            raise PublicError("Origin cầu nối không được phép.", 403)
                        return self.send(200, {"name": "SiteCraft AI Bridge", "protocol": 1,
                                              "paired": bool(service._state["pairing"].get("token_hash"))})
                    if not allowed:
                        raise PublicError("Origin extension chưa được ghép nối.", 403)
                    if self.command == "OPTIONS":
                        requested = {part.strip().lower() for part in self.headers.get("Access-Control-Request-Headers", "").split(",") if part.strip()}
                        if self.headers.get("Access-Control-Request-Method") not in ("GET", "POST") or requested - {"authorization", "content-type"}:
                            raise PublicError("Preflight cầu nối không hợp lệ.", 403)
                        return self.send(200, {"ok": True})
                    if self.command != "POST":
                        raise PublicError("Không có API cầu nối này.", 404)
                    if target.path != "/pair":
                        if len(self.headers.get_all("Authorization", [])) != 1:
                            raise PublicError("Thiếu mã xác thực cầu nối.", 401)
                        service._authorize(origin, self.headers.get("Authorization"))
                length = self.headers.get("Content-Length", "0")
                if not length.isdigit() or int(length) > MAX_BODY:
                    raise PublicError("Nội dung cầu nối quá lớn.", 413)
                if self.headers.get("Transfer-Encoding"):
                    raise PublicError("Cầu nối không nhận nội dung chunked.")
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise PublicError("Cầu nối chỉ nhận JSON.", 415)
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    raise PublicError("Nội dung cầu nối chưa đầy đủ.")
                body = _json(raw or b"{}")
                return self.send(200, service._bridge_route(target.path, body, origin, self.headers.get("Authorization")))
            except PublicError as exc:
                self.send(exc.status, {"error": str(exc)})
            except (ValueError, UnicodeError, TimeoutError):
                self.send(400, {"error": "Yêu cầu cầu nối không hợp lệ."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "Không xử lý được yêu cầu cầu nối."})

        do_GET = dispatch
        do_POST = dispatch
        do_OPTIONS = dispatch
        do_DELETE = dispatch
    return Handler
