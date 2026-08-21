# ADR-0002 — IPC protocol: stdio JSON-RPC

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** none (new contract)

## Context

Electron main and the Python sidecar need a transport. The plan §5.1
names JSON-RPC over stdio. The choice needs rationale and a frozen
protocol version before any code is written.

Constraints:

- Avoid a listening port (no auth story, no firewall drama, no
  stale-port failure mode after a crash).
- Bind privately to the desktop process; never expose the service
  outside Electron's own children.
- Support request/response and asynchronous event streams from the
  sidecar to the renderer through main.
- Be small enough to maintain by hand if necessary; we do not need a
  full RPC framework.
- Allow a clean sidecar restart and a clean renderer reload without
  dropping in-flight subscriptions.

## Decision

**JSON-RPC 2.0 over stdio, with a versioned envelope and per-request
correlation IDs.**

Wire format: one JSON value per line, terminated by `\n`. Each line is
either a request (renderer/main → sidecar), a response (sidecar →
renderer/main), or an event (sidecar → main). The framing is
newline-delimited JSON (NDJSON); transport is the child's stdin and
stdout.

Envelope:

```jsonc
{
  "jsonrpc": "2.0",
  "v": 1,                      // media-mate protocol version
  "kind": "request" | "response" | "event" | "error",
  "id": "<uuid>",              // present on request and response
  "method": "<dotted.name>",   // present on request and event
  "params": { ... },           // present on request and event
  "result": { ... },           // present on response
  "error": { "code": ..., "message": ..., "data": { ... } }
}
```

**Protocol version negotiation.** Both endpoints declare their
`v` on the first frame. If the major version differs, the lower
version declines with a `version_mismatch` error and the desktop
shell surfaces a recovery action ("update the sidecar" or "use an
older desktop"). The desktop shell pins the minimum supported sidecar
version; the sidecar pins the maximum supported desktop version.

**Schema validation.** Each method has a JSON Schema (or pydantic
model on the sidecar, TypeScript type on the desktop). Both sides
validate inbound and outbound. Validation failures are typed errors
with `code: "schema_invalid"` and a pointer to the offending field.

**Subscriptions.** A `subscribe` request returns the current snapshot
synchronously, then a stream of `event` frames with the same
correlation. The subscription is torn down by a `unsubscribe` request
or by process exit.

**Lifecycle.** The sidecar is launched by Electron main. The sidecar
sends a `ready` event on startup. The sidecar exits with a
documented exit code if it cannot initialize. Electron main owns
restart, with a backoff and a max restart count; repeated crashes
surface a desktop notification and disable sidecar-dependent UI.

**Alternatives considered:**

- *Localhost TCP with auth.* Rejected: requires an auth story, is
  observable by other local processes, fails on port collision after
  a crash, and offers no benefit over stdio inside a single
  process group.
- *Named pipe / Unix domain socket.* Rejected: Windows named pipes
  have a different API than Unix domain sockets, which complicates
  cross-platform packaging; stdio is identical across all three
  target platforms.
- *HTTP (loopback).* Rejected: overkill, requires an HTTP server in
  the sidecar, doesn't improve on stdio's simplicity.
- *Standard input across file descriptors other than 0/1.* Rejected:
  no benefit; on macOS and Linux stdio is the conventional IPC
  channel between a parent and a supervised child.

## Consequences

Positive:

- No listener port; no auth story; the only process that can reach
  the sidecar is its parent.
- Selection of the protocol is trivial in Python (stdlib `json`) and
  in TypeScript (`vscode-jsonrpc` is a known reference, but we will
  write the parser by hand for size and transparency).
- Restart is clean: the parent closes the pipes, the child exits;
  the next launch is a fresh protocol session.
- The protocol envelope is plain text; debugging is `cat` and `jq`.

Negative:

- Stdio has a practical buffer size (~64 KB on Linux, OS-dependent
  elsewhere). The protocol must be chunked; we will use per-line
  framing so a single message is bounded by the JSON content, not the
  buffer. Large payloads (audit-log query results, full receipts) are
  paginated explicitly, not streamed as one big frame.
- The protocol is a security boundary. Any message that can do work
  must be reviewed as a security boundary.

Neutral:

- The desktop node_modules tree gains a small TypeScript protocol
  parser and JSON-Schema validator. The Python side uses pydantic
  models for the same shape, plus the standard library `json` module.

## References

- `docs/MEDIA-MATE-FULL-APP-IMPLEMENTATION-PLAN.md` §5.1, §8.3
- ADR-0001 (desktop shell architecture)
- JSON-RPC 2.0 spec: https://www.jsonrpc.org/specification
