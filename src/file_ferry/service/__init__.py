"""Sidecar bootstrap package.

The ``file_ferry.service`` package is the sidecar process the desktop
shell supervises. Entry point: ``python -m file_ferry.service``.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from file_ferry.service.protocol import PROTOCOL_VERSION

__all__ = ["PROTOCOL_VERSION"]
