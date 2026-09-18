# D-1 (§12.1) — disposable local pilot: written record

**Result: PASS** for the §12.1 gate on the packaged macOS arm64 app.
D-2 is gated on this record and is **not** claimed by it. This is a local
pilot, not a production validation: an unsigned local build, local disks,
synthetic fixtures. §12.2 (real storage matrix) is untouched and every
physical gate there is `NOT RUN`.

Harness: `docs/validation/d1/run-pilot.mjs` (re-runnable; see below).

The harness **exits non-zero** unless every required condition holds —
`verified-identical` equals the expected file count, zero `MISMATCH`, zero
`missing-at-destination`, zero `not-in-plan`, `extra` empty, every empty
directory recreated, and the ledger reconciles — and it names each failing
check. A gate nobody has seen fail is not known to be a gate, so a negative
control is recorded below.

---

## Provenance — packaged release, not a checkout

| | |
| --- | --- |
| Git commit | `41f5334` — *Merge pull request #202 from dspury/docs/c1-a11y-record* |
| Packaged app | `desktop/release/mac-arm64/ferry.app` |
| App binary sha256 | `588478afc5f2bc73b6433d6e565a214dc830144be39a3d79805723292754ccd8` |
| Frozen sidecar sha256 | `5cffbc15744de39802ffd69d40f9089497cc0ca3022b1e2cf67ecf4355c11d4b` |
| Sidecar version (`app.getStatus`) | `0.3.0`, protocol `1` |
| Bundle version (`Info.plist`) | `0.0.0` (`CFBundleShortVersionString` / `CFBundleVersion`) |
| Signing | ad-hoc / linker-signed (unsigned local overlay); **not** a release build |
| Build command | `npm run package:mac:local` (built `desktop/sidecar/arm64/ferry-service` via PyInstaller, then electron-builder) |
| OS | macOS 15.7.4 (24G517), arm64 |

The sidecar sha is the one copied into the bundle
(`…/ferry.app/Contents/Resources/sidecar/ferry-service`), so the artifact under
test is the frozen binary, not `python -m file_ferry.service`.

DMGs were also produced (`ferry-0.0.0-arm64.dmg`); the pilot ran the `.app`
directly. The x64 DMG in the same build was produced **without** a sidecar
(`sidecar/x64` does not exist), which is expected on an arm64-only host and is
not exercised here.

---

## Fixtures — mixed real files, not text renamed

Generated fresh by the harness into a throwaway tree (isolated from any real
data). Formats confirmed with `file(1)`:

```
A001.MOV    ISO Media, Apple QuickTime movie
interview.wav  RIFF WAVE audio, Microsoft PCM 16-bit 44.1 kHz
hero.png    PNG image data, 320 x 240
IMG_0001.JPG  JPEG image data, JFIF, 200x150
brief.pdf   PDF document, version 1.4
archive.zip   Zip archive data
data.tar.gz   gzip compressed data
plate.bin   data (256 MiB)
```

The tree deliberately contains the §12.1 list:

- **representative media / documents / archives** — real H.264 `.MOV`,
  PCM `.WAV`, PNG, JPEG, PDF, ZIP, tar.gz (all encoded by `ffmpeg`/`zip`/`tar`,
  none renamed);
- **nested bundle** — `Bundles/Sample.photoslibrary/` with
  `Masters/2025/IMG_0001.JPG` and `Database/photos.db` inside;
- **large file** — `large/plate.bin`, 256 MiB (the D-2 gate is ≥10 GiB; this
  is a pilot-scale "large");
- **empty folders** — `Empty Folder/Nested Empty/`;
- **overlapping filenames** — `DCIM/100/A001.MOV` vs `DCIM/101/A001.MOV`, and
  `Day1/IMG_0001.JPG` vs `Day2/IMG_0001.JPG`.

### Source manifest (sha256), 15 regular files, 268,584,144 bytes

