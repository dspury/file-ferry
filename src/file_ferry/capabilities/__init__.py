"""Compatibility namespace for the existing capability modules.

The :mod:`file_ferry.capabilities` package is the future home of the
existing modules (``probe``, ``organize``, ``proxy``, ``verify``,
``resolve``, ``log``). The foundation cut provides a thin re-export
layer so the application services can address the legacy modules
by their canonical names without depending on the legacy layout.

The actual move (from module-level to package-level) happens once
Package 2.1 is complete; until then every existing module stays
in place and is imported through the legacy paths.
"""
