# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""The `bakex` command-line interface.

A thin, dependency-light (stdlib argparse) entry point so operators have a
first-class command: `bakex serve` to run the app, `bakex version` to check the
build. Kept intentionally small; richer subcommands (e.g. scan-container) can be
added as the API surface stabilises.
"""

from __future__ import annotations

import argparse
import sys

from bakex import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bakex",
        description="BakeX — bake a hardened, CIS/STIG-benchmarked golden image from a YAML blueprint.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_serve = sub.add_parser("serve", help="Run the BakeX web app + API")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")

    sub.add_parser("version", help="Print the BakeX version")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"bakex {__version__}")
        return 0

    if args.command == "serve":
        import uvicorn  # noqa: PLC0415 — deferred so `bakex version` needs no server deps

        uvicorn.run("bakex.main:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    # No command given: show help, signal misuse.
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
