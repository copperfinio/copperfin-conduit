"""Compatibility wrapper for the Conduit CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=20129)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--cache-probe", action="store_true")
    parser.add_argument("--quick-tunnel", action="store_true")
    parser.add_argument("--install-cloudflared", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args()

    start = [
        sys.executable,
        "-m",
        "conduit.cli",
        "start",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    start.append("--foreground" if args.foreground else "--background")
    subprocess.run(start, check=True)

    if args.smoke or args.cache_probe:
        smoke = [
            sys.executable,
            "-m",
            "conduit.cli",
            "smoke",
            "--root-url",
            f"http://{args.host}:{args.port}",
        ]
        if args.cache_probe:
            smoke.append("--cache-probe")
        subprocess.run(smoke, check=True)

    if args.quick_tunnel:
        tunnel = [
            sys.executable,
            "-m",
            "conduit.cli",
            "tunnel",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.install_cloudflared:
            tunnel.append("--install-cloudflared")
        return subprocess.call(tunnel)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