| path | bytes | sha256 |
| --- | ---: | --- |
| `ARCHIVES/archive.zip` | 188 | `f232f19db1575f3804fe0064df5f838f23eb9607b56e5940d24f86efbdb63980` |
| `ARCHIVES/data.tar.gz` | 362 | `108f2ffe4536dcf6a91790e276ba43e81ebe9c4d7a43759e93b1ade84d96698d` |
| `ARCHIVES/payload.txt` | 16 | `92f86a430bca3d71cc27fcedb1a9b67a487e7f1ac1c97aad57df2d40ec9f8b71` |
| `AUDIO/interview.wav` | 88278 | `76d884aeb068036704cf27022000c5e91b739ac17d6b1ce27ba61ddda870d706` |
| `Bundles/Sample.photoslibrary/Database/photos.db` | 10 | `d5fe6ba023e16665a3b54b4c5a1f30637ee39c6025a0c1aa562838757cb393ad` |
| `Bundles/Sample.photoslibrary/Masters/2025/IMG_0001.JPG` | 7661 | `c6e7ee05ff1498887e4c2182f17d27d81910fe29130def6951bcf5c68429fef2` |
| `DCIM/100/A001.MOV` | 11096 | `45ee0c504ee404e5e6fecab5088acf59e1c672bb383bf386ffae5ec3ca3236f5` |
| `DCIM/100/A002.MOV` | 11096 | `45ee0c504ee404e5e6fecab5088acf59e1c672bb383bf386ffae5ec3ca3236f5` |
| `DCIM/101/A001.MOV` | 11096 | `45ee0c504ee404e5e6fecab5088acf59e1c672bb383bf386ffae5ec3ca3236f5` |
| `DOCS/brief.pdf` | 193 | `794abaa4f6f06fc519895c22944a0ab43ad02b4fb32bdefa1952ce81613cb47b` |
| `DOCS/notes.txt` | 25 | `0fdffa2df5d5ebf6bd367710fbb8a7e731f7da8cfd5157a3c4084fd4e7fb6a16` |
| `Day1/IMG_0001.JPG` | 7990 | `dc13e92c31003c4bcc49cfc076470ba7358a3b68a9ff17cae5a7f7f900950c4b` |
| `Day2/IMG_0001.JPG` | 7990 | `dc13e92c31003c4bcc49cfc076470ba7358a3b68a9ff17cae5a7f7f900950c4b` |
| `GRAPHICS/hero.png` | 2687 | `3a4d41c65681168fd1aca09c67a547b112c5a37c501aa165fd3af4324b2bb219` |
| `large/plate.bin` | 268435456 | `7cc0c6a9b51ada24d3f02022f66593e535c78c43436bacdd983a832b0af54fac` |

Plus one empty directory, `Empty Folder/Nested Empty/`.

The mirrored duplicates (the three `A001`/`A002` movies, the two `IMG_0001`
JPEGs) are intentional: they produce the overlapping leaf names §12.1 asks
for, and they exercise relative-path routing.

---

## Procedure

Isolated application data and throwaway trees, no real profile touched:

1. Build the package (provenance above):
   `cd desktop && npm run package:mac:local`
2. Run the harness:
   `node docs/validation/d1/run-pilot.mjs`
   Defaults to `/tmp/d1-pilot` and the bundled app above; override with
   `--root`, `--app`, `--ferry`, `--port`.

The harness, in order:

1. builds the fixture tree and hashes every source file (sha256);
2. launches `ferry.app` with `--user-data-dir=<throwaway>` and
   **`PATH=/usr/bin:/bin`** (no ffmpeg anywhere on it);
3. drives scan → destination → plan → preflight → approve → transfer →
   receipt through the running app's own IPC bridge over CDP — the same
   `window.ferry.*` calls the screens make, so it is the packaged sidecar
   doing the work;
4. walks source and destination with sha256 independently of ferry, mapping
   each original through the plan's `relPath → destRelPath`;
5. quits, relaunches the app against the same app data, and re-reads the job
   and receipt;
6. runs the same flow from the CLI (`ferry --db <scratch> …`) and verifies
   that destination independently too.

`ferry`'s own "succeeded" is never the evidence; it is the claim under test.

---

## Results

### Packaged-app transfer (ffmpeg absent)

`app.getStatus` → sidecar `0.3.0`; `app.doctor` → `ffmpeg present: false`,
`ffprobe present: false`. App data and DB confined to the throwaway
`--user-data-dir`.

| | |
| --- | --- |
| Inventory | 15 files, 17 dirs, 268,584,143 bytes, 0 read errors |
| Plan | 15 files, 268,584,143 bytes, 0 conflicts, 0 blocking, 0 exclusions |
| Preflight | `passed` |
| Job | `succeeded` |
| Receipt | `finalState: succeeded`, `committed 16`, `failed 0`, `excluded 0`, `reused 0`, bytes 268,584,144 |

Note the ledger is **16 entries, not 15 files**: the engine records the empty
directory as its own committed entry. That is why `committed` (16) exceeds the
file count (15). It is accounted for below, not a discrepancy.

### Independent verification (ferry not consulted)

Independent sha256 walk of the destination against the source manifest,
mapped through the plan:

| outcome | count |
| --- | ---: |
| verified-identical | 15 |
| excluded | 0 |
| failed / missing at destination | 0 |
| not in plan | 0 |
| residual (extra files at destination) | 0 |

