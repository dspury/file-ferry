"""Sidecar CLI entry point.

Launches the JSON-RPC server on stdin/stdout. The desktop shell
supervises this process; an interactive invocation is supported for
debugging via the ``--once`` flag, which reads a single request frame
from stdin and emits a single response frame on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from media_mate.service import PROTOCOL_VERSION
from media_mate.service.server import SidecarServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="media-mate-service")
    parser.add_argument("--db", type=Path, default=None, help="override the default SQLite path")
    parser.add_argument(
        "--once",
        action="store_true",
        help="read one request from stdin, write one response, exit (debug only)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the protocol version and exit",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(f"media-mate service protocol version: {PROTOCOL_VERSION}")
        return 0

    server = SidecarServer(db_path=args.db)
    if args.once:
        return server.run_once(sys.stdin, sys.stdout)
    return server.run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
