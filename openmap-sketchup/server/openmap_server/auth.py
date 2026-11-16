import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .net import PublicError


class SupabaseAuth:
    """Use GoTrue to verify real users. No demo login, balance, or quota path."""

    def __init__(self, url, public_key, public_base):
        self.url = url.rstrip("/")
        self.key = public_key
        self.public_base = public_base.rstrip("/")
        self.flows = {}
        self.users = {}
        self.lock = threading.Lock()
        if self.url:
            self._validate_url(self.url)
        self._validate_url(self.public_base)

    @staticmethod
    def _validate_url(url):
        parsed = urllib.parse.urlsplit(url)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("Chỉ dùng HTTPS hoặc HTTP loopback cho phát triển cục bộ.")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("URL cấu hình phải là một origin, không chứa path/query/mật khẩu.")

    @property
    def configured(self):
        return bool(self.url and self.key)

    def _request(self, path, body=None, token=None, method=None):
        if not self.configured:
            raise PublicError("Máy chủ chưa cấu hình SUPABASE_URL và SUPABASE_ANON_KEY.", 503)
        headers = {"apikey": self.key, "Content-Type": "application/json", "User-Agent": "OpenMapSketchUp/0.1"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + "/auth/v1/" + path, data=data, headers=headers, method=method or ("POST" if body is not None else "GET"))
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise PublicError("Phản hồi đăng nhập quá lớn.", 502)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            status = 401 if error.code in (400, 401, 403, 422) else 502
            error.close()
            raise PublicError("Không đăng nhập được. Kiểm tra tài khoản, xác nhận email và cấu hình Supabase.", status) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PublicError("Không kết nối được dịch vụ đăng nhập Supabase.", 502) from None

    @staticmethod
    def _session(result):
        if not isinstance(result, dict) or not result.get("access_token") or not result.get("refresh_token"):
            raise PublicError("Supabase chưa cấp phiên đăng nhập. Hãy xác nhận email trước.", 401)
        return {key: result.get(key) for key in ("access_token", "refresh_token", "expires_in", "expires_at", "user")}

    def login(self, body):
        email = str(body.get("email", "")).strip()
        password = body.get("password")
        if not email or len(email) > 320 or not isinstance(password, str) or not password or len(password) > 4096:
            raise PublicError("Nhập email và mật khẩu hợp lệ.")
        return self._session(self._request("token?grant_type=password", {"email": email, "password": password}))

    def signup(self, body):
        email, password = body.get("email"), body.get("password")
        if not isinstance(email, str) or "@" not in email or len(email) > 320 or not isinstance(password, str) or not 8 <= len(password) <= 4096:
            raise PublicError("Nhập email hợp lệ và mật khẩu ít nhất 8 ký tự.")
        self._request("signup", {"email": email.strip(), "password": password})
        return {"message": "Đã gửi yêu cầu tạo tài khoản. Xác nhận email nếu dự án Supabase yêu cầu, rồi đăng nhập."}

    def refresh(self, body):
        token = body.get("refresh_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 16_384:
            raise PublicError("Phiên đăng nhập không hợp lệ.", 401)
        return self._session(self._request("token?grant_type=refresh_token", {"refresh_token": token}))

    def user(self, authorization):
        if not authorization.startswith("Bearer "):
            raise PublicError("Bạn cần đăng nhập để sử dụng.", 401)
        token = authorization[7:]
        if not token or len(token) > 16_384:
            raise PublicError("Phiên đăng nhập không hợp lệ.", 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            cached = self.users.get(digest)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        user = self._request("user", token=token)
        if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"]:
            raise PublicError("Không xác minh được tài khoản.", 401)
        with self.lock:
            now = time.monotonic()
            self.users = {key: value for key, value in self.users.items() if value[0] > now}
            self.users[digest] = (now + 15, user)
        return user

    def logout(self, authorization):
        if authorization.startswith("Bearer "):
            token = authorization[7:]
            with self.lock:
                self.users.pop(hashlib.sha256(token.encode()).hexdigest(), None)
            self._request("logout", {}, token=token)
        return {"ok": True}

    def google_start(self):
        if not self.configured:
            raise PublicError("Máy chủ chưa cấu hình Supabase.", 503)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        flow_id, poll_secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.lock:
            now = time.monotonic()
            self.flows = {key: value for key, value in self.flows.items() if value["expires"] > now}
            if len(self.flows) >= 100:
                raise PublicError("Máy chủ đang bận đăng nhập. Thử lại sau.", 503)
            self.flows[flow_id] = {"verifier": verifier, "secret": poll_secret, "expires": now + 600, "state": "pending"}
        redirect = self.public_base + "/auth/callback?flow=" + flow_id
        query = urllib.parse.urlencode({"provider": "google", "redirect_to": redirect, "code_challenge": challenge, "code_challenge_method": "s256"})
        return {"flow_id": flow_id, "poll_secret": poll_secret, "authorize_url": self.url + "/auth/v1/authorize?" + query}

    def google_callback(self, flow_id, code, error=None):
        with self.lock:
            flow = self.flows.get(flow_id)
            if not flow or flow["expires"] < time.monotonic() or flow["state"] != "pending":
                raise PublicError("Yêu cầu đăng nhập đã hết hạn hoặc đã sử dụng.")
            flow["state"] = "exchanging"
        try:
            if error or not code or len(code) > 4096:
                raise PublicError("Google chưa hoàn tất đăng nhập.", 401)
            result = self._session(self._request("token?grant_type=pkce", {"auth_code": code, "code_verifier": flow["verifier"]}))
            with self.lock:
                flow.update(state="ready", session=result)
        except PublicError as problem:
            with self.lock:
                flow.update(state="error", message=str(problem))
            raise

    def google_status(self, flow_id, secret):
        with self.lock:
            flow = self.flows.get(flow_id)
            if not flow or flow["expires"] < time.monotonic() or not secrets.compare_digest(flow["secret"], secret):
                raise PublicError("Yêu cầu đăng nhập không hợp lệ hoặc đã hết hạn.", 404)
            if flow["state"] == "ready":
                self.flows.pop(flow_id)
                return {"state": "ready", "session": flow["session"]}
            if flow["state"] == "error":
                self.flows.pop(flow_id)
                raise PublicError(flow["message"], 401)
            return {"state": "pending"}
