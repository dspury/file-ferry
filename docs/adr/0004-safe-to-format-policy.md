# ADR-0004 — Safe-to-format policy and replica verification

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** v0.2.4 opening plan (does not change shipped v0.2.4
  behavior)

## Context

The plan §2.6: "a card is never declared safe to format without
policy-satisfied, independently verified replicas. The default policy
requires a working and backup replica; users may choose a stricter
policy, never a hidden weaker one."

The plan §6.3: "a replica becomes verified only after the source and
destination checksum agree under a receipt-recorded algorithm."

The product direction §3.1: "Ferry must never say a card is safe
to format until the configured offload policy is satisfied."

"Verified" must therefore be precisely defined; "safe to format"
must be precisely gated. This ADR freezes both before any code is
written.

## Decision

### Replica verification semantics

A *replica* is a row in the `replicas` table that records one
physical location of one asset. A replica is *verified* when:

1. The source file's checksum was computed with the configured
   algorithm **A** at sidecar-internal time `t_source`.
2. The destination file's checksum was computed with the same
   algorithm **A** at sidecar-internal time `t_dest`.
3. The two checksums are byte-equal.
4. The comparison is recorded in the `replicas` row with
   `verified = 1`, `verified_at = t_dest`, `checksum_algo = A`,
   `source_checksum = <expected>`, `replica_checksum = <actual>`.

Default algorithm **A** is `xxhash64`. SHA-256 is available as an
opt-in. The chosen algorithm is recorded in the operation receipt,
not stored as a session preference (so receipts are self-describing).

**Sample verification is not sufficient for safe-to-format.** A
sample (e.g., 1-in-1000 blocks) is a fast proxy that catches gross
corruption but not the edge cases that bit-rot creates. Full-file
verification is required for the safe-to-format gate.

**No silent baseline replacement.** A replica that fails to verify
does NOT overwrite the prior verified record. The previous verified
record stays intact; the current attempt is recorded as a new
attempt with `verified = 0`. The source is not yet safe to format.

### Safe-to-format gate

The intake session records the configured policy. After every
operation, the gate is evaluated. The gate is satisfied only when
**all** of the following hold:

1. **Every required destination** in `intake_destinations` has at
   least one `replicas` row with `verified = 1` and the
   `checksum_algo` recorded in the session's policy.
2. **Source is still readable**, OR was readable at the time of the
   last successful verification (`source_readable_at` ≠ NULL).
3. **No `needs_attention` jobs** reference this source (no partial
   copy, no permission error in progress, no source eject in
   between).
4. **No uncertain warning** is open: e.g., a peer sidecar noted the
   source's volume fingerprint changed since the scan began (a
   possible continued write).
5. **The required checksum metadata is present** in every replica
   row (no NULL `checksum_algo`).

If any one of (1)–(5) fails, the safe-to-format gate is **NOT
satisfied**. The UI displays the exact unmet conditions, not a green
bar. The terminal state is "needs review" or "waiting on destination
N" — never "safe to format".

### Default policy

**Default policy requires one working replica + one backup replica.**

- *Working* = the producer's primary edit volume.
- *Backup* = a separately-attached drive (different physical
  volume, different mount point). Same-volume backup is rejected
  by the planner; the user must explicitly opt into a
  "best-effort single destination" policy that is allowed but
  visibly weaker.
- The user can opt into stricter (additional replicas, additional
  checksum algorithms, source-volume fingerprint verification on
  the source drive at the end of the run). The user **cannot opt
  into a weaker policy than the default** — the default is the
  floor, not the ceiling.

### Policy configuration

A project has a `storage_policy` record. The minimum shape:

```yaml
storage_policy:
  required_replicas: 2         # default; cannot be less than 1
  backup_on_different_volume: true  # default; cannot be relaxed
  checksum_algo: xxhash64      # default; sha256 also valid
  safety_reserve_bytes: 0       # free-space padding; default 0
  require_source_fingerprint: true  # default; cannot be relaxed
```

The CLI / desktop UI exposes the policy as a structured form with
clear warnings when the user is opting into a stricter policy. The
"automatically relax" controls do not exist; the user must
explicitly say "I want a single destination" and acknowledge the
consequence.

### Receipt format

The operation receipt stores the policy, the planned operations, the
actual results, every checksum, every warning, every failure, and
the final state. The receipt's hash covers the planned operations,
the checksums, and the final state — it does NOT cover timestamps
or host-derived paths. Two receipts of the same session differ in
metadata, not in substance.

The `safe_to_format` field on the intake session is a boolean
computed by the gate, not a user-settable flag. Setting it manually
is not a supported operation.

## Consequences

Positive:

- "Safe to format" is a verifiable statement. A reviewer can read
  the receipt and confirm the gate was satisfied.
- The default policy is impossible to relax silently. The user who
  wants a weaker policy presses a button, reads a warning, and
  confirms.
- The receipt is self-describing. Years from now, a reviewer can
  read the operation and know exactly what algorithm was used, on
  which file, with which result.

Negative:

- Full-file verification takes time. The product direction calls
  this out as a known tradeoff. The user can opt into a sample
  mode for non-critical operations (existing-media adoption?), but
  the safe-to-format gate never uses sample verification.
- The gate is strict. A source that was ejected mid-run is not
  safe to format, even if every byte was successfully copied. The
  user must re-mount the source to demonstrate continued
  readability.

Neutral:

- The CLI parity (per the plan §9) exposes the same gate via the
  same `ferry jobs` command. The desktop UI is the primary
  surface, but the gate is not desktop-specific.

## References

- `docs/FERRY-FULL-APP-IMPLEMENTATION-PLAN.md` §2.6, §6.3,
  §7.2, §11.2
- `docs/FERRY-PRODUCT-DIRECTION.md` §3.1, §6.1, §6.2
- ADR-0003 (persistence model — `replicas` table, `intake_sessions`
  table)
