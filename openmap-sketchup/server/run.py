#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

from openmap_server.app import create_server


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
    args = parser.parse_args()
    config = {**read_env(args.env), **os.environ}
    config.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:%d" % args.port)
    server, application = create_server(config, args.host, args.port)
    print("OpenMap listening at http://%s:%d" % (args.host, server.server_port), flush=True)
    print("Supabase configured: %s" % application.auth.configured, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()
