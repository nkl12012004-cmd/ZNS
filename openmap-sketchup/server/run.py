#!/usr/bin/env python3
import argparse
import os
import sys
import threading
from pathlib import Path

if os.environ.get("OPENMAP_LOG_PATH") and sys.stderr is None:
    sys.stderr = open(os.environ["OPENMAP_LOG_PATH"], "a", encoding="utf8", buffering=1)
    sys.stdout = sys.stderr

from openmap_server.app import create_server
from openmap_server.local_runtime import watch_parent, write_ready


def read_env(path):
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Dòng .env phải có dạng KEY=value.")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenMap SketchUp — Supabase login, open map processing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--env", type=Path, default=Path(__file__).with_name(".env"))
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--instance", default="")
    args = parser.parse_args()
    config = {**read_env(args.env), **os.environ}
    config["OPENMAP_CONFIG_FILE"] = str(args.env.resolve())
    config["OPENMAP_INSTANCE_ID"] = args.instance
    if config.get("OPENMAP_LOCAL_TOKEN") and config.get("OPENMAP_OCR_DIR"):
        from openmap_server.native_ocr import library
        library()  # Fail during startup if a bundled native dependency cannot load.
    config.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:%d" % args.port)
    server, application = create_server(config, args.host, args.port)
    if args.port == 0:
        config["PUBLIC_BASE_URL"] = "http://127.0.0.1:%d" % server.server_port
        application.auth.public_base = config["PUBLIC_BASE_URL"]
    done = threading.Event()
    if args.parent_pid:
        if not config.get("OPENMAP_LOCAL_TOKEN"):
            raise RuntimeError("Managed worker requires a local transport token")
        def parent_exited():
            threading.Thread(target=server.shutdown, daemon=True).start()
            # Only the owned worker exits; generated jobs are in RAM.
            if not done.wait(3):
                os._exit(0)
        watch_parent(args.parent_pid, parent_exited, done)
    if args.ready_file:
        write_ready(args.ready_file, server.server_port, args.instance)
    if sys.stdout:
        print("OpenMap listening at http://%s:%d" % (args.host, server.server_port), flush=True)
        print("Supabase configured: %s" % application.auth.configured, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()
        done.set()
        if args.ready_file:
            args.ready_file.unlink(missing_ok=True)
