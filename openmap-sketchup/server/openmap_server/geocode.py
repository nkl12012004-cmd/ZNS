"""Place search with independent providers and submit-only Nominatim fallback."""
from collections import OrderedDict
import math
import re
import threading
import time
import unicodedata
import urllib.parse

from .net import PublicError, fetch_json
from . import map_links


class Geocoder:
    def __init__(self, getter=None):
        self.getter = getter or fetch_json
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.nominatim_lock = threading.Lock()
        self.inflight = threading.BoundedSemaphore(4)
        self.last_nominatim = 0.0

    @staticmethod
    def _query(query):
        if not isinstance(query, str):
            raise PublicError("Nhập địa chỉ hoặc tên địa điểm.")
        query = unicodedata.normalize("NFC", " ".join(query.split()))
        maximum = 4096 if query.startswith("https://") else 200
        if not 2 <= len(query) <= maximum or any(ord(c) < 32 for c in query):
            raise PublicError("Nhập địa chỉ từ 2 đến 200 ký tự.")
        return query

    @staticmethod
    def _bias(lat, lon):
        if lat is None and lon is None:
            return None
        try:
            if isinstance(lat, bool) or isinstance(lon, bool):
                raise ValueError
            lat, lon = float(lat), float(lon)
            if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 80 or abs(lon) > 180:
                raise ValueError
        except (TypeError, ValueError):
            raise PublicError("Tọa độ tìm kiếm không hợp lệ.") from None
        return lat, lon

    @staticmethod
    def _result(label, lat, lon, source, subtitle=""):
        if not isinstance(label, str) or not label.strip():
            return None
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 79.9 or abs(lon) > 180:
            return None
        label = label.strip()[:800]
        return {"label": label, "display_name": label, "title": label.split(",", 1)[0],
                "subtitle": str(subtitle or label)[:800], "lat": lat, "lon": lon, "source": source}

    def _arcgis(self, query, limit, bias, timeout):
        params = {"f": "json", "SingleLine": query, "maxLocations": limit,
                  "outFields": "PlaceName,Place_addr,LongLabel", "langCode": "vi"}
        if bias:
            params["location"] = "%.6f,%.6f" % (bias[1], bias[0])
        data = self.getter("https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + urllib.parse.urlencode(params), timeout=timeout, limit=1_000_000)
        if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
            raise PublicError("Không đọc được kết quả tìm địa điểm.", 502)
        rows = []
        for item in data["candidates"][:20]:
            if not isinstance(item, dict) or not isinstance(item.get("location"), dict):
                continue
            location = item["location"]
            attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            label = attributes.get("LongLabel") or item.get("address")
            row = self._result(label, location.get("y"), location.get("x"), "arcgis", attributes.get("Place_addr"))
            if row:
                rows.append(row)
        return rows

    def _photon(self, query, limit, bias, timeout):
        params = {"q": query, "limit": limit}
        # Photon applies a very strong proximity bias: searching Hà Nội while
        # viewing HCMC otherwise returns nearby Hà Nội-named roads/businesses.
        # Search its global index; ArcGIS keeps the optional location bias.
        data = self.getter("https://photon.komoot.io/api/?" + urllib.parse.urlencode(params), timeout=timeout, limit=1_000_000)
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise PublicError("Không đọc được kết quả tìm địa điểm.", 502)
        rows = []
        for item in data["features"][:20]:
            if not isinstance(item, dict):
                continue
            props, geometry = item.get("properties"), item.get("geometry")
            if not isinstance(props, dict) or not isinstance(geometry, dict) or geometry.get("type") != "Point":
                continue
            point = geometry.get("coordinates")
            if not isinstance(point, list) or len(point) < 2:
                continue
            parts = []
            for key in ("name", "street", "housenumber", "district", "city", "state", "country"):
                value = props.get(key)
                if isinstance(value, str) and value and value not in parts:
                    parts.append(value)
            row = self._result(", ".join(parts), point[1], point[0], "photon")
            if row:
                rows.append(row)
        return rows

    def _nominatim(self, query, limit, _bias, timeout):
        # The public Nominatim API is a submit-only fallback. Never use it for
        # autocomplete; serialize requests and preserve its one-per-second rate.
        deadline = time.monotonic() + timeout
        if not self.nominatim_lock.acquire(timeout=timeout):
            raise PublicError("Dịch vụ tìm địa điểm đang bận.", 503)
        try:
            pause = 1.1 - (time.monotonic() - self.last_nominatim)
            if pause > 0:
                if time.monotonic() + pause >= deadline:
                    raise PublicError("Dịch vụ tìm địa điểm đang bận.", 503)
                time.sleep(pause)
            self.last_nominatim = time.monotonic()
            data = self.getter("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": limit}),
                               timeout=max(.1, deadline - time.monotonic()), limit=1_000_000, headers={"Accept-Language": "vi,en"})
        finally:
            self.nominatim_lock.release()
        if not isinstance(data, list):
            raise PublicError("Không đọc được kết quả tìm địa điểm.", 502)
        rows = []
        for item in data[:20]:
            if isinstance(item, dict):
                row = self._result(item.get("display_name"), item.get("lat"), item.get("lon"), "nominatim")
                if row:
                    rows.append(row)
        return rows

    def search(self, query, *, lat=None, lon=None, limit=6, suggest=False):
        query = self._query(query)
        if query.startswith(("https://", "http://")):
            if suggest:
                point = map_links.coordinates(query) if map_links.allowed(query) else None
                if not point:
                    return {"ok": True, "results": [], "attribution": ""}
            else:
                if not self.inflight.acquire(blocking=False):
                    raise PublicError("Đang tìm địa điểm khác. Chờ một chút rồi thử lại.", 503)
                try:
                    point = map_links.resolve(query)
                finally:
                    self.inflight.release()
            row = self._result("Tọa độ Google Maps", point[0], point[1], "coordinates")
            return {"ok": True, "results": [row], "is_direct_coords": True, "attribution": ""}
        bias = self._bias(lat, lon)
        try:
            if isinstance(limit, bool):
                raise ValueError
            limit = int(limit)
            if not 1 <= limit <= 8:
                raise ValueError
        except (TypeError, ValueError):
            raise PublicError("Số kết quả tìm kiếm phải từ 1 đến 8.") from None
        key = (query.casefold(), bias, limit, bool(suggest))
        now = time.monotonic()
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                self.cache.move_to_end(key)
                return cached[1]
        if not self.inflight.acquire(blocking=False):
            raise PublicError("Đang tìm địa điểm khác. Chờ một chút rồi thử lại.", 503)
        try:
            return self._search(query, limit, bias, bool(suggest), key)
        finally:
            self.inflight.release()

    def _search(self, query, limit, bias, suggest, key):
        reachable = False
        deadline = time.monotonic() + (6 if suggest else 15)
        providers = (self._photon, self._arcgis) if suggest else (self._arcgis, self._photon, self._nominatim)
        for provider in providers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                rows = provider(query, limit, bias, min(3 if suggest else 5, remaining))
                reachable = True
            except PublicError:
                continue
            unique, seen = [], set()
            for row in rows:
                # findAddressCandidates is not a prefix API. Do not surface a
                # weak ArcGIS fallback such as Hå, Norway for incomplete Hà Nộ.
                if suggest and row["source"] == "arcgis" and not self._prefix_match(query, row["title"]):
                    continue
                point = (round(row["lat"], 5), round(row["lon"], 5))
                if point not in seen:
                    seen.add(point)
                    unique.append(row)
            if unique:
                result = {"ok": True, "results": unique[:limit], "attribution": "Geocoding: Esri / Photon / © OpenStreetMap contributors", "source": unique[0]["source"]}
                self._remember(key, result, 600)
                return result
        if not reachable:
            raise PublicError("Không kết nối được dịch vụ tìm địa điểm. Thử lại hoặc dán tọa độ/link Google Maps có tọa độ.", 502)
        result = {"ok": True, "results": [], "attribution": "Geocoding: Esri / Photon / © OpenStreetMap contributors"}
        self._remember(key, result, 20)
        return result

    @staticmethod
    def _prefix_match(query, title):
        def words(value):
            text = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
            text = "".join(char for char in text if not unicodedata.combining(char))
            return re.findall(r"[^\W_]+", text, re.UNICODE)
        typed, target = words(query), words(title)
        return bool(typed and target) and ("".join(target).startswith("".join(typed)) or
                                         all(any(word.startswith(token) for word in target) for token in typed))

    def _remember(self, key, result, lifetime):
        with self.lock:
            self.cache[key] = (time.monotonic() + lifetime, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