Ledger reconciliation: `entries 16 = 15 files + 1 empty dir`, `committed 16`,
`reconciled: true`. Empty-folder check: `Empty Folder/Nested Empty/` →
**directory-recreated** at
`Sources/<label>/Empty Folder/Nested Empty/`.

**Every original is accounted for.** No residual.

### No FFmpeg requirement for general transfer

The transfer above ran with `ffmpeg` and `ffprobe` absent from the app's
`PATH` (confirmed by `app.doctor` at the time of the run) and completed with
15/15 files verified. General transfer does not require FFmpeg; only the
proxy/derive features do.

### Packaged-app restart

Quit and relaunched against the same isolated app data:

| after restart | value |
| --- | --- |
| sidecar version | `0.3.0` |
| job states | `["succeeded"]` |
| receipt `finalState` | `succeeded` |
| first `h1` | `Dashboard` |

The durable state survives a restart of the packaged app.

### CLI against the same service contracts

`ferry` CLI (workspace venv) run against a scratch `--db` and a second
destination, same source:

| step | exit |
| --- | ---: |
| `destination save` | 0 |
| `inventory create` | 0 |
| `plan create` | 0 |
| `preflight run` | 0 |
| `plan approve` | 0 |
| `transfer start` (runs to completion) | 0 |
| `transfer receipt` | 0 |
| `plan entries` | 0 |

Receipt `finalState: succeeded`; independent verification **15/15
verified-identical**, 0 extra; ledger reconciled 16 = 15 + 1; empty directory
recreated. The CLI and the app agree on the contracts and the result.

---

### Negative control — the gate can fail

A tally that only gets read by eye exits 0 on a bad run. The gate was shown to
fail on a real defect rather than asserted:

```sh
node docs/validation/d1/run-pilot.mjs --simulate-missing DOCS/notes.txt
```

`--simulate-missing` deletes the named destination file immediately before the
independent walk (a normal run never passes it). Observed:

```
[d1] negative control: removed /tmp/d1-pilot/dest/Sources/<label>/DOCS/notes.txt before the verification walk
[d1] GATE FAIL — packaged app: verified-identical 14 != expected 15 (statuses {"verified-identical":14,"missing-at-destination":1})
[d1] GATE FAIL — packaged app: missing-at-destination DOCS/notes.txt -> Sources/<label>/DOCS/notes.txt
NEGATIVE_EXIT=1
```

The two failures name the count and the file. The same harness on the clean
tree, run the same way, exits **0** with `gate {"pass": true, "failures": []}`
(`POSITIVE_EXIT=0`). The recorded run above is the clean one.

## Findings

**No blocking finding.** The pilot did what §12.1 asks: the packaged release
performs a real transfer and verifies it independently.

Two non-blocking observations, recorded rather than fixed (engine defects do
not belong in a validation change):

1. **The receipt's `committed` count includes empty directories.** A source
   with 15 files and 1 empty folder reports `committed 16` with no way to tell
   from that field alone how many are files. The full `entries` ledger does
   disambiguate (each entry names a path), so nothing is lost — but a reader
   comparing `actual.committed` to a file count will be surprised. Worth a
   definition note in §12.3's receipt documentation, and possibly a separate
   `directories` count. Not filed as an engine bug; flagged here.
2. **The x64 DMG in an arm64-host build carries no sidecar** (`sidecar/x64`
   absent, electron-builder logs "file source doesn't exist"). Expected for a
   single-arch build and out of scope for this pilot; a release build must
   build both sidecars. Pre-existing packaging behaviour, not exercised here.

## Limitations / not run

- **Local disks only.** External drives, mounted network shares, two
  sequential source drives, ≥10,001 entries, ≥10 GiB in one file, ≥2 h
  sustained transfer, and real cable-pull/restart/disconnect are §12.2 and
  are **`NOT RUN`** — no hardware or operator authorization was available.
  D-2 is not started from this record.
- **Synthetic fixtures, not licensed third-party media.** Generated valid
  formats stand in for "representative media/documents where licensed/available".
- **Unsigned local build**, ad-hoc signature only. Not a public stable
  release; signing/notarization is D-4.
- No package-level bug was found, so nothing was filed against the engine.

## Re-running

```sh
cd desktop && npm run package:mac:local
node docs/validation/d1/run-pilot.mjs            # writes <root>/report.json
```

The report carries provenance (commit, app/sidecar hashes), the source
manifest, the packaged-app receipt, the restart result, the CLI results, and
the per-file independent hash comparison.
