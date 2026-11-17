from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time
import traceback
import urllib.parse

from . import VERSION
from .auth import SupabaseAuth
from .builder import build, export_obj, parameters
from .formats import export_glb, preview_mesh
from . import ocr
from .net import PublicError, fetch_json
from .local_runtime import save_config, validate_public_config
from .geocode import Geocoder
from .original_engine import OriginalEngine


class Application:
    def __init__(self, config):
        self.auth = SupabaseAuth(config.get("SUPABASE_URL", ""), config.get("SUPABASE_ANON_KEY", ""), config.get("PUBLIC_BASE_URL", "http://127.0.0.1:8877"))
        self.config = config
        self.jobs = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="openmap")
        self.search_lock = threading.Lock()
        self.last_search = 0
        self.geocoder = Geocoder()
        self.original_engine = OriginalEngine(config) if config.get("OPENMAP_ENGINE") == "original" else None

    @property
    def local_access(self):
        # No account is needed for the private per-SketchUp worker. A standalone
        # network server still uses Supabase and never enables anonymous access.
        return bool(self.config.get("OPENMAP_LOCAL_TOKEN")) and self.config.get("OPENMAP_AUTH_MODE", "local") == "local"

    def require_local(self, headers):
        token = self.config.get("OPENMAP_LOCAL_TOKEN", "")
        if not token or not secrets.compare_digest(token, headers.get("X-OpenMap-Local", "")):
            raise PublicError("Yêu cầu cấu hình cục bộ không hợp lệ.", 403)

    def check_transport(self, headers):
        if self.config.get("OPENMAP_LOCAL_TOKEN"):
            self.require_local(headers)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job["cancel"].set()
        self.pool.shutdown(wait=True, cancel_futures=True)

    def _run(self, job):
        def progress(percent, message):
            with self.lock:
                job.update(progress=round(percent), message=message)
        with self.lock:
            if job["cancel"].is_set():
                return
            job["state"] = "running"
        try:
            original_bundle = None
            if self.original_engine:
                original_bundle = self.original_engine.build(job["params"], progress=progress, cancel=job["cancel"], job_id=job["id"])
                result, exported, glb = original_bundle["mesh"], original_bundle["obj_zip"], original_bundle["glb"]
            else:
                result = build(job["params"], progress=progress, cancel=job["cancel"], overpass=self.config.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter"))
                exported = export_obj(result)
                glb = export_glb(result)
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            if len(payload) > 128_000_000:
                raise PublicError("Mô hình quá lớn. Chia thành các mảnh nhỏ hơn.")
            with self.lock:
                if not job["cancel"].is_set():
                    partial = bool(result.get("partial"))
                    job.update(state="complete", result=result, mesh=payload, export=exported, glb=glb, progress=100,
                               partial=partial, source_degraded=bool(result.get("source_degraded")), missing_layers=result.get("missing_layers", []), warnings=result.get("warnings", []),
                               message="Đã dựng nền/địa hình; còn thiếu các lớp OSM được cảnh báo." if partial else "Sẵn sàng nạp vào SketchUp")
                    if original_bundle:
                        job.update(original_bundle={key: value for key, value in original_bundle.items() if key not in ("mesh", "obj_zip", "glb", "raw_scene")}, engine="original")
                    completed = sorted((value for value in self.jobs.values() if value["state"] == "complete" and value is not job), key=lambda value: value["created"])
                    def memory():
                        return sum(len(value.get("mesh", b"")) * 3 + len(value.get("export", b"")) + len(value.get("glb", b"")) for value in self.jobs.values())
                    while completed and memory() > 256_000_000:
                        self.jobs.pop(completed.pop(0)["id"], None)
        except Exception as error:
            if not isinstance(error, PublicError):
                traceback.print_exc()
            with self.lock:
                if not job["cancel"].is_set():
                    message = str(error) if isinstance(error, PublicError) else "Lỗi xử lý dữ liệu bản đồ. Mở Cấu hình → thư mục log để xem nguyên nhân; có thể thử lại với vùng nhỏ hơn."
                    job.update(state="error", message=message)

    def job(self, job_id, owner):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["owner"] != owner:
                raise PublicError("Không tìm thấy tác vụ của tài khoản này.", 404)
            return job

    def route(self, method, path, query, headers, body):
        self.check_transport(headers)
        if method == "GET" and path == "/health":
            import platform
            import PIL
            return {"name": "OpenMap SketchUp", "version": VERSION, "auth_configured": self.auth.configured, "ocr_available": ocr.available(self.config.get("TESSERACT_BIN")),
                    "auth_mode": "local" if self.local_access else "supabase", "instance": self.config.get("OPENMAP_INSTANCE_ID", ""), "python": platform.python_version(), "pillow": PIL.__version__,
                    "engine": "original" if self.original_engine else "openmap", "engine_status": self.original_engine.availability() if self.original_engine else {"available": True}}
        if path == "/api/runtime/config" and method in ("GET", "POST"):
            self.require_local(headers)
            if method == "POST":
                url, key = validate_public_config(body)
                replacement = {**self.config, "SUPABASE_URL": url, "SUPABASE_ANON_KEY": key}
                auth = SupabaseAuth(url, key, self.config["PUBLIC_BASE_URL"])
                path_config = self.config.get("OPENMAP_CONFIG_FILE")
                if not path_config:
                    raise PublicError("Chưa đặt đường dẫn cấu hình cục bộ.", 500)
                save_config(path_config, replacement)
                with self.lock:
                    for job in self.jobs.values():
                        job['cancel'].set()
                    self.jobs.clear()
                    self.config.update(SUPABASE_URL=url, SUPABASE_ANON_KEY=key)
                    self.auth = auth
            return {"supabase_url": self.config.get("SUPABASE_URL", ""), "public_key": self.config.get("SUPABASE_ANON_KEY", ""), "auth_configured": self.auth.configured,
                    "redirect_url": "http://127.0.0.1:*/auth/callback**"}
        if method == "POST" and path.startswith("/api/auth/"):
            if self.local_access:
                raise PublicError("Chế độ cục bộ mở thẳng bản đồ, không cần đăng nhập.")
            action = path.removeprefix("/api/auth/")
            if action in ("login", "signup", "refresh"):
                return getattr(self.auth, action)(body)
            if action == "google/start":
                return self.auth.google_start()
            if action == "logout":
                return self.auth.logout(headers.get("Authorization", ""))
        if method == "GET" and path == "/api/auth/google/status":
            return self.auth.google_status(query.get("flow_id", [""])[0], headers.get("X-Flow-Secret", ""))
        user = {"id": "local-device", "email": "Trên máy này"} if self.local_access else self.auth.user(headers.get("Authorization", ""))
        if method == "GET" and path == "/api/me":
            return {"id": user["id"], "email": user.get("email", "")}
        if method == "POST" and path == "/api/ocr":
            return ocr.recognize(body, self.config.get("TESSERACT_BIN"))
        if ((method == "GET" and path in ("/api/search", "/api/search_suggest"))
                or (method == "POST" and path in ("/api/geocode", "/api/search_suggest"))):
            params = {key: values[0] for key, values in query.items() if values} if method == "GET" else body
            return self.geocoder.search(params.get("q", params.get("query", "")), lat=params.get("lat"), lon=params.get("lon"),
                                        limit=params.get("limit", 6), suggest=path == "/api/search_suggest")
        if method == "POST" and path == "/api/jobs":
            params = parameters(body)
            if self.original_engine:
                self.original_engine.original_parameters(params)
            with self.lock:
                now = time.monotonic()
                self.jobs = {key: value for key, value in self.jobs.items() if value["state"] in ("queued", "running") or now - value["created"] < 3600}
                active = sum(value["state"] in ("queued", "running") for value in self.jobs.values())
                if active >= 8:
                    raise PublicError("Máy chủ đang xử lý nhiều tác vụ. Thử lại khi một tác vụ hoàn tất.", 503)
                # Keep completed geometry bounded in memory without usage accounting.
                completed = sorted((value for value in self.jobs.values() if value["state"] not in ("queued", "running")), key=lambda value: value["created"])
                while len(completed) >= 8:
                    self.jobs.pop(completed.pop(0)["id"], None)
                job_id = secrets.token_hex(16)
                job = {"id": job_id, "owner": user["id"], "state": "queued", "progress": 0, "message": "Đang đợi xử lý", "params": params, "created": now, "cancel": threading.Event()}
                self.jobs[job_id] = job
                self.pool.submit(self._run, job)
            return {"id": job_id, "state": "queued"}
        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})(?:/(mesh|export|glb|preview|skp|manifest))?", path)
        if match:
            job = self.job(match[1], user["id"])
            with self.lock:
                if method == "DELETE" and not match[2]:
                    job["cancel"].set()
                    job.update(state="cancelled", message="Đã hủy")
                    return {"ok": True}
                if method == "GET" and not match[2]:
                    return {key: job[key] for key in ("id", "state", "progress", "message", "partial", "source_degraded", "missing_layers", "warnings") if key in job}
                if method == "GET" and match[2]:
                    if job["state"] != "complete":
                        raise PublicError("Tác vụ chưa hoàn tất.", 409)
                    if match[2] == "mesh":
                        return job["mesh"], "application/json; charset=utf-8"
                    if match[2] == "glb":
                        return job["glb"], "model/gltf-binary"
                    if match[2] == "preview":
                        return preview_mesh(job["result"])
                    if match[2] == "manifest":
                        bundle = job.get("original_bundle", {})
                        return {"engine": job.get("engine", "openmap"), "native_skp_ready": bool(bundle.get("native_skp_ready")),
                                "origin": job["result"].get("original_origin"), "anchor": job["result"]["anchor"],
                                "center": job["result"]["center"], "hill_patch": job["result"].get("hill_patch", False),
                                "partial": job["result"].get("partial", False), "missing_layers": job["result"].get("missing_layers", []),
                                "source_degraded": job["result"].get("source_degraded", False),
                                "name": job["result"]["name"], "bbox": job["result"]["bbox"], "parameters": job["result"].get("parameters", {}),
                                "triangles": job["result"]["triangles"], "warnings": job["result"].get("warnings", []),
                                "attribution": job["result"]["attribution"]}
                    if match[2] == "skp":
                        from pathlib import Path
                        bundle = job.get("original_bundle", {})
                        path_skp = bundle.get("skp_path")
                        if not bundle.get("native_skp_ready") or not path_skp or not Path(path_skp).is_file():
                            raise PublicError("Chưa có SKP native. Nạp mô hình của tác vụ này vào SketchUp rồi lưu SKP; không chọn mảnh cũ.", 409)
                        return Path(path_skp).read_bytes(), "application/octet-stream"
                    return job["export"], "application/zip"
        raise PublicError("Không có API này.", 404)


