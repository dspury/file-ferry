"""Application services for the vNext architecture.

The :mod:`media_mate.application` package contains the business
services that the desktop shell, the CLI, and the TUI all consume.
The legacy capability modules (``probe``, ``organize``, ``proxy``,
``verify``, ``resolve``, ``log``) remain in place and are called by
the new services in this package verbatim — no re-implementation.

See ADR-0005 (application service module structure).
"""
