# ADR-0005 — Application service module structure

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** v0.2.4 `SPEC.md` §10 (extends, does not replace)

## Context

The plan §5.2 sketches a target layout:

```
src/media_mate/
  application/     project, source, intake, plan, job, receipt services
  persistence/     database connection, migrations, repositories, backup
  service/         JSON-RPC protocol, server, sidecar bootstrap
  capabilities/    compatibility home for probe/organize/proxy/verify/resolve
  cli.py            thin client over application services
  tui.py            thin client over application services
```

The plan also says: "Move existing modules only when a
compatibility-preserving extraction is proven by tests. It is
acceptable for the initial application services to call the current
modules in place; their business rules must not be duplicated in the
renderer or Electron main process."

The legacy CLI / TUI / capability modules are working code. They are
covered by 326 tests. We must not regress them. The "compatibility-
preserving foundation change" is the constraint.

This ADR freezes the new module structure and the migration policy
before code is written.

## Decision

**Frozen layout** (relative to `src/media_mate/`):

```
src/media_mate/
├── __init__.py                 # unchanged; __version__
├── cli.py                      # thin client over application services
├── tui.py                      # thin client over application services
├── config.py                   # unchanged
├── models.py                   # unchanged; legacy pydantic models
├── drives.py                   # unchanged
├── log.py                      # unchanged; legacy audit log
├── probe.py                    # unchanged
├── organize.py                 # unchanged
├── proxy.py                    # unchanged
├── verify.py                   # unchanged
├── resolve.py                  # unchanged
├── errors.py                   # unchanged
│
├── application/                # NEW: business services
│   ├── __init__.py
│   ├── projects.py             # ProjectService (CRUD)
│   ├── sources.py              # SourceService (intake scanning)
│   ├── intake.py               # IntakePlanner (plan + capacity)
│   ├── jobs.py                 # JobScheduler + JobState
│   ├── replicas.py             # ReplicaService (verify gate)
│   ├── assets.py               # AssetService (identity)
│   ├── receipts.py             # OperationReceipt writer
│   ├── policies.py             # StoragePolicy + verification
│   └── service.py              # ApplicationService (the root)
│
├── persistence/                # NEW: DB layer
│   ├── __init__.py
│   ├── connection.py           # SQLite conn with WAL + FK + busy timeout
│   ├── migrations.py           # numbered migration runner
│   ├── backup.py               # backup + restore helpers
│   ├── schema_meta.py          # schema_version bookkeeping
│   ├── repositories/           # one repo per entity
│   │   ├── __init__.py
│   │   ├── projects.py
│   │   ├── sources.py
│   │   ├── intake_sessions.py
│   │   ├── replicas.py
│   │   ├── jobs.py
│   │   └── audit_events.py
│   └── migrations/             # numbered, ordered
│       ├── __init__.py
│       ├── 001_initial_legacy.py
│       ├── ...
│       └── 007_vnext_entities.py
│
├── service/                    # NEW: sidecar bootstrap
│   ├── __init__.py
│   ├── protocol.py             # JSON-RPC envelope + message types
│   ├── server.py               # async server; reads stdin, writes stdout
│   ├── cli.py                  # `python -m media_mate.service`
│   └── client.py               # in-process typed client (CLI/TUI use)
│
└── capabilities/               # NEW: namespace for the existing modules
    ├── __init__.py             # re-exports for backward compatibility
    └── _legacy.py              # one-line aliases for probe/organize/etc.
```

**Migration policy:** existing modules stay where they are. The
`capabilities/` package exists to provide a future home for them
when the application services are stable enough to receive the
move. The application services in `application/` and `persistence/`
call into the existing modules (`probe.py`, `organize.py`, etc.)
in place. The CLI and TUI continue to call the existing modules
directly. **No mass-rename.** No re-export churn. No deprecation
aliases that do nothing.

**In-process client.** The CLI and TUI use the in-process typed
client (`media_mate.service.client.ApplicationClient`) to invoke
application services. This client speaks the same protocol the
desktop sidecar exposes, but in-process. The protocol types are
shared. This is what makes the desktop shell and the CLI / TUI
behaviorally identical.

**`application/service.py`** is the assembly root. It constructs
the SQLite connection, the migration runner, the repositories, and
the services, in dependency order. The CLI, the TUI, and the
sidecar all instantiate `ApplicationService` once. It is the
boundary between "ways of invoking" and "the actual work."

**Cross-platform Python target.** Python 3.11+ (matches the existing
floor in `pyproject.toml`). The `tier 3` target platforms (Windows,
Linux) are tested for the application services in CI; the desktop
packaging targets are macOS first, with Windows and Linux as
explicit "not yet packaged" follow-ups.

**Type discipline.** Every service method has a pydantic input
model and a pydantic output model. Repository methods are typed
against the persisted entities. Mypy strict remains the gate.

## Consequences

Positive:

- The legacy module surface is not disturbed. v0.2.4 CLI / TUI
  users see no change.
- The application services are testable in isolation. The recovery
  tests in the test matrix can exercise a single service without
  going through the sidecar.
- The service client (IPC) is the same protocol as the in-process
  client. The desktop and the CLI are talking to the same code,
  not two implementations.

Negative:

- The tree is wider. Module count grows from 11 to ~25.
- New modules mean new tests. The legacy 326 tests still pass; the
  new modules must add coverage equal to their responsibility.

Neutral:

- The desktop shell and the CLI / TUI consume the same `application/`
  code. The desktop is not a second implementation.
- The `capabilities/` namespace is a placeholder; it can be
  collapsed when the existing modules are moved into it.

## References

- `docs/MEDIA-MATE-FULL-APP-IMPLEMENTATION-PLAN.md` §5.2, §9
- `docs/MEDIA-MATE-PRODUCT-DIRECTION.md` §8
- v0.2.4 `SPEC.md` §10 (existing layout)
- ADR-0001 (desktop shell — the sidecar imports this module structure)
- ADR-0002 (IPC protocol — the protocol types live in `service/protocol.py`)
- ADR-0003 (persistence — the `persistence/` package implements §6.1)
