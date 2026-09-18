# D-2 (§12.2) — operator procedure for the six physical gates

This is the step-by-step for the real storage matrix. It can be followed
without any other context. Fill in
[`D2-storage-matrix.md`](D2-storage-matrix.md) as you go.

**This procedure cannot be run by CI.** It needs external drives, a mounted
network share, two sequential source drives, and authorization to disrupt a
device/network. Sections §12.2 is explicit that **simulated adapters do not
satisfy the real interruption gate**. Where hardware or permission is
unavailable, mark the exact gate `NOT RUN`, give the reason, and finish
everything else — and do **not** mark P7 production-validated.

> Never write `PASS` for a gate you did not run. `NOT RUN` is a complete and
> acceptable answer.

---

## 0. Preconditions

- **Hardware:** two external local drives; a separate local destination
  volume; an already-mounted network share; a second source drive for the
  sequential-source gate.
- **Authorization:** explicit permission to disconnect/reconnect the network
  and to stop/restart the app and sidecar mid-transfer (gate 6). Without it,
  gate 6 is `NOT RUN`.
- **Disposable targets only.** Every source and destination used here is
  disposable. Nothing in this procedure touches an operator's real media.
- **Isolated application data.** Run the packaged app with a throwaway
  `--user-data-dir`; do not audit against the real profile.

## 1. Build the packaged app and record provenance

```sh
cd desktop
npm run package:mac:local          # unsigned local build; not a release
```

Record in the template: the git commit (`git rev-parse HEAD`), the app path
(opaque reference), the app binary and frozen sidecar sha256:

```sh
shasum -a 256 desktop/release/mac-arm64/ferry.app/Contents/MacOS/ferry
shasum -a 256 desktop/sidecar/arm64/ferry-service
```

The sidecar version comes from the running app (`app.getStatus`), not from a
checkout.

## 2. Launch the app against isolated data

```sh
desktop/release/mac-arm64/ferry.app/Contents/MacOS/ferry \
  --user-data-dir /tmp/d2-appdata
```

Use the Transfer workspace, or the CLI, to run each gate's flow:
destination → scan → plan → preflight → approve → transfer → receipt. The
CLI runs the same service contracts and is often easier for long runs:

```sh
.venv/bin/ferry --db /tmp/d2-appdata/ferry.db transfer start <plan-id> --fingerprint <fp>
```

## 3. Start the collector before each transfer

The app records duration, average throughput and the sidecar's peak RSS in
the receipt. The collector records what a long run needs that a receipt
cannot: the throughput curve, DB/job state sampled over time, and both
processes' memory.

```sh
python scripts/d2_metrics.py \
  --app-data /tmp/d2-appdata \
  --interval 30 \
  --out /tmp/d2-timeline-g1.jsonl
```

Leave it running for the whole transfer; stop it with Ctrl-C (it writes a
`.summary.json` beside the timeline). Keep the timeline **out of the repo**
and reference it in the record by an opaque id.

At the end of a gate, check receipt integrity and walk the destination
independently of ferry:

```sh
python scripts/d2_metrics.py --db /tmp/d2-appdata/ferry.db --verify-receipt
python scripts/d2_metrics.py --db /tmp/d2-appdata/ferry.db --verify-destination
```

`--verify-receipt` recomputes each stored receipt's sha256 against the
database's `receipt_hash`, checks the exported file byte-for-byte, and counts
committed entries whose recorded source/destination checksums agree.
`--verify-destination` re-hashes source and destination with sha256 and
compares them — ferry's own xxhash64 result is the claim; this is the
evidence. Both exit non-zero on a mismatch or a residual.

## 4. The six gates

Each gate: set up per the numbered steps, run the collector across the
transfer, then run both verifier commands, then fill that gate's section of
the template — including its **observed issues** and any OS-blocked I/O
exceptions.

### Gate 1 — external local drive → separate local destination volume

1. Connect the source drive and the destination volume.
2. Choose a disposable source set on the drive; note the drive and volume as
   opaque labels and their **filesystem types** (e.g. APFS, HFS+, exFAT).
3. Start the collector (§3), then run the transfer.
4. Run both verifiers. Record counts/bytes, duration, throughput (avg and
   peak from the timeline), peak RSS for both processes, final job state,
   receipt integrity, and the independent tally.

### Gate 2 — external local drive → already-mounted network share

As Gate 1, with the already-mounted share as destination. Additionally
record the **network mount protocol** (SMB / NFS / AFP) and the link type.
Record any OS-blocked I/O exception explicitly.

### Gate 3 — populated destination with overlaps, two sequential source drives

1. Pre-populate the destination with files that **overlap** the source names,
   and note the conflict policy in force (e.g. `keep_both`).
2. Run source drive A to completion; remove it; connect source drive B; run B.
   The two drives must be **sequential**, not both present.
3. Verify after each drive; record conflicts, kept-both, skipped-identical and
   review-required counts.

### Gate 4 — ≥10,001 entries and one file ≥10 GiB (campaign tally)

Not a separate run. Across gates 1–3 and 5:

- ensure at least one transfer includes **≥10,001 entries** (record the actual
  count), and
- transfer at least one file **≥10 GiB**, independently verified.

Aggregate the totals into the template's Gate 4 section. Do not infer this
from repeated tiny-file runs.

### Gate 5 — ≥2 h prolonged transfer (or a full representative drive offload)

A single transfer that runs **≥2 hours**, or a full representative drive
offload if that is longer. This is the sustained-throughput and memory gate:

- run the collector for the entire transfer;
- record the throughput curve (average, peak interval, floor, stalls), not a
  single number;
- record sidecar and app peak RSS and whether memory returns to baseline;
- record DB/job state over time from the timeline;
- verify receipt integrity and run the independent destination walk.

### Gate 6 — controlled cancellation, restart, network disconnect/reconnect

**Requires authorization** (§0). If unavailable, mark 6a–6c `NOT RUN` with
the reason.

- **6a cancellation:** start a transfer, issue Cancel mid-flight, and record
  whether it was acknowledged within two seconds, the final job state, what
  partial output remains, the receipt's final state and committed count, and
  whether the "card still required" message is present. Verify the partial
  output independently.
- **6b restart:** stop the app and sidecar mid-transfer, restart against the
  same app data, and record the job state before/after, whether resume reused
  partial output, the receipt, and the independent walk after resume.
- **6c disconnect/reconnect:** disconnect the network mid-transfer, observe
  the operator-visible behaviour, reconnect, and record the same fields as
  6b.

## 5. Close-out

1. Aggregate Gate 4 counts/bytes.
2. For every gate actually run, confirm the independent walk is clean
   (zero `MISMATCH`, zero missing, zero residual) and the receipt integrity
   checks pass. A gate with a residual is a finding, not a pass.
3. Fill the campaign close-out: which gates are `NOT RUN` and why; **P7 is not
   production-validated** until all six are run and clean; signing follows
   release policy (D-4) and an unsigned pilot is not a stable release.
4. Keep timelines, manifests and raw output outside the repository. In the
   committed record: opaque labels, tallies, and summary numbers only.

## 6. What is already automated (does not replace the gates)

- `pytest tests/test_d2_responsiveness.py` — job creation returns without
  waiting for the copy; cancel acknowledged within two seconds; plan and
  inventory pages hard-capped so the whole plan cannot reach the renderer.
- `pytest -m slow tests/test_d2_responsiveness.py` — the 100,000-entry
  synthetic planning run (bounded pages, measured time and peak RSS).
- `python scripts/d2_metrics.py --self-test` — the collector's own arithmetic.

These are evidence about responsiveness and the planner. They are **not** the
storage matrix.
