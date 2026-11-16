import json
import urllib.error
import urllib.request


class PublicError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def fetch(url, *, method="GET", data=None, headers=None, limit=12_000_000, timeout=30):
    request = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": "OpenMapSketchUp/0.1 (self-hosted)",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = response.read(limit + 1)
            if len(result) > limit:
                raise PublicError("Dữ liệu tải về quá lớn. Hãy chọn vùng nhỏ hơn.", 502)
            return result
    except urllib.error.HTTPError as error:
        # Do not include URLs, tokens, response bodies, or credentials in errors.
        status = error.code
        error.close()
        raise PublicError("Dịch vụ dữ liệu trả lỗi HTTP %d." % status, 502) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublicError("Không kết nối được dịch vụ dữ liệu. Thử lại sau.", 502) from None


def fetch_json(url, **kwargs):
    try:
        return json.loads(fetch(url, **kwargs))
    except (ValueError, UnicodeError):
        raise PublicError("Dịch vụ trả dữ liệu JSON không hợp lệ.", 502) from None