def handler_for(application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SiteCraft/" + VERSION
        protocol_version = "HTTP/1.0"

        def log_message(self, *_):
            # HTTP logs must not expose OAuth codes, emails, or tokens.
            pass

        def send(self, status, data, content_type="application/json; charset=utf-8"):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self):
            try:
                target = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(target.query)
                if self.command == "GET" and target.path == "/auth/callback":
                    application.auth.google_callback(query.get("flow", [""])[0], query.get("code", [""])[0], query.get("error", [None])[0])
                    return self.send(200, "<!doctype html><meta charset=utf-8><title>SiteCraft</title><h1>Đã đăng nhập</h1><p>Quay lại SketchUp để tiếp tục. Bạn có thể đóng trang này.</p>".encode(), "text/html; charset=utf-8")
                if self.headers.get("Origin"):
                    raise PublicError("API này dành cho ứng dụng SketchUp.", 403)
                application.check_transport(self.headers)
                if self.command == "POST" and target.path == "/api/runtime/shutdown":
                    application.require_local(self.headers)
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return self.send(200, {"ok": True})
                length = self.headers.get("Content-Length", "0")
                maximum = 12_000_000 if target.path == "/api/ocr" else 65_536
                if not length.isdigit() or int(length) > maximum:
                    raise PublicError("Nội dung yêu cầu quá lớn.", 413)
                body = {}
                if self.command in ("POST", "DELETE") and int(length):
                    self.connection.settimeout(15)
                    body = json.loads(self.rfile.read(int(length)))
                    if not isinstance(body, dict):
                        raise PublicError("Yêu cầu phải là JSON object.")
                result = application.route(self.command, target.path, query, self.headers, body)
                if isinstance(result, tuple):
                    return self.send(200, *result)
                self.send(200, result)
            except PublicError as error:
                self.send(error.status, {"error": str(error)})
            except (ValueError, UnicodeError):
                self.send(400, {"error": "Yêu cầu không hợp lệ."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "Máy chủ không xử lý được yêu cầu."})

        do_GET = dispatch
        do_POST = dispatch
        do_DELETE = dispatch

    return Handler


def create_server(config, host="127.0.0.1", port=8877):
    application = Application(config)
    server = ThreadingHTTPServer((host, port), handler_for(application))
    server.daemon_threads = True
    return server, application
