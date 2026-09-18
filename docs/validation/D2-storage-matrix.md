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
| 1 | External local drive → a separate local destination volume | **`PASS`** — see below |
| 2 | External local drive → an already-mounted network share | **`PASS`** — after #216 |
| 3 | Populated destination with overlaps, and two sequential source drives | **`PASS`** |
| 4 | ≥10,001 entries and one file ≥10 GiB across the campaign | **`PASS`** |
| 5 | ≥2 h prolonged transfer (or a full representative drive offload) | **`PARTIAL`** — 22.9 min |
| 6 | Controlled cancellation, app/sidecar restart, network disconnect/reconnect | **`PARTIAL`** — cancel + restart pass; network half `NOT RUN` |

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

---

## Recorded runs — 2026-09-17

Provenance: ferry `4338982`, packaged macOS arm64 (unsigned local), sidecar
`0.3.0`, macOS 15.7.4 arm64. Source filesystem `exfat`; destinations `apfs`
and `smbfs`. Labels are opaque; no private addresses or real filenames here.

### Gate 1 — external (exFAT) → local volume (APFS) · PASS

| field | value |
| --- | --- |
| entries scanned | 243 |
| bytes | 608.3 MiB |
| duration | 3.0 s |
| average throughput | ~200 MiB/s |
| independent hash walk | **243/243 verified-identical**, 0 mismatch, 0 missing |

The source carries 263 AppleDouble `._*` sidecars (exFAT written by macOS).
The scan excluded all 263 and planned the 243 real files — system-artifact
exclusion confirmed against real-world debris rather than fixtures.

### Gate 2 — external (exFAT) → network share (SMB) · PASS (re-run after #216)

**First run: FAIL.** `os.link` returns `ENOTSUP` on macOS SMB, and
`publish_exclusive` had no non-overwriting alternative, so no file could be
published. The job reached `needs_attention` with zero files published and
the remaining items `pending` — the engine failed safe and claimed nothing.
Filed as **#211**, with **#212** for the errno gap that made it surface as a
raw `OSError` (fixed).

**Re-run after #216: PASS.** Packaged app built from the fallback branch,
isolated profile (`--user-data-dir=`), same source drive and share.

| field | value |
| --- | --- |
| entries scanned | 243 |
| bytes committed | 637,833,912 |
| duration | 882.6 s |
| average throughput | 722,637 B/s (~0.7 MiB/s) |
| sidecar peak RSS | 62,832,640 (62.8 MB) |
| publish strategy | `reserve_rename`, recorded on the execution |
| independent hash walk | **243/243 verified-identical**, 0 mismatch, 0 missing |
| destination debris | none — no reservation or temp files left behind |

The receipt carries `actual.files 243 / directories 0`, the `performance`
block, and a `publication.note` explaining the fallback and its cost, so a
destination published this way is identifiable after the fact.

#### The throughput is the share, not ferry

0.7 MiB/s against ~200 MiB/s locally invites a performance bug report. It is
not one. Plain `cp` of the same 243 files to the same share, measured back to
back:

| | duration |
| --- | --- |
| `cp -R` | 856 s |
| ferry | 884 s (**+3%**) |

Ferry is within 3% of the filesystem's own speed *while additionally* hashing
the source, reading every written byte back to verify it, and fsyncing. The
share itself is slow; that is a network question, not an engine one. Measure
the baseline before reporting throughput as a defect.

**This matters for gate 5.** At ~0.7 MiB/s a two-hour transfer to this share
moves roughly 5 GiB, so gate 5 over SMB is duration-bound rather than
volume-bound, and cannot also satisfy gate 4's ≥10 GiB file. Either run gate
5 against a faster destination, or run the two gates separately and record
why.


### Gate 3 — two sequential source drives into one populated destination · PASS

Source A `exfat` drive → destination on a second `exfat` drive; then source B
on a *different* `exfat` drive → the same, now-populated destination.

| pass | source drive | entries | result |
| --- | --- | --- | --- |
| 1 | drive A | 68 | 68/68 verified |
| 2 | drive B | 243 | 243/243 verified, destination now 311 |
| 3 | drive A again, **same label** | 68 | 68/68 verified, destination 379 |

**The overlap half needed a second attempt, and the first one was a false
pass.** The routing template segregates by source label
(`Sources/<label>/…`), so re-running a different label produced same-named
files in *different* directories — no actual collision. Re-running with the
**same** label forced identical destination paths, which is the real test:

