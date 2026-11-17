"""Bounded resolution of public Google Maps share links, without open redirects."""
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .net import PublicError

GOOGLE_MAPS_HOSTS = frozenset(("maps.app.goo.gl", "goo.gl", "google.com", "www.google.com", "maps.google.com", "google.com.vn", "www.google.com.vn"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def allowed(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or host not in GOOGLE_MAPS_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if host == "goo.gl" and not parsed.path.startswith("/maps/"):
            return False
        if host not in ("goo.gl", "maps.app.goo.gl", "maps.google.com") and not parsed.path.startswith("/maps"):
            return False
        return len(url) <= 8192
    except ValueError:
        return False


def coordinates(text):
    decoded = urllib.parse.unquote(text)
    patterns = (r"@([-+]?\d{1,2}(?:\.\d+)?),\s*([-+]?\d{1,3}(?:\.\d+)?)",
                r"!3d([-+]?\d{1,2}(?:\.\d+)?)!4d([-+]?\d{1,3}(?:\.\d+)?)",
                r"(?:[?&](?:q|query|ll)=)([-+]?\d{1,2}(?:\.\d+)?),\s*([-+]?\d{1,3}(?:\.\d+)?)")
    for pattern in patterns:
        match = re.search(pattern, decoded, re.IGNORECASE)
        if match:
            lat, lon = map(float, match.groups())
            if math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 79.9 and abs(lon) <= 180:
                return lat, lon
    return None


def redirect_once(url, timeout):
    opener = urllib.request.build_opener(NoRedirect())
    try:
        response = opener.open(urllib.request.Request(url, headers={"User-Agent": "OpenMapSketchUp/MapsLink"}), timeout=timeout)
        # Some links use HTTP Refresh; do not parse/execute downloaded HTML.
        with response:
            return None
    except urllib.error.HTTPError as error:
        try:
            return error.headers.get("Location") if error.code in (301, 302, 303, 307, 308) else None
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublicError("Không mở được link Google Maps. Thử copy link đầy đủ có tọa độ hoặc dán vĩ độ, kinh độ.", 502) from None


def resolve(url, getter=None):
    if not allowed(url):
        raise PublicError("Chỉ mở link HTTPS Google Maps công khai. Bạn cũng có thể dán vĩ độ, kinh độ.")
    getter = getter or redirect_once
    deadline = time.monotonic() + 8
    seen = set()
    for _ in range(5):
        if url in seen:
            break
        seen.add(url)
        result = coordinates(url)
        if result:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        location = getter(url, min(3, remaining))
        if not location:
            break
        target = urllib.parse.urljoin(url, location)
        if not allowed(target):
            raise PublicError("Link Google Maps chuyển hướng ngoài miền bản đồ được hỗ trợ. Dán link đầy đủ có tọa độ.")
        url = target
    raise PublicError("Link chưa chứa tọa độ đọc được. Mở Google Maps, copy link đầy đủ có @vĩ_độ,kinh_độ hoặc dán tọa độ.")
