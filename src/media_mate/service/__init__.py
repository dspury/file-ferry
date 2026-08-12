"""Sidecar bootstrap package.

The ``media_mate.service`` package is the sidecar process the desktop
shell supervises. Entry point: ``python -m media_mate.service``.

See ADR-0002 (IPC protocol) and ADR-0005 (application service module
structure).
"""

from media_mate.service.protocol import PROTOCOL_VERSION

__all__ = ["PROTOCOL_VERSION"]
