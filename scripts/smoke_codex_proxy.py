"""Compatibility wrapper for `conduit smoke`."""

from __future__ import annotations

import argparse

from conduit.smoke import run_smoke


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-url", default="http://127.0.0.1:20129")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--cache-probe", action="store_true")
    args = parser.parse_args()

    for line in run_smoke(
        root_url=args.root_url,
        api_key=args.api_key or None,
        model=args.model,
        cache_probe=args.cache_probe,
    ):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
