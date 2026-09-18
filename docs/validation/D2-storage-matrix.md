# D-2 (§12.2) — real storage matrix: record template

**Status: `NOT RUN`.** Every gate below is `NOT RUN` until an operator runs it
and fills the section in. This file is blank on purpose.

> Do not write `PASS` anywhere you did not run. A gate with no entry is
> `NOT RUN`, not passed. §12.2 is explicit that simulated adapters do not
> satisfy the real interruption gate, and that if hardware or permission is
> unavailable the exact gate is marked `NOT RUN` and everything else finishes
> — **and P7 is not marked production-validated.**

## How to use this file — and the leak rule

§12.2: **keep private addresses and filenames out of committed artifacts.**
This template is designed so following it does not:

- Any field marked **(opaque)** takes a short **label**, never a real value.
  Use `SRC-A`, `DEST-NAS-1`, `SHARE-2`, `HOST-1` — not a real filename,
  volume name, share path, IP, hostname, or user name.
- Record raw data — the collector timeline, the sha256 manifest, screenshots —
  wherever the campaign keeps artifacts, **outside the repository**, and put
  only its opaque reference (`ARTIFACT-1`) and its tally in this file.
- Do not paste directory trees, mount paths, `df` output, or `ps` output.

The procedure that produces each field is in
[`D2-operator-procedure.md`](D2-operator-procedure.md).

One measurement caveat, repeated here because it is a receipt a later reader
will trust: a receipt's `sidecarPeakRssBytes` is the sidecar's peak **since it
started**, not this run's. The sidecar is long-lived, so restart it before a
timed gate, and take every **per-run** peak in this file from the collector
timeline, never from the receipt's single number.

---

## Campaign provenance

| field | value |
| --- | --- |
| Date started / finished | |
| OS and version | |
| Hardware (model, CPU, RAM) | |
| ferry git commit | |
| Packaged app (opaque reference) | |
| App binary sha256 | |
| Frozen sidecar sha256 | |
| Sidecar version (`app.getStatus`) | |
| Signing status (unsigned local / signed) | |
| Collector command / version | |
| Independent-verifier command | |

## Gate status board

| # | gate (§12.2) | status |
| --- | --- | --- |
| 1 | External local drive → a separate local destination volume | `NOT RUN` |
| 2 | External local drive → an already-mounted network share | `NOT RUN` |
| 3 | Populated destination with overlaps, and two sequential source drives | `NOT RUN` |
| 4 | ≥10,001 entries and one file ≥10 GiB across the campaign | `NOT RUN` |
| 5 | ≥2 h prolonged transfer (or a full representative drive offload) | `NOT RUN` |
| 6 | Controlled cancellation, app/sidecar restart, network disconnect/reconnect | `NOT RUN` |

Gate 4 is a **campaign-level** tally, not a single run: aggregate it from all
gates at the end.

---

## Gate 1 — external local drive → separate local destination volume

**Status: `NOT RUN`**

### Setup

| field | value |
| --- | --- |
| Source drive (opaque) | |
| Destination volume (opaque) | |
| Source filesystem type | |
| Destination filesystem type | |
| Drive connection (USB / Thunderbolt / internal) | |

### Counts and bytes

| entries | files | dirs | total bytes | exclusions | failures |
| --- | --- | --- | --- | --- | --- |

### Timing and performance

| duration (s) | avg throughput (B/s) | peak throughput (B/s) | sidecar peak RSS | app peak RSS | timeline ref |
| --- | --- | --- | --- | --- | --- |

### DB / job state over time

| samples | states observed | final job state | receipt final state | timeline ref |
| --- | --- | --- | --- | --- |

### Receipt integrity

| receipt hash matches | export matches | committed entries | checksums match | checksums missing |
| --- | --- | --- | --- | --- |

### Independent hash comparison

| tool | algorithm | verified-identical | MISMATCH | missing | residual | manifest ref |
| --- | --- | --- | --- | --- | --- | --- |

### Observed issues

-

---

## Gate 2 — external local drive → already-mounted network share

**Status: `NOT RUN`**

### Setup

| field | value |
| --- | --- |
| Source drive (opaque) | |
| Network share (opaque) | |
| Source filesystem type | |
| Destination filesystem type | |
| Network mount protocol (SMB / NFS / AFP / other) | |
| Link (wired / wireless) | |

