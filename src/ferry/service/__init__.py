"""Sidecar bootstrap package.

The ``ferry.service`` package is the sidecar process the desktop
shell supervises. Entry point: ``python -m ferry.service``.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from ferry.service.protocol import PROTOCOL_VERSION

__all__ = ["PROTOCOL_VERSION"]
