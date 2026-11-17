"""Local configuration and parent-process lifetime for the bundled worker."""
import base64
import json
import os
from pathlib import Path
import secrets
import threading
import time

from .auth import SupabaseAuth
from .net import PublicError


def validate_public_config(body):
    url, key = body.get("supabase_url", ""), body.get("public_key", "")
    if not isinstance(url, str) or not isinstance(key, str):
        raise PublicError("Nhập Project URL và public key Supabase.")
    url, key = url.strip().rstrip("/"), key.strip()
    if not url or not key or len(url) > 2048 or len(key) > 16_384 or any(c in key for c in "\r\n\x00"):
        raise PublicError("Project URL hoặc public key không hợp lệ.")
    try:
        SupabaseAuth._validate_url(url)
    except ValueError as error:
        raise PublicError(str(error)) from None
    forbidden = key.startswith("sb_secret_")
    try:
        part = key.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        forbidden = forbidden or (isinstance(payload, dict) and payload.get("role") == "service_role")
    except (IndexError, ValueError, UnicodeError):
        pass
    if forbidden:
        raise PublicError("Chỉ dùng public anon/publishable key. Không dùng service_role hoặc secret key.")
    return url, key


def save_config(path, config):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    allowed = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "OVERPASS_URL", "TESSERACT_BIN")
    lines = []
    for name in allowed:
        value = str(config.get(name, ""))
        if any(c in value for c in "\r\n\x00"):
            raise PublicError("Cấu hình chứa ký tự không hợp lệ.")
        lines.append(name + "=" + value)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            stream.write("\n".join(lines) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_ready(path, port, instance):
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    data = {"port": port, "pid": os.getpid(), "instance": instance}
    with open(temporary, "x", encoding="utf8") as stream:
        json.dump(data, stream)
    os.replace(temporary, target)


def watch_parent(pid, on_exit, done):
    """Hold a process handle on Windows to avoid PID-reuse races."""
    def worker():
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    while not done.is_set():
                        if kernel.WaitForSingleObject(handle, 500) == 0:
                            break
                    else:
                        return
                finally:
                    kernel.CloseHandle(handle)
            else:
                on_exit()
                return
        else:
            while not done.wait(.5):
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    break
            else:
                return
        on_exit()
    thread = threading.Thread(target=worker, daemon=True, name="openmap-parent")
    thread.start()
    return thread
