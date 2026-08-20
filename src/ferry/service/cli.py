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

from ferry.application.service import ApplicationService
from ferry.service import PROTOCOL_VERSION
from ferry.service.server import SidecarServer
from ferry.service.wiring import wire_server


def _default_db_path() -> Path:
    """Return the default SQLite path under the user's app-data dir."""
    import platform as _platform

    base = {
        "Darwin": Path.home() / "Library" / "Application Support",
        "Windows": Path.home() / "AppData" / "Local",
    }.get(_platform.system(), Path.home() / ".local" / "share")
    return base / "ferry" / "ferry.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ferry-service")
    parser.add_argument("--db", type=Path, default=None, help="override the default SQLite path")
    parser.add_argument(
        "--app-data",
        type=Path,
        default=None,
        help="override the app-data dir (receipts, backups, logs)",
    )
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
        print(f"ferry service protocol version: {PROTOCOL_VERSION}")
        return 0

    db_path = args.db or _default_db_path()
    service = ApplicationService(db_path=db_path, app_data_dir=args.app_data or db_path.parent)
    service.bootstrap()

    server = SidecarServer(db_path=db_path)
    wire_server(server, service)

    if args.once:
        return server.run_once(sys.stdin, sys.stdout)
    return server.run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
