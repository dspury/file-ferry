# Architecture Decision Records

This directory holds the frozen architectural decisions for the
media-mate vNext implementation. ADRs are written once when a
decision is made and updated only when the decision itself changes.

## Accepted

| # | Title | Date |
|---|---|---|
| [0001](0001-desktop-shell-architecture.md) | Desktop shell architecture (Electron + Python sidecar) | 2026-08-12 |
| [0002](0002-ipc-protocol-stdio-json-rpc.md) | IPC protocol: stdio JSON-RPC | 2026-08-12 |
| [0003](0003-application-persistence.md) | Application persistence model (SQLite + migrations) | 2026-08-12 |
| [0004](0004-safe-to-format-policy.md) | Safe-to-format policy and replica verification | 2026-08-12 |
| [0005](0005-application-service-modules.md) | Application service module structure | 2026-08-12 |

## Format

Each ADR follows the [MADR](https://adr.github.io/madr/) format:

- **Status** — `Accepted`, `Superseded`, or `Deprecated`
- **Date** — when the decision was frozen
- **Context** — the problem and constraints
- **Decision** — what we are doing
- **Consequences** — positive, negative, neutral
- **References** — links to the plan, product direction, and other ADRs

## Authority

These ADRs are the contract between the plan and the code. Once an
ADR is `Accepted`, code that contradicts it is a bug. Changing an
ADR requires a new ADR that names the predecessor and the reason
for the change.