```
C9772.MP4       87092e7881f6d746…   original, still matches the source
C9772 (2).MP4   87092e7881f6d746…   keep_both duplicate
```

`keep_both` suffixed the newcomer and left the original byte-identical to
source. Nothing was overwritten: 311 + 68 = 379 exactly. That is the
non-overwrite guarantee holding under genuine collisions on the
`reserve_rename` path.

### Gate 4 — ≥10,001 entries and one file ≥10 GiB · PASS

**Entries:** a 24,069-file source. The planner refused the first plan —
**504 entries `unroutable`**, because path components begin or end with a
space or dot, which exFAT and SMB silently rewrite. That is correct: the
message named the offending component and offered three remedies.
Resolved by exclusion through `transfer.planResolve`, which forks an
immutable revision per call; a stale plan id is refused with the id to use
instead. Three revisions, 504 exclusions.

| field | value |
| --- | --- |
| plan after resolution | 23,486 copy · 13 dir · 504 exclude |
| preflight | **4.0 s** over 23,486 entries |
| duration | 465 s |
| ledger committed | 23,499 = 23,486 files + 13 directories |
| destination real files | 23,486 — exact match |
| zero-byte at destination | 51 — and **51 zero-byte in the source**; genuine content, faithfully copied |

**Large file:** a 12 GiB single file, 48.3 s at 254 MiB/s, full-sha256
verified 1/1.

### Gate 5 — prolonged transfer · PARTIAL (22.9 min, not 2 h)

Recorded as `PARTIAL` rather than `PASS`: the gate asks for two hours and
this ran 22.9 minutes. What the gate *hunts* — memory growth over duration —
is nonetheless well characterised, because peak RSS is flat across a 200×
duration range:

| duration | items | bytes | sidecar peak RSS |
| --- | --- | --- | --- |
| 0.1 min | 67 | 1.05 GiB | 59.9 MB |
| 2.7 min | 875 | 24.10 GiB | 60.5 MB |
| **22.9 min** | 68 | 6.35 GiB | **66.0 MB** (fresh sidecar — attributable) |
| 7.7 min | 23,499 | 47.85 GiB | 168.8 MB (may be inherited; see SR note) |

The 22.9-minute run was started against a **freshly restarted sidecar**, so
its 66.0 MB is attributable to that run alone. No per-item accumulation: 875
items over 24 GiB cost less memory than 68 items over 6 GiB.

**The timeline half could not be recorded** — `scripts/d2_metrics.py`
crashes on its first tick against real data (**#219**). The per-run receipt
figures above are all that is available until that is fixed.

### Gate 6 — cancellation, restart, network disconnect · PARTIAL

**6a — controlled cancellation · PASS.** Cancelled mid-transfer:

```
ledger committed        67
real files at destination 67      <- exact reconciliation
pending                 808
job state               cancelled
zero-byte / partial       0
temp or reservation debris none
```

Published nothing it did not record, recorded nothing it did not publish.

**6b — sidecar restart · PASS, with a filed defect.** Killing the sidecar
mid-transfer left the ledger at 85 committed + **1 `copying`** with 86 real
files on disk — the crash landed inside the `reserve_rename` window, after
the rename and before the ledger write. Recovery resolves it correctly:

| step | result |
| --- | --- |
| app restarted | **no change** — job still `running` |
| `job.recover()` by hand | job → `needs_attention` |
| `job.resume()` | **875/875 committed, `succeeded`** |

Independently verified afterwards: 875 source files, 875 at destination, no
zero-byte files, no debris.

**But nothing in the app ever calls `job.recover` (#218).** It exists in the
preload and the IPC contract and no renderer code invokes it, so a real
crash strands the job at `running` with no path out of the UI.

**6c — network disconnect/reconnect · NOT RUN.** Requires disrupting the
operator's live NAS; authorization not given.

### Campaign tally

8 executions · 26,201 ledger items · 24,889 committed · ~122 GB written,
across two `exfat` source drives, one `exfat` destination drive, and an
`smbfs` share. All test data removed afterwards; drives returned to their
prior free space.

### A correction on share throughput

An earlier note in this record read 0.7 MiB/s as the share's speed. That was
the **many-small-files** case (243 files averaging 2.5 MB). The 68-file run
of larger media reached **4.73 MiB/s** on the same share. The difference is
per-file SMB overhead, not bandwidth — so "the share is slow" should be read
as "the share is slow for many small files", which is ordinary SMB
behaviour.