### Counts and bytes, timing, DB state, receipt integrity, independent walk

Use the same five tables as Gate 1, with the share as destination. Record
**OS-blocked I/O exceptions** here and in the issues list — a share that
refused an operation is a finding, not a silent gap.

### Observed issues

-

---

## Gate 3 — populated destination with overlaps, two sequential source drives

**Status: `NOT RUN`**

### Setup

| field | value |
| --- | --- |
| Destination (opaque, pre-populated) | |
| Pre-existing overlap count | |
| Conflict policy in force | |
| Source drive A (opaque) | |
| Source drive B (opaque) | |
| Both drives present at once? (should be no) | |

### Counts and bytes

| source | entries | files | dirs | bytes | conflicts found | kept-both | skipped | review |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | | | | | | | | |
| B | | | | | | | | |

### Timing, DB state, receipt integrity, independent walk

Same tables as Gate 1, per source drive.

### Observed issues

-

---

## Gate 4 — ≥10,001 entries and a file ≥10 GiB (campaign tally)

**Status: `NOT RUN`**

| field | value |
| --- | --- |
| Total entries across the campaign | |
| Total bytes across the campaign | |
| Largest single file (GiB) — gate satisfied? | |
| Where the ≥10 GiB file was transferred (gate ref) | |
| Did any individual directory reach ≥10,001 entries? | |

> Do not manufacture confidence from repeated tiny-file tests (§12.2). This
> tally must come from real runs, and the ≥10 GiB file must actually be
> transferred and independently verified.

### Observed issues

-

---

## Gate 5 — ≥2 h prolonged transfer (or full representative drive offload)

**Status: `NOT RUN`**

This is where the §12.2 instrumentation matters. Attach the timeline, not a
single number: sustained throughput is the curve, not one average.

### Setup

| field | value |
| --- | --- |
| Source (opaque) | |
| Destination (opaque) | |
| Planned duration / representative drive size | |
| Actual duration (h) | |

### Sustained throughput (from the timeline)

| samples | avg throughput (B/s) | peak interval throughput (B/s) | throughput floor (B/s) | stalls observed |
| --- | --- | --- | --- | --- |

### Memory

| sidecar peak RSS | app peak RSS | memory growth over time | returns to baseline after? |
| --- | --- | --- | --- |

### DB / job state over time

| samples | states observed | rows in `transfer_execution_items` over time | final job state | receipt final state |
| --- | --- | --- | --- | --- |

### Receipt integrity

| receipt hash matches | export matches | committed entries | checksums match | checksums missing |
| --- | --- | --- | --- | --- |

### Independent hash comparison

Same table as Gate 1. A two-hour copy must still be independent-walk clean.

### Observed issues

-

---

## Gate 6 — controlled cancellation, restart, network disconnect/reconnect

**Status: `NOT RUN`**

**Authorization for actual device/network disruption is required.** Simulated
adapters do not satisfy this gate. If authorization is unavailable, mark each
sub-gate `NOT RUN` and say why — do not substitute a simulation.

### 6a — controlled cancellation

| field | value |
| --- | --- |
| Cancel issued at (elapsed / bytes) | |
| Cancel acknowledged within 2 s? | |
| Job final state | |
| Partial output left in place / cleaned? | |
| Receipt final state and committed count | |
| Source card still required (message present)? | |
| Independent walk of partial output | |

### 6b — application / sidecar restart

| field | value |
| --- | --- |
| Restart point (elapsed / bytes) | |
| Job state before / after | |
| Receipt final state | |
| Resume reused partial output? | |
| Independent walk after resume | |

### 6c — network disconnect / reconnect

| field | value |
| --- | --- |
| Disconnect point | |
| Operator-visible behaviour | |
| Reconnect point | |
| Job state before / after | |
| Resume succeeded? | |
| Independent walk after resume | |

### Observed issues

-

---

## Campaign close-out

| field | value |
| --- | --- |
| All six gates run? (if not, list `NOT RUN` and why) | |
| P7 production-validated? | **No** until all six are run and clean |
| Signing / notarization | follows release policy (D-4); an unsigned pilot is not a stable release |
| Remaining risks | |
| Operator / date | |
