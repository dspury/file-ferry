"""Persistence layer for the vNext application services.

The :mod:`file_ferry.persistence` package owns the SQLite database
connection, the numbered migration runner, the schema-version
bookkeeping, and the per-entity repositories. The application
services consume the repositories; the sidecar uses the connection
to enforce the single-writer rule.

See ADR-0003 (application persistence model).
"""

from file_ferry.persistence import migrations, runner

__all__ = ["migrations", "runner"]
