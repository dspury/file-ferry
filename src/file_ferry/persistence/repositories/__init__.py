"""Per-entity SQLite repositories.

Repositories are typed against the persisted entities. They operate on
a live ``sqlite3.Connection`` supplied by the caller (from
:mod:`file_ferry.persistence.connection`); they never own the
connection or the transaction boundary. The application services own
the transaction and combine repository calls with business rules.

See ADR-0005 (application service module structure).
"""

from file_ferry.persistence.repositories import (
    assets,
    audit,
    derivatives,
    intake,
    jobs,
    profiles,
    projects,
    replicas,
    sources,
)

__all__ = [
    "assets",
    "audit",
    "derivatives",
    "intake",
    "jobs",
    "profiles",
    "projects",
    "replicas",
    "sources",
]
