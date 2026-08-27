"""Sidecar CLI entry point.

Launches the JSON-RPC server on stdin/stdout. The desktop shell
supervises this process; an interactive invocation is supported for
debugging via the ``--once`` flag, which reads a single request frame
from stdin and emits a single response frame on stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import SupportsWrite

from file_ferry.application.service import ApplicationService
from file_ferry.paths import default_db_path
from file_ferry.service import PROTOCOL_VERSION
from file_ferry.service.server import SidecarServer
from file_ferry.service.wiring import wire_server


def warn_on_host_protocol_mismatch(
    declared: str | None, stream: SupportsWrite[str] = sys.stderr
) -> bool:
    """Report a host/sidecar protocol-version disagreement. Returns True if warned.

    The desktop shell passes its own ``PROTOCOL_VERSION`` as
    ``FERRY_PROTOCOL_VERSION`` when it spawns us. Negotiation itself stays in
    the frames (ADR-0002: the lower-version endpoint declines with
    ``version_mismatch``), so a disagreement is not fatal here — but saying so
    once at startup beats leaving the operator to infer it from every request
    failing. Electron pipes our stderr into ``sidecar.log``.
    """
    if declared is None or declared.strip() == "":
        return False
    if declared.strip() == str(PROTOCOL_VERSION):
        return False
    print(
        f"warning: host declares protocol version {declared.strip()!r}, "
        f"this sidecar speaks {PROTOCOL_VERSION}; requests will be declined "
        f"with version_mismatch until the two agree",
        file=stream,
    )
    return True


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

    warn_on_host_protocol_mismatch(os.environ.get("FERRY_PROTOCOL_VERSION"))

    db_path = args.db or default_db_path()
    service = ApplicationService(db_path=db_path, app_data_dir=args.app_data or db_path.parent)
    service.bootstrap()

    server = SidecarServer(db_path=db_path)
    wire_server(server, service)

    if args.once:
        return server.run_once(sys.stdin, sys.stdout)
    return server.run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
